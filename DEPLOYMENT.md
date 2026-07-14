# Deploying to the Web (Streamlit Community Cloud)

This guide walks through publishing the dashboard as a free, public website
using **Streamlit Community Cloud**, which deploys directly from a GitHub
repository. Every step is explained — no prior deployment experience assumed.

---

## What you'll end up with

A public URL like `https://your-app-name.streamlit.app` that anyone can
visit. Pushing new commits to GitHub automatically redeploys the site.

---

## Important limitation: storage is not permanent — but the repo ships with data

Streamlit Community Cloud gives each app a **temporary** disk. Whatever the
running app writes to `data/earnings_intelligence.db` is **wiped** whenever
the app:

- is redeployed (you push a new commit),
- reboots after a long idle period ("sleeping" on the free tier),
- or is restarted by Streamlit's infrastructure.

To work around this, `data/earnings_intelligence.db` is **committed to Git on
purpose** (it is not in `.gitignore`). Every fresh deploy or reboot starts
from whatever snapshot of the database was last pushed to GitHub — not an
empty one. Keeping the data fresh is then just a matter of refreshing your
*local* database and pushing it, in one of two ways:

1. **Automatically** — the included GitHub Actions workflow
   (`.github/workflows/daily_pipeline.yml`) runs the pipeline on a daily
   schedule and commits the refreshed database back to `main` for you. Once
   this is pushed and enabled, Streamlit Cloud picks up each automated commit
   and redeploys with fresh data — no manual steps needed. See `AUTOMATION.md`.
2. **Manually** — run `python scripts/refresh_data.py` locally, then
   `git add data/earnings_intelligence.db && git commit -m "Refresh data" && git push`.

There's also an **in-app admin refresh** panel (sidebar → "Admin: refresh
data", protected by a secret token) that reruns the pipeline directly on the
live site. It's convenient for an instant spot-refresh, but its result lives
only on that instance's temporary disk — it does **not** get committed to
Git, so it will be lost on the next redeploy or sleep cycle. For data that
survives long-term, prefer option 1 or 2 above.

A future upgrade path (not needed for V1) is swapping SQLite for a hosted
database such as Postgres, which would survive reboots automatically without
needing to commit a binary file to Git at all.

---

## Step 1 — Install Git (if needed)

Check whether Git is installed:

```bash
git --version
```

If that fails, install Xcode Command Line Tools (this also installs Git):

```bash
xcode-select --install
```

---

## Step 2 — Turn the project into a Git repository

From the project folder:

```bash
cd ~/Projects/earnings-intelligence
git init
git add .
git status
```

**Before committing**, check the `git status` output carefully. You should
**not** see `.streamlit/secrets.toml` or `.venv/` listed — `.gitignore`
excludes them. If you do see `.streamlit/secrets.toml`, stop and let me know
before continuing. You **should** see `data/earnings_intelligence.db` listed
— that's expected and intentional (see "Important limitation" above).

Then make the first commit:

```bash
git commit -m "Initial commit: Earnings Intelligence Platform"
```

**What this does:** `git init` creates a local repository. `git add .` stages
every file except the ones listed in `.gitignore` (virtual environment,
databases, logs, and your real secrets file). The commit saves a snapshot of
the project's history.

---

## Step 3 — Create a repository on GitHub

