import csv
import statistics
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


def to_float_or_none(value):
    if value in ("", "None", None):
        return None
    return float(value)


def calculate_features(rows_by_ticker):
    results = []
    for ticker, rows in rows_by_ticker.items():
        rows.sort(key=lambda r: r["timestamp"])

        yes_bids = [to_float_or_none(r["yes_bid"]) for r in rows]
        yes_asks = [to_float_or_none(r["yes_ask"]) for r in rows]
        volumes = [to_float_or_none(r["volume"]) for r in rows]

        # spreads only where both sides of the book are quoted
        spreads = [
            a - b for a, b in zip(yes_asks, yes_bids)
            if a is not None and b is not None
        ]

        # need at least 2 real prices to say anything about volatility
        clean_bids = [b for b in yes_bids if b is not None]
        if len(clean_bids) < 2:
            continue

        results.append({
            "ticker": ticker,
            "title": rows[-1]["title"],
            "num_snapshots": len(rows),
            "num_quoted": len(clean_bids),
            "avg_spread": round(statistics.mean(spreads), 1) if spreads else None,
            "volatility": round(statistics.pstdev(clean_bids), 2),
            "last_volume": volumes[-1] if volumes else None,
        })

    # widest volatility first, but only among markets that are actually quoted (liquid enough to trade)
    results.sort(key=lambda r: (r["avg_spread"] is not None, r["volatility"]), reverse=True)
    return results


if __name__ == "__main__":
    rows_by_ticker = load_data()
    features = calculate_features(rows_by_ticker)

    if not features:
        print("No markets with 2+ quoted snapshots yet — let the data collector run longer, then try again.")
    else:
        print(f"{'Ticker':<45} {'Snaps':>6} {'Quoted':>7} {'AvgSpread':>10} {'Volatility':>11} {'LastVol':>8}")
        for f in features[:15]:
            spread_str = f"{f['avg_spread']:.1f}" if f['avg_spread'] is not None else "n/a"
            vol_str = f"{f['last_volume']}" if f['last_volume'] is not None else "n/a"
            print(f"{f['ticker']:<45} {f['num_snapshots']:>6} {f['num_quoted']:>7} {spread_str:>10} {f['volatility']:>11} {vol_str:>8}")
