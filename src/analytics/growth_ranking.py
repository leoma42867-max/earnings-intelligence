"""Calculate multi-period growth signals and rank companies by momentum.

Example:
    from src.storage.sqlite_store import SQLiteStore
    from config.settings import DATABASE_FILE
    from src.analytics.growth_ranking import rank_companies_by_growth

    store = SQLiteStore(DATABASE_FILE)
    rankings = rank_companies_by_growth(store.get_all_daily_metrics())
    print(rankings.head())
"""

from __future__ import annotations

import pandas as pd


GROWTH_PERIODS = (1, 3, 7, 30)

# Social mentions and trading volume are both "count" signals — ranking is
# based on the raw increase in count (e.g. "+450 mentions"), not a percentage.
# A stock going from 2 mentions to 50 mentions is a 2400% "growth" that would
# swamp a mega-cap going from 5,000 to 8,000 mentions, even though the latter
# reflects far more actual attention. Absolute change avoids that distortion.
COUNT_SIGNALS = {
    "social_mentions": "social",
    "volume": "volume",
}

# Price only makes sense as a percentage — a $2 move means very different
# things for a $10 stock versus a $500 stock, so it keeps the old pct-growth
# treatment.
PCT_SIGNALS = {
    "close": "price",
}

SIGNALS = {**COUNT_SIGNALS, **PCT_SIGNALS}

# Off Yahoo's trending list (~top 100) is treated as one slot below the list
# when measuring how many ranks a ticker climbed.
_OFF_YAHOO_LIST_RANK = 101


