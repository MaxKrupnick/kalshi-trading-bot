"""Head-to-head: is the weather model a *better* forecaster than Kalshi's price?

Every other diagnostic in this repo asks "did the trades make money." That
question is downstream of a more basic one that had never been tested directly:
**does the NWS-derived model actually know something the market doesn't?**

The whole project rests on assuming it does (see README, "Why this approach").
If the model is merely *as good* as the market, then every "edge" the screen
finds is noise, and trading it loses the bid/ask spread by construction --
which would explain the paper-trading losses without any bug being involved.

The test: score both forecasts against the same real outcomes with a Brier
score, over *every* logged comparison in weather_edge_log.csv -- not just the
~200 that cleared the edge threshold and became paper trades. Scoring only
traded comparisons would be selecting on the model's own opinion, which is
exactly the bias under investigation.

Two things this deliberately does that a naive version wouldn't:

1. **Bootstrap CI on the difference, not just two point estimates.** Two Brier
   scores that differ in the 4th decimal are not evidence of anything without
   a sense of the sampling error.
2. **Reports the clustering caveat honestly.** The comparisons are repeated
   snapshots of the same ~100 markets, so they aren't independent draws; the
   naive CI is narrower than a properly clustered one would be. That works
   *against* precision, so it can't manufacture a "no difference" finding --
   but it's stated rather than hidden.
"""

import csv
import random
import sys
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

import weather_fair_value as wfv
from fetch_actual_temp import get_actual_high

WEATHER_EDGE_LOG = "weather_edge_log.csv"
PAPER_TRADES_FILE = "paper_trades.csv"

BOOTSTRAP_RESAMPLES = 5000
BOOTSTRAP_SEED = 7  # fixed so the reported CI is reproducible run to run

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

SERIES_TO_CITY = {cfg["series_ticker"]: city for city, cfg in wfv.CITIES.items()}


def parse_ticker(ticker):
    """"KXHIGHNY-26AUG27-B80.5" -> ("KXHIGHNY", date(2026, 8, 27))."""
    parts = ticker.split("-")
    token = parts[1]
    return parts[0], date(2000 + int(token[:2]), MONTHS[token[2:5]], int(token[5:]))


def resolved_yes(row, actual_high):
    """Did this contract settle YES, given the real recorded high?

    Mirrors weather_fair_value.model_probability()'s strike_type branching --
    note "less" markets key off cap_strike, not floor_strike.
    """
    strike_type = row["strike_type"]
    floor_strike = float(row["floor_strike"]) if row["floor_strike"] else None
    cap_strike = float(row["cap_strike"]) if row["cap_strike"] else None
    if strike_type == "greater":
        return actual_high > floor_strike
    if strike_type == "less":
        return actual_high < cap_strike
    if strike_type == "between":
        return floor_strike <= actual_high <= cap_strike
    return None


def load_traded_tickers():
    """Tickers that actually became weather paper trades, so the traded and
    untraded subsets can be reported separately."""
    traded = set()
    try:
        with open(PAPER_TRADES_FILE, newline="") as f:
            for row in csv.DictReader(f):
                if row["source"] == "weather":
                    traded.add(row["ticker"])
    except FileNotFoundError:
        pass
    return traded


def fetch_actual_highs(needed):
    actual = {}
    for city, target_date in sorted(needed):
        cfg = wfv.CITIES[city]
        try:
            high = get_actual_high(
                target_date, station=cfg["station"], tz=ZoneInfo(cfg["tz"])
            )
        except Exception as exc:  # noqa: BLE001 - one bad day shouldn't kill the run
            print(f"  ({city} {target_date}: {exc})", file=sys.stderr)
            high = None
        if high is not None:
            actual[(city, target_date)] = high
    return actual


def brier(pairs, index):
    """Mean squared error of forecast `index` (0=model, 1=market) vs outcome."""
    return sum((p[index] - p[2]) ** 2 for p in pairs) / len(pairs)


def report(label, pairs):
    if not pairs:
        print(f"{label:<40} (no scored comparisons)")
        return
    model, market = brier(pairs, 0), brier(pairs, 1)
    winner = "MODEL" if model < market else "MARKET"
    print(
        f"{label:<40} n={len(pairs):<6} model {model:.4f}  market {market:.4f}"
        f"   {winner} better"
    )


def bootstrap_difference(pairs):
    """95% CI on (model Brier - market Brier). Negative means model better."""
    random.seed(BOOTSTRAP_SEED)
    n = len(pairs)
    diffs = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        sample = [pairs[random.randrange(n)] for _ in range(n)]
        diffs.append(brier(sample, 0) - brier(sample, 1))
    diffs.sort()
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs))]
    model_better = sum(1 for d in diffs if d < 0) / len(diffs)
    return lo, hi, model_better


