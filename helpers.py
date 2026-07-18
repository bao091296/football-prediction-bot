from datetime import datetime, timezone
import pytz
from config import TIMEZONE

_tz = pytz.timezone(TIMEZONE)

PRED_CODE_TO_LABEL = {
    "HOME_WIN": "Thắng đội nhà",
    "DRAW":     "🤝 Hòa",
    "AWAY_WIN": "Thắng đội khách",
}

OPTION_INDEX_TO_CODE = {
    0: "HOME_WIN",
    1: "DRAW",
    2: "AWAY_WIN",
}

CODE_TO_OPTION_INDEX = {v: k for k, v in OPTION_INDEX_TO_CODE.items()}


def utc_to_local(utc_str: str) -> datetime:
    dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    return dt.astimezone(_tz)


def format_match_time(utc_str: str) -> str:
    local = utc_to_local(utc_str)
    return local.strftime("%d/%m/%Y %H:%M")


STAGE_LABEL = {
    "QUARTER_FINALS": "Tứ kết 🔥 ±100đ",
    "SEMI_FINALS":    "Bán kết 💥 ±150đ",
    "THIRD_PLACE":    "Hạng ba 🏆 ±300đ",
    "FINAL":          "Chung kết 🏆 ±300đ",
}

def build_poll_question(home: str, away: str, competition: str, match_time: str, stage: str = "GROUP_STAGE") -> str:
    time_str  = format_match_time(match_time)
    comp_str  = f"[{competition}] " if competition else ""
    stage_str = STAGE_LABEL.get(stage, "")
    suffix    = f"\n🎯 {stage_str}" if stage_str else ""
    return f"⚽ {comp_str}{home} vs {away}\n🕐 {time_str} (VN){suffix}"


def build_result_text(match: dict, summary: dict) -> str:
    home = match["home_team"]
    away = match["away_team"]
    hs   = match["home_score"]
    as_  = match["away_score"]
    result_label = PRED_CODE_TO_LABEL.get(match["result"], match["result"])

    lines = [
        f"📊 <b>Kết quả: {home} {hs}-{as_} {away}</b>",
        f"🏆 Kết quả dự đoán đúng: <b>{result_label}</b>",
        "",
    ]

    correct = summary["correct"]
    wrong   = summary["wrong"]
    no_pred = summary["no_pred"]
    gain    = summary["gain_per_winner"]

    lines.append(f"✅ Đoán đúng ({len(correct)} người): +{gain:.1f} điểm/người")
    lines.append(f"❌ Đoán sai ({len(wrong)} người): -50 điểm/người")
    lines.append(f"⏭️ Không đoán ({len(no_pred)} người): -50 điểm/người")
    lines.append(f"\n💰 Tổng điểm phạt: {summary['total_deducted']:.0f} điểm")
    return "\n".join(lines)


def build_poll_options(home_team: str, away_team: str) -> list[str]:
    return [
        f"🏆 {home_team} thắng",
        "🤝 Hòa",
        f"🏆 {away_team} thắng",
    ]


def name_display(user: dict) -> str:
    return user.get("full_name") or user.get("username") or f"#{user['user_id']}"
