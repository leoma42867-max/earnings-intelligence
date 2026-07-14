"""SQLite persistence for the Earnings Intelligence Platform."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from pathlib import Path

import pandas as pd


class SQLiteStore:
    """Store and retrieve platform data from a local SQLite database."""

    def __init__(self, database_path: Path | str) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def initialize(self) -> None:
        """Create all tables and indexes if they do not already exist."""
        with self._connect() as conn:
            self._migrate_legacy_schema(conn)
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS companies (
                    ticker TEXT PRIMARY KEY,
                    company_name TEXT NOT NULL,
                    sector TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS earnings (
                    id INTEGER PRIMARY KEY,
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    earnings_date TEXT NOT NULL,
                    estimated_eps REAL,
                    estimated_revenue REAL,
                    source TEXT NOT NULL DEFAULT 'yahoo_finance',
                    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ticker, earnings_date, source)
                );

                CREATE TABLE IF NOT EXISTS daily_metrics (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    metric_date TEXT NOT NULL,
                    close REAL,
                    volume INTEGER,
                    avg_volume_30d REAL,
                    price_change_pct REAL,
                    social_mentions INTEGER,
                    PRIMARY KEY (ticker, metric_date)
                );

                CREATE TABLE IF NOT EXISTS attention_scores (
                    ticker TEXT NOT NULL REFERENCES companies(ticker),
                    calculation_date TEXT NOT NULL,
                    attention_score REAL NOT NULL,
                    social_change REAL,
                    volume_change REAL,
                    price_growth_pct REAL,
                    social_points REAL,
                    volume_points REAL,
                    price_points REAL,
                    PRIMARY KEY (ticker, calculation_date)
                );

                CREATE INDEX IF NOT EXISTS idx_earnings_date
                    ON earnings(earnings_date);
                CREATE INDEX IF NOT EXISTS idx_metrics_date
                    ON daily_metrics(metric_date);
                CREATE INDEX IF NOT EXISTS idx_attention_date
                    ON attention_scores(calculation_date);
                """
            )

    def upsert_companies(self, companies: pd.DataFrame) -> None:
        """Insert or update company details keyed by ticker."""
        if companies.empty:
            return

        rows = [
            (
                str(row.ticker).upper(),
                str(_value(row, "company_name", _value(row, "name", row.ticker))),
                _value(row, "sector"),
            )
            for row in companies.itertuples(index=False)
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO companies (ticker, company_name, sector)
                VALUES (?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    company_name = excluded.company_name,
                    sector = COALESCE(excluded.sector, companies.sector),
                    updated_at = CURRENT_TIMESTAMP
                """,
                rows,
            )

    def upsert_earnings(
        self, earnings: pd.DataFrame, source: str = "yahoo_finance"
    ) -> None:
        """Store upcoming earnings events and their available analyst estimates."""
        if earnings.empty:
            return
        self.upsert_companies(earnings)
        rows = [
            (
                str(row.ticker).upper(),
                str(row.earnings_date),
                _value(row, "estimated_eps"),
                _value(row, "estimated_revenue"),
                source,
            )
            for row in earnings.itertuples(index=False)
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO earnings (
                    ticker, earnings_date, estimated_eps, estimated_revenue, source
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ticker, earnings_date, source) DO UPDATE SET
                    estimated_eps = excluded.estimated_eps,
                    estimated_revenue = excluded.estimated_revenue,
                    collected_at = CURRENT_TIMESTAMP
                """,
                rows,
            )

    def upsert_daily_metrics(self, metrics: pd.DataFrame) -> None:
        """Store price, volume, and/or social-mention values by ticker and date."""
        if metrics.empty:
            return
        self._ensure_companies(metrics["ticker"].unique())
        rows = [
            (
                str(row.ticker).upper(),
                str(_value(row, "date", _value(row, "metric_date"))),
                _value(row, "close"),
                _value(row, "volume"),
                _value(row, "avg_volume_30d"),
                _value(row, "price_change_pct"),
                _value(row, "social_mentions", _value(row, "trend_score")),
            )
            for row in metrics.itertuples(index=False)
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO daily_metrics (
                    ticker, metric_date, close, volume, avg_volume_30d,
                    price_change_pct, social_mentions
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, metric_date) DO UPDATE SET
                    close = COALESCE(excluded.close, daily_metrics.close),
                    volume = COALESCE(excluded.volume, daily_metrics.volume),
                    avg_volume_30d = COALESCE(
                        excluded.avg_volume_30d, daily_metrics.avg_volume_30d
                    ),
                    price_change_pct = COALESCE(
                        excluded.price_change_pct, daily_metrics.price_change_pct
                    ),
                    social_mentions = COALESCE(
                        excluded.social_mentions, daily_metrics.social_mentions
                    )
                """,
                rows,
            )

    def upsert_attention_scores(
        self, scores: pd.DataFrame, calculation_date: str
    ) -> None:
        """Store a daily snapshot of the 0–100 attention scores and their inputs.

        Expects the output of ``src.analytics.scoring.calculate_attention_scores``:
        an ``attention_score`` plus the canonical growth components and points.
        """
        if scores.empty:
            return
        self._ensure_companies(scores["ticker"].unique())
        rows = [
            (
                str(row.ticker).upper(),
                calculation_date,
                float(row.attention_score),
                _value(row, "social_change"),
                _value(row, "volume_change"),
                _value(row, "price_growth_pct"),
                _value(row, "social_points"),
                _value(row, "volume_points"),
                _value(row, "price_points"),
            )
            for row in scores.itertuples(index=False)
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO attention_scores (
                    ticker, calculation_date, attention_score,
                    social_change, volume_change, price_growth_pct,
                    social_points, volume_points, price_points
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(ticker, calculation_date) DO UPDATE SET
                    attention_score = excluded.attention_score,
                    social_change = excluded.social_change,
                    volume_change = excluded.volume_change,
                    price_growth_pct = excluded.price_growth_pct,
                    social_points = excluded.social_points,
                    volume_points = excluded.volume_points,
                    price_points = excluded.price_points
                """,
                rows,
            )

    def get_upcoming_earnings(self, days: int = 30) -> pd.DataFrame:
        """Return the next earnings event per ticker inside the requested window."""
        return self._query(
            """
            WITH next_earnings AS (
                SELECT ticker, MIN(earnings_date) AS earnings_date
                FROM earnings
                WHERE earnings_date BETWEEN date('now') AND date('now', ?)
                GROUP BY ticker
            )
            SELECT e.ticker, c.company_name, e.earnings_date,
                   e.estimated_eps, e.estimated_revenue, c.sector
            FROM next_earnings n
            JOIN earnings e ON e.ticker = n.ticker
                           AND e.earnings_date = n.earnings_date
            JOIN companies c ON c.ticker = e.ticker
            ORDER BY e.earnings_date, e.ticker
            """,
            (f"+{days} days",),
        )

    def get_daily_metrics(
        self, ticker: str, start_date: str | None = None, end_date: str | None = None
    ) -> pd.DataFrame:
        """Return historical daily metrics for one company."""
        clauses, params = ["ticker = ?"], [ticker.upper()]
        if start_date:
            clauses.append("metric_date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("metric_date <= ?")
            params.append(end_date)
        return self._query(
            f"SELECT metric_date AS date, ticker, close, volume, avg_volume_30d, "
            f"price_change_pct, social_mentions FROM daily_metrics "
            f"WHERE {' AND '.join(clauses)} ORDER BY metric_date",
            tuple(params),
        )

    def get_all_daily_metrics(self) -> pd.DataFrame:
        """Return all historical daily market and social-mention metrics."""
        return self._query(
            "SELECT metric_date AS date, ticker, close, volume, avg_volume_30d, "
            "price_change_pct, social_mentions FROM daily_metrics ORDER BY metric_date"
        )

    def get_rankings(self) -> pd.DataFrame:
        """Return the newest attention score for each company with a genuinely
        upcoming earnings date.

        Once a ticker's earnings date passes, the pipeline stops collecting
        fresh price/volume/mention data for it (see ``src.pipeline``), so an
        older score would otherwise sit frozen and keep re-appearing in the
        rankings forever. Requiring a matching upcoming ``earnings`` row (an
        inner join, not a left join) keeps the dashboard scoped to its stated
        purpose: companies with upcoming earnings, not stale history.
        """
        return self._query(
            """
            WITH latest_scores AS (
                SELECT ticker, MAX(calculation_date) AS calculation_date
                FROM attention_scores
                GROUP BY ticker
            ),
            next_earnings AS (
                SELECT ticker, MIN(earnings_date) AS earnings_date
                FROM earnings
                WHERE earnings_date >= date('now')
                GROUP BY ticker
            )
            SELECT a.ticker, c.company_name, c.sector, e.earnings_date,
                   e.estimated_eps, e.estimated_revenue,
                   a.attention_score, a.social_change, a.volume_change,
                   a.price_growth_pct, a.social_points, a.volume_points,
                   a.price_points, a.calculation_date
            FROM latest_scores l
            JOIN attention_scores a ON a.ticker = l.ticker
                                  AND a.calculation_date = l.calculation_date
            JOIN companies c ON c.ticker = a.ticker
            JOIN next_earnings n ON n.ticker = a.ticker
            JOIN earnings e ON e.ticker = n.ticker
                           AND e.earnings_date = n.earnings_date
            ORDER BY a.attention_score DESC, a.ticker
            """
        )

    def _migrate_legacy_schema(self, conn: sqlite3.Connection) -> None:
        """Migrate older schema versions in place, preserving collected history.

        The attention signal has changed sources twice: Google Trends
        (``trend_score`` / ``trends_growth_pct`` / ``trends_points``), then
        briefly Reddit (``reddit_mentions`` / ``reddit_growth_pct`` /
        ``reddit_points``), and now StockTwits, stored generically as
        ``social_mentions``. The social/volume ranking signal itself later
        changed from a percentage (``social_growth_pct`` / ``volume_growth_pct``)
        to a raw count increase (``social_change`` / ``volume_change``), since
        percentage growth off a tiny base was drowning out genuinely large
        gains. An even older version stored a 60/40 ``composite_score``.

        ``attention_scores`` is always safe to rebuild from scratch (it is
        fully recomputed from ``daily_metrics`` on every refresh).
        ``daily_metrics`` is migrated with an in-place column rename so that
        previously collected price/volume history is not lost.
        """
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='attention_scores'"
        ).fetchone()
        if exists:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(attention_scores)")
            }
            legacy_growth_columns = {
                "trends_growth_pct",
                "reddit_growth_pct",
                "social_growth_pct",
                "volume_growth_pct",
            }
            if "composite_score" in columns or (
                columns & legacy_growth_columns and "social_change" not in columns
            ):
                conn.execute("DROP TABLE attention_scores")

        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='daily_metrics'"
        ).fetchone()
        if exists:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(daily_metrics)")
            }
            if "social_mentions" not in columns:
                if "trend_score" in columns:
                    conn.execute(
                        "ALTER TABLE daily_metrics RENAME COLUMN trend_score TO social_mentions"
                    )
                elif "reddit_mentions" in columns:
                    conn.execute(
                        "ALTER TABLE daily_metrics RENAME COLUMN reddit_mentions TO social_mentions"
                    )

    def _ensure_companies(self, tickers: Iterable[object]) -> None:
        """Create minimal company records needed before inserting child rows."""
        rows = [(str(ticker).upper(), str(ticker).upper()) for ticker in tickers]
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR IGNORE INTO companies (ticker, company_name) VALUES (?, ?)",
                rows,
            )

    def _query(self, sql: str, params: tuple[object, ...] = ()) -> pd.DataFrame:
        """Execute a read query and return its results as a DataFrame."""
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)


def _value(row: object, name: str, default: object = None) -> object:
    """Return a DataFrame row value, converting pandas missing values to None."""
    value = getattr(row, name, default)
    return None if pd.isna(value) else value
