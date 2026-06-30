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
                        results.append(_parse_match(m, comp))
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
                        results.append(_parse_match(m, comp))
            except Exception:
                continue
    return results


def _parse_match(m: dict, competition: str) -> dict:
    score = m.get("score", {})

    # Ưu tiên regularTime (đúng 90 phút), fallback về fullTime
    reg  = score.get("regularTime", {}) or {}
    full = score.get("fullTime", {}) or {}
    home_score = reg.get("home") if reg.get("home") is not None else full.get("home")
    away_score = reg.get("away") if reg.get("away") is not None else full.get("away")

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
        "match_time": m["utcDate"],   # ISO8601 UTC
        "status":     m["status"],
        "result":     outcome,
        "home_score": home_score,
        "away_score": away_score,
    }
