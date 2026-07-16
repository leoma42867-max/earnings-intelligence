"""Prepare SQLite data for the Streamlit dashboard."""

from __future__ import annotations

import calendar as calendar_module
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

from config.settings import DATABASE_FILE
from src.storage.sqlite_store import SQLiteStore

# Tickers not on Yahoo's trending list are treated as one slot below the
# maximum list size when measuring how many ranks they climbed over 7 days.
_OFF_YAHOO_LIST_RANK = 101
# Keep day cells readable — show the highest-attention tickers first.
_CALENDAR_TICKERS_PER_DAY = 4


def get_last_data_refresh_at(
    database_path: Path | str = DATABASE_FILE,
) -> datetime | None:
    """Return when the SQLite database was last written (UTC).

    The daily GitHub Actions job and in-app/admin refreshes both rewrite
    ``earnings_intelligence.db``, so the file mtime is a reliable
    last-refreshed signal for the homepage.
    """
    path = Path(database_path)
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def format_last_data_refresh(moment: datetime | None) -> str | None:
    """Format a refresh timestamp for display on the homepage."""
    if moment is None:
        return None
    # Show Eastern time — the product audience and daily job cadence align
    # with US market hours better than raw UTC.
    try:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo("America/New_York"))
        zone_label = local.tzname() or "ET"
    except Exception:
        local = moment.astimezone()
        zone_label = local.tzname() or "local"

    # Avoid platform-specific %-d / %-I flags.
    stamp = local.strftime("%b %d, %Y at %I:%M %p").replace(" 0", " ")
    return f"Data last refreshed {stamp} {zone_label}"


def build_anticipated_earnings_calendar(
    reference_date: date | None = None,
    database_path: Path | str = DATABASE_FILE,
    tickers_per_day: int = _CALENDAR_TICKERS_PER_DAY,
) -> dict[str, object]:
    """Build the current-month anticipated-earnings calendar payload.

    ``reference_date`` defaults to today so the month rolls over automatically
    when the calendar changes. Each day lists the highest-attention tickers
    reporting that day (by latest attention score).
    """
    today = reference_date or date.today()
    store = SQLiteStore(database_path)
    events = store.get_earnings_in_month(today.year, today.month)
    days_in_month = calendar_module.monthrange(today.year, today.month)[1]
    # Monday-first week index matching calendar.setfirstweekday(calendar.MONDAY)
    first_weekday = date(today.year, today.month, 1).weekday()

    by_day: dict[int, list[dict[str, object]]] = {day: [] for day in range(1, days_in_month + 1)}
    if not events.empty:
        events = events.copy()
        events["earnings_date"] = pd.to_datetime(events["earnings_date"]).dt.date
        for _, row in events.iterrows():
            event_day = row["earnings_date"].day
            score = row.get("attention_score")
            by_day[event_day].append(
                {
                    "ticker": str(row["ticker"]),
                    "company_name": str(row.get("company_name") or row["ticker"]),
                    "attention_score": (
                        float(score) if score is not None and pd.notna(score) else None
                    ),
                }
            )
        for day, tickers in by_day.items():
            tickers.sort(
                key=lambda item: (
                    item["attention_score"] is None,
                    -(item["attention_score"] or 0.0),
                    item["ticker"],
                )
            )
            by_day[day] = tickers[:tickers_per_day]

    return {
        "year": today.year,
        "month": today.month,
        "month_label": today.strftime("%B %Y"),
        "today": today,
        "days_in_month": days_in_month,
        "first_weekday": first_weekday,
        "days": by_day,
        "event_count": int(sum(len(tickers) for tickers in by_day.values())),
    }

def load_dashboard_data() -> dict[str, pd.DataFrame]:
    """Load the canonical attention scores and history from SQLite.

    The dashboard reads the scores persisted by ``scripts/refresh_data.py`` so
    that displayed rankings always match what the pipeline stored.
    """
    store = SQLiteStore(DATABASE_FILE)
    earnings = store.get_upcoming_earnings()
    metrics = store.get_all_daily_metrics()
    attention = store.get_rankings()

    empty_payload = {
        "earnings": earnings,
        "metrics": metrics,
        "attention": pd.DataFrame(),
        "social_growth": pd.DataFrame(),
        "social_drop": pd.DataFrame(),
        "most_mentioned": pd.DataFrame(),
        "yahoo_rank_growth": pd.DataFrame(),
        "yahoo_rank_drop": pd.DataFrame(),
        "most_trending_yahoo": pd.DataFrame(),
    }

    if attention.empty:
        return empty_payload

    attention = attention.merge(
        _latest_current_mentions(metrics), on="ticker", how="left"
    )
    attention = attention.merge(_latest_yahoo_ranks(metrics), on="ticker", how="left")
    attention = attention.merge(
        _yahoo_rank_change(metrics), on="ticker", how="left"
    )

    most_mentioned = attention.dropna(subset=["current_mentions"]).sort_values(
        "current_mentions", ascending=False
    )
    social_with_change = attention.dropna(subset=["social_change"])
    social_growth = social_with_change.loc[
        social_with_change["social_change"] > 0
    ].sort_values("social_change", ascending=False)
    social_drop = social_with_change.loc[
        social_with_change["social_change"] < 0
    ].sort_values("social_change", ascending=True)
    most_trending_yahoo = attention.dropna(subset=["current_yahoo_rank"]).sort_values(
        "current_yahoo_rank", ascending=True
    )
    yahoo_with_change = attention.dropna(subset=["yahoo_rank_change"])
    yahoo_rank_growth = yahoo_with_change.loc[
        yahoo_with_change["yahoo_rank_change"] > 0
    ].sort_values("yahoo_rank_change", ascending=False)
    yahoo_rank_drop = yahoo_with_change.loc[
        yahoo_with_change["yahoo_rank_change"] < 0
    ].sort_values("yahoo_rank_change", ascending=True)

    return {
        "earnings": earnings,
        "metrics": metrics,
        "attention": attention,
        "social_growth": social_growth,
        "social_drop": social_drop,
        "most_mentioned": most_mentioned,
        "most_trending_yahoo": most_trending_yahoo,
        "yahoo_rank_growth": yahoo_rank_growth,
        "yahoo_rank_drop": yahoo_rank_drop,
    }


