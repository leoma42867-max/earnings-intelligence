"""Application configuration and constants."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DATABASE_FILE = DATA_DIR / "earnings_intelligence.db"

EARNINGS_LOOKAHEAD_DAYS = 30
SOCIAL_LOOKBACK_DAYS = 90
ATTENTION_GROWTH_WINDOW_DAYS = 14
TICKER_UNIVERSE_SIZE = 100

EARNINGS_FILE = RAW_DIR / "earnings_calendar.csv"
MARKET_DATA_FILE = RAW_DIR / "market_data.csv"
STOCK_INFO_FILE = RAW_DIR / "stock_info.csv"
SOCIAL_MENTIONS_FILE = RAW_DIR / "social_mentions.csv"
RANKINGS_FILE = PROCESSED_DIR / "rankings.csv"
