"""Configurable 0–100 attention scoring for earnings candidates.

Example:
    import pandas as pd
    from src.analytics.scoring import calculate_attention_scores

    growth = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "social_7d_change": [450, 20],
            "volume_7d_change": [2_000_000, 8_000_000],
            "volume_7d_rel_change": [0.5, 2.0],
            "price_7d_growth_pct": [10, 5],
            "yahoo_7d_change": [15, 3],
        }
    )
    ranked = calculate_attention_scores(growth)
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class AttentionScoreConfig:
    """Weights and caps used to calculate the Version 1 attention score.

    Weights must total 1.0. Social mentions, relative volume, and Yahoo trend
    climbs are ranked by raw increase (biggest gainer in the batch = 100).
    Price stays percentage-based with ``price_cap_pct``.
    """

    social_weight: float = 0.40
    yahoo_weight: float = 0.25
    volume_weight: float = 0.20
    price_weight: float = 0.15
    price_cap_pct: float = 30.0
    growth_period_days: int = 7

    def __post_init__(self) -> None:
        weights = (
            self.social_weight,
            self.yahoo_weight,
            self.volume_weight,
            self.price_weight,
        )
        if any(weight < 0 for weight in weights):
            raise ValueError("Attention-score weights cannot be negative.")
        if round(sum(weights), 10) != 1.0:
            raise ValueError("Attention-score weights must add up to 1.0.")
        if self.price_cap_pct <= 0:
            raise ValueError("Attention-score growth caps must be greater than zero.")
        if self.growth_period_days <= 0:
            raise ValueError("growth_period_days must be greater than zero.")


def calculate_attention_scores(
    growth_metrics: pd.DataFrame,
    config: AttentionScoreConfig = AttentionScoreConfig(),
) -> pd.DataFrame:
    """Calculate and rank Version 1 0–100 attention scores.

    The input normally comes from ``calculate_growth_metrics``. The selected
    growth period defaults to seven days and is configurable through
    ``AttentionScoreConfig``.

    Missing signals receive zero points. This deliberately avoids inflating a
    company's score when social mentions or another source is unavailable.
    """
    period = config.growth_period_days
    required_columns = {
        "ticker",
        f"social_{period}d_change",
        f"volume_{period}d_change",
        f"price_{period}d_growth_pct",
    }
    missing = required_columns - set(growth_metrics.columns)
    if missing:
        raise ValueError(
            "growth_metrics is missing required column(s): "
            + ", ".join(sorted(missing))
        )

    scored = growth_metrics.copy()
    social_column = f"social_{period}d_change"
    volume_raw_column = f"volume_{period}d_change"
    volume_rel_column = f"volume_{period}d_rel_change"
    price_column = f"price_{period}d_growth_pct"
    yahoo_column = f"yahoo_{period}d_change"

    # Prefer relative volume (change / 30d avg) so absolute share volume does
    # not let mega-caps dominate. Fall back to raw volume change when the
    # relative series is unavailable for the whole batch.
    volume_column = (
        volume_rel_column
        if volume_rel_column in scored.columns
        and scored[volume_rel_column].notna().any()
        else volume_raw_column
    )

    scored["social_points"] = _normalize_change(scored[social_column])
    scored["volume_points"] = _normalize_change(scored[volume_column])
    scored["price_points"] = _normalize_growth(
        scored[price_column], config.price_cap_pct
    )
    if yahoo_column in scored.columns:
        scored["yahoo_points"] = _normalize_change(scored[yahoo_column])
        scored["yahoo_change"] = scored[yahoo_column]
    else:
        scored["yahoo_points"] = 0.0
        scored["yahoo_change"] = pd.NA

    scored["social_change"] = scored[social_column]
    scored["volume_change"] = scored[volume_raw_column]
    scored["price_growth_pct"] = scored[price_column]

    scored["attention_score"] = (
        scored["social_points"] * config.social_weight
        + scored["yahoo_points"] * config.yahoo_weight
        + scored["volume_points"] * config.volume_weight
        + scored["price_points"] * config.price_weight
    ).round(2)

    scored = scored.sort_values(
        ["attention_score", "ticker"], ascending=[False, True]
    ).reset_index(drop=True)
    scored.index = scored.index + 1
    scored.index.name = "rank"
    return scored


def _normalize_growth(growth: pd.Series, cap_pct: float) -> pd.Series:
    """Turn percentage growth into a capped 0–100 component score."""
    return (growth.fillna(0).clip(lower=0, upper=cap_pct) / cap_pct * 100).round(2)


def _normalize_change(change: pd.Series) -> pd.Series:
    """Turn a raw count increase into a 0–100 component score.

    Unlike a percentage, an absolute increase has no natural fixed cap — 10
    more mentions might be huge for a small-cap and negligible for a
    mega-cap. Instead, whichever ticker in the current batch gained the most
    scores 100, and every other ticker is scaled relative to that leader. A
    decline or flat count scores zero (no attention contribution).
    """
    positive_change = change.fillna(0).clip(lower=0)
    largest_increase = positive_change.max()
    if not largest_increase or largest_increase <= 0:
        return positive_change * 0.0
    return (positive_change / largest_increase * 100).round(2)
