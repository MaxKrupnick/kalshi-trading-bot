import csv
import time

import requests

from collect_data import BASE_URL

PAPER_TRADES_FILE = "paper_trades.csv"


def get_market_statuses(tickers, max_retries=5):
    """One batched request for all tickers, not one request each -- with 20+
    open positions, per-ticker requests hit Kalshi's rate limit."""
    if not tickers:
        return {}

    for attempt in range(max_retries):
        response = requests.get(f"{BASE_URL}/markets", params={"tickers": ",".join(tickers)})
        if response.status_code == 200:
            markets = response.json().get("markets", [])
            return {m["ticker"]: (m.get("status"), m.get("result")) for m in markets}
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            print(f"  Rate limited, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        response.raise_for_status()

    print(f"  Giving up after {max_retries} rate-limit retries")
    return {}


def resolve_all():
    with open(PAPER_TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    open_rows = [r for r in rows if r["status"] == "open"]
    statuses = get_market_statuses([r["ticker"] for r in open_rows])

    newly_resolved = 0
    for row in open_rows:
        status, result = statuses.get(row["ticker"], (None, None))
        if status != "finalized" or result not in ("yes", "no"):
            continue  # not settled yet

        won = row["side"] == result
        contracts = float(row["contracts"])
        position_size = float(row["position_size_dollars"])
        pnl = (contracts - position_size) if won else -position_size

        row["status"] = "resolved"
        row["result"] = result
        row["pnl"] = round(pnl, 2)
        newly_resolved += 1
        print(f"  {'WON' if won else 'LOST'}: {row['description']} ({row['side']}) -> {result}, pnl={row['pnl']}")

    if newly_resolved:
        with open(PAPER_TRADES_FILE, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

    return rows, newly_resolved


def print_summary(rows):
    resolved = [r for r in rows if r["status"] == "resolved"]
    open_trades = [r for r in rows if r["status"] == "open"]

    print(f"\n=== Paper trading summary ===")
    print(f"Open positions: {len(open_trades)}")
    print(f"Resolved: {len(resolved)}")

    if resolved:
        wins = sum(1 for r in resolved if r["side"] == r["result"])
        total_pnl = sum(float(r["pnl"]) for r in resolved)
        print(f"Win rate: {wins}/{len(resolved)} ({wins / len(resolved):.0%})")
        print(f"Total P&L: ${total_pnl:+.2f}")


if __name__ == "__main__":
    rows, newly_resolved = resolve_all()
    print(f"\n{newly_resolved} trade(s) newly resolved this run")
    print_summary(rows)
