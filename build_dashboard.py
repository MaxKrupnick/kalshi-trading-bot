import csv
import os
from datetime import datetime, timezone

PAPER_TRADES_FILE = "paper_trades.csv"
DASHBOARD_FILE = "dashboard.html"
REFRESH_SECONDS = 60

# Each cron job appends to its own log on every run regardless of whether it
# had new data to write (e.g. resolve_paper_trades.py only rewrites its CSV
# when something actually resolved, so the CSV's mtime alone can look "stale"
# even when the job is running fine -- the log file is the reliable heartbeat).
# (log_file, expected_interval_minutes, label). Threshold is checked at 2.5x
# the interval to allow for a slow API call or a missed tick without false-alarming.
STALENESS_CHECKS = [
    ("collect_data.log", 15, "Market data collection"),
    ("log_forecast.log", 60, "Weather forecast logging"),
    ("log_sports_edge.log", 60, "Sports edge logging"),
    ("log_weather_edge.log", 15, "Weather edge logging"),
    ("resolve_paper_trades.log", 30, "Paper trade resolution"),
    ("momentum_trade.log", 15, "Momentum paper trading"),
]
STALENESS_MULTIPLIER = 2.5


def check_staleness():
    """Returns a list of (label, minutes_since_last_run) for any cron whose
    log hasn't been touched recently -- found this class of bug the hard way
    when 5 of 6 crons died silently for ~48h while this dashboard kept
    rebuilding and showing the same frozen numbers as if nothing was wrong."""
    stale = []
    now = datetime.now(timezone.utc).timestamp()
    for log_file, interval_min, label in STALENESS_CHECKS:
        if not os.path.isfile(log_file):
            stale.append((label, None))  # never ran at all
            continue
        age_min = (now - os.path.getmtime(log_file)) / 60
        if age_min > interval_min * STALENESS_MULTIPLIER:
            stale.append((label, age_min))
    return stale


