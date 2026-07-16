"""Unit tests for the Version 1 attention-score algorithm."""

import unittest

import pandas as pd

from src.analytics.scoring import AttentionScoreConfig, calculate_attention_scores


class AttentionScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        # Social / relative volume / Yahoo climbs are raw increases. FULL leads
        # every positive signal; MIXED is half on social/Yahoo; NEGATIVE declines.
        self.sample_growth = pd.DataFrame(
            {
                "ticker": ["FULL", "MIXED", "NEGATIVE", "MISSING"],
                "social_7d_change": [200, 100, -10, None],
                "volume_7d_change": [100, 100, -20, 100],
                "volume_7d_rel_change": [1.0, 1.0, -0.2, 1.0],
                "price_7d_growth_pct": [30, 0, -5, 30],
                "yahoo_7d_change": [20, 10, -5, 20],
            }
        )

    def test_scores_follow_version_one_weights(self) -> None:
        scored = calculate_attention_scores(self.sample_growth)

        # FULL leads every signal → 100.
        self.assertEqual(
            scored.loc[scored["ticker"] == "FULL", "attention_score"].iloc[0], 100
        )

        # MIXED: 50×40% + 50×25% + 100×20% + 0×15% = 52.5
        self.assertEqual(
            scored.loc[scored["ticker"] == "MIXED", "attention_score"].iloc[0], 52.5
        )

        # Negative inputs do not add attention points.
        self.assertEqual(
            scored.loc[scored["ticker"] == "NEGATIVE", "attention_score"].iloc[0], 0
        )

    def test_missing_signal_receives_zero_points(self) -> None:
        scored = calculate_attention_scores(self.sample_growth)

        # MISSING social: 0×40% + 100×25% + 100×20% + 100×15% = 60.
        self.assertEqual(
            scored.loc[scored["ticker"] == "MISSING", "attention_score"].iloc[0], 60
        )

    def test_scores_are_ranked_and_bounded(self) -> None:
        scored = calculate_attention_scores(self.sample_growth)

        self.assertEqual(scored.index.name, "rank")
        self.assertEqual(scored.iloc[0]["ticker"], "FULL")
        self.assertTrue(scored["attention_score"].between(0, 100).all())

    def test_weights_are_adjustable(self) -> None:
        config = AttentionScoreConfig(
            social_weight=0.0,
            yahoo_weight=0.0,
            volume_weight=1.0,
            price_weight=0.0,
        )
        scored = calculate_attention_scores(self.sample_growth, config)

        self.assertEqual(
            scored.loc[scored["ticker"] == "MIXED", "attention_score"].iloc[0], 100
        )

    def test_invalid_weights_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AttentionScoreConfig(
                social_weight=0.5,
                yahoo_weight=0.25,
                volume_weight=0.3,
                price_weight=0.3,
            )

    def test_relative_volume_preferred_over_raw_volume(self) -> None:
        growth = pd.DataFrame(
            {
                "ticker": ["MEGA", "SMALL"],
                "social_7d_change": [0, 0],
                "volume_7d_change": [10_000_000, 100_000],
                "volume_7d_rel_change": [0.2, 2.0],
                "price_7d_growth_pct": [0, 0],
                "yahoo_7d_change": [0, 0],
            }
        )
        config = AttentionScoreConfig(
            social_weight=0.0,
            yahoo_weight=0.0,
            volume_weight=1.0,
            price_weight=0.0,
        )
        scored = calculate_attention_scores(growth, config)
        # SMALL has higher relative volume surge despite lower raw volume.
        self.assertEqual(scored.iloc[0]["ticker"], "SMALL")
        self.assertEqual(
            scored.loc[scored["ticker"] == "SMALL", "attention_score"].iloc[0], 100
        )


if __name__ == "__main__":
    unittest.main()
