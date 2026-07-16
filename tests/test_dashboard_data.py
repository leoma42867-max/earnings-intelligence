"""Unit tests for dashboard data preparation."""

from datetime import date
import unittest

import pandas as pd

from src.dashboard.data import (
    _latest_current_mentions,
    _latest_yahoo_ranks,
    _yahoo_rank_change,
    attention_heat,
    build_anticipated_earnings_calendar,
    build_earnings_spillover,
    build_this_week_focus,
    build_weekly_postmortem,
    format_last_data_refresh,
    get_last_data_refresh_at,
    load_dashboard_data,
    reaction_sentiment,
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
                "date": [
                    "2026-07-01",
                    "2026-07-08",
                    "2026-07-01",
                    "2026-07-08",
                    "2026-07-01",
                    "2026-07-08",
                ],
                "ticker": ["AAPL", "AAPL", "MSFT", "MSFT", "NVDA", "NVDA"],
                "yahoo_trend_rank": [None, 5, 40, 20, 3, None],
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
            {
                "AAPL": 96,  # off-list → #5
                "MSFT": 20,  # #40 → #20
                "NVDA": -98,  # #3 → off-list (treated as #101)
            },
        )

    def test_last_data_refresh_helpers(self) -> None:
        from datetime import datetime, timezone
        from pathlib import Path
        from tempfile import TemporaryDirectory

        self.assertIsNone(get_last_data_refresh_at(Path("/no/such/db.sqlite")))
        self.assertIsNone(format_last_data_refresh(None))

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "metrics.db"
            db_path.write_bytes(b"")
            moment = get_last_data_refresh_at(db_path)
            self.assertIsNotNone(moment)
            assert moment is not None
            self.assertEqual(moment.tzinfo, timezone.utc)

        label = format_last_data_refresh(
            datetime(2026, 7, 14, 13, 0, tzinfo=timezone.utc)
        )
        self.assertIsNotNone(label)
        assert label is not None
        self.assertTrue(label.startswith("Data last refreshed"))
        self.assertIn("2026", label)

    def test_build_anticipated_earnings_calendar_uses_reference_month(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from src.storage.sqlite_store import SQLiteStore

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "calendar.db"
            store = SQLiteStore(db_path)
            store.upsert_earnings(
                pd.DataFrame(
                    {
                        "ticker": ["AAA", "BBB", "CCC"],
                        "company_name": ["Alpha", "Beta", "Gamma"],
                        "sector": ["Tech", "Tech", "Tech"],
                        "earnings_date": [
                            "2026-03-05",
                            "2026-03-05",
                            "2026-04-02",
                        ],
                        "estimated_eps": [1.0, 1.0, 1.0],
                        "estimated_revenue": [10.0, 10.0, 10.0],
                    }
                )
            )
            store.upsert_attention_scores(
                pd.DataFrame(
                    {
                        "ticker": ["AAA", "BBB"],
                        "attention_score": [12.0, 88.0],
                        "social_change": [1.0, 2.0],
                        "volume_change": [0.0, 0.0],
                        "price_growth_pct": [0.0, 0.0],
                        "yahoo_change": [None, None],
                        "social_points": [1.0, 2.0],
                        "volume_points": [0.0, 0.0],
                        "price_points": [0.0, 0.0],
                        "yahoo_points": [0.0, 0.0],
                    }
                ),
                calculation_date="2026-03-01",
            )

            # Before the March 5 prints so day cells sort by attention heat.
            march = build_anticipated_earnings_calendar(
                reference_date=date(2026, 3, 1),
                database_path=db_path,
            )
            april = build_anticipated_earnings_calendar(
                reference_date=date(2026, 4, 1),
                database_path=db_path,
            )

        self.assertEqual(march["month_label"], "March 2026")
        self.assertEqual(
            [item["ticker"] for item in march["days"][5]],
            ["BBB", "AAA"],
        )
        self.assertEqual(march["days"][5][0]["heat"], "high")
        self.assertEqual(march["days"][5][1]["heat"], "low")
        self.assertEqual(march["event_count"], 2)
        self.assertEqual(april["month_label"], "April 2026")
        self.assertEqual(
            [item["ticker"] for item in april["days"][2]],
            ["CCC"],
        )

    def test_reaction_sentiment_buckets(self) -> None:
        self.assertEqual(reaction_sentiment(3.0), "bullish")
        self.assertEqual(reaction_sentiment(12.5), "bullish")
        self.assertEqual(reaction_sentiment(-3.0), "bearish")
        self.assertEqual(reaction_sentiment(-4.2), "bearish")
        self.assertEqual(reaction_sentiment(0.0), "mixed")
        self.assertEqual(reaction_sentiment(2.9), "mixed")
        self.assertEqual(reaction_sentiment(-2.9), "mixed")
        self.assertEqual(reaction_sentiment(None), "unknown")

    def test_attention_heat_buckets(self) -> None:
        self.assertEqual(attention_heat(60.0), "high")
        self.assertEqual(attention_heat(30.0), "mid")
        self.assertEqual(attention_heat(29.9), "low")
        self.assertEqual(attention_heat(None), "none")

    def test_past_day_sorts_bearish_first_by_reaction(self) -> None:
        from pathlib import Path
        from tempfile import TemporaryDirectory

        from src.storage.sqlite_store import SQLiteStore

        with TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "past_sentiment.db"
            store = SQLiteStore(db_path)
            store.upsert_earnings(
                pd.DataFrame(
                    {
                        "ticker": ["IBM", "AAPL", "MSFT", "ORCL"],
                        "company_name": ["IBM", "Apple", "Microsoft", "Oracle"],
                        "sector": ["Technology"] * 4,
                        "earnings_date": ["2026-03-05"] * 4,
                        "estimated_eps": [1.0] * 4,
                        "estimated_revenue": [10.0] * 4,
                    }
                )
            )
            store.upsert_attention_scores(
                pd.DataFrame(
                    {
                        "ticker": ["IBM", "AAPL", "MSFT", "ORCL"],
                        "attention_score": [10.0, 90.0, 50.0, 5.0],
                        "social_change": [0.0] * 4,
                        "volume_change": [0.0] * 4,
                        "price_growth_pct": [0.0] * 4,
                        "yahoo_change": [None] * 4,
                        "social_points": [0.0] * 4,
                        "volume_points": [0.0] * 4,
                        "price_points": [0.0] * 4,
                        "yahoo_points": [0.0] * 4,
                    }
                ),
                calculation_date="2026-03-01",
            )
            # Closes on/near earnings and the next trading day.
            store.upsert_daily_metrics(
                pd.DataFrame(
                    {
                        "ticker": [
                            "IBM", "IBM",
                            "AAPL", "AAPL",
                            "MSFT", "MSFT",
                            # ORCL missing after-print close → unknown
                            "ORCL",
                        ],
                        "date": [
                            "2026-03-05", "2026-03-06",
                            "2026-03-05", "2026-03-06",
                            "2026-03-05", "2026-03-06",
                            "2026-03-05",
                        ],
                        "close": [
                            100.0, 95.0,   # -5% bearish
                            100.0, 104.0,  # +4% bullish
                            100.0, 101.0,  # +1% mixed
                            100.0,
                        ],
                    }
                )
            )

            calendar = build_anticipated_earnings_calendar(
                reference_date=date(2026, 3, 10),
                database_path=db_path,
            )

        day = calendar["days"][5]
        self.assertEqual(
            [item["ticker"] for item in day],
            ["IBM", "MSFT", "AAPL", "ORCL"],
        )
        self.assertEqual(
            [item["sentiment"] for item in day],
            ["bearish", "mixed", "bullish", "unknown"],
        )
        self.assertEqual(day[0]["reaction_pct"], -5.0)

    def test_build_earnings_spillover_picks_influencers_and_peers(self) -> None:
        calendar = {
            "days": {
                5: [
                    {
                        "ticker": "IBM",
                        "company_name": "IBM",
                        "sector": "Technology",
                        "attention_score": 70.0,
                        "is_past": True,
                        "reaction_pct": -4.2,
                        "sentiment": "bearish",
                        "heat": None,
                        "momentum": None,
                    },
                    {
                        "ticker": "SMALL",
                        "company_name": "Small Co",
                        "sector": "Technology",
                        "attention_score": 99.0,
                        "is_past": False,
                        "reaction_pct": None,
                        "sentiment": None,
                        "heat": "high",
                        "momentum": None,
                    },
                ]
            }
        }
        attention = pd.DataFrame(
            {
                "ticker": ["IBM", "AMD", "CRM", "SMALL", "XOM"],
                "company_name": ["IBM", "AMD", "Salesforce", "Small Co", "Exxon"],
                "sector": [
                    "Technology",
                    "Technology",
                    "Technology",
                    "Technology",
                    "Energy",
                ],
                "attention_score": [70.0, 80.0, 60.0, 99.0, 40.0],
            }
        )

        spillover = build_earnings_spillover(calendar, attention, max_peers=2)

        self.assertEqual(len(spillover), 1)
        self.assertEqual(spillover[0]["ticker"], "IBM")
        self.assertEqual(spillover[0]["status"], "bearish")
        self.assertIn("sector pressure", spillover[0]["watch_note"])
        self.assertEqual(
            [peer["ticker"] for peer in spillover[0]["peers"]],
            ["SMALL", "AMD"],
        )

    def test_build_this_week_focus_window_and_sort(self) -> None:
        attention = pd.DataFrame(
            {
                "ticker": ["LOW", "HOT", "LATER", "PAST"],
                "company_name": ["Low", "Hot", "Later", "Past"],
                "sector": ["Technology"] * 4,
                "earnings_date": [
                    "2026-07-16",
                    "2026-07-15",
                    "2026-07-30",
                    "2026-07-10",
                ],
                "attention_score": [40.0, 90.0, 99.0, 80.0],
            }
        )

        focus = build_this_week_focus(
            attention, reference_date=date(2026, 7, 14), days=7, limit=8
        )

        self.assertEqual([item["ticker"] for item in focus], ["HOT", "LOW"])
        self.assertEqual(focus[0]["heat"], "high")
        self.assertEqual(focus[1]["heat"], "mid")

    def test_build_weekly_postmortem_beats_and_misses(self) -> None:
        calendar = {
            "days": {
                10: [
                    {
                        "ticker": "BEAT",
                        "earnings_date": date(2026, 7, 10),
                        "is_past": True,
                        "reaction_pct": 8.0,
                    },
                    {
                        "ticker": "MISS",
                        "earnings_date": date(2026, 7, 11),
                        "is_past": True,
                        "reaction_pct": -6.5,
                    },
                    {
                        "ticker": "FLAT",
                        "earnings_date": date(2026, 7, 12),
                        "is_past": True,
                        "reaction_pct": 1.0,
                    },
                    {
                        "ticker": "NO_PRICE",
                        "earnings_date": date(2026, 7, 12),
                        "is_past": True,
                        "reaction_pct": None,
                    },
                    {
                        "ticker": "OLD",
                        "earnings_date": date(2026, 6, 1),
                        "is_past": True,
                        "reaction_pct": -20.0,
                    },
                    {
                        "ticker": "FUTURE",
                        "earnings_date": date(2026, 7, 20),
                        "is_past": False,
                        "reaction_pct": None,
                    },
                ]
            }
        }

        postmortem = build_weekly_postmortem(
            calendar, reference_date=date(2026, 7, 14), days=7, limit=2
        )

        self.assertEqual(
            [item["ticker"] for item in postmortem["beats"]],
            ["BEAT", "FLAT"],
        )
        self.assertEqual(
            [item["ticker"] for item in postmortem["misses"]],
            ["MISS", "FLAT"],
        )


if __name__ == "__main__":
    unittest.main()
