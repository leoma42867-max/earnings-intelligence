# Earnings Intelligence Platform

A web application that identifies companies with upcoming earnings reports experiencing unusual increases in investor attention.

## Quick Start

**New to coding?** Follow the step-by-step guide in **[SETUP.md](SETUP.md)**.
For daily automation, see **[AUTOMATION.md](AUTOMATION.md)**.
To publish this as a free public website, see **[DEPLOYMENT.md](DEPLOYMENT.md)**.

```bash
cd ~/Projects/earnings-intelligence
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/refresh_data.py
streamlit run app.py
```

## How It Works

1. **Ticker Universe** — Builds a fresh list of ~100 tickers currently getting attention, combining StockTwits' trending symbols with Yahoo Finance's most-actively-traded stocks
2. **Earnings Calendar** — Filters that list down to companies reporting earnings in the next 30 days
3. **Market Data** — Collects daily price and volume from Yahoo Finance
4. **StockTwits Mentions** — Counts daily ticker mentions on StockTwits (free, no API key)
5. **Attention Growth** — Compares recent vs prior mentions and volume
6. **Ranking** — Scores and ranks companies by composite attention signal
7. **Dashboard** — Displays results in an interactive Streamlit UI

## Project Structure

```
earnings-intelligence/
├── app.py                          # Streamlit dashboard (main entry point)
├── requirements.txt                # Python dependencies
├── README.md                       # Project documentation
├── .gitignore                      # Git ignore rules
│
├── config/
│   └── settings.py                 # Paths, constants, and file locations
│
├── data/
│   └── earnings_intelligence.db    # SQLite database (generated locally)
│
├── src/
│   ├── collectors/                 # Data fetching modules
│   │   ├── ticker_universe.py    # Dynamic ~100-ticker "most hyped" candidate list
│   │   ├── earnings_calendar.py  # Upcoming earnings from Yahoo Finance
│   │   ├── market_data.py        # Stock price and volume data
│   │   └── social_mentions.py    # Daily StockTwits ticker-mention counts
│   │
│   ├── storage/                    # Persistence layer
│   │   └── sqlite_store.py          # Schema, upserts, and history queries
│   │
│   ├── analytics/                  # Analysis and scoring
│   │   ├── growth_ranking.py       # Multi-period growth metrics
│   │   └── scoring.py              # Canonical 0–100 attention score
│   │
│   └── models/                     # Data models
│       └── company.py              # Company dataclass
│
└── scripts/
    └── refresh_data.py             # End-to-end data pipeline script
```

## File Reference

| File | Purpose |
|------|---------|
| `app.py` | Streamlit frontend — loads rankings and renders the dashboard with summary metrics, ranked table, and per-company charts |
| `requirements.txt` | Pinned Python package dependencies |
| `config/settings.py` | Central configuration: directory paths, database location, and analysis parameters |
| `src/collectors/ticker_universe.py` | Builds the ~100-ticker candidate pool from StockTwits trending symbols + Yahoo Finance's most-actively-traded stocks |
| `src/collectors/earnings_calendar.py` | Given a list of tickers, finds which are reporting earnings in the next 30 days |
| `src/collectors/market_data.py` | Downloads daily OHLCV data and computes volume averages |
| `src/collectors/social_mentions.py` | Counts daily ticker mentions via StockTwits' free, public API (no credentials needed) |
| `src/storage/sqlite_store.py` | Creates SQLite tables and provides insert/query functions for all platform data |
| `src/analytics/growth_ranking.py` | Calculates 1/3/7/30-day growth for social mentions, volume, and price |
| `src/analytics/scoring.py` | Canonical 0–100 attention score (single source of truth) |
| `src/models/company.py` | `Company` dataclass representing a tracked company |
| `scripts/refresh_data.py` | Orchestrates the full pipeline: collect → store → score → rank |
| `data/earnings_intelligence.db` | Local SQLite database holding companies, earnings, daily metrics, and attention-score history |

## Scoring

The attention score is a single 0–100 value defined in `src/analytics/scoring.py`.
Each 7-day signal is scaled to 0–100 (negative/flat change scores 0) and
combined with these weights:

- **40%** — StockTwits mentions gained (raw count increase, e.g. "+450 mentions")
- **25%** — Yahoo Finance trending-rank climb (how many spots up the list)
- **20%** — Relative trading volume (volume vs each ticker’s own baseline)
- **15%** — Price momentum (percentage change)

Social mentions, Yahoo climbs, and volume are ranked by their **absolute
increase**, not a percentage — a stock going from 2 to 50 mentions is a 2400%
"growth" that would otherwise swamp a mega-cap going from 5,000 to 8,000
mentions, even though the latter reflects far more real attention. Whichever
ticker gained the most on a given day scores 100 on that signal, and every
other ticker is scaled relative to that leader. Price stays percentage-based,
since a $2 move means very different things for a $10 stock versus a $500 stock.

`scripts/refresh_data.py` computes and stores this score; the dashboard reads
the stored values, so automation and the UI always agree. Weights and the
price cap are adjustable via `AttentionScoreConfig`.

## V1 Limitations

- SQLite storage is local-only; it is not intended for concurrent or hosted multi-user access
- The ~100-ticker candidate pool is refreshed each run from StockTwits' trending list (always ~30 symbols) plus Yahoo Finance's most-actives screener; if both are briefly unavailable, the pipeline falls back to a small static watchlist for that run rather than collecting nothing
- StockTwits' public stream only returns each symbol's ~30 most recent messages (no arbitrary date-range search), so very heavily discussed tickers can have their daily mention count saturate at that cap
- No credentials are required for the social-mentions signal — it uses a free, public, unauthenticated StockTwits endpoint
- A full refresh now takes roughly 1–2 minutes (up from ~30–60 seconds) since it checks ~100 candidate tickers for upcoming earnings instead of a fixed ~30
- Scheduling is optional and runs locally (see [AUTOMATION.md](AUTOMATION.md))

## License

MIT
