import bisect
import csv
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

from backfill_prices import get_candlesticks, to_float_or_none

PAPER_TRADES_FILE = "paper_trades.csv"
MARKET_DATA_FILE = "market_data.csv"
LIQUIDITY_CACHE_FILE = "liquidity_snapshot_cache.csv"

# Neither weather_edge_log.csv nor sports_edge_log.csv store bid/ask spread
# (only market_mid), so liquidity at trade time has to be reconstructed from
# collect_data.py's raw snapshots (market_data.csv), which do have yes_bid/
# yes_ask/volume, matched to each paper trade's ticker + opened_at.
#
# market_data.csv only has continuous coverage since collect_data.py's
# SERIES_TO_TRACK was fixed to include all 6 weather cities (2026-08-17) --
# most already-resolved trades predate that fix, so for anything not found
# there this falls back to fetching real historical candlesticks directly
# for that specific ticker (same API backfill_prices.py already uses), cached
# locally so re-running this script doesn't re-fetch every time.

EDGE_BUCKETS = [
    ("0.05-0.08", 0.05, 0.08),
    ("0.08-0.15", 0.08, 0.15),
    ("0.15+", 0.15, float("inf")),
]

SPREAD_BUCKETS = [
    ("tight (<0.05)", 0, 0.05),
    ("medium (0.05-0.10)", 0.05, 0.10),
    ("wide (0.10+)", 0.10, float("inf")),
]


def load_resolved_trades():
    with open(PAPER_TRADES_FILE, newline="") as f:
        return [r for r in csv.DictReader(f) if r["status"] == "resolved"]


