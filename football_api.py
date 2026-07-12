"""
Wrapper cho football-data.org API v4.
Free tier: 10 req/min, dữ liệu chậm ~1 phút.
"""

import ssl
import certifi
import aiohttp
from datetime import datetime, timezone, timedelta
from config import FOOTBALL_API_KEY, FOOTBALL_API_BASE, WATCHED_COMPETITIONS

HEADERS = {"X-Auth-Token": FOOTBALL_API_KEY}


async def fetch_upcoming_matches(days_ahead: int = 2) -> list[dict]:
    """Lấy các trận sắp diễn ra trong `days_ahead` ngày tới."""
    now = datetime.now(timezone.utc)
    date_from = now.strftime("%Y-%m-%d")
    date_to   = (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    results = []
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        for comp in WATCHED_COMPETITIONS:
            comp = comp.strip()
            if not comp:
                continue
            url = f"{FOOTBALL_API_BASE}/competitions/{comp}/matches"
            params = {"dateFrom": date_from, "dateTo": date_to, "status": "SCHEDULED"}
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    for m in data.get("matches", []):
                        parsed = _parse_match(m, comp)
                        # Bỏ qua trận chưa có tên đội (TBD)
                        if parsed["home_team"] and parsed["away_team"]:
                            results.append(parsed)
            except Exception:
                continue
    return results


async def fetch_finished_matches(days_back: int = 1) -> list[dict]:
    """Lấy kết quả các trận vừa kết thúc."""
    now = datetime.now(timezone.utc)
    date_from = (now - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to   = now.strftime("%Y-%m-%d")

    results = []
    ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(headers=HEADERS, connector=connector, timeout=timeout) as session:
        for comp in WATCHED_COMPETITIONS:
            comp = comp.strip()
            if not comp:
                continue
            url = f"{FOOTBALL_API_BASE}/competitions/{comp}/matches"
            params = {"dateFrom": date_from, "dateTo": date_to, "status": "FINISHED"}
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        continue
                    data = await resp.json()
                    for m in data.get("matches", []):
                        parsed = _parse_match(m, comp)
                        if parsed["home_team"] and parsed["away_team"]:
                            results.append(parsed)
            except Exception:
                continue
    return results


def _parse_match(m: dict, competition: str) -> dict:
    score    = m.get("score", {})
    duration = score.get("duration", "REGULAR")  # REGULAR | EXTRA_TIME | PENALTY_SHOOTOUT

    reg  = score.get("regularTime", {}) or {}
    full = score.get("fullTime", {}) or {}

    if duration in ("EXTRA_TIME", "PENALTY_SHOOTOUT"):
        # fullTime của API = kết quả SAU hiệp phụ/penalty → phải dùng regularTime (90 phút)
        home_score = reg.get("home")
        away_score = reg.get("away")
        # Một số trận API trả regularTime=null dù duration=EXTRA_TIME
        # → trận đi ET tức là hòa sau 90 phút, fallback về halfTime score
        if home_score is None or away_score is None:
            ht = score.get("halfTime", {}) or {}
            home_score = ht.get("home")
            away_score = ht.get("away")
    else:
        # Trận kết thúc trong 90 phút → fullTime chính là 90 phút
        home_score = full.get("home")
        away_score = full.get("away")

    # Tính kết quả chỉ theo 90 phút → giữ "Hòa" cho knockout
    outcome = None
    if home_score is not None and away_score is not None:
        if home_score > away_score:
            outcome = "HOME_WIN"
        elif home_score < away_score:
            outcome = "AWAY_WIN"
        else:
            outcome = "DRAW"

    return {
        "ext_id":     str(m["id"]),
        "home_team":  m["homeTeam"]["name"],
        "away_team":  m["awayTeam"]["name"],
        "competition": competition,
        "match_time": m["utcDate"],
        "status":     m["status"],
        "stage":      m.get("stage", "GROUP_STAGE"),
        "result":     outcome,
        "home_score": home_score,
        "away_score": away_score,
    }
