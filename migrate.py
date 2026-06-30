"""
Chạy trước bot.py: xoá sạch DB và seed đúng dữ liệu 2 trận 29/06.
Chỉ chạy nếu chưa có dữ liệu (predictions = 0).
"""
import asyncio, aiosqlite, os, sys

DB_PATH = os.getenv("DB_PATH", "football_bot.db")
DEDUCT  = 50

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

# Brazil vs Japan: HOME_WIN (2-1)
# Germany vs Paraguay: DRAW (1-1 trong 90 phút)
MATCHES = [
    {
        "ext_id": "553123", "home": "Brazil", "away": "Japan",
        "time": "2026-06-29T17:00:00Z", "result": "HOME_WIN",
        "hs": 2, "as": 1,
        "preds": {
            8814280223:"HOME_WIN", 1682575734:"HOME_WIN", 822425008:"HOME_WIN",
            5200492637:"HOME_WIN", 5138244411:"HOME_WIN",
            1800116341:"DRAW",    1762927178:"DRAW",     934622455:"DRAW",
        },
    },
    {
        "ext_id": "553124", "home": "Germany", "away": "Paraguay",
        "time": "2026-06-29T20:30:00Z", "result": "DRAW",
        "hs": 1, "as": 1,
        "preds": {
            8814280223:"AWAY_WIN", 1682575734:"HOME_WIN", 822425008:"HOME_WIN",
            5200492637:"HOME_WIN", 5138244411:"HOME_WIN", 1800116341:"HOME_WIN",
            1762927178:"HOME_WIN", 934622455:"HOME_WIN",
        },
    },
]

async def main():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Kiểm tra xem đã seed chưa (đúng dữ liệu)
        async with db.execute(
            "SELECT COUNT(*) as c FROM predictions p "
            "JOIN matches m ON p.match_id=m.match_id "
            "WHERE m.ext_id IN ('553123','553124') AND p.user_id > 0"
        ) as cur:
            row = await cur.fetchone()
            if row["c"] >= 16:   # 8 preds × 2 trận
                print("✅ Dữ liệu lịch sử đã đúng, bỏ qua migrate.")
                return

        print("🔄 Bắt đầu migrate dữ liệu lịch sử 29/06...")

        # Xoá sạch dữ liệu cũ (kể cả fake ID)
        await db.execute("DELETE FROM predictions")
        await db.execute("DELETE FROM users")
        await db.execute(
            "UPDATE matches SET status='SCHEDULED',result=NULL,home_score=NULL,away_score=NULL "
            "WHERE ext_id IN ('553123','553124')"
        )

        # Insert 8 voters
        for uid, uname, fname in VOTERS:
            await db.execute(
                "INSERT INTO users (user_id,username,full_name,points) VALUES (?,?,?,0)",
                (uid, uname, fname)
            )

        # Tính và insert predictions + điểm cho từng trận
        for m in MATCHES:
            await db.execute(
                "INSERT INTO matches (ext_id,home_team,away_team,competition,match_time,status,result,home_score,away_score) "
                "VALUES (?,?,?,'WC',?,'FINISHED',?,?,?) "
                "ON CONFLICT(ext_id) DO UPDATE SET status='FINISHED',result=excluded.result,"
                "home_score=excluded.home_score,away_score=excluded.away_score",
                (m["ext_id"],m["home"],m["away"],m["time"],m["result"],m["hs"],m["as"])
            )
            async with db.execute("SELECT match_id FROM matches WHERE ext_id=?", (m["ext_id"],)) as cur:
                match_id = (await cur.fetchone())[0]

            preds   = m["preds"]
            correct = [uid for uid,p in preds.items() if p == m["result"]]
            wrong   = [uid for uid,p in preds.items() if p != m["result"]]
            gain    = (len(wrong) * DEDUCT / len(correct)) if correct else 0

            for uid, pred in preds.items():
                is_c  = 1 if pred == m["result"] else 0
                delta = gain if is_c else -DEDUCT
                await db.execute(
                    "INSERT INTO predictions (user_id,match_id,prediction,is_correct,points_delta) VALUES (?,?,?,?,?)",
                    (uid, match_id, pred, is_c, delta)
                )
                await db.execute("UPDATE users SET points=points+? WHERE user_id=?", (delta, uid))

            print(f"⚽ {m['home']} vs {m['away']}: {len(correct)} đúng (+{gain:.1f}đ), {len(wrong)} sai (-{DEDUCT}đ)")

        await db.commit()

        # In BXH
        print("\n🏆 Bảng xếp hạng sau migrate:")
        async with db.execute("SELECT full_name,points FROM users ORDER BY points DESC") as cur:
            for i, row in enumerate(await cur.fetchall(), 1):
                sign = "+" if row["points"] >= 0 else ""
                print(f"  {i}. {row['full_name']}: {sign}{row['points']:.1f}đ")

        print("\n✅ Migrate xong!")

asyncio.run(main())
