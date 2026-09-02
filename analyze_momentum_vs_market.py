"""Head-to-head: is the momentum signal a *better* forecaster than Kalshi's price?

This is the momentum arm's version of `analyze_model_vs_market.py`, and it asks
the same question that test asked of the weather model: not "did the trades make
money," but **does this signal actually know something the market price doesn't?**

Why it matters here specifically. The weather fair-value model was measured to
have no forecasting advantage (Brier 0.0891 vs the market's 0.0881, CI on the
difference straddling zero), which is what made its losses inevitable rather than
buggy. Momentum was built as the *control* arm for that experiment -- the thing
the project's founding premise said should be weak. Since 2026-08-26 it has been
mildly profitable on paper (+$108.74 over 296 resolved trades), and the whole
point of the stricter gate adopted after the weather result is that a positive
P&L at this n is not evidence. This script applies that gate.

The momentum "model" is a deterministic function of the market's own price:

    model_prob = clamp(last_mid + CONTINUATION_FACTOR * (last_mid - first_mid))

so the test reduces to a clean question: **does extrapolating half of the recent
6h move beat simply quoting the current mid?** If the answer is no, the arm's
recent profit is noise plus favorable settlement luck, and it should not graduate
toward live trading no matter how the P&L looks.

Three methodological choices carried over from the weather analysis:

1. **Score every comparison, not just the traded ones.** Scoring only the
   snapshots that cleared EDGE_THRESHOLD would be selecting on the signal's own
   opinion, which is precisely the bias under investigation. The traded subset is
   reported separately, as a diagnostic for adverse selection.
2. **Bootstrap a CI on the difference,** not just two point estimates. Two Brier
   scores differing in the 4th decimal mean nothing without sampling error.
3. **Take the clustering seriously.** Comparisons are repeated snapshots of the
   same ~1,800 markets, so they are nowhere near independent draws. The weather
   script reported this as a caveat; here it is handled directly, by also running
   a bootstrap that resamples *whole tickers* rather than individual rows. The
   clustered interval is the honest one; the naive one is shown alongside only to
   make the size of the difference visible.
"""

import csv
import random
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import momentum_signal as ms
from collect_data import BASE_URL

MARKET_DATA_FILE = "market_data.csv"
SETTLEMENT_CACHE = "settlement_cache.csv"

# Evaluate on a fixed hourly grid. The live arm runs 4x/hour, but adjacent
# snapshots of the same market are almost perfectly correlated; hourly keeps the
# sample honest without changing the signal definition.
EVAL_EVERY_HOURS = 1

EDGE_THRESHOLD = 0.05  # matches paper_trade.EDGE_THRESHOLD
BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 7  # fixed so the reported CI is reproducible run to run
BATCH_SIZE = 100


def load_quotes():
    """ticker -> chronological [(ts, yes_bid, yes_ask)] over the whole log."""
    by_ticker = defaultdict(list)
    with open(MARKET_DATA_FILE, newline="") as f:
        for row in csv.DictReader(f):
            bid = ms.to_float_or_none(row["yes_bid"])
            ask = ms.to_float_or_none(row["yes_ask"])
            if bid is None or ask is None:
                continue
            by_ticker[row["ticker"]].append(
                (datetime.fromisoformat(row["timestamp"]), bid, ask)
            )
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda t: t[0])
    return by_ticker


def load_settlement_cache():
    try:
        with open(SETTLEMENT_CACHE, newline="") as f:
            return {r["ticker"]: r["result"] for r in csv.DictReader(f)}
    except FileNotFoundError:
        return {}


