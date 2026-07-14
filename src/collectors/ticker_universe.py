"""Build a dynamic universe of the most-discussed / most-active US equities.

Earlier versions of this project tracked a fixed list of ~30 large-cap
tickers. That misses the point of an *attention* platform — a stock nobody
hardcoded into a watchlist can still be exactly the kind of unusually-hyped
name this project is meant to surface. This module replaces the static list
with two free, unauthenticated, live signals combined into one ranked pool:

- **StockTwits trending symbols** — StockTwits' own trending algorithm
  (message/watch-count velocity). This is a direct social "hype" signal, but
  the public endpoint always returns a fixed ~30 symbols, however large a
  limit is requested.
- **Yahoo Finance "most actives" screener** — the highest-volume US equities
  today. A market-side proxy for what's currently getting attention, capable
  of filling out the rest of the list.

Results are merged (StockTwits trending ranked first, since it is the more
direct "hype" signal), de-duplicated, and capped at ``limit``. If both
sources fail — e.g. a network outage — callers fall back to a small static
watchlist so the pipeline always has *something* to work with rather than
collecting zero data for a day.
"""

from __future__ import annotations

import requests
import yfinance as yf


_TRENDING_URL = "https://api.stocktwits.com/api/2/trending/symbols.json"
_USER_AGENT = "earnings-intelligence-platform/1.0"

# Used only if both live sources fail (e.g. an outage). Deliberately small —
# this is a break-glass fallback, not a replacement watchlist.
FALLBACK_TICKERS = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
    "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
    "DIS", "NFLX", "CRM", "AMD", "INTC", "BA", "GS", "C",
    "BAC", "XOM", "CVX", "PFE", "ABBV", "KO", "PEP",
]


def fetch_hyped_tickers(limit: int = 100) -> list[str]:
    """Return up to ``limit`` tickers most likely to be attracting attention today.

    Combines StockTwits' trending symbols with Yahoo Finance's most-actives
    screener, in that priority order. Falls back to :data:`FALLBACK_TICKERS`
    if both sources fail.
    """
    tickers: list[str] = []
    seen: set[str] = set()

    for symbol in _fetch_stocktwits_trending():
        if symbol and symbol not in seen:
            seen.add(symbol)
            tickers.append(symbol)

    if len(tickers) < limit:
        for symbol in _fetch_yahoo_most_active(limit):
            if len(tickers) >= limit:
                break
            if symbol and symbol not in seen:
                seen.add(symbol)
                tickers.append(symbol)

    if not tickers:
        print("Warning: trending-ticker sources unavailable — using fallback watchlist.")
        return list(FALLBACK_TICKERS)

    return tickers[:limit]


def _fetch_stocktwits_trending() -> list[str]:
    """Return StockTwits' current trending-symbols list (usually ~30 tickers)."""
    try:
        response = requests.get(
            _TRENDING_URL,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"Warning: StockTwits trending symbols unavailable: {exc}")
        return []

    return [
        str(item["symbol"]).strip().upper()
        for item in payload.get("symbols", [])
        # StockTwits' trending feed mixes in crypto and other instrument
        # classes; keep only common stock so earnings lookups aren't wasted
        # on symbols that will never have an earnings date.
        if item.get("symbol") and item.get("instrument_class") == "Stock"
    ]


def _fetch_yahoo_most_active(limit: int) -> list[str]:
    """Return Yahoo Finance's most-actively-traded US equities today."""
    try:
        result = yf.screen("most_actives", count=limit)
    except Exception as exc:
        print(f"Warning: Yahoo Finance most-actives screener unavailable: {exc}")
        return []

    return [
        str(quote["symbol"]).strip().upper()
        for quote in result.get("quotes", [])
        # The screener occasionally mixes in ETFs; keep only individual
        # equities, which are the only ones that can report earnings.
        if quote.get("symbol") and quote.get("quoteType") == "EQUITY"
    ]


# Example:
# from src.collectors.ticker_universe import fetch_hyped_tickers
# fetch_hyped_tickers(100)
