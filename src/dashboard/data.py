"""Prepare SQLite data for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd

from config.settings import DATABASE_FILE
from src.storage.sqlite_store import SQLiteStore

# Tickers not on Yahoo's trending list are treated as one slot below the
# maximum list size when measuring how many ranks they climbed over 7 days.
_OFF_YAHOO_LIST_RANK = 101


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
        "most_mentioned": pd.DataFrame(),
        "yahoo_rank_growth": pd.DataFrame(),
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
    social_growth = attention.dropna(subset=["social_change"]).sort_values(
        "social_change", ascending=False
    )
    most_trending_yahoo = attention.dropna(subset=["current_yahoo_rank"]).sort_values(
        "current_yahoo_rank", ascending=True
    )
    yahoo_rank_growth = attention.dropna(subset=["yahoo_rank_change"]).sort_values(
        "yahoo_rank_change", ascending=False
    )

    return {
        "earnings": earnings,
        "metrics": metrics,
        "attention": attention,
        "social_growth": social_growth,
        "most_mentioned": most_mentioned,
        "most_trending_yahoo": most_trending_yahoo,
        "yahoo_rank_growth": yahoo_rank_growth,
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
    """Return each ticker's most recent Yahoo Finance trending rank."""
    if metrics.empty or "yahoo_trend_rank" not in metrics.columns:
        return pd.DataFrame(columns=["ticker", "current_yahoo_rank"])

    ranks = metrics.dropna(subset=["yahoo_trend_rank"]).sort_values("date")
    if ranks.empty:
        return pd.DataFrame(columns=["ticker", "current_yahoo_rank"])

    latest = ranks.groupby("ticker", as_index=False).last()[
        ["ticker", "yahoo_trend_rank"]
    ]
    return latest.rename(columns={"yahoo_trend_rank": "current_yahoo_rank"})


def _yahoo_rank_change(metrics: pd.DataFrame, days: int = 7) -> pd.DataFrame:
    """Return how many Yahoo trending ranks each ticker climbed over ``days``."""
    if metrics.empty or "yahoo_trend_rank" not in metrics.columns:
        return pd.DataFrame(columns=["ticker", "yahoo_rank_change"])

    history = metrics.copy()
    history["date"] = pd.to_datetime(history["date"])
    history = history.sort_values(["ticker", "date"])

    records: list[dict[str, object]] = []
    for ticker, ticker_data in history.groupby("ticker", sort=False):
        latest = ticker_data.iloc[-1]
        if pd.isna(latest["yahoo_trend_rank"]):
            continue

        target_date = latest["date"] - pd.Timedelta(days=days)
        previous_rows = ticker_data[ticker_data["date"] <= target_date]
        if previous_rows.empty:
            continue

        previous_rank = previous_rows.iloc[-1]["yahoo_trend_rank"]
        previous_value = (
            int(previous_rank)
            if pd.notna(previous_rank)
            else _OFF_YAHOO_LIST_RANK
        )
        current_value = int(latest["yahoo_trend_rank"])
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
