"""Is Kalshi's price *structurally* mispriced at the extremes -- and is that tradeable?

The third and last test in this project, and the only one that doesn't involve a model of
mine at all. The first two tests asked "is my forecast better than the price." Both said no.
This one skips the model entirely and asks a question about the market itself:

    **Do cheap contracts settle YES less often than their price implies?**

That pattern -- longshots overpriced, favourites underpriced -- is the favourite-longshot
bias, the most documented anomaly in prediction and betting markets, known since the 1940s.
If it's present here it needs no forecasting advantage to exploit: you sell the longshot and
collect the difference. No external data, no edge over anyone's information. Pure structure.

It matters for a second reason. The weather arm's single worst bucket was entries under
$0.15: 84 trades, 2% win rate against ~6% implied, -$501.83. That is this bias, and the arm
was on the *wrong side* of it -- buying the overpriced longshots its model liked. So the
question "was the profitable trade just the opposite of what I was doing?" is a fair one and
deserves a real answer rather than a shrug.

Three things this does that a naive version wouldn't:

1. **Prices the trade at the real quoted ask, not the mid.** A 3-cent mispricing with a
   3-cent spread is not a trade. Every earlier arm on this project lost part of its money to
   exactly that gap, so the EV here is computed against `no_ask` -- what you would actually
   have paid -- rather than a theoretical midpoint.
2. **Deduplicates to one observation per market per hour.** The raw log has a snapshot every
   15 minutes; four near-identical rows of the same market are not four pieces of evidence.
3. **Bootstraps clustered by market.** 3,000 snapshots of 550 markets is 550 independent
   draws, not 3,000. This is the step that decides the answer, and it is the step a hopeful
   version of this script would skip.

Spoiler, recorded honestly: the bias is clearly visible, the spread-adjusted EV is positive
as a point estimate, and the clustered interval straddles zero. Not tradeable on this sample.
"""

import collections
import csv
import random
import sys

import momentum_signal as ms
from analyze_momentum_vs_market import load_settlement_cache

MARKET_DATA_FILE = "market_data.csv"

# Buckets are finer at the extremes, where the bias is supposed to live and where a
# few cents of mispricing is a large fraction of the price.
BUCKETS = [
    (0.01, 0.05), (0.05, 0.10), (0.10, 0.15), (0.15, 0.25), (0.25, 0.40),
    (0.40, 0.60), (0.60, 0.75), (0.75, 0.85), (0.85, 0.90), (0.90, 0.95), (0.95, 0.99),
]

# The range the calibration table flags as overpriced. Set from the table below, and
# deliberately not optimised further -- picking the best-looking sub-range and then
# testing it on the same data is how you manufacture an edge that isn't there.
TRADE_RANGE = (0.05, 0.25)

MIN_BUCKET_N = 100
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 7


