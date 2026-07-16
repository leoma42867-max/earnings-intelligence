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
_CALENDAR_TICKERS_PER_DAY = 6
_REACTION_BULLISH_PCT = 3.0
_REACTION_BEARISH_PCT = -3.0
_HEAT_HIGH = 60.0
_HEAT_MID = 30.0

# Mega-cap / sector influencers whose prints can move peers.
_SECTOR_INFLUENCERS: dict[str, tuple[str, ...]] = {
    "Technology": (
        "AAPL", "MSFT", "NVDA", "GOOGL", "GOOG", "META", "AVGO", "IBM",
        "ORCL", "CRM", "AMD", "INTC", "CSCO", "ADBE", "QCOM",
    ),
    "Communication Services": ("META", "GOOGL", "GOOG", "NFLX", "DIS", "T", "VZ"),
    "Consumer Cyclical": ("AMZN", "TSLA", "HD", "NKE", "SBUX", "MCD", "BKNG"),
    "Consumer Defensive": ("WMT", "COST", "PG", "KO", "PEP", "PM"),
    "Financial Services": ("JPM", "BAC", "GS", "MS", "V", "MA", "BRK-B", "C"),
    "Healthcare": ("UNH", "JNJ", "LLY", "ABBV", "MRK", "PFE", "TMO"),
    "Energy": ("XOM", "CVX", "COP", "SLB", "EOG"),
    "Industrials": ("CAT", "GE", "HON", "UPS", "BA", "RTX"),
    "Basic Materials": ("LIN", "APD", "SHW", "FCX"),
    "Utilities": ("NEE", "DUK", "SO"),
    "Real Estate": ("PLD", "AMT", "CCI"),
}

_SENTIMENT_SORT = {"bearish": 0, "mixed": 1, "bullish": 2, "unknown": 3}
_HEAT_SORT = {"high": 0, "mid": 1, "low": 2, "none": 3}


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


def reaction_sentiment(reaction_pct: float | None) -> str:
    """Map a post-earnings price reaction percent to a sentiment bucket."""
    if reaction_pct is None or pd.isna(reaction_pct):
        return "unknown"
    if reaction_pct >= _REACTION_BULLISH_PCT:
        return "bullish"
    if reaction_pct <= _REACTION_BEARISH_PCT:
        return "bearish"
    return "mixed"


def attention_heat(attention_score: float | None) -> str:
    """Bucket upcoming-report attention into high / mid / low heat."""
    if attention_score is None or pd.isna(attention_score):
        return "none"
    if attention_score >= _HEAT_HIGH:
        return "high"
    if attention_score >= _HEAT_MID:
        return "mid"
    return "low"


def _post_earnings_reaction_pct(
    metrics: pd.DataFrame, ticker: str, earnings_date: date
) -> float | None:
    """Return % price change from earnings-day close to the next trading close."""
    if metrics.empty or "close" not in metrics.columns:
        return None
    history = metrics[metrics["ticker"] == ticker].copy()
    if history.empty:
        return None
    history["date"] = pd.to_datetime(history["date"]).dt.date
    history = history.dropna(subset=["close"]).sort_values("date")
    if history.empty:
        return None

    on_or_before = history[history["date"] <= earnings_date]
    if on_or_before.empty:
        return None
    before_close = float(on_or_before.iloc[-1]["close"])
    if before_close == 0:
        return None

    after = history[history["date"] > earnings_date]
    if after.empty:
        return None
    after_close = float(after.iloc[0]["close"])
    return round(((after_close - before_close) / before_close) * 100, 2)


def _pre_earnings_momentum(
    metrics: pd.DataFrame, ticker: str, earnings_date: date, days: int = 7
) -> str | None:
    """Return ↑ / ↓ for 7-day price momentum into the report when available."""
    if metrics.empty or "close" not in metrics.columns:
        return None
    history = metrics[metrics["ticker"] == ticker].copy()
    if history.empty:
        return None
    history["date"] = pd.to_datetime(history["date"]).dt.date
    history = history.dropna(subset=["close"]).sort_values("date")
    cutoff = min(earnings_date, date.today())
    usable = history[history["date"] <= cutoff]
    if usable.empty:
        return None
    latest = usable.iloc[-1]
    prior_cutoff = date.fromordinal(latest["date"].toordinal() - days)
    historical = usable[usable["date"] <= prior_cutoff]
    if historical.empty:
        return None
    previous = float(historical.iloc[-1]["close"])
    current = float(latest["close"])
    if previous == 0:
        return None
    change = ((current - previous) / previous) * 100
    if change >= 1.0:
        return "↑"
    if change <= -1.0:
        return "↓"
    return None


