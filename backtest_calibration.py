import csv
import sys
from collections import defaultdict
from datetime import datetime, timedelta

SETTLED_FILE = "market_data_settled.csv"
NUM_BUCKETS = 10  # decile buckets: 0-10%, 10-20%, ... 90-100%
MIN_CATEGORY_SAMPLE = 30  # below this, a decile breakdown is mostly noise
LEAD_HOURS = 24  # fixed lead time before close, for a fair cross-category comparison

# Series -> category. Kept explicit (from the CSV's "series" column) rather
# than guessed from ticker naming, which isn't consistent (e.g. KXFEDHIKE
# produces tickers like "FEDHIKE-27DEC31", no "KX" prefix).
CATEGORY_MAP = {
    "KXHIGHNY": "weather",
    "KXFEDHIKE": "economics",
    "KXCPI": "economics",
    "KXPAYROLLS": "economics",
    "KXU3": "economics",
    "KXPCECORE": "economics",
    "KXBTCMAX150": "crypto",
    "KXEGGS": "commodities",
    "KXNFLGAME": "sports",
    "KXMLBGAME": "sports",
    "KXWNBAGAME": "sports",
}


def load_settled_data():
    rows_by_ticker = defaultdict(list)
    with open(SETTLED_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["yes_bid"] and row["yes_ask"]:
                rows_by_ticker[row["ticker"]].append(row)
    return rows_by_ticker


def is_real_quote(row):
    # After a market settles, Kalshi's candlesticks report a degenerate
    # yes_bid=0/yes_ask=1 placeholder (empty book) rather than a real price.
    # Exclude those so "late price" reflects an actual live quote.
    spread = float(row["yes_ask"]) - float(row["yes_bid"])
    return spread < 0.9


def mid(row):
    return (float(row["yes_bid"]) + float(row["yes_ask"])) / 2


def price_at_lead_time(real_quotes, lead_hours):
    """Price observed ~lead_hours before this market's last real quote (its
    close, effectively). Falls back to the earliest available quote if the
    market's whole observed history is shorter than lead_hours -- common for
    short-lived markets like daily weather strikes."""
    close_time = datetime.fromisoformat(real_quotes[-1]["timestamp"])
    target_time = close_time - timedelta(hours=lead_hours)

    candidates = [r for r in real_quotes if datetime.fromisoformat(r["timestamp"]) <= target_time]
    if not candidates:
        return mid(real_quotes[0]), True  # fell back to earliest available
    return mid(candidates[-1]), False


def decision_prices(rows_by_ticker):
    """For each ticker: result, prices at a few reference points, category."""
    markets = []
    for ticker, rows in rows_by_ticker.items():
        rows.sort(key=lambda r: r["timestamp"])
        result = rows[-1]["result"]
        if result not in ("yes", "no"):
            continue

        real_quotes = [r for r in rows if is_real_quote(r)]
        if not real_quotes:
            continue  # every candle for this market was a degenerate placeholder

        lead_price, fell_back = price_at_lead_time(real_quotes, LEAD_HOURS)
        series = rows[-1].get("series", "")
        markets.append({
            "ticker": ticker,
            "result": 1 if result == "yes" else 0,
            "early_price": mid(real_quotes[0]),
            "late_price": mid(real_quotes[-1]),
            "lead_price": lead_price,
            "lead_price_fallback": fell_back,
            "category": CATEGORY_MAP.get(series, series or "unknown"),
        })
    return markets


def bucket_index(price):
    # clamp to [0, NUM_BUCKETS - 1] so a price of exactly 1.0 doesn't overflow
    return min(int(price * NUM_BUCKETS), NUM_BUCKETS - 1)


def calibration_table(markets, price_key):
    buckets = defaultdict(list)
    for m in markets:
        buckets[bucket_index(m[price_key])].append(m["result"])

    rows = []
    brier_sum = 0
    for m in markets:
        brier_sum += (m[price_key] - m["result"]) ** 2
    brier_score = brier_sum / len(markets) if markets else None

    for i in range(NUM_BUCKETS):
        outcomes = buckets.get(i, [])
        bucket_low, bucket_high = i / NUM_BUCKETS, (i + 1) / NUM_BUCKETS
        if outcomes:
            actual_rate = sum(outcomes) / len(outcomes)
        else:
            actual_rate = None
        rows.append({
            "range": f"{bucket_low:.0%}-{bucket_high:.0%}",
            "count": len(outcomes),
            "actual_yes_rate": actual_rate,
        })
    return rows, brier_score


def print_calibration(label, markets, price_key):
    rows, brier = calibration_table(markets, price_key)
    print(f"\n{label} (n={len(markets)}, Brier score={brier:.4f} -- lower is better, 0.25 = coin-flip baseline)")
    print(f"{'Price range':<12} {'Count':>6} {'Actual YES rate':>16}")
    for r in rows:
        rate_str = f"{r['actual_yes_rate']:.0%}" if r["actual_yes_rate"] is not None else "n/a"
        print(f"{r['range']:<12} {r['count']:>6} {rate_str:>16}")


def print_by_category(markets, price_key, label):
    by_category = defaultdict(list)
    for m in markets:
        by_category[m["category"]].append(m)

    print(f"\n=== {label} calibration by category (higher Brier = more room for edge) ===")
    print(f"{'Category':<14} {'n':>6} {'Brier score':>12} {'Fallback %':>11}")
    summary = []
    for category, group in by_category.items():
        _, brier = calibration_table(group, price_key)
        fallback_pct = sum(1 for m in group if m.get("lead_price_fallback")) / len(group)
        summary.append((category, len(group), brier, fallback_pct))
    summary.sort(key=lambda x: x[2], reverse=True)
    for category, n, brier, fallback_pct in summary:
        flag = "  (small sample, noisy)" if n < MIN_CATEGORY_SAMPLE else ""
        print(f"{category:<14} {n:>6} {brier:>12.4f} {fallback_pct:>10.0%}{flag}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        SETTLED_FILE = sys.argv[1]

    rows_by_ticker = load_settled_data()
    markets = decision_prices(rows_by_ticker)

    if not markets:
        print("No settled markets with usable price data found.")
    else:
        print_calibration("EARLY price (first observed) vs actual outcome", markets, "early_price")
        print_calibration("LATE price (last observed before settlement) vs actual outcome", markets, "late_price")
        print_calibration(f"LEAD-{LEAD_HOURS}h price (fixed time before close) vs actual outcome", markets, "lead_price")
        print_by_category(markets, "early_price", "EARLY-price (first observed, lifespan-biased)")
        print_by_category(markets, "lead_price", f"LEAD-{LEAD_HOURS}h (fixed lead time, fair comparison)")
        print(
            "\nIf a price bucket's 'actual YES rate' roughly matches its price range, "
            "the market was well-calibrated there -- meaning there's no easy edge sitting "
            "in the price alone, consistent with going the external-data-model route "
            "instead of pure price-based signals."
        )