def _latest_current_mentions(metrics: pd.DataFrame) -> pd.DataFrame:
    """Return each ticker's most recently available StockTwits mention count."""
    if metrics.empty or "social_mentions" not in metrics.columns:
        return pd.DataFrame(columns=["ticker", "current_mentions"])

    mentions = metrics.dropna(subset=["social_mentions"]).sort_values("date")
    if mentions.empty:
        return pd.DataFrame(columns=["ticker", "current_mentions"])

    latest = mentions.groupby("ticker", as_index=False).last()[
        ["ticker", "social_mentions"]
    ]
    return latest.rename(columns={"social_mentions": "current_mentions"})


def _latest_yahoo_ranks(metrics: pd.DataFrame) -> pd.DataFrame:
    """Return each ticker's Yahoo Finance trending rank from the latest day.

    Uses the most recent calendar snapshot per ticker. Tickers that have
    dropped off Yahoo's list (``NULL`` on the latest day) are omitted so they
    do not keep appearing under "Most trending" with a stale older rank.
    """
    if metrics.empty or "yahoo_trend_rank" not in metrics.columns:
        return pd.DataFrame(columns=["ticker", "current_yahoo_rank"])

    history = metrics.sort_values("date")
    if history.empty:
        return pd.DataFrame(columns=["ticker", "current_yahoo_rank"])

    # Use tail(1), not groupby().last() — last() skips NA and would keep a
    # stale on-list rank after a ticker falls off Yahoo's trending list.
    latest = history.groupby("ticker", as_index=False).tail(1)[
        ["ticker", "yahoo_trend_rank"]
    ]
    latest = latest.dropna(subset=["yahoo_trend_rank"])
    return latest.rename(columns={"yahoo_trend_rank": "current_yahoo_rank"})


def _yahoo_rank_change(metrics: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """Return how many Yahoo trending ranks each ticker climbed over ``days``.

    Positive = climbed (e.g. #20 → #5 is +15). Negative = fell (e.g. #5 → #20
    is -15). Tickers that drop entirely off Yahoo's list are treated as rank
    ``_OFF_YAHOO_LIST_RANK`` for the current side of the comparison.
    """
    if metrics.empty or "yahoo_trend_rank" not in metrics.columns:
        return pd.DataFrame(columns=["ticker", "yahoo_rank_change"])

    history = metrics.copy()
    history["date"] = pd.to_datetime(history["date"])
    history = history.sort_values(["ticker", "date"])

    records: list[dict[str, object]] = []
    for ticker, ticker_data in history.groupby("ticker", sort=False):
        latest = ticker_data.iloc[-1]
        target_date = latest["date"] - pd.Timedelta(days=days)
        previous_rows = ticker_data[ticker_data["date"] <= target_date]
        if previous_rows.empty:
            continue

        previous_rank = previous_rows.iloc[-1]["yahoo_trend_rank"]
        current_rank = latest["yahoo_trend_rank"]
        # No signal if the ticker was off-list at both ends of the window.
        if pd.isna(previous_rank) and pd.isna(current_rank):
            continue

        previous_value = (
            int(previous_rank)
            if pd.notna(previous_rank)
            else _OFF_YAHOO_LIST_RANK
        )
        current_value = (
            int(current_rank)
            if pd.notna(current_rank)
            else _OFF_YAHOO_LIST_RANK
        )
        records.append(
            {
                "ticker": ticker,
                "yahoo_rank_change": previous_value - current_value,
            }
        )

    return pd.DataFrame(records)


def get_company_data(ticker: str) -> dict[str, object]:
    """Return all dashboard-ready information for a selected ticker."""
    data = load_dashboard_data()
    ticker = ticker.upper()
    metrics = data["metrics"]
    company_metrics = metrics[metrics["ticker"] == ticker].copy()
    company_earnings = data["earnings"]
    company_earnings = company_earnings[company_earnings["ticker"] == ticker]
    company_score = data["attention"]
    company_score = company_score[company_score["ticker"] == ticker]

    return {
        "metrics": company_metrics,
        "earnings": company_earnings.iloc[0].to_dict()
        if not company_earnings.empty
        else {},
        "score": company_score.iloc[0].to_dict() if not company_score.empty else {},
    }


def format_market_cap(value: float | int | None) -> str:
    """Format values for compact dashboard display."""
    if value is None or pd.isna(value):
        return "—"
    if value >= 1_000_000_000:
        return f"${value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"${value / 1_000_000:.1f}M"
    return f"${value:,.0f}"
