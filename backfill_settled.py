import csv
import os
import time

import requests

from backfill_prices import LOOKBACK_DAYS, candle_to_row, get_candlesticks
from collect_data import BASE_URL, SERIES_TO_TRACK

SETTLED_FILE = "market_data_settled.csv"


def get_markets_page(params, max_retries=5):
    for attempt in range(max_retries):
        response = requests.get(f"{BASE_URL}/markets", params=params)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            print(f"    Rate limited listing markets, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            time.sleep(wait)
            continue
        print(f"  Error fetching markets: {response.status_code}")
        return {}
    print(f"  Giving up listing markets after {max_retries} rate-limit retries")
    return {}


def get_settled_markets_for_series(series_ticker, min_close_ts, max_close_ts):
    markets = []
    cursor = None
    while True:
        params = {
            "series_ticker": series_ticker,
            "status": "settled",
            "min_close_ts": min_close_ts,
            "max_close_ts": max_close_ts,
        }
        if cursor:
            params["cursor"] = cursor
        data = get_markets_page(params)
        markets.extend(data.get("markets", []))
        cursor = data.get("cursor")
        if not cursor:
            break
    return markets


def backfill_settled():
    end_ts = int(time.time())
    start_ts = end_ts - LOOKBACK_DAYS * 24 * 3600
    file_exists = os.path.isfile(SETTLED_FILE)

    with open(SETTLED_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["timestamp", "ticker", "title", "yes_bid", "yes_ask", "no_bid", "no_ask", "volume", "result"]
            )

        total_rows = 0
        for series in SERIES_TO_TRACK:
            markets = get_settled_markets_for_series(series, start_ts, end_ts)
            print(f"{series}: {len(markets)} settled markets in the last {LOOKBACK_DAYS} days")
            for m in markets:
                result = m.get("result")  # "yes" or "no" -- the actual outcome
                candles = get_candlesticks(series, m["ticker"], start_ts, end_ts)
                for candle in candles:
                    row = candle_to_row(candle, m["ticker"], m.get("title"))
                    row.append(result)
                    writer.writerow(row)
                total_rows += len(candles)
                time.sleep(0.3)  # be polite to the API's rate limit
        return total_rows


if __name__ == "__main__":
    rows = backfill_settled()
    print(f"Backfilled {rows} settled-market candle rows (with outcomes) to {SETTLED_FILE}")
