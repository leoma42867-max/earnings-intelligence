"""Integration tests for SQLite persistence using a temporary database."""

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from src.storage.sqlite_store import SQLiteStore


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = TemporaryDirectory()
        self.store = SQLiteStore(Path(self.temp_directory.name) / "test.db")

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def test_company_and_earnings_upsert_then_retrieve(self) -> None:
        earnings_date = (date.today() + timedelta(days=5)).isoformat()
        earnings = pd.DataFrame(
            {
                "ticker": ["aapl"],
                "company_name": ["Apple Inc."],
                "sector": ["Technology"],
                "earnings_date": [earnings_date],
                "estimated_eps": [2.0],
                "estimated_revenue": [100.0],
            }
        )

        self.store.upsert_earnings(earnings)
        self.store.upsert_earnings(earnings.assign(estimated_eps=2.5))
        result = self.store.get_upcoming_earnings()

        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "ticker"], "AAPL")
        self.assertEqual(result.loc[0, "company_name"], "Apple Inc.")
        self.assertEqual(result.loc[0, "estimated_eps"], 2.5)

    def test_get_earnings_in_month_returns_month_scoped_events_with_scores(self) -> None:
        target = date.today().replace(day=15)
        other_month = (target.replace(day=1) + timedelta(days=32)).replace(day=10)
        earnings = pd.DataFrame(
            {
                "ticker": ["HOT", "COLD", "NEXT"],
                "company_name": ["Hot Co", "Cold Co", "Next Mo"],
                "sector": ["Tech", "Tech", "Tech"],
                "earnings_date": [
                    target.isoformat(),
                    target.isoformat(),
                    other_month.isoformat(),
                ],
                "estimated_eps": [1.0, 1.0, 1.0],
                "estimated_revenue": [10.0, 10.0, 10.0],
            }
        )
        scores = pd.DataFrame(
            {
                "ticker": ["HOT", "COLD"],
                "attention_score": [90.0, 20.0],
                "social_change": [10.0, 1.0],
                "volume_change": [0.0, 0.0],
                "price_growth_pct": [0.0, 0.0],
                "yahoo_change": [None, None],
                "social_points": [50.0, 5.0],
                "volume_points": [0.0, 0.0],
                "price_points": [0.0, 0.0],
                "yahoo_points": [0.0, 0.0],
            }
        )
        self.store.upsert_earnings(earnings)
        self.store.upsert_attention_scores(scores, calculation_date=date.today().isoformat())

        month = self.store.get_earnings_in_month(target.year, target.month)
        tickers = month["ticker"].tolist()
        self.assertEqual(tickers, ["HOT", "COLD"])
        self.assertEqual(month.loc[0, "attention_score"], 90.0)
        self.assertNotIn("NEXT", tickers)

    def test_daily_metric_upserts_merge_market_and_social_values(self) -> None:
        market = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "date": ["2026-01-02"],
                "close": [100.0],
                "volume": [1_000],
                "avg_volume_30d": [900],
                "price_change_pct": [1.0],
            }
        )
        mentions = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "date": ["2026-01-02"],
                "social_mentions": [55],
            }
        )

        self.store.upsert_daily_metrics(market)
        self.store.upsert_daily_metrics(mentions)
        result = self.store.get_daily_metrics("aapl")

        self.assertEqual(len(result), 1)
        self.assertEqual(result.loc[0, "close"], 100.0)
        self.assertEqual(result.loc[0, "social_mentions"], 55)

    def test_yahoo_trend_rank_upsert_overwrites_null_when_ticker_drops_off_list(
        self,
    ) -> None:
        market = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "date": ["2026-01-02"],
                "close": [100.0],
                "volume": [1_000],
                "avg_volume_30d": [900],
                "price_change_pct": [1.0],
            }
        )
        on_list = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "date": ["2026-01-02"],
                "yahoo_trend_rank": [3],
            }
        )
        off_list = pd.DataFrame(
            {
                "ticker": ["AAPL"],
                "date": ["2026-01-02"],
                "yahoo_trend_rank": [None],
            }
        )

        self.store.upsert_daily_metrics(market)
        self.store.upsert_yahoo_trend_ranks(on_list)
        self.store.upsert_yahoo_trend_ranks(off_list)
        result = self.store.get_daily_metrics("aapl")

        self.assertEqual(len(result), 1)
        self.assertIsNone(result.loc[0, "yahoo_trend_rank"])

    def test_attention_scores_return_ranked_company_data(self) -> None:
        earnings = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "company_name": ["Apple", "Microsoft"],
                "earnings_date": [
                    (date.today() + timedelta(days=5)).isoformat(),
                    (date.today() + timedelta(days=8)).isoformat(),
                ],
                "estimated_eps": [2.0, 3.0],
                "estimated_revenue": [100.0, 200.0],
            }
        )
        scores = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "attention_score": [68.0, 5.0],
                "social_change": [450.0, 0.0],
                "volume_change": [2_000_000.0, 500_000.0],
                "price_growth_pct": [5.0, 1.0],
                "social_points": [100.0, 0.0],
                "volume_points": [20.0, 10.0],
                "price_points": [16.7, 3.3],
            }
        )

        self.store.upsert_earnings(earnings)
        self.store.upsert_attention_scores(scores, calculation_date=date.today().isoformat())
        result = self.store.get_rankings()

        self.assertEqual(result["ticker"].tolist(), ["AAPL", "MSFT"])
        self.assertEqual(result.iloc[0]["attention_score"], 68.0)
        self.assertEqual(result.iloc[0]["social_change"], 450.0)

    def test_stored_scores_match_scoring_module_output(self) -> None:
        """Guard against the pipeline/dashboard scoring split regressing."""
        from src.analytics.scoring import calculate_attention_scores

        earnings = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "company_name": ["Apple", "Microsoft"],
                "earnings_date": [
                    (date.today() + timedelta(days=5)).isoformat(),
                    (date.today() + timedelta(days=8)).isoformat(),
                ],
                "estimated_eps": [2.0, 3.0],
                "estimated_revenue": [100.0, 200.0],
            }
        )
        growth = pd.DataFrame(
            {
                "ticker": ["AAPL", "MSFT"],
                "social_7d_change": [450.0, 100.0],
                "volume_7d_change": [2_000_000.0, 8_000_000.0],
                "price_7d_growth_pct": [30.0, 5.0],
            }
        )
        scored = calculate_attention_scores(growth)

        self.store.upsert_earnings(earnings)
        self.store.upsert_attention_scores(
            scored, calculation_date=date.today().isoformat()
        )
        stored = self.store.get_rankings().set_index("ticker")["attention_score"]
        expected = scored.set_index("ticker")["attention_score"]

        for ticker in expected.index:
            self.assertAlmostEqual(stored[ticker], expected[ticker], places=2)

    def test_legacy_social_growth_pct_column_is_migrated_without_data_loss(self) -> None:
        """A database using the pre-absolute-change schema should upgrade in place.

        This covers the most recent migration: social/volume ranking moved
        from a percentage (``social_growth_pct``/``volume_growth_pct``) to a
        raw count increase (``social_change``/``volume_change``).
        """
        self.temp_directory.cleanup()
        self.temp_directory = TemporaryDirectory()
        db_path = Path(self.temp_directory.name) / "legacy_pct.db"

        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE companies (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    sector TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE daily_metrics (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    metric_date TEXT NOT NULL,
                    close REAL,
                    volume INTEGER,
                    avg_volume_30d REAL,
                    price_change_pct REAL,
                    social_mentions INTEGER,
                    PRIMARY KEY (ticker, metric_date)
                );
                CREATE TABLE attention_scores (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    calculation_date TEXT NOT NULL,
                    attention_score REAL NOT NULL,
                    social_growth_pct REAL,
                    volume_growth_pct REAL,
                    price_growth_pct REAL,
                    social_points REAL,
                    volume_points REAL,
                    price_points REAL,
                    PRIMARY KEY (ticker, calculation_date)
                );
                """
            )
            conn.execute(
                "INSERT INTO companies (ticker, company_name) VALUES ('AAPL', 'Apple Inc.')"
            )
            conn.execute(
                "INSERT INTO daily_metrics "
                "(ticker, metric_date, close, volume, avg_volume_30d, price_change_pct, social_mentions) "
                "VALUES ('AAPL', '2026-01-02', 100.0, 1000, 900, 1.0, 42)"
            )

        migrated_store = SQLiteStore(db_path)
        metrics = migrated_store.get_daily_metrics("AAPL")

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics.loc[0, "social_mentions"], 42)

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attention_scores)")}
        self.assertIn("social_change", columns)
        self.assertIn("volume_change", columns)
        self.assertNotIn("social_growth_pct", columns)
        self.assertNotIn("volume_growth_pct", columns)

    def test_rankings_exclude_companies_without_upcoming_earnings(self) -> None:
        """A ticker whose earnings date has passed should drop out of rankings."""
        earnings = pd.DataFrame(
            {
                "ticker": ["AAPL", "STALE"],
                "company_name": ["Apple", "Stale Corp"],
                "earnings_date": [
                    (date.today() + timedelta(days=5)).isoformat(),
                    (date.today() - timedelta(days=10)).isoformat(),
                ],
                "estimated_eps": [2.0, 1.0],
                "estimated_revenue": [100.0, 50.0],
            }
        )
        scores = pd.DataFrame(
            {
                "ticker": ["AAPL", "STALE"],
                "attention_score": [50.0, 90.0],
                "social_change": [50.0, 90.0],
                "volume_change": [50.0, 90.0],
                "price_growth_pct": [50.0, 90.0],
                "social_points": [50.0, 90.0],
                "volume_points": [50.0, 90.0],
                "price_points": [50.0, 90.0],
            }
        )

        self.store.upsert_earnings(earnings)
        self.store.upsert_attention_scores(scores, calculation_date=date.today().isoformat())
        result = self.store.get_rankings()

        self.assertEqual(result["ticker"].tolist(), ["AAPL"])

    def test_legacy_trend_score_column_is_migrated_without_data_loss(self) -> None:
        """A database created before the social-signal renames should upgrade in place."""
        self.temp_directory.cleanup()
        self.temp_directory = TemporaryDirectory()
        db_path = Path(self.temp_directory.name) / "legacy.db"

        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE companies (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    sector TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE daily_metrics (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    metric_date TEXT NOT NULL,
                    close REAL,
                    volume INTEGER,
                    avg_volume_30d REAL,
                    price_change_pct REAL,
                    trend_score INTEGER,
                    PRIMARY KEY (ticker, metric_date)
                );
                CREATE TABLE attention_scores (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    calculation_date TEXT NOT NULL,
                    attention_score REAL NOT NULL,
                    trends_growth_pct REAL,
                    volume_growth_pct REAL,
                    price_growth_pct REAL,
                    trends_points REAL,
                    volume_points REAL,
                    price_points REAL,
                    PRIMARY KEY (ticker, calculation_date)
                );
                """
            )
            conn.execute(
                "INSERT INTO companies (ticker, company_name) VALUES ('AAPL', 'Apple Inc.')"
            )
            conn.execute(
                "INSERT INTO daily_metrics "
                "(ticker, metric_date, close, volume, avg_volume_30d, price_change_pct, trend_score) "
                "VALUES ('AAPL', '2026-01-02', 100.0, 1000, 900, 1.0, 42)"
            )

        migrated_store = SQLiteStore(db_path)
        metrics = migrated_store.get_daily_metrics("AAPL")

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics.loc[0, "close"], 100.0)
        self.assertEqual(metrics.loc[0, "social_mentions"], 42)

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attention_scores)")}
        self.assertIn("social_change", columns)
        self.assertNotIn("trends_growth_pct", columns)

    def test_legacy_reddit_mentions_column_is_migrated_without_data_loss(self) -> None:
        """A database created during the brief Reddit phase should also upgrade in place."""
        self.temp_directory.cleanup()
        self.temp_directory = TemporaryDirectory()
        db_path = Path(self.temp_directory.name) / "legacy_reddit.db"

        with sqlite3.connect(db_path) as conn:
            conn.executescript(
                """
                CREATE TABLE companies (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    sector TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE daily_metrics (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    metric_date TEXT NOT NULL,
                    close REAL,
                    volume INTEGER,
                    avg_volume_30d REAL,
                    price_change_pct REAL,
                    reddit_mentions INTEGER,
                    PRIMARY KEY (ticker, metric_date)
                );
                CREATE TABLE attention_scores (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    calculation_date TEXT NOT NULL,
                    attention_score REAL NOT NULL,
                    reddit_growth_pct REAL,
                    volume_growth_pct REAL,
                    price_growth_pct REAL,
                    reddit_points REAL,
                    volume_points REAL,
                    price_points REAL,
                    PRIMARY KEY (ticker, calculation_date)
                );
                """
            )
            conn.execute(
                "INSERT INTO companies (ticker, company_name) VALUES ('AAPL', 'Apple Inc.')"
            )
            conn.execute(
                "INSERT INTO daily_metrics "
                "(ticker, metric_date, close, volume, avg_volume_30d, price_change_pct, reddit_mentions) "
                "VALUES ('AAPL', '2026-01-02', 100.0, 1000, 900, 1.0, 7)"
            )

        migrated_store = SQLiteStore(db_path)
        metrics = migrated_store.get_daily_metrics("AAPL")

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics.loc[0, "social_mentions"], 7)

        with sqlite3.connect(db_path) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(attention_scores)")}
        self.assertIn("social_change", columns)
        self.assertNotIn("reddit_growth_pct", columns)


if __name__ == "__main__":
    unittest.main()
