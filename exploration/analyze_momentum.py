import csv
import sys
from collections import defaultdict

CSV_FILE = sys.argv[1] if len(sys.argv) > 1 else "market_data.csv"

def load_data():
    rows_by_ticker = defaultdict(list)
    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows_by_ticker[row["ticker"]].append(row)
    return rows_by_ticker

def calculate_momentum(rows_by_ticker):
    results = []
    for ticker, rows in rows_by_ticker.items():
        # sort by timestamp so "first" and "last" are actually chronological
        rows.sort(key=lambda r: r["timestamp"])

        # only rows with a real quote count towards momentum
        quoted_rows = [r for r in rows if r["yes_bid"] not in ("", "None")]
        if len(quoted_rows) < 2:
            continue  # need at least 2 quoted snapshots to measure movement

        first_price = float(quoted_rows[0]["yes_bid"])
        last_price = float(quoted_rows[-1]["yes_bid"])
        change = last_price - first_price

        results.append({
            "ticker": ticker,
            "title": rows[-1]["title"],
            "first_price": first_price,
            "last_price": last_price,
            "change": change,
            "num_snapshots": len(quoted_rows),
        })

    results.sort(key=lambda r: abs(r["change"]), reverse=True)
    return results

if __name__ == "__main__":
    rows_by_ticker = load_data()
    momentum = calculate_momentum(rows_by_ticker)

    if not momentum:
        print("No markets with 2+ snapshots yet — let the data collector run longer, then try again.")
    else:
        print(f"{'Ticker':<45} {'First':>6} {'Last':>6} {'Change':>7} {'Snapshots':>10}")
        for m in momentum[:15]:
            print(f"{m['ticker']:<45} {m['first_price']:>6} {m['last_price']:>6} {m['change']:>+7} {m['num_snapshots']:>10}")