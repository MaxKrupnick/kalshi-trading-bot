import csv
import os
import time
from datetime import datetime, timezone

import requests

from collect_data import BASE_URL, SERIES_TO_TRACK, get_markets_for_series

BACKFILL_FILE = "market_data_backfill.csv"
LOOKBACK_DAYS = 30
PERIOD_INTERVAL_MIN = 60  # hourly candles


def to_float_or_none(value):
    if value in (None, "", "None"):
        return None
    return float(value)


def get_candlesticks(series_ticker, market_ticker, start_ts, end_ts, max_retries=5):
    url = f"{BASE_URL}/series/{series_ticker}/markets/{market_ticker}/candlesticks"
    params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": PERIOD_INTERVAL_MIN}

    for attempt in range(max_retries):
        response = requests.get(url, params=params)
        if response.status_code == 200:
            return response.json().get("candlesticks", [])
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            print(f"    Rate limited on {market_ticker}, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        print(f"    Skipping {market_ticker}: got status {response.status_code}")
        return []

    print(f"    Giving up on {market_ticker} after {max_retries} rate-limit retries")
    return []


def candle_to_row(candle, ticker, title):
    timestamp = datetime.fromtimestamp(candle["end_period_ts"], tz=timezone.utc).isoformat()
    yes_bid = to_float_or_none(candle.get("yes_bid", {}).get("close_dollars"))
    yes_ask = to_float_or_none(candle.get("yes_ask", {}).get("close_dollars"))
    # Kalshi's Yes/No prices are complementary (Yes + No = $1) -- no direct
    # no_bid/no_ask candlestick data, so derive it from the Yes side.
    no_bid = round(1 - yes_ask, 4) if yes_ask is not None else None
    no_ask = round(1 - yes_bid, 4) if yes_bid is not None else None
    return [
        timestamp,
        ticker,
        title,
        yes_bid,
        yes_ask,
        no_bid,
        no_ask,
        to_float_or_none(candle.get("volume_fp")),
    ]


def backfill():
    end_ts = int(time.time())
    start_ts = end_ts - LOOKBACK_DAYS * 24 * 3600
    file_exists = os.path.isfile(BACKFILL_FILE)

    with open(BACKFILL_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "ticker", "title", "yes_bid", "yes_ask", "no_bid", "no_ask", "volume"])

        total_rows = 0
        for series in SERIES_TO_TRACK:
            markets = get_markets_for_series(series)
            print(f"{series}: backfilling {len(markets)} markets")
            for m in markets:
                candles = get_candlesticks(series, m["ticker"], start_ts, end_ts)
                for candle in candles:
                    writer.writerow(candle_to_row(candle, m["ticker"], m.get("title")))
                total_rows += len(candles)
                time.sleep(0.3)  # be polite to the API's rate limit
        return total_rows


if __name__ == "__main__":
    rows = backfill()
    print(f"Backfilled {rows} historical candle rows to {BACKFILL_FILE}")
