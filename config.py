import os
from dotenv import load_dotenv

load_dotenv()

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Football API (football-data.org)
FOOTBALL_API_KEY = os.getenv("FOOTBALL_API_KEY", "")
FOOTBALL_API_BASE = "https://api.football-data.org/v4"

# Theo dõi các giải đấu (competition codes)
# PL=Premier League, CL=Champions League, WC=World Cup, PD=La Liga, BL1=Bundesliga
WATCHED_COMPETITIONS = os.getenv(
    "WATCHED_COMPETITIONS", "PL,CL,WC"
).split(",")

# Cài đặt điểm
POINTS_DEDUCT = 50          # Điểm trừ khi đoán sai / không đoán
POLL_OPEN_HOURS_BEFORE = 12  # Mở poll trước trận bao nhiêu tiếng
POLL_CLOSE_MINUTES_BEFORE = 5  # Đóng poll trước giờ đá bao nhiêu phút
CHAT_THREAD_ID = int(os.getenv("CHAT_THREAD_ID", "0")) or None


# Cơ sở dữ liệu
DB_PATH = os.getenv("DB_PATH", "football_bot.db")

# Múi giờ (Asia/Ho_Chi_Minh = UTC+7)
TIMEZONE = "Asia/Ho_Chi_Minh"

# Whitelist người chơi — chỉ các user_id này mới được tương tác với bot
ALLOWED_USER_IDS = {
    1682575734,  # Alie
    822425008,   # Andy
    5200492637,  # Aron
    1800116341,  # Bugi | Coincu
    5138244411,  # Hercules
    1528481986,  # Kien Vu
    5031836927,  # Leonn
    1065810166,  # Thana Who
    1762927178,  # Tommy
    934622455,   # Vịt Tư Mã
    8814280223,  # Zane
}
