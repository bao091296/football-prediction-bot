"""
Bot Telegram dự đoán bóng đá.
Chạy: python bot.py
"""

import logging
import asyncio
from datetime import datetime, timezone, timedelta

from telegram import Update, BotCommand
from telegram.ext import (
    Application, CommandHandler, PollAnswerHandler,
    ContextTypes, MessageHandler, filters,
)

import database as db
import football_api as api
from helpers import (
    build_poll_question, build_poll_options, build_result_text,
    OPTION_INDEX_TO_CODE, PRED_CODE_TO_LABEL, name_display, format_match_time,
)
from config import TELEGRAM_BOT_TOKEN, ADMIN_IDS, POLL_CLOSE_MINUTES_BEFORE, CHAT_THREAD_ID
import scheduler as sched

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    level=logging.INFO,
    force=True,
)
# Đảm bảo log ra stdout để Railway capture được
import sys
logging.getLogger().handlers[0].stream = sys.stdout
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def ensure_user(update: Update):
    user = update.effective_user
    await db.upsert_user(user.id, user.username or "", user.full_name or "")


# ── Lệnh người dùng ────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    chat = update.effective_chat
    if chat.type in ("group", "supergroup"):
        await db.register_group(chat.id)
    await update.message.reply_text(
        "⚽ <b>Bot dự đoán bóng đá</b>\n\n"
        "📋 Lệnh:\n"
        "/diem — Bảng xếp hạng điểm\n"
        "/dudoan — Lịch sử dự đoán của bạn\n"
        "/trandau — Xem các trận sắp tới\n"
        "/help — Trợ giúp\n\n"
        "Bot sẽ tự động tạo bảng bình chọn trước mỗi trận đấu.\n"
        "Đoán đúng → ăn điểm, đoán sai / không đoán → trừ 50 điểm.",
        parse_mode="HTML",
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "⚽ <b>Hướng dẫn sử dụng</b>\n\n"
        "<b>Cách chơi:</b>\n"
        "1. Bot tự động tạo poll trước mỗi trận 12 tiếng\n"
        "2. Bình chọn kết quả của bạn trong poll\n"
        "3. Poll tự đóng trước giờ bóng lăn 5 phút\n"
        "4. Sau trận, bot tính điểm tự động\n\n"
        "<b>Tính điểm:</b>\n"
        "• Đoán đúng: +điểm (chia đều từ tổng điểm thua)\n"
        "• Đoán sai / không đoán: -50 điểm\n\n"
        "<b>Ví dụ:</b> 3 đúng, 5 sai, 2 không đoán\n"
        "→ Mỗi người đúng được: (50×7)÷3 ≈ 116.7 điểm\n\n"
        "<b>Lệnh:</b>\n"
        "/diem — Bảng xếp hạng\n"
        "/dudoan — Lịch sử dự đoán của bạn\n"
        "/trandau — Các trận sắp tới"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def cmd_diem(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    board = await db.get_leaderboard(20)
    if not board:
        await update.message.reply_text("Chưa có dữ liệu điểm.")
        return

    lines = ["🏆 <b>Bảng xếp hạng</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(board):
        medal = medals[i] if i < 3 else f"{i+1}."
        pts   = u["points"]
        sign  = "+" if pts >= 0 else ""
        lines.append(f"{medal} {name_display(u)}: <b>{sign}{pts:.1f}</b> điểm")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_dudoan(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await ensure_user(update)
    preds = await db.get_user_predictions(update.effective_user.id, 10)
    if not preds:
        await update.message.reply_text("Bạn chưa có dự đoán nào.")
        return

    lines = [f"📋 <b>Lịch sử dự đoán của bạn</b>\n"]
    for p in preds:
        match_str = f"{p['home_team']} vs {p['away_team']}"
        pred_label = PRED_CODE_TO_LABEL.get(p["prediction"], p["prediction"])
        if p["is_correct"] is None:
            status = "⏳ Chờ kết quả"
        elif p["is_correct"]:
            delta = p.get("points_delta", 0) or 0
            status = f"✅ Đúng (+{delta:.1f}đ)"
        else:
            delta = p.get("points_delta", 0) or 0
            status = f"❌ Sai ({delta:.1f}đ)"
        lines.append(f"• {match_str}\n  Dự đoán: {pred_label} | {status}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_trandau(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    matches = await db.get_all_scheduled_matches()
    if not matches:
        await update.message.reply_text("Không có trận nào sắp tới.")
        return

    lines = ["📅 <b>Các trận sắp tới</b>\n"]
    for m in matches:
        time_str = format_match_time(m["match_time"])
        poll_status = "✅ Đã tạo poll" if m["poll_message_id"] else "⏳ Chưa có poll"
        comp = f"[{m['competition']}] " if m["competition"] else ""
        lines.append(f"⚽ <code>#{m['match_id']}</code> {comp}{m['home_team']} vs {m['away_team']}\n"
                     f"   🕐 {time_str} | {poll_status}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── Lệnh Admin ─────────────────────────────────────────────────────────────────

async def cmd_them_tran(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /them_tran <đội nhà> vs <đội khách> <dd/mm/yyyy HH:MM> [giải đấu]
    Ví dụ: /them_tran "Man Utd" vs "Arsenal" 25/12/2024 20:00 Premier League
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return

    args = ctx.args
    full = " ".join(args)

    # Parse: <home> vs <away> <date> <time> [competition]
    try:
        vs_idx  = full.index(" vs ")
        home    = full[:vs_idx].strip()
        rest    = full[vs_idx + 4:]
        parts   = rest.split()
        away    = parts[0]
        date_s  = parts[1]   # dd/mm/yyyy
        time_s  = parts[2]   # HH:MM
        comp    = " ".join(parts[3:]) if len(parts) > 3 else ""

        import pytz
        tz = pytz.timezone("Asia/Ho_Chi_Minh")
        local_dt = datetime.strptime(f"{date_s} {time_s}", "%d/%m/%Y %H:%M")
        local_dt = tz.localize(local_dt)
        utc_str  = local_dt.astimezone(timezone.utc).isoformat()

        match_id = await db.upsert_match(
            home_team   = home,
            away_team   = away,
            match_time  = utc_str,
            competition = comp,
            chat_id     = update.effective_chat.id,
        )
        await update.message.reply_text(
            f"✅ Đã thêm trận #{match_id}:\n"
            f"⚽ {home} vs {away}\n"
            f"🕐 {date_s} {time_s} (VN)\n"
            f"🏆 Giải: {comp or 'Không rõ'}\n\n"
            f"Poll sẽ được tạo tự động trong lần kiểm tra tiếp theo."
        )
    except Exception as e:
        await update.message.reply_text(
            f"❌ Lỗi: {e}\n\n"
            "Cú pháp: /them_tran TênĐộiNhà vs TênĐộiKhách dd/mm/yyyy HH:MM [Giải đấu]\n"
            "Ví dụ: /them_tran ManUtd vs Arsenal 25/12/2024 20:00 Premier League"
        )


async def cmd_tao_poll(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /tao_poll <match_id>  — Admin tạo poll ngay lập tức cho một trận.
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return

    if not ctx.args:
        await update.message.reply_text("Cú pháp: /tao_poll <match_id>")
        return

    match_id = int(ctx.args[0])
    match = await db.get_match(match_id)
    if not match:
        await update.message.reply_text("Không tìm thấy trận.")
        return
    if match["poll_message_id"]:
        await update.message.reply_text("Trận này đã có poll rồi.")
        return

    chat_id  = update.effective_chat.id
    question = build_poll_question(
        match["home_team"], match["away_team"],
        match["competition"], match["match_time"]
    )
    close_dt = (
        datetime.fromisoformat(match["match_time"].replace("Z", "+00:00"))
        - timedelta(minutes=POLL_CLOSE_MINUTES_BEFORE)
    )
    # Nếu thời gian đóng đã qua, không set close_date
    use_close = close_dt > datetime.now(timezone.utc)
    msg = await ctx.bot.send_poll(
        chat_id                 = update.effective_chat.id,
        message_thread_id       = CHAT_THREAD_ID,
        question                = question,
        options                 = build_poll_options(match["home_team"], match["away_team"]),
        is_anonymous            = False,
        allows_multiple_answers = False,
        close_date              = close_dt if use_close else None,
    )
    await db.save_poll_info(match_id, msg.message_id, msg.poll.id, chat_id)
    await update.message.reply_text(f"✅ Đã tạo poll cho trận #{match_id}.")


async def cmd_cap_nhat(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """
    /cap_nhat <match_id> <home_score> <away_score>
    """
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return

    try:
        match_id   = int(ctx.args[0])
        home_score = int(ctx.args[1])
        away_score = int(ctx.args[2])
    except (IndexError, ValueError):
        await update.message.reply_text("Cú pháp: /cap_nhat <match_id> <bàn_nhà> <bàn_khách>")
        return

    if home_score > away_score:
        result = "HOME_WIN"
    elif home_score < away_score:
        result = "AWAY_WIN"
    else:
        result = "DRAW"

    match = await db.get_match(match_id)
    if not match:
        await update.message.reply_text("Không tìm thấy trận.")
        return

    # Nếu đã tính điểm rồi → hoàn tác trước
    if await db.is_match_settled(match_id):
        await db.unsettle_match(match_id)
        logger.info(f"[cap_nhat] Đã unsettle trận {match_id} để tính lại.")

    await db.update_match_result(match_id, result, home_score, away_score)

    all_users = await db.get_all_active_users()
    summary   = await db.settle_match(match_id, result, all_users)

    # Gửi kết quả vào group
    match["result"]     = result
    match["home_score"] = home_score
    match["away_score"] = away_score
    text = build_result_text(match, summary)
    chat_id = match.get("chat_id") or update.effective_chat.id
    await ctx.bot.send_message(chat_id=chat_id, message_thread_id=CHAT_THREAD_ID, text=text, parse_mode="HTML")
    await update.message.reply_text("✅ Đã cập nhật kết quả và tính điểm.")


async def cmd_dong_bo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin chạy đồng bộ thủ công."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return
    await update.message.reply_text("⏳ Đang đồng bộ lịch thi đấu...")
    await sched.job_sync_upcoming_matches()
    await update.message.reply_text("✅ Đồng bộ xong. Dùng /trandau để xem.")


async def cmd_users(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin xem toàn bộ users trong DB."""
    if not is_admin(update.effective_user.id):
        return
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, username, full_name, points FROM users ORDER BY user_id") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    lines = ["👥 <b>Toàn bộ users trong DB:</b>\n"]
    for r in rows:
        sign = "+" if r["points"] >= 0 else ""
        lines.append(f"ID: <code>{r['user_id']}</code> | @{r['username']} | {r['full_name']} | {sign}{r['points']:.1f}đ")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_full_reset(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Xoá TOÀN BỘ predictions + users rồi tự seed lại dữ liệu lịch sử."""
    if not is_admin(update.effective_user.id):
        return
    import aiosqlite
    from config import DB_PATH, POINTS_DEDUCT

    USERS = [
        (8814280223, "Zane1602",    "Zane"),
        (1682575734, "alieforreal", "Alie"),
        (822425008,  "Andy_cc",     "Andy"),
        (5200492637, "Aron713",     "Aron"),
        (5138244411, "qle23",       "Hercules 🐾"),
        (1800116341, "bugicoincu",  "Bugi | Coincu"),
        (1762927178, "TommyH0",     "Tommy 🐾"),
        (934622455,  "pevitsocute", "Vịt Tư Mã"),
    ]
    MATCHES = [
        {
            "ext_id": "553123", "home_team": "Brazil", "away_team": "Japan",
            "match_time": "2026-06-29T17:00:00Z", "result": "HOME_WIN",
            "home_score": 2, "away_score": 1,
            "preds": {8814280223:"HOME_WIN",1682575734:"HOME_WIN",822425008:"HOME_WIN",5200492637:"HOME_WIN",
                      5138244411:"HOME_WIN",1800116341:"DRAW",1762927178:"DRAW",934622455:"DRAW"},
        },
        {
            "ext_id": "553124", "home_team": "Germany", "away_team": "Paraguay",
            "match_time": "2026-06-29T20:30:00Z", "result": "DRAW",
            "home_score": 1, "away_score": 1,
            "preds": {1800116341:"HOME_WIN",1762927178:"HOME_WIN",1682575734:"HOME_WIN",822425008:"HOME_WIN",
                      5200492637:"HOME_WIN",934622455:"HOME_WIN",5138244411:"HOME_WIN",8814280223:"AWAY_WIN"},
        },
    ]

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        # Xoá sạch toàn bộ
        await conn.execute("DELETE FROM predictions")
        await conn.execute("DELETE FROM users")
        await conn.execute(
            "UPDATE matches SET status='SCHEDULED', result=NULL, home_score=NULL, away_score=NULL "
            "WHERE ext_id IN ('553123','553124')"
        )
        await conn.commit()

        # Seed users
        for uid, username, full_name in USERS:
            await conn.execute(
                "INSERT OR REPLACE INTO users (user_id, username, full_name, points) VALUES (?,?,?,0)",
                (uid, username, full_name)
            )

        # Seed matches + predictions
        for m in MATCHES:
            await conn.execute("""
                INSERT INTO matches (ext_id,home_team,away_team,competition,match_time,status,result,home_score,away_score)
                VALUES (?,?,?,'WC',?,'FINISHED',?,?,?)
                ON CONFLICT(ext_id) DO UPDATE SET status='FINISHED',result=excluded.result,
                home_score=excluded.home_score,away_score=excluded.away_score
            """, (m["ext_id"],m["home_team"],m["away_team"],m["match_time"],
                  m["result"],m["home_score"],m["away_score"]))

            async with conn.execute("SELECT match_id FROM matches WHERE ext_id=?", (m["ext_id"],)) as cur:
                match_id = (await cur.fetchone())[0]

            result  = m["result"]
            preds   = m["preds"]
            correct = [uid for uid, p in preds.items() if p == result]
            wrong   = [uid for uid, p in preds.items() if p != result]
            gain    = (len(wrong) * POINTS_DEDUCT / len(correct)) if correct else 0

            for uid, pred in preds.items():
                is_c  = 1 if pred == result else 0
                delta = gain if is_c else -POINTS_DEDUCT
                await conn.execute(
                    "INSERT OR REPLACE INTO predictions (user_id,match_id,prediction,is_correct,points_delta) VALUES (?,?,?,?,?)",
                    (uid, match_id, pred, is_c, delta)
                )
                await conn.execute("UPDATE users SET points=points+? WHERE user_id=?", (delta, uid))

        await conn.commit()

    logger.info("[full_reset] Xoá sạch và seed lại xong.")
    await update.message.reply_text("✅ Xoá sạch và seed lại xong. Nhờ mọi người gõ /start để cập nhật tên Telegram.")


async def seed_history():
    """Seed dữ liệu 2 trận 29/06. Luôn chạy, tự kiểm tra và sửa nếu sai."""
    import aiosqlite
    from config import DB_PATH, POINTS_DEDUCT

    VOTERS = [
        (8814280223, "Zane1602",    "Zane"),
        (1682575734, "alieforreal", "Alie"),
        (822425008,  "Andy_cc",     "Andy"),
        (5200492637, "Aron713",     "Aron"),
        (5138244411, "qle23",       "Hercules 🐾"),
        (1800116341, "bugicoincu",  "Bugi | Coincu"),
        (1762927178, "TommyH0",     "Tommy 🐾"),
        (934622455,  "pevitsocute", "Vịt Tư Mã"),
    ]
    MATCHES = [
        {
            "ext_id": "553123", "home_team": "Brazil", "away_team": "Japan",
            "match_time": "2026-06-29T17:00:00Z", "result": "HOME_WIN",
            "home_score": 2, "away_score": 1,
            "preds": {8814280223:"HOME_WIN",1682575734:"HOME_WIN",822425008:"HOME_WIN",5200492637:"HOME_WIN",
                      5138244411:"HOME_WIN",1800116341:"DRAW",1762927178:"DRAW",934622455:"DRAW"},
        },
        {
            "ext_id": "553124", "home_team": "Germany", "away_team": "Paraguay",
            "match_time": "2026-06-29T20:30:00Z", "result": "DRAW",
            "home_score": 1, "away_score": 1,
            "preds": {1800116341:"HOME_WIN",1762927178:"HOME_WIN",1682575734:"HOME_WIN",822425008:"HOME_WIN",
                      5200492637:"HOME_WIN",934622455:"HOME_WIN",5138244411:"HOME_WIN",8814280223:"AWAY_WIN"},
        },
    ]

    # Tính điểm kỳ vọng cho mỗi voter
    expected_points = {}
    for uid, _, _ in VOTERS:
        expected_points[uid] = 0
    for m in MATCHES:
        result  = m["result"]
        preds   = m["preds"]
        correct = [u for u, p in preds.items() if p == result]
        wrong   = [u for u, p in preds.items() if p != result]
        gain    = (len(wrong) * POINTS_DEDUCT / len(correct)) if correct else 0
        for uid, pred in preds.items():
            delta = gain if pred == result else -POINTS_DEDUCT
            expected_points[uid] = expected_points.get(uid, 0) + delta

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Kiểm tra điểm hiện tại của voters
        needs_seed = False
        for uid, exp in expected_points.items():
            async with conn.execute("SELECT points FROM users WHERE user_id=?", (uid,)) as cur:
                row = await cur.fetchone()
                if row is None or abs(row["points"] - exp) > 0.01:
                    needs_seed = True
                    break

        if not needs_seed:
            logger.info("[seed] Dữ liệu lịch sử đã đúng, bỏ qua.")
            return

        logger.info("[seed] Phát hiện dữ liệu sai, tiến hành seed lại...")

        # Xoá predictions cũ của 2 trận này
        for m in MATCHES:
            async with conn.execute("SELECT match_id FROM matches WHERE ext_id=?", (m["ext_id"],)) as cur:
                row = await cur.fetchone()
                if row:
                    await conn.execute("DELETE FROM predictions WHERE match_id=?", (row[0],))

        # Reset điểm voters về 0 trước khi tính lại
        for uid, _, _ in VOTERS:
            await conn.execute(
                "INSERT INTO users (user_id, username, full_name, points) VALUES (?,?,?,0) "
                "ON CONFLICT(user_id) DO UPDATE SET points=0",
                (uid, "?", "?")
            )

        # Insert matches + predictions + điểm
        for m in MATCHES:
            await conn.execute("""
                INSERT INTO matches (ext_id,home_team,away_team,competition,match_time,status,result,home_score,away_score)
                VALUES (?,?,?,'WC',?,'FINISHED',?,?,?)
                ON CONFLICT(ext_id) DO UPDATE SET status='FINISHED',result=excluded.result,
                home_score=excluded.home_score,away_score=excluded.away_score
            """, (m["ext_id"],m["home_team"],m["away_team"],m["match_time"],
                  m["result"],m["home_score"],m["away_score"]))

            async with conn.execute("SELECT match_id FROM matches WHERE ext_id=?", (m["ext_id"],)) as cur:
                match_id = (await cur.fetchone())[0]

            result  = m["result"]
            preds   = m["preds"]
            correct = [uid for uid, p in preds.items() if p == result]
            wrong   = [uid for uid, p in preds.items() if p != result]
            gain    = (len(wrong) * POINTS_DEDUCT / len(correct)) if correct else 0

            for uid, pred in preds.items():
                is_c  = 1 if pred == result else 0
                delta = gain if is_c else -POINTS_DEDUCT
                await conn.execute(
                    "INSERT INTO predictions (user_id,match_id,prediction,is_correct,points_delta) "
                    "VALUES (?,?,?,?,?) ON CONFLICT(user_id,match_id) DO UPDATE SET "
                    "prediction=excluded.prediction,is_correct=excluded.is_correct,points_delta=excluded.points_delta",
                    (uid, match_id, pred, is_c, delta)
                )
                await conn.execute("UPDATE users SET points=points+? WHERE user_id=?", (delta, uid))
            logger.info(f"[seed] {m['home_team']} vs {m['away_team']}: {len(correct)} đúng (+{gain:.1f}đ), {len(wrong)} sai")

        await conn.commit()
        logger.info("[seed] ✅ Seed xong! Điểm kỳ vọng: %s", expected_points)


async def cmd_fix_points(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Set thẳng điểm đúng cho 8 người vote 29/06."""
    logger.info(f"[fix_points] Gọi bởi user {update.effective_user.id if update.effective_user else 'unknown'}")
    if not is_admin(update.effective_user.id):
        await update.effective_message.reply_text("⛔ Không có quyền.")
        return
    import aiosqlite
    from config import DB_PATH
    POINTS = {
        8814280223: -20.0,   # Zane
        1682575734: -20.0,   # Alie
        822425008:  -20.0,   # Andy
        5200492637: -20.0,   # Aron
        5138244411: -20.0,   # Hercules
        1800116341: -100.0,  # Bugi
        1762927178: -100.0,  # Tommy
        934622455:  -100.0,  # Vịt Tư Mã
    }
    lines = ["✅ <b>Kết quả /fix_points:</b>\n"]
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        for uid, pts in POINTS.items():
            await conn.execute("UPDATE users SET points=? WHERE user_id=?", (pts, uid))
            async with conn.execute("SELECT full_name, points FROM users WHERE user_id=?", (uid,)) as cur:
                row = await cur.fetchone()
                if row:
                    lines.append(f"✓ {row['full_name']}: {row['points']:.1f}đ")
                else:
                    lines.append(f"⚠️ ID {uid} không tìm thấy trong DB!")
        await conn.commit()
    await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_recalc_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reset điểm toàn bộ user về 0, tính lại từ tất cả trận FINISHED."""
    if not is_admin(update.effective_user.id):
        return
    import aiosqlite
    from config import DB_PATH, POINTS_DEDUCT

    await update.message.reply_text("⏳ Đang tính lại toàn bộ điểm...")

    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Reset tất cả điểm về 0
        await conn.execute("UPDATE users SET points = 0")
        # Reset tất cả predictions về chưa tính
        await conn.execute("UPDATE predictions SET is_correct = NULL, points_delta = NULL")
        await conn.commit()

        # Lấy tất cả trận FINISHED có result, theo thứ tự thời gian
        async with conn.execute("""
            SELECT match_id, result FROM matches
            WHERE status = 'FINISHED' AND result IS NOT NULL
            ORDER BY match_time ASC
        """) as cur:
            finished = await cur.fetchall()

        # Lấy tất cả user_ids
        async with conn.execute("SELECT user_id FROM users") as cur:
            all_user_ids = [r["user_id"] for r in await cur.fetchall()]

        lines = [f"🔄 <b>Tính lại điểm ({len(finished)} trận):</b>\n"]

        for m in finished:
            match_id = m["match_id"]
            result   = m["result"]

            # Lấy predictions của trận này
            async with conn.execute(
                "SELECT user_id, prediction FROM predictions WHERE match_id = ?", (match_id,)
            ) as cur:
                preds = {r["user_id"]: r["prediction"] for r in await cur.fetchall()}

            correct   = [uid for uid, p in preds.items() if p == result]
            wrong     = [uid for uid, p in preds.items() if p != result]
            no_pred   = [uid for uid in all_user_ids if uid not in preds]
            total_losers = len(wrong) + len(no_pred)
            no_change = not correct or not wrong

            gain  = (total_losers * POINTS_DEDUCT / len(correct)) if (correct and not no_change) else 0
            deduct = 0 if no_change else POINTS_DEDUCT

            for uid in correct:
                delta = gain if not no_change else 0
                await conn.execute("UPDATE predictions SET is_correct=1, points_delta=? WHERE user_id=? AND match_id=?", (delta, uid, match_id))
                if delta:
                    await conn.execute("UPDATE users SET points=points+? WHERE user_id=?", (delta, uid))
            for uid in wrong:
                delta = -deduct
                await conn.execute("UPDATE predictions SET is_correct=0, points_delta=? WHERE user_id=? AND match_id=?", (delta, uid, match_id))
                if deduct:
                    await conn.execute("UPDATE users SET points=points-? WHERE user_id=?", (deduct, uid))
            for uid in no_pred:
                if deduct:
                    await conn.execute("UPDATE users SET points=points-? WHERE user_id=?", (deduct, uid))

            note = " (không tính điểm)" if no_change else f" +{gain:.1f}đ/{len(correct)} đúng, -{deduct}đ/{total_losers} sai"
            lines.append(f"• Trận #{match_id}: {result}{note}")

        await conn.commit()

        # Bảng xếp hạng mới
        async with conn.execute("SELECT full_name, points FROM users ORDER BY points DESC") as cur:
            board = await cur.fetchall()

        lines.append("\n🏆 <b>BXH mới:</b>")
        for i, u in enumerate(board, 1):
            sign = "+" if u["points"] >= 0 else ""
            lines.append(f"  {i}. {u['full_name']}: {sign}{u['points']:.1f}đ")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_matches(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin xem toàn bộ trận + match_id."""
    if not is_admin(update.effective_user.id):
        return
    import aiosqlite
    from config import DB_PATH
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute("SELECT match_id, home_team, away_team, status, result, home_score, away_score FROM matches ORDER BY match_id") as cur:
            rows = [dict(r) for r in await cur.fetchall()]
    lines = ["🗂 <b>Tất cả trận:</b>\n"]
    for r in rows:
        score = f" {r['home_score']}-{r['away_score']}" if r['home_score'] is not None else ""
        res   = f" ({r['result']})" if r['result'] else ""
        lines.append(f"<code>#{r['match_id']}</code> {r['home_team']} vs {r['away_team']} — {r['status']}{score}{res}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_reset_tran(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin reset trận về SCHEDULED để tính lại (dùng khi /cap_nhat nhầm)."""
    if not is_admin(update.effective_user.id):
        return
    if not ctx.args:
        await update.message.reply_text("Cú pháp: /reset_tran <match_id>")
        return
    match_id = int(ctx.args[0])
    match = await db.get_match(match_id)
    if not match:
        await update.message.reply_text("Không tìm thấy trận.")
        return
    await db.unsettle_match(match_id)
    await update.message.reply_text(
        f"✅ Đã reset trận #{match_id} ({match['home_team']} vs {match['away_team']}) về SCHEDULED."
    )


async def cmd_push_bxh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin đẩy BXH vào group topic."""
    if not is_admin(update.effective_user.id):
        return
    board = await db.get_leaderboard(50)
    if not board:
        await update.message.reply_text("Chưa có dữ liệu.")
        return
    lines = ["🏆 <b>Bảng xếp hạng hiện tại</b>\n"]
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(board):
        rank = medals[i] if i < 3 else f"{i+1}."
        pts  = u["points"]
        sign = "+" if pts >= 0 else ""
        lines.append(f"{rank} {name_display(u)}: <b>{sign}{pts:.1f}</b> điểm")
    groups = await db.get_all_groups()
    if groups:
        await ctx.bot.send_message(
            chat_id           = groups[0],
            message_thread_id = CHAT_THREAD_ID,
            text              = "\n".join(lines),
            parse_mode        = "HTML",
        )
    await update.message.reply_text("✅ Đã gửi BXH vào nhóm.")


async def cmd_sync(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Admin trigger đồng bộ kết quả + tính điểm ngay lập tức."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ Bạn không có quyền dùng lệnh này.")
        return
    await update.message.reply_text("⏳ Đang kiểm tra kết quả và tính điểm...")
    await sched.job_sync_results()
    await update.message.reply_text("✅ Xong. Nếu có kết quả mới sẽ thấy thông báo trong topic.")


async def cmd_admin_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    text = (
        "🔧 <b>Lệnh Admin</b>\n\n"
        "/them_tran TênNhà vs TênKhách dd/mm/yyyy HH:MM [Giải] — Thêm trận thủ công\n"
        "/tao_poll &lt;match_id&gt; — Tạo poll ngay cho trận\n"
        "/cap_nhat &lt;match_id&gt; &lt;bàn_nhà&gt; &lt;bàn_khách&gt; — Cập nhật kết quả\n"
        "/dong_bo — Đồng bộ lịch từ API\n"
        "/admin — Xem lệnh này"
    )
    await update.message.reply_text(text, parse_mode="HTML")


# ── Poll answer handler ────────────────────────────────────────────────────────

async def handle_poll_answer(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    answer  = update.poll_answer
    poll_id = answer.poll_id
    user    = answer.user

    await db.upsert_user(user.id, user.username or "", user.full_name or "")

    match = await db.get_match_by_poll(poll_id)
    if not match:
        return

    if not answer.option_ids:
        # Người dùng rút phiếu — xóa dự đoán (coi như không đoán)
        return

    option_idx = answer.option_ids[0]
    prediction = OPTION_INDEX_TO_CODE.get(option_idx)
    if not prediction:
        return

    await db.save_prediction(user.id, match["match_id"], prediction)
    logger.info(f"User {user.id} dự đoán trận {match['match_id']}: {prediction}")



# ── Main ───────────────────────────────────────────────────────────────────────

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Lỗi bot: %s", context.error, exc_info=context.error)


async def force_fix_points():
    """Luôn set đúng điểm cho 8 người vote 29/06 khi bot khởi động."""
    logger.info("[fix] >>> force_fix_points bắt đầu")
    import aiosqlite
    from config import DB_PATH
    VOTERS = [
        (8814280223, "Zane1602",    "Zane",           30.0),
        (1682575734, "alieforreal", "Alie",            30.0),
        (822425008,  "Andy_cc",     "Andy",            30.0),
        (5200492637, "Aron713",     "Aron",            30.0),
        (5138244411, "qle23",       "Hercules 🐾",     30.0),
        (1800116341, "bugicoincu",  "Bugi | Coincu",  -50.0),
        (1762927178, "TommyH0",     "Tommy 🐾",       -50.0),
        (934622455,  "pevitsocute", "Vịt Tư Mã",     -50.0),
    ]
    try:
        logger.info(f"[fix] DB_PATH={DB_PATH}")
        async with aiosqlite.connect(DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            for uid, uname, fname, pts in VOTERS:
                await conn.execute(
                    "INSERT INTO users (user_id, username, full_name, points) VALUES (?,?,?,?) "
                    "ON CONFLICT(user_id) DO UPDATE SET points=excluded.points",
                    (uid, uname, fname, pts)
                )
                logger.info(f"[fix] {fname} ({uid}) → {pts}đ")
            await conn.commit()
        logger.info("[fix] ✅ force_fix_points xong.")
    except Exception as e:
        logger.error(f"[fix] Lỗi: {e}", exc_info=True)


async def post_init(app: Application):
    logger.info("[post_init] >>> bắt đầu")
    await db.init_db()
    sched.start_scheduler(app)
    asyncio.create_task(sched.job_sync_upcoming_matches())
    asyncio.create_task(sched.job_create_polls())

    await app.bot.set_my_commands([
        BotCommand("start",    "Bắt đầu / đăng ký"),
        BotCommand("diem",     "Bảng xếp hạng điểm"),
        BotCommand("dudoan",   "Lịch sử dự đoán của bạn"),
        BotCommand("trandau",  "Các trận sắp tới"),
        BotCommand("help",     "Hướng dẫn sử dụng"),
    ])


def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .read_timeout(30)
        .write_timeout(30)
        .connect_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start",      cmd_start))
    app.add_handler(CommandHandler("help",       cmd_help))
    app.add_handler(CommandHandler("diem",       cmd_diem))
    app.add_handler(CommandHandler("dudoan",     cmd_dudoan))
    app.add_handler(CommandHandler("trandau",    cmd_trandau))

    # Admin
    app.add_handler(CommandHandler("them_tran",  cmd_them_tran))
    app.add_handler(CommandHandler("tao_poll",   cmd_tao_poll))
    app.add_handler(CommandHandler("cap_nhat",   cmd_cap_nhat))
    app.add_handler(CommandHandler("dong_bo",    cmd_dong_bo))
    app.add_handler(CommandHandler("sync",       cmd_sync))
    app.add_handler(CommandHandler("reset_tran",  cmd_reset_tran))
    app.add_handler(CommandHandler("recalc_all",  cmd_recalc_all))
    app.add_handler(CommandHandler("push_bxh",    cmd_push_bxh))
    app.add_handler(CommandHandler("matches",    cmd_matches))
    app.add_handler(CommandHandler("fix_points", cmd_fix_points))
    app.add_handler(CommandHandler("users",      cmd_users))
    app.add_handler(CommandHandler("full_reset", cmd_full_reset))
    app.add_handler(CommandHandler("admin",      cmd_admin_help))

    app.add_handler(PollAnswerHandler(handle_poll_answer))
    app.add_error_handler(error_handler)

    logger.info("Bot đang khởi động...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
