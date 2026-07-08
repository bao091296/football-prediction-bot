"""
Chạy trước bot.py: seed đúng dữ liệu 8 voters + 2 trận 29/06.
Dùng UPSERT nên an toàn khi chạy nhiều lần.
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

# Brazil vs Japan: HOME_WIN (2-1 trong 90 phút)
# Germany vs Paraguay: DRAW (1-1 trong 90 phút)
MATCHES = [
    {
        "ext_id": "553123", "home": "Brazil", "away": "Japan",
        "time": "2026-06-29T17:00:00Z", "result": "HOME_WIN",
        "hs": 2, "as_": 1,
        "preds": {
            8814280223:"HOME_WIN", 1682575734:"HOME_WIN", 822425008:"HOME_WIN",
            5200492637:"HOME_WIN", 5138244411:"HOME_WIN",
            1800116341:"DRAW",    1762927178:"DRAW",     934622455:"DRAW",
        },
    },
    {
        "ext_id": "553124", "home": "Germany", "away": "Paraguay",
        "time": "2026-06-29T20:30:00Z", "result": "DRAW",
        "hs": 1, "as_": 1,
        "preds": {
            8814280223:"AWAY_WIN", 1682575734:"HOME_WIN", 822425008:"HOME_WIN",
            5200492637:"HOME_WIN", 5138244411:"HOME_WIN", 1800116341:"HOME_WIN",
            1762927178:"HOME_WIN", 934622455:"HOME_WIN",
        },
    },
]

# Tính điểm kỳ vọng cho từng voter (áp dụng luật mới: all-correct/all-wrong → ±0)
def calc_expected():
    pts = {uid: 0.0 for uid, _, _ in VOTERS}
    for m in MATCHES:
        result  = m["result"]
        preds   = m["preds"]
        correct = [u for u, p in preds.items() if p == result]
        wrong   = [u for u, p in preds.items() if p != result]
        # Luật mới: tất cả đúng hoặc tất cả sai → không tính điểm
        if not correct or not wrong:
            continue
        gain = len(wrong) * DEDUCT / len(correct)
        for uid, pred in preds.items():
            pts[uid] += gain if pred == result else -DEDUCT
    return pts

async def main():
    print("=== migrate.py bắt đầu ===", flush=True)

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Chỉ chạy nếu chưa có predictions cho 2 trận lịch sử
        async with db.execute(
            "SELECT COUNT(*) as c FROM predictions p "
            "JOIN matches m ON p.match_id=m.match_id "
            "WHERE m.ext_id IN ('553123','553124')"
        ) as cur:
            row = await cur.fetchone()
            if row["c"] >= 16:
                print("✅ Dữ liệu lịch sử đã có, bỏ qua.", flush=True)
                return

        print("🔄 Seed dữ liệu lịch sử lần đầu...", flush=True)

        expected = calc_expected()

        # Chỉ INSERT user nếu chưa tồn tại, KHÔNG ghi đè điểm
        for uid, uname, fname in VOTERS:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, username, full_name, points) VALUES (?,?,?,0)",
                (uid, uname, fname)
            )
            print(f"  ✓ {fname} ({uid}) — đã insert (nếu chưa có)", flush=True)

        # UPSERT matches với kết quả đúng
        for m in MATCHES:
            await db.execute(
                "INSERT INTO matches (ext_id,home_team,away_team,competition,match_time,status,result,home_score,away_score) "
                "VALUES (?,?,?,'WC',?,'FINISHED',?,?,?) "
                "ON CONFLICT(ext_id) DO UPDATE SET status='FINISHED',result=excluded.result,"
                "home_score=excluded.home_score,away_score=excluded.away_score",
                (m["ext_id"],m["home"],m["away"],m["time"],m["result"],m["hs"],m["as_"])
            )
            async with db.execute("SELECT match_id FROM matches WHERE ext_id=?", (m["ext_id"],)) as cur:
                match_id = (await cur.fetchone())[0]

            result  = m["result"]
            preds   = m["preds"]
            correct = [u for u, p in preds.items() if p == result]
            wrong   = [u for u, p in preds.items() if p != result]
            # Luật mới: tất cả đúng hoặc tất cả sai → ±0
            no_change = not correct or not wrong
            gain = (len(wrong) * DEDUCT / len(correct)) if (correct and not no_change) else 0

            for uid, pred in preds.items():
                is_c  = 1 if pred == result else 0
                delta = 0 if no_change else (gain if is_c else -DEDUCT)
                await db.execute(
                    "INSERT INTO predictions (user_id,match_id,prediction,is_correct,points_delta) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(user_id,match_id) DO UPDATE SET prediction=excluded.prediction,"
                    "is_correct=excluded.is_correct,points_delta=excluded.points_delta",
                    (uid, match_id, pred, is_c, delta)
                )

            print(f"⚽ {m['home']} vs {m['away']}: {len(correct)} đúng (+{gain:.1f}đ), {len(wrong)} sai (-{DEDUCT}đ)", flush=True)

        # Cập nhật điểm ban đầu từ 2 trận lịch sử
        for uid, pts in expected.items():
            await db.execute("UPDATE users SET points=? WHERE user_id=?", (pts, uid))
            print(f"  💰 User {uid}: {pts:+.1f}đ", flush=True)

        await db.commit()

        # In BXH
        print("\n🏆 Bảng xếp hạng sau migrate:", flush=True)
        async with db.execute("SELECT full_name,points FROM users ORDER BY points DESC") as cur:
            for i, row in enumerate(await cur.fetchall(), 1):
                sign = "+" if row["points"] >= 0 else ""
                print(f"  {i}. {row['full_name']}: {sign}{row['points']:.1f}đ", flush=True)

    print("\n✅ Migrate xong!", flush=True)

asyncio.run(main())
