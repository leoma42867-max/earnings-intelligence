"""The core data-refresh pipeline, reusable from a CLI, scheduler, or app.

Both ``scripts/refresh_data.py`` (command line / cron / GitHub Actions) and
the Streamlit app's admin-gated "Refresh data now" button call
``run_refresh_pipeline`` so there is exactly one implementation to keep in
sync with the storage schema and scoring model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from config.settings import DATABASE_FILE, TICKER_UNIVERSE_SIZE
from src.analytics.growth_ranking import calculate_growth_metrics
from src.analytics.scoring import calculate_attention_scores
from src.collectors.earnings_calendar import fetch_upcoming_earnings
from src.collectors.market_data import fetch_market_data
from src.collectors.social_mentions import fetch_social_mentions
from src.collectors.ticker_universe import fetch_hyped_tickers
from src.collectors.yahoo_trending import fetch_yahoo_trend_ranks
from src.storage.sqlite_store import SQLiteStore


@dataclass
class PipelineResult:
    """Outcome of one refresh run, used for CLI printing and UI feedback."""

    tickers_found: int = 0
    social_mentions_collected: bool = False
    rankings: pd.DataFrame = field(default_factory=pd.DataFrame)
    messages: list[str] = field(default_factory=list)
    success: bool = True

    def log(self, message: str) -> None:
        self.messages.append(message)


def run_refresh_pipeline(database_path=DATABASE_FILE) -> PipelineResult:
    """Collect fresh data, store it, and recompute attention scores.

    Safe to call repeatedly (all storage operations are idempotent upserts).
    Any collector failure for one ticker does not stop the overall run.
    """
    from src.storage.sqlite_store import market_today

    result = PipelineResult()
    store = SQLiteStore(database_path)
    as_of = market_today()

    result.log(f"Finding today's top {TICKER_UNIVERSE_SIZE} most-hyped tickers...")
    universe = fetch_hyped_tickers(TICKER_UNIVERSE_SIZE)
    result.log(f"Candidate universe: {len(universe)} tickers.")

    result.log("Fetching upcoming earnings...")
    earnings = fetch_upcoming_earnings(universe)
    if not earnings.empty:
        tickers = earnings["ticker"].tolist()
        result.tickers_found = len(tickers)
        result.log(f"Found {len(tickers)} companies: {', '.join(tickers)}")
        store.upsert_earnings(earnings)

        result.log("Fetching market data...")
        market = fetch_market_data(tickers)
        store.upsert_daily_metrics(market)

        result.log("Fetching StockTwits mention counts...")
        mentions = fetch_social_mentions(tickers)
        if mentions.empty:
            result.log("StockTwits returned no mention data (network or API issue).")
        else:
            store.upsert_daily_metrics(mentions)
            result.social_mentions_collected = True

        result.log("Fetching Yahoo Finance trending ranks...")
        yahoo_ranks = fetch_yahoo_trend_ranks(tickers)
        if yahoo_ranks.empty:
            result.log("Yahoo Finance returned no trending data (network or API issue).")
        else:
            store.upsert_yahoo_trend_ranks(yahoo_ranks)
            on_list = yahoo_ranks["yahoo_trend_rank"].notna().sum()
            result.log(f"Yahoo trending snapshot saved ({on_list} tickers on-list).")
    else:
        result.log("No upcoming earnings found in this refresh; rescoring existing history.")

    result.log("Calculating attention scores...")
    # Scope scoring to companies with a genuinely upcoming earnings date —
    # the same universe ``get_rankings()`` displays. Social/volume points
    # are normalized relative to the single biggest gainer in this batch
    # (see ``scoring._normalize_change``), so including long-departed
    # tickers still sitting in history would let a stale one-off spike from
    # months ago permanently suppress every current score.
    upcoming = store.get_upcoming_earnings(as_of=as_of)
    active_tickers = set(upcoming["ticker"]) if not upcoming.empty else set()
    all_metrics = store.get_all_daily_metrics()
    if active_tickers:
        all_metrics = all_metrics[all_metrics["ticker"].isin(active_tickers)]
    else:
        all_metrics = all_metrics.iloc[0:0]
    growth = calculate_growth_metrics(all_metrics)

    if growth.empty:
        result.log("No metric history available yet — no scores produced.")
        if active_tickers:
            result.success = False
            result.log(
                "Refresh failed: upcoming earnings exist but no scores were produced."
            )
        return result

    rankings = calculate_attention_scores(growth)
    store.upsert_attention_scores(rankings, calculation_date=as_of.isoformat())
    result.rankings = rankings
    result.log(f"Saved {len(rankings)} attention score(s).")
    if result.rankings.empty and active_tickers:
        result.success = False
        result.log(
            "Refresh failed: upcoming earnings exist but no scores were produced."
        )
    return result
