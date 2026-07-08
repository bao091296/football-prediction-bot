"""
Các tác vụ tự động chạy định kỳ.
"""

import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import database as db
import football_api as api
from helpers import build_poll_question, build_poll_options, build_result_text, OPTION_INDEX_TO_CODE
from config import POLL_CLOSE_MINUTES_BEFORE, CHAT_THREAD_ID

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="UTC")
_bot_app = None   # set khi khởi động


def set_application(app):
    global _bot_app
    _bot_app = app


async def job_sync_upcoming_matches():
    """Lấy lịch thi đấu sắp tới và lưu vào DB."""
    logger.info("[scheduler] Đồng bộ lịch thi đấu...")
    try:
        matches = await api.fetch_upcoming_matches(days_ahead=3)
        groups  = await db.get_all_groups()
        default_chat = groups[0] if groups else None

        for m in matches:
            await db.upsert_match(
                home_team   = m["home_team"],
                away_team   = m["away_team"],
                match_time  = m["match_time"],
                competition = m["competition"],
                ext_id      = m["ext_id"],
                chat_id     = default_chat,
                stage       = m.get("stage", "GROUP_STAGE"),
            )
        logger.info(f"[scheduler] Đồng bộ xong {len(matches)} trận.")
    except Exception as e:
        logger.error(f"[scheduler] Lỗi sync lịch: {e}")


async def job_create_polls():
    """Tạo poll Telegram cho các trận cần tạo (trong khung giờ)."""
    if not _bot_app:
        return
    now = datetime.now(timezone.utc)
    try:
        pending = await db.get_upcoming_matches_to_poll(now)
        for match in pending:
            chat_id = match["chat_id"]
            if not chat_id:
                continue
            question = build_poll_question(
                match["home_team"], match["away_team"],
                match["competition"], match["match_time"],
                match.get("stage", "GROUP_STAGE"),
            )
            match_dt = datetime.fromisoformat(match["match_time"].replace("Z", "+00:00"))
            close_dt = match_dt - timedelta(minutes=POLL_CLOSE_MINUTES_BEFORE)
            # Nếu giờ đóng poll đã qua (tạo poll muộn), không set close_date
            use_close = close_dt > datetime.now(timezone.utc)

            options = build_poll_options(match["home_team"], match["away_team"])
            msg = await _bot_app.bot.send_poll(
                chat_id              = chat_id,
                message_thread_id    = CHAT_THREAD_ID,
                question             = question + ("\n⚠️ Poll tạo muộn - trận đang diễn ra!" if not use_close else ""),
                options              = options,
                is_anonymous         = False,
                allows_multiple_answers = False,
                close_date           = close_dt if use_close else None,
            )
            await db.save_poll_info(
                match_id       = match["match_id"],
                poll_message_id = msg.message_id,
                poll_id        = msg.poll.id,
                chat_id        = chat_id,
            )

            # Gửi tin nhắn tag toàn bộ user nhắc vote
            users = await db.get_leaderboard(100)
            if users:
                tags = " ".join(
                    f"[{u['full_name']}](tg://user?id={u['user_id']})" for u in users
                )
                await _bot_app.bot.send_message(
                    chat_id           = chat_id,
                    message_thread_id = CHAT_THREAD_ID,
                    text              = f"🗳 Vote thôi anh em ơi!!!\n{tags}",
                    parse_mode        = "Markdown",
                )
            logger.info(f"[scheduler] Đã tạo poll trận {match['match_id']}")
    except Exception as e:
        logger.error(f"[scheduler] Lỗi tạo poll: {e}")


async def job_sync_results():
    """Lấy kết quả và tính điểm cho các trận vừa kết thúc."""
    if not _bot_app:
        return
    logger.info("[scheduler] Kiểm tra kết quả trận...")
    try:
        # Bước 1: Lấy kết quả từ API, upsert vào DB rồi cập nhật kết quả
        finished_from_api = await api.fetch_finished_matches(days_back=2)
        groups = await db.get_all_groups()
        default_chat = groups[0] if groups else None

        for m in finished_from_api:
            if not m["result"]:
                continue
            # Upsert để đảm bảo trận luôn có trong DB dù chưa được sync lịch
            await db.upsert_match(
                home_team   = m["home_team"],
                away_team   = m["away_team"],
                match_time  = m["match_time"],
                competition = m["competition"],
                ext_id      = m["ext_id"],
                chat_id     = default_chat,
                stage       = m.get("stage", "GROUP_STAGE"),
            )
            match = await db.get_match_by_ext_id(m["ext_id"])
            if not match:
                continue
            if match["status"] != "FINISHED":
                await db.update_match_result(
                    match["match_id"], m["result"],
                    m["home_score"], m["away_score"]
                )
                logger.info(
                    f"[scheduler] Cập nhật kết quả trận {match['match_id']}: "
                    f"{m['home_score']}-{m['away_score']} ({m['result']})"
                )

        # Bước 2: Tìm các trận FINISHED chưa tính điểm
        unscored = await db.get_finished_unscored_matches()
        if not unscored:
            return

        all_user_ids = await db.get_all_active_users()

        for match in unscored:
            already = await db.is_match_settled(match["match_id"])
            if already:
                continue

            # Tính điểm
            summary = await db.settle_match(
                match["match_id"], match["result"], all_user_ids
            )
            logger.info(
                f"[scheduler] Đã tính điểm trận {match['match_id']} - "
                f"Đúng: {len(summary['correct'])}, Sai: {len(summary['wrong'])}, "
                f"Không đoán: {len(summary['no_pred'])}"
            )

            # Gửi thông báo vào group
            chat_id = match.get("chat_id")
            if not chat_id:
                continue

            text = await build_result_message(match, summary)
            await _bot_app.bot.send_message(
                chat_id           = chat_id,
                message_thread_id = CHAT_THREAD_ID,
                text              = text,
                parse_mode        = "HTML",
            )

    except Exception as e:
        logger.error(f"[scheduler] Lỗi sync kết quả: {e}", exc_info=True)