def save_settlement_cache(cache):
    with open(SETTLEMENT_CACHE, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ticker", "result"])
        for ticker, result in sorted(cache.items()):
            w.writerow([ticker, result])


def fetch_settlements(tickers, cache):
    """Batched, cached lookup of final settlement. Same batching and rate-limit
    handling as resolve_paper_trades.py -- 1,800 per-ticker requests would be
    both slow and rude to the API."""
    missing = sorted(t for t in tickers if t not in cache)
    if not missing:
        return cache

    print(f"Fetching settlement for {len(missing)} uncached tickers...", flush=True)
    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i : i + BATCH_SIZE]
        for attempt in range(5):
            resp = requests.get(f"{BASE_URL}/markets", params={"tickers": ",".join(batch)})
            if resp.status_code == 200:
                for m in resp.json().get("markets", []):
                    status, result = m.get("status"), m.get("result")
                    if status == "finalized" and result in ("yes", "no"):
                        cache[m["ticker"]] = result
                    else:
                        cache[m["ticker"]] = ""  # known, but not settled yet
                break
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                print(f"  rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            resp.raise_for_status()
        for t in batch:
            cache.setdefault(t, "")
        print(f"  {min(i + BATCH_SIZE, len(missing))}/{len(missing)}", flush=True)
    save_settlement_cache(cache)
    return cache


def build_snapshots(quotes_by_ticker, settlements):
    """Replay momentum_signal's exact logic on an hourly grid over history.

    Returns rows of (ticker, model_prob, market_mid, outcome, cleared_threshold).
    """
    lookback = timedelta(hours=ms.LOOKBACK_HOURS)
    step = timedelta(hours=EVAL_EVERY_HOURS)
    rows = []

    for ticker, quotes in quotes_by_ticker.items():
        outcome_str = settlements.get(ticker, "")
        if outcome_str not in ("yes", "no"):
            continue  # unsettled -> unscoreable, drop it
        outcome = 1.0 if outcome_str == "yes" else 0.0

        start, end = quotes[0][0], quotes[-1][0]
        t = start + lookback
        # align to the hour so the grid is deterministic
        t = t.replace(minute=0, second=0, microsecond=0) + step
        while t <= end:
            window = [q for q in quotes if t - lookback <= q[0] <= t]
            if len(window) < ms.MIN_SNAPSHOTS:
                t += step
                continue

            first_mid = (window[0][1] + window[0][2]) / 2
            last_bid, last_ask = window[-1][1], window[-1][2]
            last_mid = (last_bid + last_ask) / 2
            move = last_mid - first_mid
            if abs(move) < ms.MIN_MOVE:
                t += step
                continue

            projected = last_mid + ms.CONTINUATION_FACTOR * move
            model_prob = min(max(projected, 0.01), 0.99)

            # would this snapshot have been traded? mirrors paper_trade's
            # comparison against the ask, not the mid
            edge_yes = model_prob - last_ask
            edge_no = (1 - model_prob) - (1 - last_bid)
            cleared = max(edge_yes, edge_no) >= EDGE_THRESHOLD

            rows.append((ticker, model_prob, last_mid, outcome, cleared))
            t += step

    return rows


def brier(pairs):
    """pairs: iterable of (forecast, outcome)."""
    pairs = list(pairs)
    if not pairs:
        return float("nan")
    return sum((f - o) ** 2 for f, o in pairs) / len(pairs)


def bootstrap_diff(rows, clustered, resamples=BOOTSTRAP_RESAMPLES):
    """95% CI on (model Brier - market Brier). Negative favours the model.

    clustered=True resamples whole tickers, which respects the fact that
    snapshots of one market are not independent observations.
    """
    rng = random.Random(BOOTSTRAP_SEED)
    if clustered:
        by_ticker = defaultdict(list)
        for ticker, mp, mk, o, _ in rows:
            by_ticker[ticker].append((mp, mk, o))
        units = list(by_ticker.values())
    else:
        units = [[(mp, mk, o)] for _, mp, mk, o, _ in rows]

    diffs = []
    n = len(units)
    for _ in range(resamples):
        model_se = market_se = count = 0.0
        for _ in range(n):
            for mp, mk, o in units[rng.randrange(n)]:
                model_se += (mp - o) ** 2
                market_se += (mk - o) ** 2
                count += 1
        if count:
            diffs.append(model_se / count - market_se / count)
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs)) - 1]
    return lo, hi


def report(rows):
    model = brier((mp, o) for _, mp, _, o, _ in rows)
    market = brier((mk, o) for _, _, mk, o, _ in rows)
    tickers = {r[0] for r in rows}

    print()
    print("=" * 68)
    print("  MOMENTUM SIGNAL vs KALSHI PRICE -- head-to-head Brier score")
    print("=" * 68)
    print(f"\nScored comparisons : {len(rows):,} across {len(tickers):,} settled markets")
    print(f"Signal definition  : mid + {ms.CONTINUATION_FACTOR} x (move over {ms.LOOKBACK_HOURS}h), "
          f"min move {ms.MIN_MOVE}, min {ms.MIN_SNAPSHOTS} snapshots")
    print(f"Evaluation grid    : every {EVAL_EVERY_HOURS}h\n")
    print(f"  Brier, momentum model : {model:.4f}")
    print(f"  Brier, market mid     : {market:.4f}")
    print(f"  difference            : {model - market:+.4f}   (negative = model is better)")

    lo_n, hi_n = bootstrap_diff(rows, clustered=False)
    lo_c, hi_c = bootstrap_diff(rows, clustered=True)
    print(f"\n  95% CI, naive bootstrap     : [{lo_n:+.4f}, {hi_n:+.4f}]")
    print(f"  95% CI, clustered by ticker : [{lo_c:+.4f}, {hi_c:+.4f}]   <- the honest one")

    traded = [r for r in rows if r[4]]
    if traded:
        tm = brier((mp, o) for _, mp, _, o, _ in traded)
        tk = brier((mk, o) for _, _, mk, o, _ in traded)
        print(f"\n  On the {len(traded):,} snapshots that cleared EDGE_THRESHOLD={EDGE_THRESHOLD}:")
        print(f"    Brier, momentum model : {tm:.4f}")
        print(f"    Brier, market mid     : {tk:.4f}")
        print(f"    difference            : {tm - tk:+.4f}")
        if tm > tk:
            print("    -> the market forecasts better on exactly the trades the signal picked;")
            print("       that is adverse selection, the same pattern the weather arm showed.")
        else:
            print("    -> the signal holds up on its own selections, not just on average.")

    print()
    if lo_c < 0 < hi_c:
        print("VERDICT: no measurable forecasting advantage either way -- the clustered")
        print("interval straddles zero. By the gate adopted after the weather result,")
        print("recent paper P&L is not sufficient grounds to advance this arm.")
    elif hi_c < 0:
        print("VERDICT: the momentum signal forecasts genuinely better than the market")
        print("price, with the clustered interval entirely below zero. That contradicts")
        print("the project's founding premise and is worth pursuing.")
    else:
        print("VERDICT: the market forecasts better than the momentum signal; the")
        print("clustered interval is entirely above zero.")
    print()


def main():
    print("Loading market_data.csv...", flush=True)
    quotes = load_quotes()
    print(f"  {len(quotes):,} tickers with quotes", flush=True)

    cache = load_settlement_cache()
    cache = fetch_settlements(set(quotes), cache)
    settled = {t: r for t, r in cache.items() if r in ("yes", "no")}
    print(f"  {len(settled):,} of {len(quotes):,} tickers have finalized settlement", flush=True)

    print("Replaying the momentum signal over history...", flush=True)
    rows = build_snapshots(quotes, settled)
    if not rows:
        print("No scoreable comparisons -- nothing to report.")
        return 1
    report(rows)
    return 0


if __name__ == "__main__":
    sys.exit(main())
