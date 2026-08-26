"""Would recalibrating the forecast sigma actually have fixed the losses?

`calibrate_sigma.py` shows the model's assumed forecast uncertainty is far too
wide -- measured RMSE runs ~1.9-3.4F against a hand-set curve of 2.0-7.2F. The
obvious conclusion is that too-wide sigma manufactures fake probability in the
temperature tails, which is where the money was lost (the sub-$0.15 entry
bucket is the single worst-performing slice of the whole track record).

That conclusion is plausible enough to act on -- and expensive to get wrong,
since it means editing the model constants that every future trade depends on.
So this tests it against real outcomes first instead: replay every resolved
weather paper trade with the *measured* sigma, and see which trades would no
longer have cleared the edge threshold at all.

This is a counterfactual, and it has an honest limit worth stating: it can only
re-score the trades that were actually taken. A narrower sigma would also have
opened *different* trades near the distribution's center that were never
logged, and those aren't in this data. So read the output as "would the fix
have avoided these specific losses," not "here is the P&L the fix would have
produced."
"""

import csv
import math
from collections import defaultdict
from datetime import datetime, timezone

import paper_trade

PAPER_TRADES_FILE = "paper_trades.csv"
WEATHER_EDGE_LOG = "weather_edge_log.csv"

# Measured RMSE by lead-time bucket, from `python3 calibrate_sigma.py`.
# Update these together with that script's output -- they are a snapshot of a
# measurement, not independent constants.
MEASURED_SIGMA_F = [
    (12, 2.15),
    (48, 1.92),
    (120, 2.77),
    (float("inf"), 3.38),
]

MONTHS = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}


def measured_sigma(lead_hours):
    for upper, sigma in MEASURED_SIGMA_F:
        if lead_hours <= upper:
            return sigma
    return MEASURED_SIGMA_F[-1][1]


def resolution_time(ticker):
    """Roughly when the contract's underlying day-high is determined.

    "KXHIGHNY-26AUG27-B80.5" -> 2026-08-27 18:00 UTC (early afternoon local,
    close enough for bucketing lead time into 12/48/120h bands)."""
    token = ticker.split("-")[1]
    return datetime(
        2000 + int(token[:2]), MONTHS[token[2:5]], int(token[5:]),
        18, 0, tzinfo=timezone.utc,
    )


def normal_cdf(x, mean, sigma):
    return 0.5 * (1 + math.erf((x - mean) / (sigma * math.sqrt(2))))


def model_probability(strike_type, floor_strike, cap_strike, forecast_high, sigma):
    """Same math as weather_fair_value.model_probability, re-implemented here
    against logged fields so this script can replay history without needing a
    live API call per trade."""
    if strike_type == "greater":
        return 1 - normal_cdf(floor_strike + 0.5, forecast_high, sigma)
    if strike_type == "less":
        return normal_cdf(cap_strike - 0.5, forecast_high, sigma)
    if strike_type == "between":
        return (normal_cdf(cap_strike + 0.5, forecast_high, sigma)
                - normal_cdf(floor_strike - 0.5, forecast_high, sigma))
    raise ValueError(f"unsupported strike_type: {strike_type}")


def load_edge_log():
    rows = defaultdict(list)
    with open(WEATHER_EDGE_LOG, newline="") as f:
        for row in csv.DictReader(f):
            rows[row["ticker"]].append(row)
    return rows


def nearest_snapshot(edge_rows, ticker, when):
    """The logged comparison closest in time to when the trade was opened --
    the model's actual inputs at decision time, not a later revision."""
    candidates = edge_rows.get(ticker)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda r: abs(datetime.fromisoformat(r["logged_at"]) - when),
    )