async def build_result_message(match: dict, summary: dict) -> str:
    """Tạo tin nhắn kết quả chi tiết có tên người."""
    from helpers import PRED_CODE_TO_LABEL, name_display

    home = match["home_team"]
    away = match["away_team"]
    result = match["result"]

    # Tên kết quả cụ thể theo đội
    if result == "HOME_WIN":
        result_label = f"🏆 {home} thắng"
    elif result == "AWAY_WIN":
        result_label = f"🏆 {away} thắng"
    else:
        result_label = "🤝 Hòa"

    lines = [
        f"📊 <b>{home} {match['home_score']} - {match['away_score']} {away}</b>",
        f"Kết quả đúng: <b>{result_label}</b>",
        "",
    ]

    gain        = summary["gain_per_winner"]
    correct_ids = summary["correct"]
    wrong_ids   = summary["wrong"]
    no_pred_ids = summary["no_pred"]
    no_change   = summary.get("no_change", False)

    # Lấy tên người dùng
    all_ids = correct_ids + wrong_ids + no_pred_ids
    users = await db.get_users_by_ids(all_ids)

    if no_change:
        if correct_ids:
            lines.append("🤝 <b>Tất cả đoán đúng — không tính điểm lần này!</b>")
        else:
            lines.append("🤝 <b>Không ai đoán đúng — không tính điểm lần này!</b>")

    if correct_ids:
        label = f"+{gain:.1f}đ mỗi người" if not no_change else "±0đ"
        lines.append(f"✅ <b>Đoán đúng ({len(correct_ids)} người) {label}:</b>")
        for uid in correct_ids:
            u = users.get(uid, {"full_name": f"#{uid}", "username": ""})
            lines.append(f"  • {name_display(u)}")
    elif not no_change:
        lines.append("✅ Không ai đoán đúng cả!")

    lines.append("")

    if wrong_ids:
        deduct_label = "±0đ" if no_change else f"-{summary.get('deduct',50):.0f}đ mỗi người"
        lines.append(f"❌ <b>Đoán sai ({len(wrong_ids)} người) {deduct_label}:</b>")
        for uid in wrong_ids:
            u = users.get(uid, {"full_name": f"#{uid}", "username": ""})
            lines.append(f"  • {name_display(u)}")
        lines.append("")

    if no_pred_ids:
        deduct_label = "±0đ" if no_change else f"-{summary.get('deduct',50):.0f}đ mỗi người"
        lines.append(f"⏭️ <b>Không tham gia ({len(no_pred_ids)} người) {deduct_label}:</b>")
        for uid in no_pred_ids:
            u = users.get(uid, {"full_name": f"#{uid}", "username": ""})
            lines.append(f"  • {name_display(u)}")
        lines.append("")

    if not no_change:
        lines.append(f"💰 Tổng điểm phạt: <b>{summary['total_deducted']:.0f}đ</b>")

    # Bảng xếp hạng toàn bộ
    board = await db.get_leaderboard(50)
    if board:
        lines.append("")
        lines.append("🏆 <b>Bảng xếp hạng:</b>")
        medals = ["🥇", "🥈", "🥉"]
        for i, u in enumerate(board):
            rank = medals[i] if i < 3 else f"{i+1}."
            pts  = u["points"]
            sign = "+" if pts >= 0 else ""
            lines.append(f"  {rank} {name_display(u)}: {sign}{pts:.1f}đ")

    return "\n".join(lines)


def start_scheduler(app):
    set_application(app)
    # Đồng bộ lịch mỗi 30 phút để kịp bắt thay đổi lịch
    scheduler.add_job(job_sync_upcoming_matches, IntervalTrigger(minutes=30), id="sync_matches")
    # Kiểm tra poll cần tạo mỗi 15 phút
    scheduler.add_job(job_create_polls, IntervalTrigger(minutes=15), id="create_polls")
    # Kiểm tra kết quả mỗi 30 phút
    scheduler.add_job(job_sync_results, IntervalTrigger(minutes=30), id="sync_results")
    scheduler.start()
    logger.info("[scheduler] Đã khởi động scheduler.")
