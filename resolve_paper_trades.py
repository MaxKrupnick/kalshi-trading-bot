import csv

import requests

from collect_data import BASE_URL

PAPER_TRADES_FILE = "paper_trades.csv"


def get_market_status(ticker):
    response = requests.get(f"{BASE_URL}/markets", params={"tickers": ticker})
    response.raise_for_status()
    markets = response.json().get("markets", [])
    if not markets:
        return None, None
    m = markets[0]
    return m.get("status"), m.get("result")


def resolve_trade(row):
    status, result = get_market_status(row["ticker"])
    if status != "finalized" or result not in ("yes", "no"):
        return False  # not settled yet

    won = row["side"] == result
    contracts = float(row["contracts"])
    position_size = float(row["position_size_dollars"])
    pnl = (contracts - position_size) if won else -position_size

    row["status"] = "resolved"
    row["result"] = result
    row["pnl"] = round(pnl, 2)
    return True


def resolve_all():
    with open(PAPER_TRADES_FILE, newline="") as f:
        rows = list(csv.DictReader(f))
        fieldnames = list(rows[0].keys()) if rows else []

    newly_resolved = 0
    for row in rows:
        if row["status"] != "open":
            continue
        if resolve_trade(row):
            newly_resolved += 1
            outcome = "WON" if row["side"] == row["result"] else "LOST"
            print(f"  {outcome}: {row['description']} ({row['side']}) -> {row['result']}, pnl={row['pnl']}")

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
