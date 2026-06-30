"""
Migration chạy một lần trước khi bot khởi động.
Xoá sạch DB cũ và seed đúng dữ liệu 2 trận 29/06.
"""
import asyncio
import aiosqlite
import os

DB_PATH = os.getenv("DB_PATH", "football_bot.db")
POINTS_DEDUCT = 50

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
        "preds": {
            8814280223: "HOME_WIN",  # Zane   → đúng
            1682575734: "HOME_WIN",  # Alie   → đúng
            822425008:  "HOME_WIN",  # Andy   → đúng
            5200492637: "HOME_WIN",  # Aron   → đúng
            5138244411: "HOME_WIN",  # Hercules → đúng
            1800116341: "DRAW",      # Bugi   → sai
            1762927178: "DRAW",      # Tommy  → sai
            934622455:  "DRAW",      # Vịt Tư Mã → sai
        },
    },
    {
        "ext_id": "553124", "home_team": "Germany", "away_team": "Paraguay",
        "match_time": "2026-06-29T20:30:00Z", "result": "DRAW",
        "home_score": 1, "away_score": 1,
        "preds": {
            8814280223: "AWAY_WIN",  # Zane   → sai
            1682575734: "HOME_WIN",  # Alie   → sai
            822425008:  "HOME_WIN",  # Andy   → sai
            5200492637: "HOME_WIN",  # Aron   → sai
            5138244411: "HOME_WIN",  # Hercules → sai
            1800116341: "HOME_WIN",  # Bugi   → sai
            1762927178: "HOME_WIN",  # Tommy  → sai
            934622455:  "HOME_WIN",  # Vịt Tư Mã → sai
        },
    },
]


async def run():
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row

        # Xoá sạch
        await conn.execute("DELETE FROM predictions")
        await conn.execute("DELETE FROM users")
        await conn.execute(
            "UPDATE matches SET status='SCHEDULED', result=NULL, home_score=NULL, away_score=NULL "
            "WHERE ext_id IN ('553123','553124')"
        )
        await conn.commit()
        print("✅ Đã xoá sạch predictions + users")

        # Seed users
        for uid, username, full_name in USERS:
            await conn.execute(
                "INSERT INTO users (user_id, username, full_name, points) VALUES (?,?,?,0) "
                "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name, points=0",
                (uid, username, full_name)
            )

        # Seed matches + predictions + điểm
        for m in MATCHES:
            await conn.execute("""
                INSERT INTO matches (ext_id,home_team,away_team,competition,match_time,status,result,home_score,away_score)
                VALUES (?,?,?,'WC',?,'FINISHED',?,?,?)
                ON CONFLICT(ext_id) DO UPDATE SET
                    status='FINISHED', result=excluded.result,
                    home_score=excluded.home_score, away_score=excluded.away_score
            """, (m["ext_id"], m["home_team"], m["away_team"], m["match_time"],
                  m["result"], m["home_score"], m["away_score"]))

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
                await conn.execute("""
                    INSERT INTO predictions (user_id, match_id, prediction, is_correct, points_delta)
                    VALUES (?,?,?,?,?)
                    ON CONFLICT(user_id, match_id) DO UPDATE SET
                        prediction=excluded.prediction, is_correct=excluded.is_correct, points_delta=excluded.points_delta
                """, (uid, match_id, pred, is_c, delta))
                await conn.execute(
                    "UPDATE users SET points = points + ? WHERE user_id = ?", (delta, uid)
                )

            print(f"⚽ {m['home_team']} vs {m['away_team']}: {len(correct)} đúng (+{gain:.1f}đ), {len(wrong)} sai (-50đ)")

        await conn.commit()

        # In BXH
        print("\n🏆 Bảng xếp hạng:")
        async with conn.execute("SELECT full_name, points FROM users ORDER BY points DESC") as cur:
            for i, row in enumerate(await cur.fetchall(), 1):
                sign = "+" if row["points"] >= 0 else ""
                print(f"  {i}. {row['full_name']}: {sign}{row['points']:.1f}đ")

asyncio.run(run())
