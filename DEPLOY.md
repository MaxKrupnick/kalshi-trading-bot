# Deploying the bot to an always-on server

**Status: draft.** Written 2026-08-25, revised 2026-08-26. Not executed yet —
review before running.

## Why

The pipeline is a set of cron jobs writing to local CSVs. On a laptop that
sleeps (lid closed, on battery, at college) macOS cron simply skips every
missed run — it does not catch up on wake. That has caused two multi-day data
gaps so far (2026-08-15 and 2026-08-25). A cheap Linux VM that never sleeps
fixes it with **zero code changes**: same cron, same scripts, same local-CSV
architecture.

## What runs where

- Current data pipeline (`collect_data`, `log_forecast`, `log_weather_edge`,
  `resolve_paper_trades`, `build_dashboard`, momentum `paper_trade`) hits only
  **public** Kalshi and NWS endpoints — **no credentials required**.
- `.env` (`KALSHI_API_KEY_ID`, `ODDS_API_KEY`) and `kalshi_private_key.pem` are
  needed only by the (currently disabled) sports arm and by future live order
  execution. Bring them anyway so step 8 isn't blocked later.

## 0. Push your local commits first

The server gets its code by cloning from GitHub, so anything sitting
uncommitted or unpushed on the laptop **will not be there**. Push via GitHub
Desktop (command-line `git push` doesn't authenticate from this shell), then
confirm the branch is clean:

```bash
git status && git log --oneline origin/main..HEAD
```

That second command should print nothing. If it lists commits, they haven't
been pushed yet.

## 1. Provision the VM

**Option A — DigitalOcean via GitHub Student Developer Pack (recommended).**
1. Apply: <https://education.github.com/pack> (verify with your `.edu` email;
   approval is usually 1–3 days). The pack includes $200 DigitalOcean credit.
2. Create a Droplet: Ubuntu 24.04 LTS, "Basic / Regular" $6/mo (or $4/mo
   512 MB — enough for this), region near you, add your SSH key.
3. $200 credit ≈ 3 years at $6/mo.

**Option B — Oracle Cloud Always Free (no card charge, permanent free tier).**
An Ampere A1 or AMD micro instance running Ubuntu is more than enough. More
signup friction; no ongoing cost.

Either way you end up with `ssh <user>@<server-ip>`.

## 2. Base setup on the VM

```bash
sudo apt update && sudo apt install -y python3-venv git tzdata
```