def load_market_snapshots(tickers):
    """ticker -> sorted list of (timestamp, spread, volume). Only keeps
    tickers we actually need -- market_data.csv covers every tracked series,
    most of which aren't relevant here."""
    by_ticker = defaultdict(list)
    with open(MARKET_DATA_FILE, newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"]
            if ticker not in tickers:
                continue
            bid, ask = row["yes_bid"], row["yes_ask"]
            if bid in ("", None) or ask in ("", None):
                continue
            ts = datetime.fromisoformat(row["timestamp"])
            spread = float(ask) - float(bid)
            volume = float(row["volume"]) if row["volume"] not in ("", None) else None
            by_ticker[ticker].append((ts, spread, volume))
    for ticker in by_ticker:
        by_ticker[ticker].sort(key=lambda t: t[0])
    return by_ticker


def load_liquidity_cache():
    cache = {}
    if not os.path.isfile(LIQUIDITY_CACHE_FILE):
        return cache
    with open(LIQUIDITY_CACHE_FILE, newline="") as f:
        for row in csv.DictReader(f):
            spread = to_float_or_none(row["spread"])
            volume = to_float_or_none(row["volume"])
            cache[(row["ticker"], row["opened_at"])] = (spread, volume)
    return cache


def append_to_cache(ticker, opened_at, spread, volume):
    file_exists = os.path.isfile(LIQUIDITY_CACHE_FILE)
    with open(LIQUIDITY_CACHE_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["ticker", "opened_at", "spread", "volume"])
        writer.writerow([ticker, opened_at, spread, volume])


def fetch_historical_snapshot(ticker, opened_at):
    """Real historical spread/volume for one specific ticker around
    opened_at, via Kalshi's candlesticks API (same one backfill_prices.py
    uses) -- a targeted single-market fetch, not a full series backfill, so
    it works even for markets that have since closed and dropped off the
    series' "open" listing."""
    series_ticker = ticker.split("-")[0]
    start_ts = int((opened_at - timedelta(hours=3)).timestamp())
    end_ts = int((opened_at + timedelta(hours=1)).timestamp())
    candles = get_candlesticks(series_ticker, ticker, start_ts, end_ts)
    if not candles:
        return None, None

    opened_ts = opened_at.timestamp()
    best = min(candles, key=lambda c: abs(c["end_period_ts"] - opened_ts))
    yes_bid = to_float_or_none(best.get("yes_bid", {}).get("close_dollars"))
    yes_ask = to_float_or_none(best.get("yes_ask", {}).get("close_dollars"))
    if yes_bid is None or yes_ask is None:
        return None, None
    return round(yes_ask - yes_bid, 4), to_float_or_none(best.get("volume_fp"))


def nearest_snapshot(snapshots, opened_at):
    """Closest snapshot at or before opened_at; falls back to the earliest
    available snapshot if the trade was opened before any market_data.csv
    coverage existed for that ticker (e.g. collect_data.py hadn't picked it
    up yet at that exact moment)."""
    if not snapshots:
        return None
    timestamps = [s[0] for s in snapshots]
    idx = bisect.bisect_right(timestamps, opened_at) - 1
    if idx < 0:
        idx = 0
    return snapshots[idx]


def main():
    trades = load_resolved_trades()
    tickers = {r["ticker"] for r in trades}
    snapshots_by_ticker = load_market_snapshots(tickers)
    cache = load_liquidity_cache()

    enriched = []
    from_market_data, from_candlesticks, no_match = 0, 0, 0
    for r in trades:
        opened_at = datetime.fromisoformat(r["opened_at"])
        snap = nearest_snapshot(snapshots_by_ticker.get(r["ticker"], []), opened_at)
        if snap is not None:
            _, spread, volume = snap
            enriched.append((r, spread, volume))
            from_market_data += 1
            continue

        cache_key = (r["ticker"], r["opened_at"])
        if cache_key in cache:
            spread, volume = cache[cache_key]
        else:
            print(f"  fetching historical candles for {r['ticker']}...")
            spread, volume = fetch_historical_snapshot(r["ticker"], opened_at)
            append_to_cache(r["ticker"], r["opened_at"], spread, volume)
            time.sleep(0.3)  # be polite to the API's rate limit, same pace as backfill_prices.py

        if spread is None:
            no_match += 1
            continue
        enriched.append((r, spread, volume))
        from_candlesticks += 1

    print(f"{len(enriched)}/{len(trades)} resolved trades matched to a liquidity snapshot "
          f"({from_market_data} from market_data.csv, {from_candlesticks} from historical "
          f"candlesticks, {no_match} unmatched)\n")

    # Spread only, deliberately not volume: market_data.csv's volume is
    # cumulative-since-open while the candlestick fallback's volume is
    # per-candle -- the exact same "same column name, different meaning"
    # trap already documented in backfill_prices.py. Averaging them together
    # here would silently reproduce that bug. Spread doesn't have this
    # problem (both sources report the same yes_bid/yes_ask dollar quotes).
    print("Does the model's claimed edge size correlate with how liquid the market actually was?")
    print(f"{'Edge size':<10} {'n':>4} {'Avg spread':>11}")
    for name, lo, hi in EDGE_BUCKETS:
        bucket = [(r, s, v) for r, s, v in enriched if lo <= float(r["edge_at_entry"]) < hi]
        if not bucket:
            print(f"{name:<10} {'0':>4} {'--':>11}")
            continue
        avg_spread = sum(s for _, s, _ in bucket) / len(bucket)
        print(f"{name:<10} {len(bucket):>4} {avg_spread:>11.3f}")

    print("\nDoes trading in a wider-spread (less liquid) market actually cost real ROI?")
    print(f"{'Spread':<20} {'n':>4} {'Actual wins':>12} {'Expected wins':>14} {'P&L':>10} {'ROI':>8}")
    for name, lo, hi in SPREAD_BUCKETS:
        bucket = [(r, s, v) for r, s, v in enriched if lo <= s < hi]
        if not bucket:
            print(f"{name:<20} {'0':>4} {'--':>12} {'--':>14} {'--':>10} {'--':>8}")
            continue
        rs = [r for r, _, _ in bucket]
        n = len(rs)
        wins = sum(1 for r in rs if r["side"] == r["result"])
        expected = sum(float(r["entry_price"]) for r in rs)
        pnl = sum(float(r["pnl"]) for r in rs)
        risked = sum(float(r["position_size_dollars"]) for r in rs)
        roi = pnl / risked * 100 if risked else 0
        print(f"{name:<20} {n:>4} {wins:>7}/{n:<4} {expected:>14.1f} {pnl:>+10.2f} {roi:>+7.1f}%")

    print("\nIf big claimed edges cluster in wide-spread/low-volume markets, and wide-spread")
    print("trades underperform, that supports the hypothesis that the model's biggest 'edges'")
    print("are disproportionately noise (a stale quote in a thin book) rather than real signal.")


if __name__ == "__main__":
    main()