def main():
    with open(WEATHER_EDGE_LOG, newline="") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} logged comparisons in {WEATHER_EDGE_LOG}", file=sys.stderr)

    today = date.today()
    needed = set()
    for row in rows:
        try:
            series, target_date = parse_ticker(row["ticker"])
        except (IndexError, KeyError, ValueError):
            continue
        # Only past days can be scored -- a market whose day hasn't happened
        # yet has no outcome to compare either forecast against.
        if series in SERIES_TO_CITY and target_date < today:
            needed.add((SERIES_TO_CITY[series], target_date))

    print(f"fetching real recorded highs for {len(needed)} (city, date) pairs...",
          file=sys.stderr)
    actual = fetch_actual_highs(needed)
    print(f"got {len(actual)}", file=sys.stderr)

    traded = load_traded_tickers()

    pairs = []          # (model_prob, market_mid, outcome)
    by_city = defaultdict(list)
    by_edge = defaultdict(list)
    traded_pairs, untraded_pairs = [], []

    for row in rows:
        try:
            series, target_date = parse_ticker(row["ticker"])
        except (IndexError, KeyError, ValueError):
            continue
        city = SERIES_TO_CITY.get(series)
        high = actual.get((city, target_date))
        if high is None:
            continue
        outcome = resolved_yes(row, high)
        if outcome is None:
            continue
        market_mid = float(row["market_mid"])
        # A 0 or 1 mid is an empty book, not a real quote (same placeholder
        # problem backtest_calibration.py had to exclude) -- skip it.
        if not 0 < market_mid < 1:
            continue

        entry = (float(row["model_prob"]), market_mid, 1.0 if outcome else 0.0)
        pairs.append(entry)
        by_city[city].append(entry)
        (traded_pairs if row["ticker"] in traded else untraded_pairs).append(entry)

        edge = abs(float(row["edge"]))
        bucket = ("below threshold (<0.05)" if edge < 0.05
                  else "0.05-0.15" if edge < 0.15
                  else "0.15+ (model most confident)")
        by_edge[bucket].append(entry)

    if not pairs:
        print("No scored comparisons -- need resolved market days with real "
              "observations. Let the logs accumulate and re-run.")
        return

    print()
    print("=" * 78)
    print("BRIER SCORE: the model's forecast vs Kalshi's price, same outcomes")
    print("(lower is better; this is the project's founding assumption under test)")
    print("=" * 78)
    report("ALL logged comparisons", pairs)
    print()
    report("  ...the model chose to trade", traded_pairs)
    report("  ...the model passed on", untraded_pairs)
    print()
    for bucket in ["below threshold (<0.05)", "0.05-0.15", "0.15+ (model most confident)"]:
        report(f"  edge {bucket}", by_edge.get(bucket, []))
    print()
    for city in sorted(by_city):
        report(f"  {city}", by_city[city])

    lo, hi, model_better = bootstrap_difference(pairs)
    model, market = brier(pairs, 0), brier(pairs, 1)
    print()
    print("=" * 78)
    print("IS THE DIFFERENCE REAL? (bootstrap, "
          f"{BOOTSTRAP_RESAMPLES} resamples)")
    print("=" * 78)
    print(f"  model Brier - market Brier = {model - market:+.4f}  "
          "(negative = model is the better forecaster)")
    print(f"  95% CI: [{lo:+.4f}, {hi:+.4f}]")
    print(f"  resamples where the model beat the market: {100 * model_better:.1f}%")
    print()
    if lo < 0 < hi:
        print("  -> The CI straddles zero: the model and the market forecast these")
        print("     markets about EQUALLY WELL. There is no measurable information")
        print("     advantage to trade on. Any 'edge' the threshold finds is then")
        print("     noise, and paying the ask instead of the mid makes trading it")
        print("     negative-expectancy by construction -- no bug required.")
    elif hi < 0:
        print("  -> The model is genuinely the better forecaster. An edge exists;")
        print("     if paper trading still loses, look at execution/sizing next.")
    else:
        print("  -> The market is genuinely the better forecaster. The external")
        print("     data source is adding noise, not information.")

    print()
    print("Caveat, stated rather than buried: these comparisons are repeated")
    print("snapshots of the same markets over time, so they are not independent")
    print("draws. A properly clustered CI would be WIDER than the one above --")
    print("which can only weaken a claim of difference, never manufacture the")
    print("'no difference' result.")


if __name__ == "__main__":
    main()
