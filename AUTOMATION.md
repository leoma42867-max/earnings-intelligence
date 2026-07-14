# Daily Pipeline Automation

The daily pipeline performs this sequence:

1. Builds a ~100-ticker "most hyped" candidate list (StockTwits trending + Yahoo Finance most-actives)
2. Updates the upcoming earnings calendar for those candidates
3. Downloads daily stock-price and volume data
4. Counts StockTwits mentions per ticker (free, public API — no signup needed)
5. Stores collected history in `data/earnings_intelligence.db`
6. Calculates attention metrics and rankings
7. Makes the refreshed SQLite data available to the Streamlit dashboard

## Run It Manually

From the project directory:

```bash
source .venv/bin/activate
python scripts/scheduler.py --once
```

This is the same refresh process used by all automation options.

## Option 1: Local Computer (Mac)

Run the scheduler continuously at a local time:

```bash
source .venv/bin/activate
python scripts/scheduler.py --daily-at 06:30
```

Keep that Terminal window open. Stop it with `Ctrl + C`.

### Recommended Mac option: launchd

`launchd` runs the command without needing an open Terminal. Create
`~/Library/LaunchAgents/com.earningsintelligence.daily.plist` with this content,
replacing `YOUR_USERNAME` with your Mac user name:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>Label</key>
    <string>com.earningsintelligence.daily</string>
    <key>ProgramArguments</key>
    <array>
      <string>/Users/YOUR_USERNAME/Projects/earnings-intelligence/.venv/bin/python</string>
      <string>/Users/YOUR_USERNAME/Projects/earnings-intelligence/scripts/scheduler.py</string>
      <string>--once</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USERNAME/Projects/earnings-intelligence</string>
    <key>StartCalendarInterval</key>
    <dict>
      <key>Hour</key><integer>6</integer>
      <key>Minute</key><integer>30</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/YOUR_USERNAME/Projects/earnings-intelligence/logs/launchd.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USERNAME/Projects/earnings-intelligence/logs/launchd-error.log</string>
  </dict>
</plist>
```

Load it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.earningsintelligence.daily.plist
```

Run it immediately to test:

```bash
launchctl kickstart -k gui/$(id -u)/com.earningsintelligence.daily
```

To disable it later:

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.earningsintelligence.daily.plist
```

**Limitation:** the computer must be powered on and logged in when the schedule
is due. It is suitable for personal use, not guaranteed production automation.

## Option 2: GitHub Actions (recommended if deployed to Streamlit Cloud)

The repository includes `.github/workflows/daily_pipeline.yml`.

After the project is pushed to GitHub, GitHub runs it daily at 13:00 UTC and
also provides a **Run workflow** button for manual runs. Change the cron line
to change its schedule.

The workflow runs the pipeline, then **commits the refreshed
`data/earnings_intelligence.db` back to the `main` branch** (only if it
actually changed) and pushes. This is a deliberate choice for this project:
Streamlit Community Cloud has no persistent disk of its own (see
`DEPLOYMENT.md`), so committing the database is what makes the *deployed*
dashboard show fresh data automatically — each automated commit triggers a
Streamlit Cloud redeploy that picks up the new snapshot. No manual refresh
step is needed once this workflow is enabled.

This trades away clean diff history for the database file (every run adds a
binary-file commit) in exchange for a fully hands-off pipeline. For a project
with heavier write volume or multiple contributors, swap this for uploading
to persistent object storage or a hosted database instead — but for a
single-writer personal project refreshing once a day, a growing SQLite file
in Git history is a reasonable, simple trade-off.

## Option 3: Cloud Hosting

Use a platform with:

- a scheduled job/cron service to run `python scripts/scheduler.py --once`
- persistent storage shared with the Streamlit app

Examples include Render Cron Jobs, Railway Cron, Fly.io Machines, or a cloud
VM with cron. The job must write to the same persistent volume used by the
Streamlit process.

SQLite is practical for Version 1 when a single app process and a single
scheduled job share one disk. For multiple app instances, high traffic, or
reliable concurrent writes, migrate to PostgreSQL instead.
