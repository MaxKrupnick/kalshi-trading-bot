import csv
from collections import defaultdict
from datetime import datetime, timedelta, timezone

MARKET_DATA_FILE = "market_data.csv"

# Deliberate control arm for the fair-value strategy. The project's premise
# (see README) is that trading Kalshi's own price movement is a weak strategy
# and real edge has to come from independent external data -- but that was
# argued qualitatively and never actually tested. Running it as a real,
# separately-tracked paper-trading arm turns an assumption into a measurement.
#
# Why this is worth the effort: if momentum also loses, that's evidence these
# markets are just hard (and the fair-value model isn't uniquely broken). If
# momentum does BETTER, that's a genuinely surprising result that would mean
# the project's core premise needs revisiting. Either outcome is informative;
# "we assumed it was bad" is not.

LOOKBACK_HOURS = 6
MIN_SNAPSHOTS = 3  # need a few quoted points, not just two, before calling it a trend
MIN_MOVE = 0.03    # ignore sub-3-cent drift as noise, not signal

# How much of the recent move to extrapolate forward. 1.0 would mean "expect
# the exact same move again" -- aggressive. 0.5 is a deliberately modest
# assumption of partial continuation. This is the strategy's one real free
# parameter and is NOT fitted to outcomes (that would be curve-fitting on the
# same data used to evaluate it); it's set once, up front, and left alone.
CONTINUATION_FACTOR = 0.5


def to_float_or_none(value):
    if value in (None, "", "None"):
        return None
    return float(value)


def load_recent_quotes(now=None):
    """ticker -> chronological list of (timestamp, yes_bid, yes_ask) within
    the lookback window."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    by_ticker = defaultdict(list)

    with open(MARKET_DATA_FILE, newline="") as f:
        for row in csv.DictReader(f):
            yes_bid = to_float_or_none(row["yes_bid"])
            yes_ask = to_float_or_none(row["yes_ask"])
            if yes_bid is None or yes_ask is None:
                continue
            ts = datetime.fromisoformat(row["timestamp"])
            if ts < cutoff:
                continue
            by_ticker[row["ticker"]].append((ts, yes_bid, yes_ask, row.get("title")))

    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda t: t[0])
    return by_ticker


def build_comparisons(now=None):
    """Same output shape as weather/sports fair value: a model probability to
    compare against the live quote, so this plugs into the existing paper
    trading pipeline unchanged."""
    quotes_by_ticker = load_recent_quotes(now=now)
    rows = []

    for ticker, quotes in quotes_by_ticker.items():
        if len(quotes) < MIN_SNAPSHOTS:
            continue

        _, first_bid, first_ask, _ = quotes[0]
        _, last_bid, last_ask, title = quotes[-1]
        first_mid = (first_bid + first_ask) / 2
        last_mid = (last_bid + last_ask) / 2
        move = last_mid - first_mid

        if abs(move) < MIN_MOVE:
            continue

        # Extrapolate partial continuation of the recent move, clamped to a
        # valid probability. Clamping to [0.01, 0.99] rather than [0, 1] since
        # a model probability of exactly 0 or 1 claims certainty this strategy
        # has no basis for.
        projected = last_mid + CONTINUATION_FACTOR * move
        model_prob = min(max(projected, 0.01), 0.99)

        rows.append({
            "ticker": ticker,
            "title": title,
            "description": f"{ticker} momentum {move:+.2f} over {LOOKBACK_HOURS}h",
            "window_move": move,
            "first_mid": first_mid,
            "market_mid": last_mid,
            "model_prob": model_prob,
            "yes_bid": last_bid,
            "yes_ask": last_ask,
            "num_snapshots": len(quotes),
            "edge": model_prob - last_mid,
        })

    rows.sort(key=lambda r: abs(r["edge"]), reverse=True)
    return rows


if __name__ == "__main__":
    comparisons = build_comparisons()
    if not comparisons:
        print(f"No markets moved more than {MIN_MOVE:.2f} in the last {LOOKBACK_HOURS}h "
              f"(with at least {MIN_SNAPSHOTS} quoted snapshots).")
    else:
        print(f"{len(comparisons)} markets with a momentum signal "
              f"(>{MIN_MOVE:.2f} move over {LOOKBACK_HOURS}h, {CONTINUATION_FACTOR} continuation assumed)\n")
        print(f"{'Ticker':<34} {'Move':>7} {'MktMid':>7} {'ModelP':>7} {'Edge':>7} {'Snaps':>6}")
        for r in comparisons[:20]:
            print(f"{r['ticker']:<34} {r['window_move']:>+7.2f} {r['market_mid']:>7.2f} "
                  f"{r['model_prob']:>7.2f} {r['edge']:>+7.2f} {r['num_snapshots']:>6}")