1. Go to [github.com/new](https://github.com/new) and sign in.
2. Enter a repository name, e.g. `earnings-intelligence`.
3. Leave it **empty** — do **not** check "Add a README" (your project
   already has one; checking this creates a conflicting history).
4. Choose **Public** or **Private** — Streamlit Community Cloud's free tier
   supports deploying from both. With a private repo, your source code stays
   private while the running app is still publicly viewable at its URL.
5. Click **Create repository**.
6. Copy the repository URL shown on the next page — it looks like
   `https://github.com/YOUR_USERNAME/earnings-intelligence.git`.

---

## Step 4 — Push your code to GitHub

Back in Terminal:

```bash
git remote add origin https://github.com/YOUR_USERNAME/earnings-intelligence.git
git branch -M main
git push -u origin main
```

**What this does:** connects your local repository to the one on GitHub,
renames your local branch to `main` (GitHub's default), and uploads your
commit history.

**If this is your first push from this Mac**, a browser window will likely
open asking you to sign in to GitHub and authorize Git — follow the prompts.
If you're prompted for a password on the command line instead, GitHub no
longer accepts your account password there; you'll need a
[Personal Access Token](https://github.com/settings/tokens) used as the
password, or install the GitHub CLI (`brew install gh` then `gh auth login`)
for a simpler sign-in flow.

Refresh the GitHub repository page in your browser to confirm your files
appear.

---

## Step 5 — Create your Streamlit Community Cloud account

1. Go to [share.streamlit.io](https://share.streamlit.io).
2. Click **Sign in** or **Continue with GitHub**.
3. Authorize Streamlit to access your GitHub account when prompted.

This is a free tier — no credit card required.

---

## Step 6 — Deploy the app

1. Click **Create app** (or **New app**).
2. Choose **"Deploy a public app from GitHub"**.
3. Fill in:
   - **Repository:** `YOUR_USERNAME/earnings-intelligence`
   - **Branch:** `main`
   - **Main file path:** `app.py`
4. Click **Advanced settings** before deploying:
   - **Python version:** choose `3.11` or `3.12` from the dropdown.
     (Streamlit Community Cloud does **not** read a `runtime.txt` file — the
     Python version must be selected here, in the deploy dialog. If you skip
     this, it may default to a newer Python version that some pinned
     packages in `requirements.txt` don't yet have prebuilt wheels for.)
   - **Secrets:** paste the following. Replace the admin token value with
     your own long random string (this is your admin password for the
     in-app refresh control — see Step 7). No other credentials are
     needed — the social-mentions signal uses StockTwits' free, public,
     unauthenticated API:

     ```toml
     ADMIN_REFRESH_TOKEN = "choose-a-long-random-string-here"
     ```

5. Click **Deploy**.

Streamlit will now build the environment and install `requirements.txt`.
This typically takes 2–5 minutes the first time. You can watch progress in
the build log shown on screen.

---

## Step 7 — Configuring environment variables (secrets)

Streamlit Community Cloud has no traditional "environment variables" panel —
secrets serve that role. They're written in TOML format and exposed to your
app as `st.secrets`. This project's `config/secrets.py` reads them (falling
back to real OS environment variables for local scripts):

```toml
ADMIN_REFRESH_TOKEN = "choose-a-long-random-string-here"
```

To view or change secrets after deployment:

1. Open your app from the [Streamlit Cloud dashboard](https://share.streamlit.io).
2. Click the **⋮** menu → **Settings** → **Secrets**.
3. Edit the TOML, then click **Save**. The app automatically restarts.

**Never commit real secrets to GitHub.** `.streamlit/secrets.toml` is already
listed in `.gitignore`. Only `.streamlit/secrets.toml.example` (with a
placeholder value) is tracked, so collaborators know which keys to set.

---

## Step 8 — Verify the live site

1. Once the build finishes, Streamlit shows your public URL
   (`https://your-app-name.streamlit.app`).
2. Open it. Because `data/earnings_intelligence.db` is committed to the repo,
   you should see it load with whatever rankings were present the last time
   the database was refreshed and pushed — no manual step needed on a fresh
   deploy.
3. If you want fresher numbers right now, open **Admin: refresh data** in the
   sidebar, enter your token, and click **Run full refresh now** (~1–2
   minutes — it's fetching live data for ~100 candidate tickers from Yahoo
   Finance and StockTwits).
   Remember this in-app refresh does not persist past the next redeploy or
   sleep cycle (see "Important limitation" above) — for a lasting update,
   refresh and push locally, or rely on the daily GitHub Actions workflow.

Visit the **Company** page (sidebar) to confirm ticker charts render too.

---

## Step 9 — Ongoing updates

**To deploy code changes:** commit and push to GitHub as usual —

```bash
git add .
git commit -m "Describe your change"
git push
```

Streamlit Community Cloud watches your `main` branch and redeploys
automatically within about a minute of each push.

**To refresh data after a reboot:** revisit the site, open **Admin: refresh
data**, and click **Run full refresh now** again. There's no need to redeploy
just to refresh data.

**To rename the app or change its subdomain:** use the app's **Settings** in
the Streamlit Cloud dashboard.

**To use a custom domain** (e.g. `earnings.yourdomain.com`): this requires a
paid Streamlit plan or a separate hosting provider — Community Cloud's free
tier only provides the `*.streamlit.app` subdomain.

---

## Step 10 — Free tier limits to be aware of

- **Resources:** Community Cloud apps run with limited CPU/RAM (around 1 GB).
  This project's SQLite + Streamlit setup fits comfortably within that.
- **Sleep after inactivity:** free apps sleep if unused for a while and wake
  up (with a short delay) on the next visit. Waking up gives it a fresh disk
  restored from the last Git commit — so it reloads whatever data was last
  pushed, not an empty database.
- **Private repositories work fine:** Streamlit Community Cloud can deploy
  from private GitHub repos on the free tier — your source code stays
  private, while the running app itself is still publicly viewable at its URL.
- **Social-mention data:** no credentials required — StockTwits' public API
  needs no signup or Secrets entry, so this signal works out of the box on
  a fresh deploy.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Build fails installing a package | Python version mismatch | Redeploy with a different Python version in Advanced settings (Community Cloud ignores `runtime.txt`) |
| "No dashboard data is available" on a fresh deploy | `data/earnings_intelligence.db` wasn't committed, or was emptied locally before pushing | Run `python scripts/refresh_data.py` locally, then commit and push the database file |
| Admin refresh button says "Incorrect admin token" | Secret not saved, or typo | Re-check **Settings → Secrets** on Streamlit Cloud matches what you typed |
| Push to GitHub asks for a password and rejects it | GitHub no longer accepts account passwords over plain Git | Use a Personal Access Token, or `gh auth login` |
| App stuck "Oh no, error running app" | Check the **Manage app** logs in the bottom-right of the site for the Python traceback | Fix locally, then `git push` again |
