"""Prepare SQLite data for the Streamlit dashboard."""

from __future__ import annotations

import pandas as pd

from config.settings import DATABASE_FILE
from src.storage.sqlite_store import SQLiteStore


def load_dashboard_data() -> dict[str, pd.DataFrame]:
    """Load the canonical attention scores and history from SQLite.

    The dashboard reads the scores persisted by ``scripts/refresh_data.py`` so
    that displayed rankings always match what the pipeline stored.
    """
    store = SQLiteStore(DATABASE_FILE)
    earnings = store.get_upcoming_earnings()
    metrics = store.get_all_daily_metrics()
    attention = store.get_rankings()

    if attention.empty:
        return {
            "earnings": earnings,
            "metrics": metrics,
            "attention": pd.DataFrame(),
            "social_growth": pd.DataFrame(),
            "most_mentioned": pd.DataFrame(),
        }

    # Two separate dashboard categories:
    # - ``most_mentioned``: highest *current* StockTwits search volume
    # - ``social_growth``: largest *increase* in searches over 7 days
    attention = attention.merge(
        _latest_current_mentions(metrics), on="ticker", how="left"
    )
    most_mentioned = attention.dropna(subset=["current_mentions"]).sort_values(
        "current_mentions", ascending=False
    )

    social_growth = attention.dropna(subset=["social_change"]).sort_values(
        "social_change", ascending=False
    )

    return {
        "earnings": earnings,
        "metrics": metrics,
        "attention": attention,
        "social_growth": social_growth,
        "most_mentioned": most_mentioned,
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
