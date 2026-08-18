import csv
import math
import re
from datetime import datetime, timedelta, timezone

PAPER_TRADES_FILE = "paper_trades.csv"

# The whole strategy's thesis (from backtest_calibration.py's original finding) is that
# Kalshi's own price is only weakly predictive early but catches up to well-calibrated by
# the time a market closes -- so any real edge should be concentrated in trades placed with
# more lead time, not close to resolution. This checks whether that pattern actually shows
# up in the paper-trading data itself, instead of just assuming it from the price-only
# backtest. If edge is real but decaying, aggregate P&L (flat/negative so far) could still be
# hiding a genuinely profitable early-lead-time slice.

WEATHER_EVENT_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})$")
SPORTS_EVENT_RE = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})(\d{4})[A-Z]+$")

BUCKETS = [
    ("<6h", 0, 6),
    ("6-24h", 6, 24),
    ("24-72h", 24, 72),
    (">72h", 72, float("inf")),
]

EDGE_BUCKETS = [
    ("0.05-0.08", 0.05, 0.08),
    ("0.08-0.15", 0.08, 0.15),
    ("0.15+", 0.15, float("inf")),
]


def event_key(ticker):
    return ticker.rsplit("-", 1)[0]


def resolution_time(ticker):
    """Approximate UTC resolution time for a market. Weather: the ticker only
    encodes a date, not a close time -- a daily-high market effectively
    resolves at end of day, so this uses midnight at the *start* of the next
    day as a simple, consistent proxy (slightly early, but fine for coarse
    bucketing). Sports: the ticker encodes the game's start time directly;
    used as-is since most MLB games resolve within a few hours of first
    pitch, well inside this script's bucket widths."""
    key = event_key(ticker)
    m = SPORTS_EVENT_RE.search(key)
    if m:
        yy, mon, dd, hhmm = m.groups()
        dt = datetime.strptime(f"20{yy}-{mon}-{dd} {hhmm}", "%Y-%b-%d %H%M")
        return dt.replace(tzinfo=timezone.utc)
    m = WEATHER_EVENT_RE.search(key)
    if m:
        yy, mon, dd = m.groups()
        dt = datetime.strptime(f"20{yy}-{mon}-{dd}", "%Y-%b-%d") + timedelta(days=1)
        return dt.replace(tzinfo=timezone.utc)
    return None


def bucket_for(lead_hours):
    for name, lo, hi in BUCKETS:
        if lo <= lead_hours < hi:
            return name
    return None


def main():
    with open(PAPER_TRADES_FILE, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "resolved"]

    by_bucket = {name: [] for name, _, _ in BUCKETS}
    unparsed = 0

    for r in rows:
        resolve_at = resolution_time(r["ticker"])
        if resolve_at is None:
            unparsed += 1
            continue
        opened_at = datetime.fromisoformat(r["opened_at"])
        lead_hours = (resolve_at - opened_at).total_seconds() / 3600
        bucket = bucket_for(max(lead_hours, 0))
        if bucket:
            by_bucket[bucket].append(r)

    if unparsed:
        print(f"({unparsed} trades skipped -- ticker didn't match either format)\n")

    print(f"{'Lead time':<10} {'n':>4} {'Actual wins':>12} {'Expected wins':>14} {'P&L':>10} {'ROI':>8}")
    for name, _, _ in BUCKETS:
        trades = by_bucket[name]
        if not trades:
            print(f"{name:<10} {'0':>4} {'--':>12} {'--':>14} {'--':>10} {'--':>8}")
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["side"] == t["result"])
        expected = sum(float(t["entry_price"]) for t in trades)
        pnl = sum(float(t["pnl"]) for t in trades)
        risked = sum(float(t["position_size_dollars"]) for t in trades)
        roi = pnl / risked * 100 if risked else 0
        print(f"{name:<10} {n:>4} {wins:>7}/{n:<4} {expected:>14.1f} {pnl:>+10.2f} {roi:>+7.1f}%")

    print("\nIf the strategy's core thesis is right, ROI should trend better (less negative /")
    print("more positive) in the longer-lead-time buckets, where the market has had less time")
    print("to catch up to the same information. A flat or reversed pattern here, even with this")
    print("small a sample, is a reason to question the thesis itself, not just wait for more data.")

    print(f"\n{'Edge size':<10} {'n':>4} {'Actual wins':>12} {'Expected wins':>14} {'P&L':>10} {'ROI':>8}")
    for name, lo, hi in EDGE_BUCKETS:
        trades = [r for r in rows if lo <= float(r["edge_at_entry"]) < hi]
        if not trades:
            print(f"{name:<10} {'0':>4} {'--':>12} {'--':>14} {'--':>10} {'--':>8}")
            continue
        n = len(trades)
        wins = sum(1 for t in trades if t["side"] == t["result"])
        expected = sum(float(t["entry_price"]) for t in trades)
        pnl = sum(float(t["pnl"]) for t in trades)
        risked = sum(float(t["position_size_dollars"]) for t in trades)
        roi = pnl / risked * 100 if risked else 0
        print(f"{name:<10} {n:>4} {wins:>7}/{n:<4} {expected:>14.1f} {pnl:>+10.2f} {roi:>+7.1f}%")

    print("\nIf the model's edge estimate were meaningful, bigger claimed edges should perform")
    print("at least as well as smaller ones, not worse -- the model is claiming more confidence")
    print("there. If the largest-edge bucket is instead the worst performer, that's a sign the")
    print("biggest 'edges' are disproportionately model error (e.g. a stale odds line, a wrong")
    print("forecast) rather than real mispricing, not a sign to trade more aggressively on them.")


if __name__ == "__main__":
    main()
