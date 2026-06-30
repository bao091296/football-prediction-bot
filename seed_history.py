"""
Seed dữ liệu lịch sử 2 trận tối 29/06/2026.
Chạy một lần duy nhất: railway run python3 seed_history.py
"""
import asyncio
import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "football_bot.db")

# ── Dữ liệu vote từ screenshot ─────────────────────────────────────────────────

# user_id tạm dùng số âm, sẽ merge khi user /start trên bot
USERS = [
    (-1, "zane",         "Zane"),
    (-2, "alie",         "Alie 🅱"),
    (-3, "coincu_anhan", "Coincu Anh An"),
    (-4, "aron",         "Aron"),
    (-5, "coincu_quyn",  "Coincu Quyn"),
    (-6, "bugi_coincu",  "Bugi | Coincu"),
    (-7, "tommy",        "Tommy 🐾"),
    (-8, "tran_son",     "Trần Sơn"),
]

# Trận 1: Brazil vs Japan — kết quả: HOME_WIN (Brazil thắng 2-1)
MATCH_1 = {
    "ext_id":     "553123",   # ext_id thực từ API
    "home_team":  "Brazil",
    "away_team":  "Japan",
    "competition": "WC",
    "match_time": "2026-06-29T17:00:00Z",
    "result":     "HOME_WIN",
    "home_score": 2,
    "away_score": 1,
}
# HOME_WIN=0, DRAW=1, AWAY_WIN=2 (theo index option poll)
PREDS_1 = {
    -1: "HOME_WIN",  # Zane        → đúng
    -2: "HOME_WIN",  # Alie        → đúng
    -3: "HOME_WIN",  # Coincu Anh An → đúng
    -4: "HOME_WIN",  # Aron        → đúng
    -5: "HOME_WIN",  # Coincu Quyn → đúng
    -6: "DRAW",      # Bugi|Coincu → sai
    -7: "DRAW",      # Tommy       → sai
    -8: "DRAW",      # Trần Sơn    → sai
}

# Trận 2: Germany vs Paraguay — kết quả: AWAY_WIN (Paraguay thắng 4-5)
MATCH_2 = {
    "ext_id":     "553124",
    "home_team":  "Germany",
    "away_team":  "Paraguay",
    "competition": "WC",
    "match_time": "2026-06-29T20:30:00Z",
    "result":     "AWAY_WIN",
    "home_score": 4,
    "away_score": 5,
}
PREDS_2 = {
    -6: "HOME_WIN",  # Bugi|Coincu → sai
    -7: "HOME_WIN",  # Tommy       → sai
    -2: "HOME_WIN",  # Alie        → sai
    -3: "HOME_WIN",  # Coincu Anh An → sai
    -4: "HOME_WIN",  # Aron        → sai
    -8: "HOME_WIN",  # Trần Sơn    → sai
    -5: "HOME_WIN",  # Coincu Quyn → sai
    -1: "AWAY_WIN",  # Zane        → đúng
}

POINTS_DEDUCT = 50


async def seed():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # 1. Insert users (bỏ qua nếu đã có)
        for uid, username, full_name in USERS:
            await db.execute("""
                INSERT OR IGNORE INTO users (user_id, username, full_name, points)
                VALUES (?, ?, ?, 0)
            """, (uid, username, full_name))

        # 2. Xử lý từng trận
        for match_data, preds in [(MATCH_1, PREDS_1), (MATCH_2, PREDS_2)]:
            # Upsert match
            await db.execute("""
                INSERT INTO matches
                    (ext_id, home_team, away_team, competition, match_time,
                     status, result, home_score, away_score)
                VALUES (?, ?, ?, ?, ?, 'FINISHED', ?, ?, ?)
                ON CONFLICT(ext_id) DO UPDATE SET
                    status     = 'FINISHED',
                    result     = excluded.result,
                    home_score = excluded.home_score,
                    away_score = excluded.away_score
            """, (
                match_data["ext_id"], match_data["home_team"], match_data["away_team"],
                match_data["competition"], match_data["match_time"],
                match_data["result"], match_data["home_score"], match_data["away_score"],
            ))

            # Lấy match_id
            async with db.execute(
                "SELECT match_id FROM matches WHERE ext_id = ?", (match_data["ext_id"],)
            ) as cur:
                row = await cur.fetchone()
                match_id = row[0]

            result = match_data["result"]
            correct = [uid for uid, pred in preds.items() if pred == result]
            wrong   = [uid for uid, pred in preds.items() if pred != result]
            total_deducted  = len(wrong) * POINTS_DEDUCT
            gain_per_winner = total_deducted / len(correct) if correct else 0

            # Insert predictions + cập nhật điểm
            for uid, pred in preds.items():
                is_correct = 1 if pred == result else 0
                delta = gain_per_winner if is_correct else -POINTS_DEDUCT
                await db.execute("""
                    INSERT INTO predictions (user_id, match_id, prediction, is_correct, points_delta)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, match_id) DO UPDATE SET
                        prediction   = excluded.prediction,
                        is_correct   = excluded.is_correct,
                        points_delta = excluded.points_delta
                """, (uid, match_id, pred, is_correct, delta))

                await db.execute(
                    "UPDATE users SET points = points + ? WHERE user_id = ?",
                    (delta, uid)
                )

            print(f"✅ {match_data['home_team']} vs {match_data['away_team']}: "
                  f"Đúng {len(correct)} (+{gain_per_winner:.1f}đ), Sai {len(wrong)} (-50đ)")

        await db.commit()

        # 3. In bảng xếp hạng
        print("\n🏆 Bảng xếp hạng sau 2 trận:")
        async with db.execute(
            "SELECT full_name, points FROM users ORDER BY points DESC"
        ) as cur:
            for i, row in enumerate(await cur.fetchall(), 1):
                sign = "+" if row[0] >= 0 else ""
                print(f"  {i}. {row['full_name']}: {sign}{row[1]:.1f}đ")


asyncio.run(seed())
