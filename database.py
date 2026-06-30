import aiosqlite
import asyncio
from datetime import datetime
from config import DB_PATH, POINTS_DEDUCT

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                points      REAL DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS matches (
                match_id        INTEGER PRIMARY KEY,
                ext_id          TEXT UNIQUE,           -- ID từ football-data.org (nếu có)
                home_team       TEXT NOT NULL,
                away_team       TEXT NOT NULL,
                competition     TEXT,
                match_time      TEXT NOT NULL,         -- ISO8601 UTC
                status          TEXT DEFAULT 'SCHEDULED', -- SCHEDULED | LIVE | FINISHED | CANCELLED
                result          TEXT,                  -- 'HOME_WIN' | 'DRAW' | 'AWAY_WIN'
                home_score      INTEGER,
                away_score      INTEGER,
                poll_message_id INTEGER,
                chat_id         INTEGER,
                poll_id         TEXT,
                created_at      TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS predictions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL,
                match_id    INTEGER NOT NULL,
                prediction  TEXT NOT NULL,             -- 'HOME_WIN' | 'DRAW' | 'AWAY_WIN'
                is_correct  INTEGER,                   -- NULL=chưa biết, 1=đúng, 0=sai
                points_delta REAL,                     -- điểm được cộng/trừ
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(user_id, match_id)
            );

            CREATE TABLE IF NOT EXISTS group_settings (
                chat_id             INTEGER PRIMARY KEY,
                competition_filter  TEXT,              -- JSON list các giải theo dõi
                auto_poll           INTEGER DEFAULT 1,
                registered_at       TEXT DEFAULT (datetime('now'))
            );
        """)
        await db.commit()


# ── Users ──────────────────────────────────────────────────────────────────────

async def upsert_user(user_id: int, username: str, full_name: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (user_id, username, full_name)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username  = excluded.username,
                full_name = excluded.full_name
        """, (user_id, username, full_name))
        await db.commit()


async def get_user(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_leaderboard(limit: int = 20) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT user_id, username, full_name, points
            FROM users
            ORDER BY points DESC
            LIMIT ?
        """, (limit,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Matches ────────────────────────────────────────────────────────────────────

async def upsert_match(
    home_team: str,
    away_team: str,
    match_time: str,           # ISO8601 UTC string
    competition: str = "",
    ext_id: str | None = None,
    chat_id: int | None = None,
) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        if ext_id:
            await db.execute("""
                INSERT INTO matches (ext_id, home_team, away_team, competition, match_time, chat_id)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(ext_id) DO UPDATE SET
                    home_team   = excluded.home_team,
                    away_team   = excluded.away_team,
                    competition = excluded.competition,
                    match_time  = excluded.match_time,
                    chat_id     = COALESCE(matches.chat_id, excluded.chat_id)
            """, (ext_id, home_team, away_team, competition, match_time, chat_id))
        else:
            await db.execute("""
                INSERT INTO matches (home_team, away_team, competition, match_time, chat_id)
                VALUES (?, ?, ?, ?, ?)
            """, (home_team, away_team, competition, match_time, chat_id))
        await db.commit()

        if ext_id:
            async with db.execute("SELECT match_id FROM matches WHERE ext_id = ?", (ext_id,)) as cur:
                row = await cur.fetchone()
                return row[0]
        else:
            async with db.execute("SELECT last_insert_rowid()") as cur:
                row = await cur.fetchone()
                return row[0]


async def get_match(match_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_upcoming_matches_to_poll(now_utc: datetime) -> list[dict]:
    """Lấy các trận chưa tạo poll mà cần tạo (trong 12h tới)."""
    from config import POLL_OPEN_HOURS_BEFORE
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        now_str = now_utc.strftime("%Y-%m-%d %H:%M:%S")
        async with db.execute("""
            SELECT * FROM matches
            WHERE status = 'SCHEDULED'
              AND poll_message_id IS NULL
              AND chat_id IS NOT NULL
              AND datetime(match_time) <= datetime(?, '+{} hours')
              AND datetime(match_time) > datetime(?, '-2 hours')
        """.format(POLL_OPEN_HOURS_BEFORE),
            (now_str, now_str)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def save_poll_info(match_id: int, poll_message_id: int, poll_id: str, chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE matches SET poll_message_id = ?, poll_id = ?, chat_id = ?
            WHERE match_id = ?
        """, (poll_message_id, poll_id, chat_id, match_id))
        await db.commit()


async def get_match_by_poll(poll_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE poll_id = ?", (poll_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def update_match_result(match_id: int, result: str, home_score: int, away_score: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE matches SET status = 'FINISHED', result = ?, home_score = ?, away_score = ?
            WHERE match_id = ?
        """, (result, home_score, away_score, match_id))
        await db.commit()


async def get_finished_unscored_matches() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT m.* FROM matches m
            WHERE m.status = 'FINISHED'
              AND m.result IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM predictions p
                  WHERE p.match_id = m.match_id AND p.is_correct IS NULL
              )
        """) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_all_scheduled_matches() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT * FROM matches
            WHERE status = 'SCHEDULED'
            ORDER BY match_time
            LIMIT 10
        """) as cur:
            return [dict(r) for r in await cur.fetchall()]


# ── Predictions ────────────────────────────────────────────────────────────────

async def save_prediction(user_id: int, match_id: int, prediction: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO predictions (user_id, match_id, prediction)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, match_id) DO UPDATE SET
                prediction = excluded.prediction,
                is_correct = NULL,
                points_delta = NULL
        """, (user_id, match_id, prediction))
        await db.commit()


