# Setup Guide (Beginner Friendly)

This guide walks you through running the Earnings Intelligence Platform on your Mac, step by step. No prior coding experience required.

---

## What You'll Need

- A Mac computer
- An internet connection
- About 10 minutes

---

## Step 0: Install Python (One-Time Setup)

Your Mac needs **Python** (the programming language) and **Xcode Command Line Tools** (a helper package Apple provides).

### Check if Python is already installed

1. Open **Terminal**:
   - Press `Cmd + Space`, type **Terminal**, press Enter
2. Copy and paste this command, then press Enter:

```bash
python3 --version
```

- If you see something like `Python 3.11.6` — you're good, skip to Step 1.
- If you see an error about "developer tools" or "xcode-select", continue below.

### Install Xcode Command Line Tools

1. In Terminal, run:

```bash
xcode-select --install
```

2. A popup window will appear. Click **Install** and wait for it to finish (this can take a few minutes).
3. Run `python3 --version` again to confirm it works.

---

## Step 1: Open the Project Folder in Terminal

Every command below assumes you are **inside the project folder**. Run this once at the start of each session:

```bash
cd ~/Projects/earnings-intelligence
```

**What this does:** Moves you into the project directory so your commands affect the right files.

---

## Step 2: Create a Virtual Environment

A **virtual environment** is an isolated space for this project's packages. It keeps this app's dependencies separate from everything else on your computer.

```bash
python3 -m venv .venv
```

**What this does:** Creates a hidden folder called `.venv` containing a fresh Python environment.

You only need to run this **once** — the first time you set up the project.

---

## Step 3: Activate the Virtual Environment

Before installing packages or running the app, activate the environment:

```bash
source .venv/bin/activate
```

**How you know it worked:** Your Terminal prompt will show `(.venv)` at the beginning, like:

```
(.venv) leo@MacBook earnings-intelligence %
```

**Important:** Run this command **every time** you open a new Terminal window to work on this project.

To deactivate later (optional):

```bash
deactivate
```

---

## Step 4: Install Required Packages

With the virtual environment active (`(.venv)` visible), install all dependencies:

```bash
pip install -r requirements.txt
```

**What this does:** Reads `requirements.txt` and downloads the libraries the app needs:

| Package   | What it does                                      |
|-----------|---------------------------------------------------|
| streamlit | Powers the web dashboard you see in your browser  |
| pandas    | Handles data tables and calculations              |
| yfinance  | Fetches stock market data from Yahoo Finance      |
| requests  | Fetches StockTwits mention counts (no API key needed) |
| numpy     | Supports numerical calculations                   |

This may take 1–2 minutes. You only need to run it **once** (or again if packages are updated).

---

## Step 5: Download Data

Before the dashboard can show anything, you need to fetch stock, earnings, and StockTwits mention data:

```bash
python scripts/refresh_data.py
```

**What this does:**
1. Builds a list of ~100 tickers currently getting attention (StockTwits trending + Yahoo Finance most-actives)
2. Finds which of those have earnings in the next 30 days
3. Downloads stock prices and trading volume
4. Counts StockTwits mentions per ticker (free, public API — no signup needed)
5. Calculates attention growth and rankings
6. Saves everything to the local SQLite database in the `data/` folder

This takes 2–5 minutes depending on your internet speed. Re-run this whenever you want fresh data.

---

## Step 6: Launch the Dashboard

Start the web application:

```bash
streamlit run app.py
```

**What happens:**
- Terminal will show a message like `Local URL: http://localhost:8501`
- Your web browser should open automatically
- If it doesn't, copy `http://localhost:8501` and paste it into Chrome or Safari

**To stop the app:** Click back in Terminal and press `Ctrl + C`.

---

## Quick Reference (Daily Use)

Open Terminal and run these four commands in order:

```bash
cd ~/Projects/earnings-intelligence
source .venv/bin/activate
python scripts/refresh_data.py      # optional — only when you want fresh data
streamlit run app.py
```

---

## Troubleshooting

### "command not found: python3"
Install Xcode Command Line Tools (see Step 0), then try again.

### "No module named streamlit" (or pandas, etc.)
Your virtual environment isn't active. Run:
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

### Dashboard says "No ranking data found"
You haven't fetched data yet. Run:
```bash
python scripts/refresh_data.py
```

### Browser doesn't open automatically
Manually go to: **http://localhost:8501**

### "Address already in use"
A previous session is still running. Either close that Terminal window, or stop it with `Ctrl + C`, then try again.

---

## What's in requirements.txt?

```
streamlit==1.59.2
pandas==3.0.3
yfinance==1.5.1
requests==2.34.2
numpy==2.5.1
plotly==6.9.0
```

Each line is one package pinned to an exact version (e.g. `==1.59.2`), so everyone who sets up this project installs the same tested versions instead of whatever is newest that day. You don't need to edit this file — `pip install -r requirements.txt` handles everything.