def calculate_growth_metrics(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    """Calculate 1, 3, 7, and 30-day change for each ticker.

    Args:
        daily_metrics: A DataFrame containing ``date``, ``ticker``,
            ``social_mentions``, ``volume``, and ``close``. Fields can be
            null when a source did not return data. Optional columns
            ``avg_volume_30d`` and ``yahoo_trend_rank`` improve scoring.

    Returns:
        One row per ticker. Social mentions and volume are reported as the
        raw ``current value - value N days earlier`` (e.g. ``social_7d_change``).
        Volume also gets a relative change vs 30-day average volume
        (``volume_7d_rel_change``) so mega-caps do not dominate the score.
        Price is a percentage (``price_7d_growth_pct``). Yahoo trend climbs
        are ``yahoo_7d_change`` (positive = moved up the trending list).
    """
    metrics = daily_metrics.copy()
    _validate_metrics(metrics)
    metrics["date"] = pd.to_datetime(metrics["date"])
    metrics = metrics.sort_values(["ticker", "date"])

    records: list[dict[str, object]] = []
    for ticker, ticker_data in metrics.groupby("ticker", sort=False):
        latest_row = ticker_data.iloc[-1]
        record: dict[str, object] = {
            "ticker": ticker,
            "latest_date": latest_row["date"].date().isoformat(),
        }

        for source_column, label in COUNT_SIGNALS.items():
            for days in GROWTH_PERIODS:
                raw_change = _change_for_period(ticker_data, source_column, days)
                record[f"{label}_{days}d_change"] = raw_change
                if label == "volume":
                    record[f"volume_{days}d_rel_change"] = _relative_volume_change(
                        raw_change, latest_row.get("avg_volume_30d")
                    )

        for source_column, label in PCT_SIGNALS.items():
            for days in GROWTH_PERIODS:
                record[f"{label}_{days}d_growth_pct"] = _growth_for_period(
                    ticker_data, source_column, days
                )

        for days in GROWTH_PERIODS:
            record[f"yahoo_{days}d_change"] = _yahoo_rank_climb_for_period(
                ticker_data, days
            )

        records.append(record)

    return pd.DataFrame(records)


def rank_companies_by_growth(daily_metrics: pd.DataFrame) -> pd.DataFrame:
    """Return companies ranked by equally weighted available momentum signals.

    Since count changes (social mentions, volume) and percentage changes
    (price) are not directly comparable, each 1-, 3-, 7-, and 30-day signal is
    first rescaled 0–100 relative to the largest gainer in this batch (see
    ``src.analytics.scoring._normalize_change``/``_normalize_growth``), then
    averaged. It is a simple V1 momentum ranking, not investment advice.
    """
    growth = calculate_growth_metrics(daily_metrics)
    if growth.empty:
        return growth

    from src.analytics.scoring import _normalize_change, _normalize_growth

    score_columns: list[str] = []
    for label in COUNT_SIGNALS.values():
        for days in GROWTH_PERIODS:
            # Prefer relative volume so absolute share volume does not dominate.
            column = (
                f"volume_{days}d_rel_change"
                if label == "volume"
                else f"{label}_{days}d_change"
            )
            score_column = f"{column}_score"
            growth[score_column] = _normalize_change(growth[column])
            score_columns.append(score_column)
    for label in PCT_SIGNALS.values():
        for days in GROWTH_PERIODS:
            column = f"{label}_{days}d_growth_pct"
            score_column = f"{column}_score"
            growth[score_column] = _normalize_growth(growth[column], cap_pct=30.0)
            score_columns.append(score_column)
    for days in GROWTH_PERIODS:
        column = f"yahoo_{days}d_change"
        score_column = f"{column}_score"
        growth[score_column] = _normalize_change(growth[column])
        score_columns.append(score_column)

    growth["growth_score"] = growth[score_columns].mean(axis=1, skipna=True).round(2)
    growth = growth.drop(columns=score_columns)
    growth = growth.dropna(subset=["growth_score"])
    growth = growth.sort_values(
        ["growth_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)
    growth.index = growth.index + 1
    growth.index.name = "rank"
    return growth


def _change_for_period(
    ticker_data: pd.DataFrame, column: str, days: int
) -> float | None:
    """Calculate the raw (absolute) change from N days earlier to the latest value."""
    usable_data = ticker_data.dropna(subset=[column])
    if usable_data.empty:
        return None

    latest = usable_data.iloc[-1]
    target_date = latest["date"] - pd.Timedelta(days=days)
    historical = usable_data[usable_data["date"] <= target_date]
    if historical.empty:
        return None

    previous_value = historical.iloc[-1][column]
    current_value = latest[column]
    return round(current_value - previous_value, 2)


def _relative_volume_change(
    raw_volume_change: float | None, avg_volume_30d: object
) -> float | None:
    """Scale a volume change by 30-day average volume (unusual-activity signal)."""
    if raw_volume_change is None:
        return None
    if avg_volume_30d is None or pd.isna(avg_volume_30d):
        return None
    average = float(avg_volume_30d)
    if average <= 0:
        return None
    return round(raw_volume_change / average, 4)


def _yahoo_rank_climb_for_period(
    ticker_data: pd.DataFrame, days: int
) -> float | None:
    """Return how many Yahoo trending ranks climbed over ``days`` (positive = up)."""
    if "yahoo_trend_rank" not in ticker_data.columns:
        return None

    history = ticker_data.sort_values("date")
    if history.empty:
        return None

    latest = history.iloc[-1]
    target_date = latest["date"] - pd.Timedelta(days=days)
    previous_rows = history[history["date"] <= target_date]
    if previous_rows.empty:
        return None

    previous_rank = previous_rows.iloc[-1]["yahoo_trend_rank"]
    current_rank = latest["yahoo_trend_rank"]
    if pd.isna(previous_rank) and pd.isna(current_rank):
        return None

    previous_value = (
        int(previous_rank) if pd.notna(previous_rank) else _OFF_YAHOO_LIST_RANK
    )
    current_value = (
        int(current_rank) if pd.notna(current_rank) else _OFF_YAHOO_LIST_RANK
    )
    return float(previous_value - current_value)


def _growth_for_period(
    ticker_data: pd.DataFrame, column: str, days: int
) -> float | None:
    """Calculate a percentage change from the latest value to N days earlier."""
    usable_data = ticker_data.dropna(subset=[column])
    if usable_data.empty:
        return None

    latest = usable_data.iloc[-1]
    target_date = latest["date"] - pd.Timedelta(days=days)
    historical = usable_data[usable_data["date"] <= target_date]
    if historical.empty:
        return None

    previous_value = historical.iloc[-1][column]
    current_value = latest[column]
    if previous_value == 0:
        return None

    return round(((current_value - previous_value) / previous_value) * 100, 2)


def _validate_metrics(daily_metrics: pd.DataFrame) -> None:
    """Fail early with a clear message when a caller supplies the wrong data."""
    required_columns = {"date", "ticker"}
    missing = required_columns - set(daily_metrics.columns)
    if missing:
        raise ValueError(
            "daily_metrics is missing required column(s): " + ", ".join(sorted(missing))
        )

    # ``trend_score`` (Google Trends) and ``reddit_mentions`` (Reddit) were
    # earlier column names for this signal; support them transparently for
    # any caller not yet migrated to the generic ``social_mentions`` name.
    if "social_mentions" not in daily_metrics.columns:
        for legacy_column in ("trend_score", "reddit_mentions"):
            if legacy_column in daily_metrics.columns:
                daily_metrics.rename(
                    columns={legacy_column: "social_mentions"}, inplace=True
                )
                break

    for column in SIGNALS:
        if column not in daily_metrics.columns:
            daily_metrics[column] = pd.NA
