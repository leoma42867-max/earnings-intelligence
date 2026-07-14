"""Configurable 0–100 attention scoring for earnings candidates.

Example:
    import pandas as pd
    from src.analytics.scoring import calculate_attention_scores

    growth = pd.DataFrame(
        {
            "ticker": ["AAPL", "MSFT"],
            "social_7d_change": [450, 20],
            "volume_7d_change": [2_000_000, 8_000_000],
            "price_7d_growth_pct": [10, 5],
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

    Weights must total 1.0. Social mentions and volume are ranked by their
    *raw count increase* rather than a percentage (see module docstring), so
    they have no fixed cap — instead, the biggest gainer in the current
    batch scores 100 and everyone else is scaled relative to it. Price stays
    percentage-based, so ``price_cap_pct`` still converts it to a bounded
    0–100 signal; a price growth rate at or above the cap receives 100 points.
    """

    social_weight: float = 0.50
    volume_weight: float = 0.30
    price_weight: float = 0.20
    price_cap_pct: float = 30.0
    growth_period_days: int = 7

    def __post_init__(self) -> None:
        weights = (
            self.social_weight,
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
    volume_column = f"volume_{period}d_change"
    price_column = f"price_{period}d_growth_pct"

    # A negative/flat change has no attention contribution. A positive
    # change is scaled 0–100 relative to today's biggest gainer for social
    # mentions and volume (raw counts), and relative to a fixed percentage
    # cap for price (see the two helpers below for why each uses a different
    # normalization).
    scored["social_points"] = _normalize_change(scored[social_column])
    scored["volume_points"] = _normalize_change(scored[volume_column])
    scored["price_points"] = _normalize_growth(
        scored[price_column], config.price_cap_pct
    )

    # Canonical, period-independent column names so storage and the dashboard
    # never depend on the configured growth-period suffix.
    scored["social_change"] = scored[social_column]
    scored["volume_change"] = scored[volume_column]
    scored["price_growth_pct"] = scored[price_column]

    scored["attention_score"] = (
        scored["social_points"] * config.social_weight
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