`tzdata` matters: several scripts use `zoneinfo.ZoneInfo` for per-city day
boundaries (Denver and LA aren't Eastern), and on a minimal image that raises
`ZoneInfoNotFoundError` at runtime rather than at install time.

**The repo is private**, so a plain `git clone` over HTTPS will fail —
GitHub stopped accepting account passwords for git. Use a Personal Access
Token. On GitHub: Settings → Developer settings → Personal access tokens →
Fine-grained tokens → generate one scoped to just this repo with
**Contents: Read-only**. Then, on the VM:

```bash
git clone https://github.com/cktzjcrpdv-netizen/kalshi-trading-bot.git
# username: cktzjcrpdv-netizen
# password: paste the token (not your GitHub password)
cd kalshi-trading-bot
git config credential.helper store   # so the weekly `git pull` doesn't re-prompt
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Read-only is deliberate — the server should never be able to push. Note that
`credential.helper store` writes the token to `~/.git-credentials` in
plaintext, which is the tradeoff for unattended pulls; a read-only,
single-repo token keeps the blast radius small.

Ubuntu 24.04 ships Python 3.12; the code uses nothing newer (the laptop
happens to run 3.14, but only stdlib + `requests` + `python-dotenv` are in
play).

## 3. Bring over the files git doesn't track

**You run these from your laptop** (they involve the private key — I won't
handle key material). From the repo directory on the laptop:

```bash
# credentials (for the sports arm / future live trading)
scp .env kalshi_private_key.pem <user>@<server-ip>:~/kalshi-trading-bot/

# the track record + accumulated history — do NOT start these fresh
scp paper_trades.csv forecast_log.csv weather_edge_log.csv sports_edge_log.csv \
    market_data.csv liquidity_snapshot_cache.csv \
    <user>@<server-ip>:~/kalshi-trading-bot/
```

`paper_trades.csv` is the entire paper-trading track record — losing it resets
the experiment. `forecast_log.csv` is the sigma-calibration dataset.
`weather_edge_log.csv` is what `analyze_model_vs_market.py` scores, i.e. the
evidence behind the project's headline finding. The rest are convenience
(history the cron would otherwise take weeks to rebuild).

`market_data.csv` is ~21 MB and the largest single transfer here; on a slow
connection, send it last so a failure there doesn't block the small files that
actually matter.

The older one-off datasets (`market_data_old.csv`, `market_data_backfill.csv`,
`market_data_settled.csv`) can come too if you want the backtests runnable on
the server, but nothing in the live loop needs them.

## 4. Install cron

```bash
cd ~/kalshi-trading-bot
sed "s#__HOME__#$PWD#g" crontab.txt | crontab -
crontab -l   # confirm the paths resolved
```

Server timezone doesn't matter — all schedules are intervals, and the scripts
compute per-city day boundaries internally. (`timedatectl set-timezone UTC` if
you want logs in UTC.)

## 5. View the dashboard remotely

`dashboard.html` is now a file on a remote box. Simplest private option:

1. Install [Tailscale](https://tailscale.com/download/linux) on the VM and on
   your laptop/phone (free personal plan). `sudo tailscale up`.
2. Serve the file over the tailnet **only**:
   ```bash
   cd ~/kalshi-trading-bot
   .venv/bin/python3 -m http.server 8000 --bind "$(tailscale ip -4)"
   ```
3. Open `http://<vm-tailscale-name>:8000/dashboard.html` from any of your
   devices.

⚠️ **Bind to the Tailscale IP, not `0.0.0.0`.** The VM has a public IP, so
`--bind 0.0.0.0` would publish the dashboard — and a directory listing of the
whole repo, including any CSV sitting in it — to the open internet on port
8000. Binding to the tailnet address keeps it reachable only from your own
devices. (`tailscale serve https / http://localhost:8000` is the tidier
equivalent if you'd rather not think about bind addresses.)

To keep it running after you log out, put it under systemd rather than a cron
line — it's a long-lived process, not a periodic job, and cron would start a
second copy every time it fired:

```bash
sudo tee /etc/systemd/system/kalshi-dashboard.service >/dev/null <<'UNIT'
[Unit]
Description=Kalshi dashboard (tailnet only)
After=network-online.target tailscaled.service

[Service]
User=%i
WorkingDirectory=/home/<user>/kalshi-trading-bot
ExecStart=/bin/sh -c '/home/<user>/kalshi-trading-bot/.venv/bin/python3 -m http.server 8000 --bind "$(tailscale ip -4)"'
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl enable --now kalshi-dashboard
```

(Alternative: `scp` the file down when you want to look. Tailscale is the least
fiddly for phone access.)

## 6. Verify

```bash
# force one run of each and check for errors
cd ~/kalshi-trading-bot
for s in collect_data log_forecast log_weather_edge resolve_paper_trades build_dashboard; do
  echo "== $s =="; .venv/bin/python3 $s.py 2>&1 | tail -3
done
.venv/bin/python3 paper_trade.py --momentum-only 2>&1 | tail -3
```

Then wait ~20 min and confirm the `.log` files have fresh timestamps and the
dashboard's staleness banner is clear.

Watch for two things specifically on a first run:

- **`resolve_paper_trades.py` re-resolving trades that are already closed.** It
  keys off `status == "open"` in the CSV you copied over, so if the copy is
  stale relative to what the laptop has since resolved, you'll get duplicate
  work (harmless) or a mismatched P&L (not). Copy `paper_trades.csv` *last*,
  right before cutting over, and stop the laptop's cron first.
- **A `ZoneInfoNotFoundError`** from any weather script means `tzdata` didn't
  install — go back to step 2.

## 7. Keeping it current

Development still happens on the laptop and pushes to GitHub. On the server:

```bash
cd ~/kalshi-trading-bot && git pull
```

Do this after any code change. Consider a weekly `git pull` cron once things
are stable. The server only ever pulls — it never commits (its CSV changes are
gitignored).

## 8. Decommission the laptop cron

Both machines running the same schedule means **both are appending to their own
`paper_trades.csv`**, and the two track records will silently diverge. Don't
leave them overlapping longer than a verification window.

Once the server has run clean for a day:

```bash
crontab -l > ~/laptop-crontab-backup.txt   # keep a copy first
crontab -r                                 # on the LAPTOP
```

Then treat the **server's** `paper_trades.csv` as the real one from that moment
on. If you want the laptop's copy for local analysis, `scp` it back down rather
than letting the laptop keep writing its own.

## Cost summary

| Option | Up-front | Ongoing | Notes |
|---|---|---|---|
| DigitalOcean + Student Pack | $0 | $0 for ~3 yrs, then $4–6/mo | Best-documented; standard portfolio story |
| Oracle Cloud Always Free | $0 | $0 indefinitely | More signup friction |