def main():
    edge_rows = load_edge_log()

    with open(PAPER_TRADES_FILE, newline="") as f:
        trades = [r for r in csv.DictReader(f)
                  if r["source"] == "weather" and r["status"] == "resolved"]

    if not trades:
        print("No resolved weather trades yet.")
        return

    original_pnl = sum(float(t["pnl"]) for t in trades)
    kept_pnl = 0.0
    dropped_pnl = 0.0
    kept = dropped = unmatched = 0
    by_entry = defaultdict(lambda: [0, 0, 0.0, 0.0])  # kept, dropped, kept P&L, dropped P&L

    for trade in trades:
        opened = datetime.fromisoformat(trade["opened_at"])
        snapshot = nearest_snapshot(edge_rows, trade["ticker"], opened)
        pnl = float(trade["pnl"])
        if snapshot is None:
            unmatched += 1
            kept_pnl += pnl
            continue

        lead_hours = max(
            (resolution_time(trade["ticker"]) - opened).total_seconds() / 3600, 0
        )
        floor_strike = float(snapshot["floor_strike"]) if snapshot["floor_strike"] else None
        cap_strike = float(snapshot["cap_strike"]) if snapshot["cap_strike"] else None
        corrected_prob = model_probability(
            snapshot["strike_type"], floor_strike, cap_strike,
            float(snapshot["forecast_high"]), measured_sigma(lead_hours),
        )

        entry_price = float(trade["entry_price"])
        # The edge for the side that was actually taken, against the same price
        # that was actually paid.
        corrected_edge = (corrected_prob - entry_price if trade["side"] == "yes"
                          else (1 - corrected_prob) - entry_price)

        bucket = ("<0.15" if entry_price < 0.15
                  else "0.15-0.75" if entry_price < 0.75 else ">=0.75")

        if corrected_edge < paper_trade.EDGE_THRESHOLD:
            dropped += 1
            dropped_pnl += pnl
            by_entry[bucket][1] += 1
            by_entry[bucket][3] += pnl
            continue

        # Still traded -- but edge-weighted sizing means a different stake.
        old_size = float(trade["position_size_dollars"])
        new_size = paper_trade.position_size_for_edge(corrected_edge)
        scaled = pnl * (new_size / old_size) if old_size else pnl
        kept += 1
        kept_pnl += scaled
        by_entry[bucket][0] += 1
        by_entry[bucket][2] += pnl

    print("=" * 74)
    print("COUNTERFACTUAL: resolved weather trades replayed with measured sigma")
    print("=" * 74)
    print(f"resolved weather trades: {len(trades)}"
          + (f"  ({unmatched} with no matching edge-log snapshot)" if unmatched else ""))
    print()
    print(f"  actual P&L:                        ${original_pnl:>9.2f}")
    print(f"  trades that would still be taken:  {kept:>9}")
    print(f"  trades the fix would have skipped: {dropped:>9}"
          f"   (their real P&L: ${dropped_pnl:,.2f})")
    print(f"  counterfactual P&L:                ${kept_pnl:>9.2f}")
    print()
    print(f"{'entry price':<14}{'kept':>6}{'skipped':>9}{'kept P&L':>13}{'skipped P&L':>14}")
    for bucket in ["<0.15", "0.15-0.75", ">=0.75"]:
        if bucket in by_entry:
            k, d, kp, dp = by_entry[bucket]
            print(f"{bucket:<14}{k:>6}{d:>9}{kp:>13.2f}{dp:>14.2f}")

    print()
    improvement = kept_pnl - original_pnl
    print(f"Net effect of the sigma fix on these trades: ${improvement:+,.2f}")
    if kept_pnl < 0:
        print()
        print("Still negative. The sigma fix removes some of the damage but does not")
        print("turn the strategy positive -- so 'sigma was too wide' is at best a")
        print("contributing cause, not the explanation. Before editing the model")
        print("constants, check whether the model has any forecasting advantage over")
        print("the market at all (`analyze_model_vs_market.py`) -- if it doesn't,")
        print("no amount of sigma tuning creates one.")

    print()
    print("Limit of this counterfactual: it can only re-score trades that were")
    print("actually taken. A narrower sigma would also open different trades near")
    print("the distribution's center that were never logged, so this answers")
    print("'would the fix have avoided these losses', not 'what P&L would it earn'.")


if __name__ == "__main__":
    main()