def build_anticipated_earnings_calendar(
    reference_date: date | None = None,
    database_path: Path | str = DATABASE_FILE,
    tickers_per_day: int = _CALENDAR_TICKERS_PER_DAY,
) -> dict[str, object]:
    """Build the current-month anticipated-earnings calendar payload.

    ``reference_date`` defaults to today so the month rolls over automatically
    when the calendar changes. Past days use post-earnings price reaction
    sentiment; future days use attention heat and optional pre-report momentum.
    """
    today = reference_date or date.today()
    store = SQLiteStore(database_path)
    events = store.get_earnings_in_month(today.year, today.month)
    metrics = store.get_all_daily_metrics()
    days_in_month = calendar_module.monthrange(today.year, today.month)[1]
    first_weekday = date(today.year, today.month, 1).weekday()

    by_day: dict[int, list[dict[str, object]]] = {
        day: [] for day in range(1, days_in_month + 1)
    }
    if not events.empty:
        events = events.copy()
        events["earnings_date"] = pd.to_datetime(events["earnings_date"]).dt.date
        for _, row in events.iterrows():
            event_date = row["earnings_date"]
            event_day = event_date.day
            score = row.get("attention_score")
            attention_value = (
                float(score) if score is not None and pd.notna(score) else None
            )
            is_past = event_date < today
            reaction_pct = (
                _post_earnings_reaction_pct(metrics, str(row["ticker"]), event_date)
                if is_past
                else None
            )
            sentiment = reaction_sentiment(reaction_pct) if is_past else None
            heat = attention_heat(attention_value) if not is_past else None
            momentum = (
                None
                if is_past
                else _pre_earnings_momentum(metrics, str(row["ticker"]), event_date)
            )
            by_day[event_day].append(
                {
                    "ticker": str(row["ticker"]),
                    "company_name": str(row.get("company_name") or row["ticker"]),
                    "sector": str(row.get("sector") or "") or None,
                    "earnings_date": event_date,
                    "attention_score": attention_value,
                    "is_past": is_past,
                    "reaction_pct": reaction_pct,
                    "sentiment": sentiment,
                    "heat": heat,
                    "momentum": momentum,
                }
            )

        for day, tickers in by_day.items():
            if not tickers:
                continue
            if tickers[0]["is_past"]:
                tickers.sort(
                    key=lambda item: (
                        _SENTIMENT_SORT.get(
                            str(item.get("sentiment") or "unknown"), 3
                        ),
                        -(
                            abs(item["reaction_pct"])
                            if item.get("reaction_pct") is not None
                            else -1
                        ),
                        item["ticker"],
                    )
                )
            else:
                tickers.sort(
                    key=lambda item: (
                        _HEAT_SORT.get(str(item.get("heat") or "none"), 3),
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


def build_earnings_spillover(
    calendar: dict[str, object],
    attention: pd.DataFrame,
    max_influencers: int = 6,
    max_peers: int = 5,
) -> list[dict[str, object]]:
    """Return mega-cap calendar influencers and same-sector peers in the blast radius."""
    influencer_universe = {
        ticker for names in _SECTOR_INFLUENCERS.values() for ticker in names
    }
    calendar_items: list[dict[str, object]] = []
    for day_tickers in calendar.get("days", {}).values():
        calendar_items.extend(day_tickers)

    influencers = [
        item
        for item in calendar_items
        if str(item["ticker"]) in influencer_universe
    ]
    if not influencers:
        return []

    def _influencer_rank(item: dict[str, object]) -> tuple:
        reaction = item.get("reaction_pct")
        return (
            0 if item.get("is_past") and item.get("sentiment") == "bearish" else 1,
            0 if not item.get("is_past") else 1,
            -(abs(reaction) if reaction is not None else 0.0),
            -(item.get("attention_score") or 0.0),
            str(item["ticker"]),
        )

    influencers = sorted(influencers, key=_influencer_rank)[:max_influencers]

    peer_source = attention.copy() if not attention.empty else pd.DataFrame()
    results: list[dict[str, object]] = []
    for item in influencers:
        ticker = str(item["ticker"])
        sector = item.get("sector")
        if (
            not sector
            and not peer_source.empty
            and "sector" in peer_source.columns
            and (peer_source["ticker"] == ticker).any()
        ):
            sector = str(
                peer_source.loc[peer_source["ticker"] == ticker, "sector"].iloc[0]
            )

        peers: list[dict[str, object]] = []
        if sector and not peer_source.empty and "sector" in peer_source.columns:
            same_sector = peer_source[
                (peer_source["sector"] == sector) & (peer_source["ticker"] != ticker)
            ].sort_values("attention_score", ascending=False)
            for _, peer in same_sector.head(max_peers).iterrows():
                peers.append(
                    {
                        "ticker": str(peer["ticker"]),
                        "company_name": str(
                            peer.get("company_name") or peer["ticker"]
                        ),
                        "attention_score": float(peer["attention_score"])
                        if pd.notna(peer.get("attention_score"))
                        else None,
                    }
                )

        if item.get("is_past") and item.get("sentiment") == "bearish":
            watch_note = "sector pressure after bearish print"
        elif item.get("is_past") and item.get("sentiment") == "bullish":
            watch_note = "sector lift after bullish print"
        elif item.get("is_past"):
            watch_note = "mixed post-report reaction — watch peers"
        elif (item.get("attention_score") or 0) >= _HEAT_HIGH:
            watch_note = "high attention into print — watch peers"
        else:
            watch_note = "upcoming influencer print — watch peers"

        status = (
            str(item.get("sentiment") or "unknown")
            if item.get("is_past")
            else "upcoming"
        )
        results.append(
            {
                "ticker": ticker,
                "company_name": item.get("company_name") or ticker,
                "sector": sector or "Unknown",
                "status": status,
                "reaction_pct": item.get("reaction_pct"),
                "attention_score": item.get("attention_score"),
                "watch_note": watch_note,
                "peers": peers,
            }
        )
    return results


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
