"""Unit tests for dashboard data preparation."""

import unittest

import pandas as pd

from src.dashboard.data import (
    _latest_current_mentions,
    _latest_yahoo_ranks,
    _yahoo_rank_change,
    load_dashboard_data,
)


class DashboardDataTests(unittest.TestCase):
    def test_latest_current_mentions_returns_most_recent_count_per_ticker(self) -> None:
        metrics = pd.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-08", "2026-07-01", "2026-07-08"],
                "ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "social_mentions": [10, 50, 100, 80],
            }
        )

        latest = _latest_current_mentions(metrics)

        self.assertEqual(
            latest.set_index("ticker")["current_mentions"].to_dict(),
            {"AAPL": 50, "MSFT": 80},
        )

    def test_load_dashboard_data_splits_level_and_growth_rankings(self) -> None:
        """Most-searched and highest-growth are separate orderings."""
        from unittest.mock import patch

        rankings = pd.DataFrame(
            {
                "ticker": ["HOT", "BIG"],
                "company_name": ["Hot Climber", "Big Stable"],
                "earnings_date": ["2026-07-20", "2026-07-21"],
                "attention_score": [90.0, 10.0],
                "social_change": [200.0, 5.0],
                "volume_change": [0.0, 0.0],
                "price_growth_pct": [0.0, 0.0],
            }
        )
        metrics = pd.DataFrame(
            {
                "date": ["2026-07-08", "2026-07-08"],
                "ticker": ["HOT", "BIG"],
                "social_mentions": [30, 500],
            }
        )

        with (
            patch("src.dashboard.data.SQLiteStore") as mock_store,
            patch("src.dashboard.data.DATABASE_FILE", "test.db"),
        ):
            store = mock_store.return_value
            store.get_upcoming_earnings.return_value = pd.DataFrame()
            store.get_all_daily_metrics.return_value = metrics
            store.get_rankings.return_value = rankings

            data = load_dashboard_data()

        self.assertEqual(data["most_mentioned"]["ticker"].tolist(), ["BIG", "HOT"])
        self.assertEqual(data["social_growth"]["ticker"].tolist(), ["HOT", "BIG"])

    def test_yahoo_rank_helpers_track_trending_position_changes(self) -> None:
        metrics = pd.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-08", "2026-07-01", "2026-07-08"],
                "ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "yahoo_trend_rank": [None, 5, 40, 20],
            }
        )

        latest = _latest_yahoo_ranks(metrics)
        self.assertEqual(
            latest.set_index("ticker")["current_yahoo_rank"].to_dict(),
            {"AAPL": 5, "MSFT": 20},
        )

        changes = _yahoo_rank_change(metrics, days=7)
        self.assertEqual(
            changes.set_index("ticker")["yahoo_rank_change"].to_dict(),
            {"AAPL": 96, "MSFT": 20},
        )


if __name__ == "__main__":
    unittest.main()
