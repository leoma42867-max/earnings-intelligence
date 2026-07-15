"""Collect daily Yahoo Finance trending ranks for tracked tickers.

Yahoo does not publish raw per-ticker search counts like StockTwits message
streams do. The closest public equivalent is Yahoo Finance's **trending
symbols** feed — a ranked list (up to ~100 US symbols) driven by search
volume, news, and trading activity on Yahoo Finance itself.

We snapshot each ticker's position on that list once per refresh (rank 1 =
most searched on Yahoo). Tickers outside the top 100 are stored with a
``NULL`` rank for that day so a later drop-off is visible in history.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import requests

from config.settings import TICKER_UNIVERSE_SIZE


_TRENDING_URL = "https://query1.finance.yahoo.com/v1/finance/trending/US"
_USER_AGENT = "earnings-intelligence-platform/1.0"
# Yahoo's trending endpoint accepts ``count``; 100 matches our universe size.
_TRENDING_COUNT = TICKER_UNIVERSE_SIZE

RANK_COLUMNS = ["date", "ticker", "yahoo_trend_rank"]


def fetch_yahoo_trend_ranks(
    tickers: list[str],
    metric_date: str | None = None,
    timeout: float = 10.0,
) -> pd.DataFrame:
    """Return today's Yahoo Finance trend rank for each requested ticker.

    Args:
        tickers: Symbols to score (normally the current earnings universe).
        metric_date: ISO date for the snapshot (defaults to today, UTC-local).

    Returns:
        DataFrame with columns ``date``, ``ticker``, ``yahoo_trend_rank``.
        Rank is ``1`` for the #1 trending symbol on Yahoo Finance; ``NULL``
        when the ticker is not in the current top-100 trending list.
    """
    snapshot_date = metric_date or date.today().isoformat()
    rank_by_ticker = _fetch_trending_equity_ranks()
    # API/network failure → empty frame so the pipeline skips the upsert and
    # keeps yesterday's ranks instead of writing an all-NULL wipe for today.
    if rank_by_ticker is None:
        return pd.DataFrame(columns=RANK_COLUMNS)

    records = [
        {
            "date": snapshot_date,
            "ticker": ticker.strip().upper(),
            "yahoo_trend_rank": rank_by_ticker.get(ticker.strip().upper()),
        }
        for ticker in tickers
        if ticker.strip()
    ]
    return pd.DataFrame(records, columns=RANK_COLUMNS)


def _fetch_trending_equity_ranks() -> dict[str, int] | None:
    """Return ``{ticker: rank}`` for Yahoo Finance's current US trending list.

    Returns ``None`` when the request fails so callers can avoid overwriting
    prior successful snapshots with an all-null day.
    """
    try:
        response = requests.get(
            _TRENDING_URL,
            params={"count": _TRENDING_COUNT},
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"Warning: Yahoo Finance trending symbols unavailable: {exc}")
        return None

    quotes = payload.get("finance", {}).get("result", [{}])[0].get("quotes", [])
    ranks: dict[str, int] = {}
    rank = 1
    for quote in quotes:
        symbol = str(quote.get("symbol", "")).strip().upper()
        if not symbol or not _looks_like_equity(symbol):
            continue
        if symbol not in ranks:
            ranks[symbol] = rank
            rank += 1
    return ranks


def _looks_like_equity(symbol: str) -> bool:
    """Filter out crypto pairs and other non-equity trending symbols."""
    if "-" in symbol:
        return False
    if symbol.endswith("=X") or symbol.startswith("^"):
        return False
    return True