def load_observations():
    """(ticker, yes_mid, no_ask, settled_no) -- one row per market per hour."""
    settled = {t: r for t, r in load_settlement_cache().items() if r in ("yes", "no")}
    rows, seen = [], collections.defaultdict(set)

    with open(MARKET_DATA_FILE, newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"]
            if ticker not in settled:
                continue
            yes_bid = ms.to_float_or_none(row["yes_bid"])
            yes_ask = ms.to_float_or_none(row["yes_ask"])
            no_ask = ms.to_float_or_none(row["no_ask"])
            if yes_bid is None or yes_ask is None or no_ask is None:
                continue
            hour = row["timestamp"][:13]
            if hour in seen[ticker]:
                continue
            seen[ticker].add(hour)
            rows.append((ticker, (yes_bid + yes_ask) / 2, no_ask,
                         1.0 if settled[ticker] == "no" else 0.0))
    return rows


def calibration_table(rows):
    print("Is the market's own price calibrated?  (all settled markets, hourly)\n")
    print(f"{'price bucket':>14} {'n':>7} {'markets':>8} {'avg price':>10} "
          f"{'actual YES':>11} {'gap':>8}")
    print("-" * 62)
    for lo, hi in BUCKETS:
        sel = [r for r in rows if lo <= r[1] < hi]
        if len(sel) < MIN_BUCKET_N:
            continue
        n = len(sel)
        price = sum(r[1] for r in sel) / n
        actual = sum(1 - r[3] for r in sel) / n  # settled YES = not settled NO
        print(f"{lo:.2f}-{hi:.2f}".rjust(14), f"{n:>7}", f"{len({r[0] for r in sel}):>8}",
              f"{price:>10.3f}", f"{actual:>11.3f}", f"{actual - price:>+8.3f}")
    print("\nNegative gap = settles YES less often than priced = longshot overpriced.")


def ev_table(rows):
    print("\n\nStrategy: SELL the longshot (buy NO) at the real quoted no_ask\n")
    print(f"{'yes-mid bucket':>15} {'n':>7} {'markets':>8} {'pay':>8} {'P(no)':>8} {'EV':>9}")
    print("-" * 60)
    for lo, hi in BUCKETS[:5]:
        sel = [r for r in rows if lo <= r[1] < hi]
        if len(sel) < MIN_BUCKET_N:
            continue
        n = len(sel)
        pay = sum(r[2] for r in sel) / n
        p_no = sum(r[3] for r in sel) / n
        print(f"{lo:.2f}-{hi:.2f}".rjust(15), f"{n:>7}", f"{len({r[0] for r in sel}):>8}",
              f"{pay:>8.3f}", f"{p_no:>8.3f}", f"{p_no - pay:>+9.3f}")
    print("\nEV is per contract, after paying the quoted ask rather than the mid.")


def clustered_ci(rows):
    lo, hi = TRADE_RANGE
    sel = [r for r in rows if lo <= r[1] < hi]
    by_ticker = collections.defaultdict(list)
    for ticker, _, no_ask, settled_no in sel:
        by_ticker[ticker].append((no_ask, settled_no))
    units = list(by_ticker.values())

    flat = [x for u in units for x in u]
    point = sum(w - p for p, w in flat) / len(flat)

    rng = random.Random(BOOTSTRAP_SEED)
    draws = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        total = count = 0.0
        for _ in range(len(units)):
            for p, w in units[rng.randrange(len(units))]:
                total += w - p
                count += 1
        draws.append(total / count)
    draws.sort()
    ci_lo = draws[int(0.025 * len(draws))]
    ci_hi = draws[int(0.975 * len(draws)) - 1]

    losers = [1 for p, w in flat if w == 0.0]
    avg_cost = sum(p for p, w in flat) / len(flat)

    print("\n" + "=" * 62)
    print(f"  SELLING LONGSHOTS PRICED {lo:.2f}-{hi:.2f}")
    print("=" * 62)
    print(f"\n  {len(flat):,} observations across {len(units):,} distinct markets")
    print(f"  point EV per contract        : {point:+.4f}")
    print(f"  95% CI, clustered by market  : [{ci_lo:+.4f}, {ci_hi:+.4f}]")
    print(f"  loss rate                    : {len(losers)}/{len(flat)} "
          f"({len(losers) / len(flat):.1%}), each losing ~{avg_cost:.2f}/contract")
    print()
    if ci_lo > 0:
        print("VERDICT: the edge survives clustering. Worth pursuing -- but note the payoff")
        print("shape: frequent small wins against rare large losses, which needs far more")
        print("data than this before any size is put behind it.")
    else:
        print("VERDICT: does NOT survive. The point estimate is positive and the clustered")
        print("interval includes zero, so this is the same shape of result as the momentum")
        print("arm's profitable month -- a number that looks like an edge until it is given")
        print("an honest error bar. Not tradeable on this sample.")
    print()


def main():
    rows = load_observations()
    if not rows:
        print("No settled observations -- run analyze_momentum_vs_market.py first to")
        print("populate settlement_cache.csv.")
        return 1
    calibration_table(rows)
    ev_table(rows)
    clustered_ci(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
