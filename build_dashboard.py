import csv
from datetime import datetime, timezone

PAPER_TRADES_FILE = "paper_trades.csv"
DASHBOARD_FILE = "dashboard.html"
REFRESH_SECONDS = 60


def load_trades():
    try:
        with open(PAPER_TRADES_FILE, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def fmt_money(value):
    return f"${value:+.2f}" if value >= 0 else f"-${abs(value):.2f}"


def source_badge(source):
    color = "#3b82f6" if source == "weather" else "#f59e0b"
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


def build():
    trades = load_trades()
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
</style>
</head>
<body>
  <h1>Kalshi Bot — Paper Trading</h1>
  <div class="subtitle">Auto-refreshes every {REFRESH_SECONDS}s · Last built {now}</div>

  <div class="cards">
    <div class="card"><div class="label">Open Positions</div><div class="value">{len(open_trades)}</div></div>
    <div class="card"><div class="label">Resolved</div><div class="value">{len(resolved)}</div></div>
    <div class="card"><div class="label">Win Rate</div><div class="value">{win_rate}</div></div>
    <div class="card"><div class="label">Total P&amp;L</div><div class="value {'pos' if total_pnl >= 0 else 'neg'}">{fmt_money(total_pnl)}</div></div>
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

    return len(open_trades), len(resolved)


if __name__ == "__main__":
    open_count, resolved_count = build()
    print(f"Built {DASHBOARD_FILE}: {open_count} open, {resolved_count} resolved")
