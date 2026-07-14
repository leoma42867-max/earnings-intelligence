"""Collect an upcoming earnings calendar from a replaceable data provider."""

from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import pandas as pd
import yfinance as yf

from config.settings import EARNINGS_FILE, EARNINGS_LOOKAHEAD_DAYS


CALENDAR_COLUMNS = [
    "ticker",
    "company_name",
    "earnings_date",
    "estimated_eps",
    "estimated_revenue",
    "sector",
]


class EarningsCalendarProvider(Protocol):
    """Contract that any earnings-data provider must implement.

    To change data sources later, create another class with a
    ``get_earnings(ticker)`` method that returns a dictionary with the keys
    listed in ``CALENDAR_COLUMNS`` (or ``None`` when no event is available).
    """

    def get_earnings(self, ticker: str) -> dict[str, object] | None:
        """Return the next earnings event and estimates for one ticker."""


class YahooFinanceEarningsProvider:
    """Yahoo Finance implementation of :class:`EarningsCalendarProvider`."""

    def get_earnings(self, ticker: str) -> dict[str, object] | None:
        """Fetch Yahoo Finance's next earnings event and analyst estimates."""
        stock = yf.Ticker(ticker)
        info = stock.info
        earnings_date = _next_earnings_date(stock, info)
        if earnings_date is None:
            return None

        # Yahoo's calendar endpoint sometimes includes revenue and EPS
        # estimates. Missing estimates are left as None instead of guessed.
        calendar = stock.calendar
        calendar_data = calendar if isinstance(calendar, dict) else {}

        return {
            "ticker": ticker,
            "company_name": info.get("shortName", ticker),
            "earnings_date": earnings_date,
            "estimated_eps": _number_or_none(
                calendar_data.get("Earnings Average")
                or info.get("epsForward")
            ),
            "estimated_revenue": _number_or_none(
                calendar_data.get("Revenue Average")
            ),
            "sector": info.get("sector"),
        }


def fetch_upcoming_earnings(
    tickers: list[str] | None = None,
    lookahead_days: int = EARNINGS_LOOKAHEAD_DAYS,
    provider: EarningsCalendarProvider | None = None,
) -> pd.DataFrame:
    """
    Return companies reporting earnings within the specified lookahead window.

    Args:
        tickers: Symbols to check. Uses the starter watchlist when omitted.
        lookahead_days: Number of calendar days to search from today.
        provider: Earnings data source. Defaults to Yahoo Finance.

    Returns:
        A DataFrame with ticker, company name, earnings date, estimated EPS,
        and estimated revenue. Estimates can be blank when unavailable.
    """
    if tickers is None:
        tickers = _default_watchlist()
    if provider is None:
        provider = YahooFinanceEarningsProvider()

    today = date.today()
    cutoff = today + timedelta(days=lookahead_days)
    records: list[dict] = []

    for ticker in tickers:
        symbol = ticker.strip().upper()
        if not symbol:
            continue

        try:
            event = provider.get_earnings(symbol)
            if event is None:
                continue
            earnings_date = pd.Timestamp(event["earnings_date"]).date()
            if today <= earnings_date <= cutoff:
                event["earnings_date"] = earnings_date.isoformat()
                records.append(event)
        except Exception as exc:
            # A failure for one ticker must not block the rest of the calendar.
            print(f"Warning: unable to fetch earnings for {symbol}: {exc}")
            continue

    return pd.DataFrame(records, columns=CALENDAR_COLUMNS)


def save_upcoming_earnings(
    tickers: list[str] | None = None,
    lookahead_days: int = EARNINGS_LOOKAHEAD_DAYS,
    output_path: Path | str = EARNINGS_FILE,
    provider: EarningsCalendarProvider | None = None,
) -> Path:
    """Collect upcoming earnings and save the calendar to a CSV file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    calendar = fetch_upcoming_earnings(tickers, lookahead_days, provider)
    calendar.to_csv(output_path, index=False)
    print(f"Saved {len(calendar)} earnings event(s) → {output_path}")
    return output_path


def _next_earnings_date(stock: yf.Ticker, info: dict) -> date | None:
    """Return the earliest upcoming event date Yahoo provides for a ticker."""
    calendar = stock.calendar
    if isinstance(calendar, dict) and calendar.get("Earnings Date"):
        dates = calendar["Earnings Date"]
        if not isinstance(dates, (list, tuple)):
            dates = [dates]
        upcoming = [
            pd.Timestamp(value).date()
            for value in dates
            if pd.Timestamp(value).date() >= date.today()
        ]
        if upcoming:
            return min(upcoming)

    timestamp = info.get("earningsTimestamp") or info.get("earningsDate")
    if isinstance(timestamp, (list, tuple)):
        timestamp = timestamp[0] if timestamp else None
    if timestamp is None:
        return None
    return pd.Timestamp(timestamp, unit="s").date()


def _number_or_none(value: object) -> float | None:
    """Convert Yahoo's numeric values to floats; preserve unavailable values."""
    if value is None or pd.isna(value):
        return None
    return float(value)


def _default_watchlist() -> list[str]:
    """Small static fallback list used only when no tickers are supplied.

    The live pipeline (``src.pipeline``) always passes its own dynamic
    ~100-ticker "most hyped" candidate list from
    ``src.collectors.ticker_universe``, so this only matters for direct,
    standalone use of this module.
    """
    return [
        "AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA",
        "JPM", "V", "UNH", "JNJ", "WMT", "PG", "MA", "HD",
        "DIS", "NFLX", "CRM", "AMD", "INTC", "BA", "GS", "C",
        "BAC", "XOM", "CVX", "PFE", "ABBV", "KO", "PEP",
    ]


# Example:
# from src.collectors.earnings_calendar import save_upcoming_earnings
# save_upcoming_earnings(["AAPL", "MSFT", "NVDA"])
