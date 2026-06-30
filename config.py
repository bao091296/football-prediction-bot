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


# Cơ sở dữ liệu
DB_PATH = os.getenv("DB_PATH", "football_bot.db")

# Múi giờ (Asia/Ho_Chi_Minh = UTC+7)
TIMEZONE = "Asia/Ho_Chi_Minh"
