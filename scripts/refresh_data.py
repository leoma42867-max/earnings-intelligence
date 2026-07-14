"""CLI entry point for the data-refresh pipeline.

The actual pipeline logic lives in ``src/pipeline.py`` so the Streamlit app
can trigger the same refresh from an admin-gated button without shelling out.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.pipeline import run_refresh_pipeline


def main() -> None:
    result = run_refresh_pipeline()
    for message in result.messages:
        print(message)

    if not result.rankings.empty:
        print("\nTop 5 by attention score:")
        columns = [
            "ticker", "attention_score", "social_change",
            "volume_change", "price_growth_pct",
        ]
        print(result.rankings[columns].head(5).to_string())
    else:
        print("No rankings produced.")


if __name__ == "__main__":
    main()
