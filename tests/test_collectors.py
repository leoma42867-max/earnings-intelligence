"""Offline unit tests for data collectors."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import pandas as pd

from src.collectors import (
    earnings_calendar,
    market_data,
    social_mentions,
    stock_info,
    ticker_universe,
)


class StubEarningsProvider:
    def get_earnings(self, ticker: str) -> dict | None:
        events = {
            "AAPL": {
                "ticker": ticker,
                "company_name": "Apple Inc.",
                "earnings_date": date.today() + timedelta(days=7),
                "estimated_eps": 2.0,
                "estimated_revenue": 100.0,
                "sector": "Technology",
            },
            "LATE": {
                "ticker": ticker,
                "company_name": "Late Corp",
                "earnings_date": date.today() + timedelta(days=31),
                "estimated_eps": None,
                "estimated_revenue": None,
            },
        }
        if ticker == "BROKEN":
            raise RuntimeError("provider unavailable")
        return events.get(ticker)


def _iso_timestamp(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeStockTwitsResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class CollectorTests(unittest.TestCase):
    def test_earnings_collector_filters_window_and_normalizes_tickers(self) -> None:
        result = earnings_calendar.fetch_upcoming_earnings(
            [" aapl ", "LATE", "BROKEN", ""], provider=StubEarningsProvider()
        )

        self.assertEqual(result["ticker"].tolist(), ["AAPL"])
        self.assertEqual(result.loc[0, "company_name"], "Apple Inc.")
        self.assertEqual(result.loc[0, "sector"], "Technology")
        self.assertEqual(
            list(result.columns), earnings_calendar.CALENDAR_COLUMNS
        )

    def test_earnings_collector_saves_csv(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "earnings.csv"
            earnings_calendar.save_upcoming_earnings(
                ["AAPL"], output_path=output, provider=StubEarningsProvider()
            )
            saved = pd.read_csv(output)

        self.assertEqual(saved.loc[0, "ticker"], "AAPL")

    @patch("src.collectors.market_data.yf.Ticker")
    def test_market_collector_returns_rows_and_skips_failed_tickers(self, ticker_mock) -> None:
        history = pd.DataFrame(
            {
                "Close": [100.0, 110.0],
                "Volume": [1000, 2000],
            },
            index=pd.to_datetime(["2026-01-01", "2026-01-02"]),
        )
        history.index.name = "Date"
        ticker_mock.side_effect = [
            type("Stock", (), {"history": lambda self, **_: history})(),
            RuntimeError("bad ticker"),
        ]

        result = market_data.fetch_market_data(["AAPL", "BAD"], lookback_days=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(result["ticker"].unique().tolist(), ["AAPL"])
        self.assertEqual(result.iloc[-1]["price_change_pct"], 10.0)

    @patch("src.collectors.social_mentions.time.sleep")
    @patch("src.collectors.social_mentions.requests.get")
    def test_social_mentions_collector_counts_daily_mentions(
        self, get_mock, sleep_mock
    ) -> None:
        payloads_by_ticker = {
            "AAPL": {
                "response": {"status": 200},
                "messages": [
                    {"created_at": _iso_timestamp(0)},
                    {"created_at": _iso_timestamp(0)},
                ],
            },
            "MSFT": {
                "response": {"status": 200},
                "messages": [{"created_at": _iso_timestamp(1)}],
            },
        }
        get_mock.side_effect = lambda url, **_: FakeStockTwitsResponse(
            payloads_by_ticker[url.rsplit("/", 1)[-1].removesuffix(".json")]
        )

        result = social_mentions.fetch_social_mentions(
            [" aapl ", "msft"], lookback_days=7
        )

        self.assertEqual(list(result.columns), ["date", "ticker", "social_mentions"])
        aapl_row = result[result["ticker"] == "AAPL"].iloc[0]
        self.assertEqual(aapl_row["social_mentions"], 2)
        msft_row = result[result["ticker"] == "MSFT"].iloc[0]
        self.assertEqual(msft_row["social_mentions"], 1)
        sleep_mock.assert_called()

    @patch("src.collectors.social_mentions.time.sleep")
    @patch("src.collectors.social_mentions.requests.get")
    def test_social_mentions_collector_skips_failed_ticker(
        self, get_mock, sleep_mock
    ) -> None:
        get_mock.side_effect = RuntimeError("network unavailable")

        result = social_mentions.fetch_social_mentions(["AAPL"])

        self.assertTrue(result.empty)
        self.assertEqual(list(result.columns), ["date", "ticker", "social_mentions"])

    @patch("src.collectors.stock_info._fetch_single_ticker")
    def test_stock_info_normalizes_symbols_and_continues_after_failure(self, fetch_mock) -> None:
        fetch_mock.side_effect = [
            {
                "ticker": "AAPL",
                "current_price": 100.0,
                "daily_change_pct": 1.0,
                "volume": 100,
                "market_cap": 1_000,
                "sector": "Technology",
                "fetched_at": "2026-01-01 00:00:00 UTC",
            },
            RuntimeError("Yahoo unavailable"),
        ]

        result = stock_info.fetch_stock_info([" aapl ", "bad"])

        self.assertEqual(result["ticker"].tolist(), ["AAPL"])
        self.assertEqual(fetch_mock.call_args_list[0].args, ("AAPL",))
        self.assertEqual(fetch_mock.call_args_list[1].args, ("BAD",))

    def test_daily_change_handles_zero_previous_close(self) -> None:
        self.assertEqual(stock_info._calculate_daily_change(100, 0), 0.0)
        self.assertEqual(stock_info._calculate_daily_change(110, 100), 10.0)

    @patch("src.collectors.ticker_universe.yf.screen")
    @patch("src.collectors.ticker_universe.requests.get")
    def test_hyped_tickers_merges_and_dedupes_both_sources(
        self, get_mock, screen_mock
    ) -> None:
        get_mock.return_value = FakeStockTwitsResponse(
            {
                "symbols": [
                    {"symbol": "IBM", "instrument_class": "Stock"},
                    {"symbol": "ORCL", "instrument_class": "Stock"},
                    {"symbol": "ETH.X", "instrument_class": "Crypto"},
                ]
            }
        )
        screen_mock.return_value = {
            "quotes": [
                {"symbol": "ORCL", "quoteType": "EQUITY"},
                {"symbol": "SOFI", "quoteType": "EQUITY"},
                {"symbol": "DIA", "quoteType": "ETF"},
                {"symbol": "PLTR", "quoteType": "EQUITY"},
            ]
        }

        result = ticker_universe.fetch_hyped_tickers(limit=4)

        self.assertEqual(result, ["IBM", "ORCL", "SOFI", "PLTR"])

    @patch("src.collectors.ticker_universe.yf.screen")
    @patch("src.collectors.ticker_universe.requests.get")
    def test_hyped_tickers_falls_back_when_both_sources_fail(
        self, get_mock, screen_mock
    ) -> None:
        get_mock.side_effect = RuntimeError("network unavailable")
        screen_mock.side_effect = RuntimeError("network unavailable")

        result = ticker_universe.fetch_hyped_tickers(limit=10)

        self.assertEqual(result, ticker_universe.FALLBACK_TICKERS)


if __name__ == "__main__":
    unittest.main()
