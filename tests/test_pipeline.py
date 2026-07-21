"""Integration tests for the end-to-end refresh pipeline."""

from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import pandas as pd

from src.pipeline import run_refresh_pipeline
from src.storage.sqlite_store import SQLiteStore


class PipelineScoringScopeTests(unittest.TestCase):
    """Guard against stale, no-longer-displayed tickers skewing live scores.

    Social mentions and trading volume are ranked by their raw count
    increase, normalized relative to the single biggest gainer *in the
    batch that gets scored* (see ``scoring._normalize_change``). If that
    batch ever included tickers whose earnings have already passed — which
    ``get_rankings()`` filters out of the dashboard anyway — a one-off
    historical spike from a ticker nobody sees anymore could permanently
    anchor the "100 points" bar and silently suppress every current score.
    """

    def setUp(self) -> None:
        self.temp_directory = TemporaryDirectory()
        self.db_path = Path(self.temp_directory.name) / "pipeline.db"

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_stale_tickers_history_does_not_suppress_active_scores(self) -> None:
        store = SQLiteStore(self.db_path)

        # STALE's earnings already passed, so get_rankings() will never show
        # it — but its history (a huge one-off mention spike) still sits in
        # daily_metrics forever, since nothing prunes old rows.
        store.upsert_earnings(
            pd.DataFrame(
                {
                    "ticker": ["STALE"],
                    "company_name": ["Stale Corp"],
                    "earnings_date": [(date.today() - timedelta(days=10)).isoformat()],
                    "estimated_eps": [1.0],
                    "estimated_revenue": [50.0],
                }
            )
        )
        store.upsert_daily_metrics(
            pd.DataFrame(
                {
                    "ticker": ["STALE", "STALE"],
                    "date": [
                        (date.today() - timedelta(days=17)).isoformat(),
                        (date.today() - timedelta(days=10)).isoformat(),
                    ],
                    "social_mentions": [10, 100_000],
                    "volume": [1_000, 1_000],
                    "close": [10.0, 10.0],
                }
            )
        )

        # ACTIVE has a genuinely upcoming earnings date and a much smaller,
        # but real, mention increase over the last week.
        store.upsert_daily_metrics(
            pd.DataFrame(
                {
                    "ticker": ["ACTIVE"],
                    "date": [(date.today() - timedelta(days=7)).isoformat()],
                    "social_mentions": [5],
                    "volume": [1_000],
                    "close": [20.0],
                }
            )
        )

        active_earnings = pd.DataFrame(
            {
                "ticker": ["ACTIVE"],
                "company_name": ["Active Inc."],
                "earnings_date": [(date.today() + timedelta(days=5)).isoformat()],
                "estimated_eps": [2.0],
                "estimated_revenue": [200.0],
            }
        )
        active_market = pd.DataFrame(
            {
                "ticker": ["ACTIVE"],
                "date": [date.today().isoformat()],
                "close": [22.0],
                "volume": [1_100],
                "avg_volume_30d": [1_000],
                "price_change_pct": [10.0],
            }
        )
        active_mentions = pd.DataFrame(
            {"ticker": ["ACTIVE"], "date": [date.today().isoformat()], "social_mentions": [55]}
        )

        yahoo_ranks = pd.DataFrame(
            {
                "ticker": ["ACTIVE"],
                "date": [date.today().isoformat()],
                "yahoo_trend_rank": [4],
            }
        )

        with (
            patch("src.pipeline.fetch_hyped_tickers", return_value=["ACTIVE"]),
            patch("src.pipeline.fetch_upcoming_earnings", return_value=active_earnings),
            patch("src.pipeline.fetch_market_data", return_value=active_market),
            patch("src.pipeline.fetch_social_mentions", return_value=active_mentions),
            patch("src.pipeline.fetch_yahoo_trend_ranks", return_value=yahoo_ranks),
        ):
            result = run_refresh_pipeline(database_path=self.db_path)

        rankings = result.rankings
        self.assertEqual(rankings["ticker"].tolist(), ["ACTIVE"])
        active_row = rankings.iloc[0]

        # ACTIVE's +50 mention increase is the only one in the scored batch
        # (STALE is excluded), so it should score the full 100 points, not a
        # tiny fraction of STALE's +99,990 historical spike.
        self.assertEqual(active_row["social_points"], 100.0)
        self.assertEqual(active_row["social_change"], 50.0)

        # STALE never appears in the dashboard-facing rankings.
        final_rankings = store.get_rankings()
        self.assertNotIn("STALE", final_rankings["ticker"].tolist())
        self.assertTrue(result.success)

    def test_refresh_fails_when_upcoming_exist_but_no_scores(self) -> None:
        store = SQLiteStore(self.db_path)
        store.upsert_earnings(
            pd.DataFrame(
                {
                    "ticker": ["ACTIVE"],
                    "company_name": ["Active Co"],
                    "earnings_date": [(date.today() + timedelta(days=5)).isoformat()],
                    "estimated_eps": [1.0],
                    "estimated_revenue": [50.0],
                }
            )
        )

        with (
            patch("src.pipeline.fetch_hyped_tickers", return_value=["ACTIVE"]),
            patch(
                "src.pipeline.fetch_upcoming_earnings",
                return_value=pd.DataFrame(),
            ),
            patch("src.pipeline.fetch_market_data"),
            patch("src.pipeline.fetch_social_mentions"),
            patch("src.pipeline.fetch_yahoo_trend_ranks"),
        ):
            result = run_refresh_pipeline(database_path=self.db_path)

        self.assertFalse(result.success)
        self.assertTrue(result.rankings.empty)


if __name__ == "__main__":
    unittest.main()