async def get_predictions_for_match(match_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT p.*, u.username, u.full_name
            FROM predictions p
            JOIN users u ON u.user_id = p.user_id
            WHERE p.match_id = ?
        """, (match_id,)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def get_user_predictions(user_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("""
            SELECT p.*, m.home_team, m.away_team, m.competition, m.match_time,
                   m.home_score, m.away_score, m.result
            FROM predictions p
            JOIN matches m ON m.match_id = p.match_id
            WHERE p.user_id = ?
            ORDER BY m.match_time DESC
            LIMIT ?
        """, (user_id, limit)) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def settle_match(match_id: int, result: str, all_user_ids: list[int]) -> dict:
    """
    Tính điểm cho một trận đã có kết quả.
    Người đoán đúng: +delta, người đoán sai/không đoán: -POINTS_DEDUCT
    Trả về dict summary.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        # Lấy tất cả dự đoán của trận
        async with db.execute(
            "SELECT * FROM predictions WHERE match_id = ?", (match_id,)
        ) as cur:
            preds = {r["user_id"]: r["prediction"] for r in await cur.fetchall()}

        correct_users = [uid for uid, pred in preds.items() if pred == result]
        wrong_users   = [uid for uid, pred in preds.items() if pred != result]
        no_pred_users = [uid for uid in all_user_ids if uid not in preds]

        total_losers = len(wrong_users) + len(no_pred_users)

        # Nếu tất cả đúng hoặc tất cả sai/không vote → không tính điểm
        all_correct = total_losers == 0 and len(correct_users) > 0
        all_wrong   = len(correct_users) == 0
        no_change   = all_correct or all_wrong

        total_deducted  = 0 if no_change else total_losers * POINTS_DEDUCT
        gain_per_winner = (total_deducted / len(correct_users)) if (correct_users and not no_change) else 0

        if not no_change:
            # Cập nhật điểm và đánh dấu dự đoán
            for uid in correct_users:
                await db.execute("""
                    UPDATE predictions SET is_correct = 1, points_delta = ?
                    WHERE user_id = ? AND match_id = ?
                """, (gain_per_winner, uid, match_id))
                await db.execute(
                    "UPDATE users SET points = points + ? WHERE user_id = ?",
                    (gain_per_winner, uid)
                )

            for uid in wrong_users:
                await db.execute("""
                    UPDATE predictions SET is_correct = 0, points_delta = ?
                    WHERE user_id = ? AND match_id = ?
                """, (-POINTS_DEDUCT, uid, match_id))
                await db.execute(
                    "UPDATE users SET points = points - ? WHERE user_id = ?",
                    (POINTS_DEDUCT, uid)
                )

            # Người không đoán: trừ điểm nhưng KHÔNG insert prediction
            for uid in no_pred_users:
                await db.execute(
                    "UPDATE users SET points = points - ? WHERE user_id = ?",
                    (POINTS_DEDUCT, uid)
                )
        else:
            # Vẫn đánh dấu is_correct nhưng delta = 0
            for uid in correct_users:
                await db.execute("""
                    UPDATE predictions SET is_correct = 1, points_delta = 0
                    WHERE user_id = ? AND match_id = ?
                """, (uid, match_id))
            for uid in wrong_users:
                await db.execute("""
                    UPDATE predictions SET is_correct = 0, points_delta = 0
                    WHERE user_id = ? AND match_id = ?
                """, (uid, match_id))

        await db.commit()

    return {
        "correct": correct_users,
        "wrong": wrong_users,
        "no_pred": no_pred_users,
        "gain_per_winner": gain_per_winner,
        "total_deducted": total_deducted,
        "no_change": no_change,
    }


# ── Group settings ─────────────────────────────────────────────────────────────

async def register_group(chat_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO group_settings (chat_id) VALUES (?)
        """, (chat_id,))
        await db.commit()


async def get_all_groups() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT chat_id FROM group_settings WHERE auto_poll = 1") as cur:
            return [r[0] for r in await cur.fetchall()]


async def get_all_active_users() -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT user_id FROM users") as cur:
            return [r[0] for r in await cur.fetchall()]


async def get_match_by_ext_id(ext_id: str) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM matches WHERE ext_id = ?", (ext_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def get_users_by_ids(user_ids: list[int]) -> dict[int, dict]:
    """Trả về {user_id: user_dict} cho danh sách IDs."""
    if not user_ids:
        return {}
    placeholders = ",".join("?" * len(user_ids))
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            f"SELECT * FROM users WHERE user_id IN ({placeholders})", user_ids
        ) as cur:
            return {r["user_id"]: dict(r) for r in await cur.fetchall()}


async def is_match_settled(match_id: int) -> bool:
    """Trả về True nếu trận đã được tính điểm (tất cả prediction đã có is_correct)."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) FROM predictions
            WHERE match_id = ? AND is_correct IS NULL
        """, (match_id,)) as cur:
            count = (await cur.fetchone())[0]
        async with db.execute(
            "SELECT status FROM matches WHERE match_id = ?", (match_id,)
        ) as cur:
            row = await cur.fetchone()
            status = row[0] if row else None
        return status == "FINISHED" and count == 0