def load_trades():
    try:
        with open(PAPER_TRADES_FILE, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def fmt_money(value):
    return f"${value:+.2f}" if value >= 0 else f"-${abs(value):.2f}"


SOURCE_COLORS = {"weather": "#3b82f6", "sports": "#f59e0b", "momentum": "#a855f7"}


def source_badge(source):
    color = SOURCE_COLORS.get(source, "#8b96a3")
    return f'<span class="badge" style="background:{color}22;color:{color}">{source}</span>'


def side_badge(side):
    color = "#22c55e" if side == "yes" else "#ef4444"
    return f'<span class="badge" style="background:{color}22;color:{color}">{side.upper()}</span>'


def clean_description(t):
    # weather descriptions are stored as "TICKER strike-range" -- the table
    # already has a Ticker column, so drop the redundant prefix for display.
    desc = t["description"]
    prefix = t["ticker"] + " "
    return desc[len(prefix):] if desc.startswith(prefix) else desc


def row_html(t, resolved=False):
    description = clean_description(t)
    if resolved:
        won = t["side"] == t["result"]
        pnl = float(t["pnl"])
        outcome = '<span class="badge" style="background:#22c55e22;color:#22c55e">WON</span>' if won \
            else '<span class="badge" style="background:#ef444422;color:#ef4444">LOST</span>'
        return f"""<tr>
            <td>{source_badge(t['source'])}</td>
            <td class="mono">{t['ticker']}</td>
            <td>{description}</td>
            <td>{side_badge(t['side'])}</td>
            <td class="num">{float(t['entry_price']):.2f}</td>
            <td class="num">{float(t['edge_at_entry']):+.2f}</td>
            <td>{outcome}</td>
            <td class="num {'pos' if pnl >= 0 else 'neg'}">{fmt_money(pnl)}</td>
        </tr>"""
    return f"""<tr>
        <td>{source_badge(t['source'])}</td>
        <td class="mono">{t['ticker']}</td>
        <td>{description}</td>
        <td>{side_badge(t['side'])}</td>
        <td class="num">{float(t['entry_price']):.2f}</td>
        <td class="num">{float(t['edge_at_entry']):+.2f}</td>
        <td class="num">${float(t['position_size_dollars']):.0f}</td>
        <td class="dim">{t['opened_at'][:16].replace('T', ' ')}</td>
    </tr>"""


def stale_banner_html(stale):
    if not stale:
        return ""
    items = "".join(
        f"<li><b>{label}</b> — {'never ran' if mins is None else f'{mins:.0f} min ago'}</li>"
        for label, mins in stale
    )
    return f"""
  <div class="stale-banner">
    ⚠ Data may be stale — the following jobs haven't logged a run recently:
    <ul>{items}</ul>
  </div>"""


def by_strategy_html(resolved, open_trades):
    """Per-strategy breakdown -- the whole point of running momentum as a
    control arm alongside the fair-value strategies is comparing them, so the
    comparison belongs on the dashboard rather than only in an analysis
    script run by hand."""
    sources = sorted({t["source"] for t in resolved} | {t["source"] for t in open_trades})
    rows = []
    for source in sources:
        res = [t for t in resolved if t["source"] == source]
        opn = [t for t in open_trades if t["source"] == source]
        if res:
            wins = sum(1 for t in res if t["side"] == t["result"])
            pnl = sum(float(t["pnl"]) for t in res)
            risked = sum(float(t["position_size_dollars"]) for t in res)
            roi = pnl / risked * 100 if risked else 0
            record = f"{wins}/{len(res)} ({wins / len(res):.0%})"
            pnl_cell = f'<td class="num {"pos" if pnl >= 0 else "neg"}">{fmt_money(pnl)}</td>'
            roi_cell = f'<td class="num {"pos" if roi >= 0 else "neg"}">{roi:+.1f}%</td>'
        else:
            record, pnl_cell, roi_cell = "—", '<td class="num dim">—</td>', '<td class="num dim">—</td>'
        rows.append(f"""<tr>
            <td>{source_badge(source)}</td>
            <td class="num">{len(opn)}</td>
            <td class="num">{len(res)}</td>
            <td class="num">{record}</td>
            {pnl_cell}
            {roi_cell}
        </tr>""")
    return "\n".join(rows) or '<tr><td colspan="6" class="empty">No trades yet</td></tr>'


def build():
    trades = load_trades()
    stale = check_staleness()
    open_trades = [t for t in trades if t["status"] == "open"]
    resolved = [t for t in trades if t["status"] == "resolved"]

    wins = sum(1 for t in resolved if t["side"] == t["result"])
    win_rate = f"{wins}/{len(resolved)} ({wins / len(resolved):.0%})" if resolved else "—"
    total_pnl = sum(float(t["pnl"]) for t in resolved) if resolved else 0.0

    open_trades.sort(key=lambda t: abs(float(t["edge_at_entry"])), reverse=True)
    resolved.sort(key=lambda t: t["opened_at"], reverse=True)

    open_rows = "\n".join(row_html(t) for t in open_trades) or \
        '<tr><td colspan="8" class="empty">No open positions</td></tr>'
    resolved_rows = "\n".join(row_html(t, resolved=True) for t in resolved) or \
        '<tr><td colspan="8" class="empty">No resolved trades yet</td></tr>'

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>Kalshi Bot — Paper Trading Dashboard</title>
<style>
  :root {{
    color-scheme: light dark;
    --bg: #0b0f14; --card: #131a22; --border: #223; --text: #e6edf3;
    --dim: #8b96a3; --accent: #3b82f6;
  }}
  @media (prefers-color-scheme: light) {{
    :root {{ --bg: #f7f8fa; --card: #ffffff; --border: #e2e5e9; --text: #0f1620; --dim: #64748b; }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    margin: 0; padding: 32px 24px; max-width: 1100px; margin-inline: auto;
  }}
  h1 {{ font-size: 1.4rem; margin: 0 0 4px; }}
  .subtitle {{ color: var(--dim); font-size: 0.85rem; margin-bottom: 28px; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin-bottom: 32px; }}
  .card {{ background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px; }}
  .card .label {{ color: var(--dim); font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; }}
  .card .value {{ font-size: 1.6rem; font-weight: 600; margin-top: 4px; }}
  .pos {{ color: #22c55e; }} .neg {{ color: #ef4444; }}
  h2 {{ font-size: 1.05rem; margin: 28px 0 12px; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--border); border-radius: 10px; overflow: hidden; }}
  th, td {{ padding: 10px 12px; text-align: left; font-size: 0.85rem; border-bottom: 1px solid var(--border); }}
  th {{ color: var(--dim); font-weight: 500; text-transform: uppercase; font-size: 0.72rem; letter-spacing: 0.04em; }}
  tr:last-child td {{ border-bottom: none; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .mono {{ font-family: ui-monospace, monospace; font-size: 0.8rem; }}
  .dim {{ color: var(--dim); font-size: 0.78rem; }}
  .badge {{ padding: 2px 8px; border-radius: 6px; font-size: 0.72rem; font-weight: 600; }}
  .empty {{ text-align: center; color: var(--dim); padding: 24px; }}
  .wrap {{ overflow-x: auto; }}
  .stale-banner {{
    background: #f59e0b22; border: 1px solid #f59e0b; color: var(--text);
    border-radius: 10px; padding: 12px 16px; margin-bottom: 24px; font-size: 0.85rem;
  }}
  .stale-banner ul {{ margin: 6px 0 0; padding-left: 20px; }}
</style>
</head>
<body>
  <h1>Kalshi Bot — Paper Trading</h1>
  <div class="subtitle">Auto-refreshes every {REFRESH_SECONDS}s · Last built {now}</div>
  {stale_banner_html(stale)}

  <div class="cards">
    <div class="card"><div class="label">Open Positions</div><div class="value">{len(open_trades)}</div></div>
    <div class="card"><div class="label">Resolved</div><div class="value">{len(resolved)}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value">{win_rate}</div></div>
    <div class="card"><div class="label">Total P&amp;L</div><div class="value {'pos' if total_pnl >= 0 else 'neg'}">{fmt_money(total_pnl)}</div></div>
  </div>

  <h2>By Strategy</h2>
  <div class="wrap">
  <table>
    <tr><th>Strategy</th><th class="num">Open</th><th class="num">Resolved</th><th class="num">Win rate</th><th class="num">P&amp;L</th><th class="num">ROI</th></tr>
    {by_strategy_html(resolved, open_trades)}
  </table>
  </div>

  <h2>Open Positions</h2>
  <div class="wrap">
  <table>
    <tr><th>Source</th><th>Ticker</th><th>Description</th><th>Side</th><th class="num">Entry</th><th class="num">Edge</th><th class="num">Size</th><th>Opened</th></tr>
    {open_rows}
  </table>
  </div>

  <h2>Resolved Trades</h2>
  <div class="wrap">
  <table>
    <tr><th>Source</th><th>Ticker</th><th>Description</th><th>Side</th><th class="num">Entry</th><th class="num">Edge</th><th>Outcome</th><th class="num">P&amp;L</th></tr>
    {resolved_rows}
  </table>
  </div>
</body>
</html>
"""

    with open(DASHBOARD_FILE, "w") as f:
        f.write(html)

    return len(open_trades), len(resolved), stale


if __name__ == "__main__":
    open_count, resolved_count, stale = build()
    print(f"Built {DASHBOARD_FILE}: {open_count} open, {resolved_count} resolved")
    if stale:
        names = ", ".join(label for label, _ in stale)
        print(f"STALE: {names}")
