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
# Truncation is applied at render time so spillover still sees every event.
CALENDAR_TICKERS_PER_DAY = 6
_CALENDAR_TICKERS_PER_DAY = CALENDAR_TICKERS_PER_DAY  # backwards-compatible alias
_REACTION_BULLISH_PCT = 3.0
_REACTION_BEARISH_PCT = -3.0
# Display tiers are relative to today's upcoming-earnings batch (not raw /100).
_TIER_ON_RADAR_PCT = 0.10
_TIER_WARMING_PCT = 0.25
_TIER_LABELS = {
    "on_radar": "On the radar",
    "warming_up": "Warming up",
    "background": "Background",
}
_TIER_TO_HEAT = {
    "on_radar": "high",
    "warming_up": "mid",
    "background": "low",
}

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


def format_last_data_refresh(
    moment: datetime | None,
    now: datetime | None = None,
) -> str | None:
    """Format a refresh timestamp for display on the homepage.

    Example: ``Data last refreshed Jul 17 at 12:50 PM EDT (3 hours ago)``.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)

    # Show Eastern time — the product audience and daily job cadence align
    # with US market hours better than raw UTC.
    try:
        from zoneinfo import ZoneInfo

        local = moment.astimezone(ZoneInfo("America/New_York"))
        zone_label = local.tzname() or "ET"
        reference = (now or datetime.now(timezone.utc)).astimezone(
            ZoneInfo("America/New_York")
        )
    except Exception:
        local = moment.astimezone()
        zone_label = local.tzname() or "local"
        reference = (now or datetime.now().astimezone()).astimezone()

    # Avoid platform-specific %-d / %-I flags. No year — freshness matters more.
    stamp = local.strftime("%b %d at %I:%M %p").replace(" 0", " ")
    elapsed_seconds = max(0, int((reference - local).total_seconds()))
    hours_ago = elapsed_seconds // 3600
    if hours_ago <= 0:
        age_label = "less than 1 hour ago"
    elif hours_ago == 1:
        age_label = "1 hour ago"
    else:
        age_label = f"{hours_ago} hours ago"
    return f"Data last refreshed {stamp} {zone_label} ({age_label})"


def reaction_sentiment(reaction_pct: float | None) -> str:
    """Map a post-earnings price reaction percent to a sentiment bucket."""
    if reaction_pct is None or pd.isna(reaction_pct):
        return "unknown"
    if reaction_pct >= _REACTION_BULLISH_PCT:
        return "bullish"
    if reaction_pct <= _REACTION_BEARISH_PCT:
        return "bearish"
    return "mixed"


def attention_tier_for_rank(rank: int, total: int) -> str:
    """Map a 1-based attention rank into an investor-friendly tier.

    Top ~10% of the upcoming batch = on the radar, top ~25% = warming up,
    everyone else = background. Absolute /100 scores stay for sorting only.
    """
    if total <= 0 or rank <= 0:
        return "background"
    # #1 → ~100th percentile of the batch.
    percentile = (total - rank + 1) / total
    if percentile >= (1.0 - _TIER_ON_RADAR_PCT):
        return "on_radar"
    if percentile >= (1.0 - _TIER_WARMING_PCT):
        return "warming_up"
    return "background"


def attention_tier_label(tier: str | None) -> str:
    """Human-readable label for an attention tier."""
    if not tier:
        return _TIER_LABELS["background"]
    return _TIER_LABELS.get(tier, _TIER_LABELS["background"])


def attention_heat(tier_or_score: str | float | None = None) -> str:
    """Map a display tier (preferred) or legacy score into CSS heat buckets."""
    if tier_or_score is None or (isinstance(tier_or_score, float) and pd.isna(tier_or_score)):
        return "none"
    if isinstance(tier_or_score, str):
        return _TIER_TO_HEAT.get(tier_or_score, "none")
    # Legacy absolute-score path kept for older callers/tests.
    if tier_or_score >= 60:
        return "high"
    if tier_or_score >= 30:
        return "mid"
    return "low"


def format_attention_headline(
    rank: int | None, total: int | None, tier: str | None
) -> str:
    """Build the primary attention line shown to investors."""
    label = attention_tier_label(tier)
    if rank is None or total is None or total <= 0:
        return label
    return f"#{int(rank)} of {int(total)} · {label}"


def build_why_chips(row: dict[str, object] | pd.Series) -> list[str]:
    """Plain-language reasons this ticker is getting attention."""
    def _num(key: str) -> float | None:
        value = row.get(key) if isinstance(row, dict) else row.get(key)
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    chips: list[str] = []
    social = _num("social_change")
    if social is not None and social > 0:
        chips.append(f"Mentions +{social:,.0f}")
    yahoo = _num("yahoo_change")
    if yahoo is None:
        yahoo = _num("yahoo_rank_change")
    if yahoo is not None and yahoo > 0:
        chips.append(f"Yahoo ↑{yahoo:,.0f} ranks")
    volume_pts = _num("volume_points")
    if volume_pts is not None and volume_pts >= 40:
        chips.append("Unusual volume")
    price = _num("price_growth_pct")
    if price is not None and price >= 1:
        chips.append(f"Price +{price:.0f}% (7d)")
    if not chips:
        chips.append("Quiet this week")
    return chips


def annotate_attention_display(attention: pd.DataFrame) -> pd.DataFrame:
    """Add rank, tier, and headline columns for dashboard display."""
    if attention.empty or "attention_score" not in attention.columns:
        return attention
    framed = attention.sort_values(
        ["attention_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)
    total = len(framed)
    framed["attention_rank"] = range(1, total + 1)
    framed["attention_total"] = total
    framed["attention_tier"] = [
        attention_tier_for_rank(int(rank), total) for rank in framed["attention_rank"]
    ]
    framed["attention_tier_label"] = framed["attention_tier"].map(attention_tier_label)
    framed["attention_headline"] = [
        format_attention_headline(int(rank), total, tier)
        for rank, tier in zip(framed["attention_rank"], framed["attention_tier"])
    ]
    framed["attention_heat"] = framed["attention_tier"].map(
        lambda tier: attention_heat(str(tier))
    )
    return framed


def _post_earnings_reaction_pct(
    metrics: pd.DataFrame, ticker: str, earnings_date: date
) -> float | None:
    """Return % price change from earnings-day close to the next trading close.

    Approximation: ignores BMO vs AMC timing. For before-market-open prints the
    earnings-day close already includes much of the move, so the measured
    “next-day” reaction can understate the full gap. Prefer this as directional
    color on the calendar, not a precise event study.
    """
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
    tickers_per_day: int | None = None,
) -> dict[str, object]:
    """Build the current-month anticipated-earnings calendar payload.

    ``reference_date`` defaults to today so the month rolls over automatically
    when the calendar changes. Past days use post-earnings price reaction
    sentiment; future days use attention heat and optional pre-report momentum.

    Day lists are returned in full. Pass ``tickers_per_day`` only when a caller
    wants display truncation; the homepage renderer truncates separately so
    spillover can still see every influencer.
    """
    today = reference_date or date.today()
    store = SQLiteStore(database_path)
    events = store.get_earnings_in_month(today.year, today.month)
    metrics = store.get_all_daily_metrics()
    rankings = store.get_rankings()
    if rankings.empty and not events.empty:
        # Historical reference dates (or empty live window) still need relative
        # tiers from whatever attention scores are attached to this month.
        scored = events.dropna(subset=["attention_score"])[
            ["ticker", "attention_score"]
        ].drop_duplicates(subset=["ticker"])
        display = annotate_attention_display(scored)
    else:
        display = annotate_attention_display(rankings)
    display_by_ticker = (
        display.set_index("ticker").to_dict(orient="index") if not display.empty else {}
    )
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
            ticker = str(row["ticker"])
            score = row.get("attention_score")
            attention_value = (
                float(score) if score is not None and pd.notna(score) else None
            )
            is_past = event_date < today
            reaction_pct = (
                _post_earnings_reaction_pct(metrics, ticker, event_date)
                if is_past
                else None
            )
            sentiment = reaction_sentiment(reaction_pct) if is_past else None
            display_row = display_by_ticker.get(ticker, {})
            tier = None if is_past else display_row.get("attention_tier")
            heat = attention_heat(tier) if not is_past else None
            momentum = (
                None
                if is_past
                else _pre_earnings_momentum(metrics, ticker, event_date)
            )
            by_day[event_day].append(
                {
                    "ticker": ticker,
                    "company_name": str(row.get("company_name") or ticker),
                    "sector": str(row.get("sector") or "") or None,
                    "earnings_date": event_date,
                    "attention_score": attention_value,
                    "attention_rank": display_row.get("attention_rank"),
                    "attention_total": display_row.get("attention_total"),
                    "attention_tier": tier,
                    "attention_tier_label": (
                        None if is_past else display_row.get("attention_tier_label")
                    ),
                    "attention_headline": (
                        None if is_past else display_row.get("attention_headline")
                    ),
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
            if tickers_per_day is not None:
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

        peers = same_sector_peers(ticker, sector, peer_source, max_peers=max_peers)

        if item.get("is_past") and item.get("sentiment") == "bearish":
            watch_note = "sector pressure after bearish print"
        elif item.get("is_past") and item.get("sentiment") == "bullish":
            watch_note = "sector lift after bullish print"
        elif item.get("is_past"):
            watch_note = "mixed post-report reaction — watch peers"
        elif item.get("attention_tier") == "on_radar":
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


def same_sector_peers(
    ticker: str,
    sector: str | None,
    attention: pd.DataFrame,
    max_peers: int = 5,
) -> list[dict[str, object]]:
    """Return top same-sector peers by attention score, excluding ``ticker``."""
    if (
        not sector
        or attention.empty
        or "sector" not in attention.columns
        or "ticker" not in attention.columns
    ):
        return []
    same_sector = attention[
        (attention["sector"] == sector) & (attention["ticker"] != ticker)
    ].sort_values("attention_score", ascending=False)
    peers: list[dict[str, object]] = []
    for _, peer in same_sector.head(max_peers).iterrows():
        peers.append(
            {
                "ticker": str(peer["ticker"]),
                "company_name": str(peer.get("company_name") or peer["ticker"]),
                "attention_score": float(peer["attention_score"])
                if pd.notna(peer.get("attention_score"))
                else None,
            }
        )
    return peers


def build_this_week_focus(
    attention: pd.DataFrame,
    reference_date: date | None = None,
    days: int = 7,
    limit: int = 8,
) -> list[dict[str, object]]:
    """Return upcoming prints in the next ``days`` days, ranked by attention."""
    if attention.empty or "earnings_date" not in attention.columns:
        return []
    framed = attention
    if "attention_tier" not in framed.columns:
        framed = annotate_attention_display(framed)
    today = reference_date or date.today()
    end = date.fromordinal(today.toordinal() + days)
    frame = framed.copy()
    frame["earnings_date"] = pd.to_datetime(frame["earnings_date"]).dt.date
    window = frame[
        (frame["earnings_date"] >= today) & (frame["earnings_date"] < end)
    ].sort_values("attention_score", ascending=False)
    results: list[dict[str, object]] = []
    for _, row in window.head(limit).iterrows():
        score = (
            float(row["attention_score"])
            if pd.notna(row.get("attention_score"))
            else None
        )
        tier = (
            str(row["attention_tier"])
            if pd.notna(row.get("attention_tier"))
            else None
        )
        rank = (
            int(row["attention_rank"])
            if pd.notna(row.get("attention_rank"))
            else None
        )
        total = (
            int(row["attention_total"])
            if pd.notna(row.get("attention_total"))
            else None
        )
        results.append(
            {
                "ticker": str(row["ticker"]),
                "company_name": str(row.get("company_name") or row["ticker"]),
                "earnings_date": row["earnings_date"],
                "attention_score": score,
                "attention_rank": rank,
                "attention_total": total,
                "attention_tier": tier,
                "attention_tier_label": attention_tier_label(tier),
                "attention_headline": format_attention_headline(rank, total, tier),
                "why_chips": build_why_chips(row),
                "heat": attention_heat(tier),
                "sector": str(row["sector"])
                if pd.notna(row.get("sector")) and row.get("sector")
                else None,
            }
        )
    return results


def build_weekly_postmortem(
    reference_date: date | None = None,
    days: int = 7,
    limit: int = 5,
    database_path: Path | str = DATABASE_FILE,
) -> dict[str, list[dict[str, object]]]:
    """Return biggest post-report beats and misses from the last ``days`` days.

    Queries a rolling date window from SQLite so prints near a month boundary
    (e.g. Jun 28 when today is Jul 3) are included even when the month calendar
    only shows the current month.
    """
    today = reference_date or date.today()
    start = date.fromordinal(today.toordinal() - days)
    store = SQLiteStore(database_path)
    events = store.get_earnings_between(start, today)
    metrics = store.get_all_daily_metrics()

    items: list[dict[str, object]] = []
    if not events.empty:
        framed = events.copy()
        framed["earnings_date"] = pd.to_datetime(framed["earnings_date"]).dt.date
        for _, row in framed.iterrows():
            event_date = row["earnings_date"]
            if not (start <= event_date < today):
                continue
            ticker = str(row["ticker"])
            reaction = _post_earnings_reaction_pct(metrics, ticker, event_date)
            if reaction is None:
                continue
            items.append(
                {
                    "ticker": ticker,
                    "company_name": str(row.get("company_name") or ticker),
                    "sector": str(row.get("sector") or "") or None,
                    "earnings_date": event_date,
                    "is_past": True,
                    "reaction_pct": reaction,
                    "sentiment": reaction_sentiment(reaction),
                }
            )

    beats = sorted(
        items, key=lambda row: float(row["reaction_pct"]), reverse=True
    )[:limit]
    misses = sorted(items, key=lambda row: float(row["reaction_pct"]))[:limit]
    return {"beats": beats, "misses": misses}


def get_researchable_tickers(
    database_path: Path | str = DATABASE_FILE,
) -> list[str]:
    """Return tickers with stored company, earnings, or metrics history."""
    store = SQLiteStore(database_path)
    return store.get_all_tickers()


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
        "most_mentioned": pd.DataFrame(),
        "yahoo_rank_growth": pd.DataFrame(),
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
    attention = annotate_attention_display(attention)

    most_mentioned = attention.dropna(subset=["current_mentions"]).sort_values(
        "current_mentions", ascending=False
    )
    yahoo_with_change = attention.dropna(subset=["yahoo_rank_change"])
    yahoo_rank_growth = yahoo_with_change.loc[
        yahoo_with_change["yahoo_rank_change"] > 0
    ].sort_values("yahoo_rank_change", ascending=False)

    return {
        "earnings": earnings,
        "metrics": metrics,
        "attention": attention,
        "most_mentioned": most_mentioned,
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


def get_company_data(
    ticker: str, database_path: Path | str = DATABASE_FILE
) -> dict[str, object]:
    """Return all dashboard-ready information for a selected ticker."""
    data = load_dashboard_data()
    ticker = ticker.upper()
    metrics = data["metrics"]
    company_metrics = metrics[metrics["ticker"] == ticker].copy()
    company_earnings = data["earnings"]
    company_earnings = company_earnings[company_earnings["ticker"] == ticker]
    company_score = data["attention"]
    company_score = company_score[company_score["ticker"] == ticker]

    earnings = (
        company_earnings.iloc[0].to_dict() if not company_earnings.empty else {}
    )
    score = company_score.iloc[0].to_dict() if not company_score.empty else {}
    in_live_rankings = bool(score)

    # Past prints drop out of upcoming rankings — fall back to stored rows.
    store = SQLiteStore(database_path)
    if not earnings:
        earnings = store.get_latest_earnings_for_ticker(ticker)
    if not score:
        score = store.get_latest_attention_for_ticker(ticker)
    if not earnings.get("company_name") or not earnings.get("sector"):
        profile = store.get_company_profile(ticker)
        earnings = {**profile, **earnings}

    peers = same_sector_peers(
        ticker,
        earnings.get("sector") or score.get("sector"),
        data["attention"],
    )

    why_chips = build_why_chips(score)
    if in_live_rankings:
        headline = score.get("attention_headline") or format_attention_headline(
            score.get("attention_rank"),
            score.get("attention_total"),
            score.get("attention_tier"),
        )
    elif score:
        # Avoid a bare "Background" that looks like today's relative tier.
        headline = "Not in this week's rankings"
    else:
        headline = "No attention score yet"

    return {
        "metrics": company_metrics,
        "earnings": earnings,
        "score": score,
        "peers": peers,
        "why_chips": why_chips,
        "attention_headline": headline,
        "in_live_rankings": in_live_rankings,
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


def format_share_volume(value: float | int | None) -> str:
    """Format share volume with M / B suffixes for compact metric display."""
    if value is None or pd.isna(value):
        return "—"
    amount = float(value)
    if amount >= 1_000_000_000:
        return f"{amount / 1_000_000_000:.1f}B"
    if amount >= 1_000_000:
        return f"{amount / 1_000_000:.1f}M"
    if amount >= 1_000:
        return f"{amount / 1_000:.1f}K"
    return f"{amount:,.0f}"
