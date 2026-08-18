import requests
import csv
import os
from datetime import datetime, timezone

from weather_fair_value import CITIES as WEATHER_CITIES

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
CSV_FILE = "market_data.csv"

# Weather series are derived from weather_fair_value.CITIES instead of listed
# here separately -- this exact list drifting out of sync with CITIES (only
# ever tracking KXHIGHNY here, missing the other 5 cities added 2026-08-14)
# was a real bug found 2026-08-17, the same class as log_forecast.py's
# NYC-only gap found the same day. Deriving it means adding a city in one
# place (CITIES) is enough; it can't drift out of sync with this list again.
SERIES_TO_TRACK = [c["series_ticker"] for c in WEATHER_CITIES.values()] + [
    "KXFEDHIKE",    # Next Fed rate hike
    "KXCPI",        # CPI / inflation
    "KXBTCMAX150",  # Will Bitcoin hit $150k
    "KXEGGS",       # Egg prices
    "KXNFLGAME",    # NFL game winner
    "KXMLBGAME",    # MLB game winner
    "KXWNBAGAME",   # WNBA game winner
    "KXPAYROLLS",   # Nonfarm payrolls
    "KXU3",         # Unemployment rate
    "KXPCECORE",    # Core PCE inflation (Fed's preferred gauge)
]

def get_markets_for_series(series_ticker):
    response = requests.get(
        f"{BASE_URL}/markets",
        params={"series_ticker": series_ticker, "status": "open"}
    )
    if response.status_code != 200:
        print(f"  Skipping {series_ticker}: got status {response.status_code}")
        return []
    return response.json()["markets"]

def collect_all_tracked_markets():
    all_markets = []
    for series in SERIES_TO_TRACK:
        markets = get_markets_for_series(series)
        print(f"{series}: found {len(markets)} open markets")
        all_markets.extend(markets)
    return all_markets

def save_snapshot(markets):
    timestamp = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.isfile(CSV_FILE)

    with open(CSV_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["timestamp", "ticker", "title", "yes_bid", "yes_ask", "no_bid", "no_ask", "volume"])
        for m in markets:
            writer.writerow([
                timestamp,
                m.get("ticker"),
                m.get("title"),
                m.get("yes_bid_dollars"),
                m.get("yes_ask_dollars"),
                m.get("no_bid_dollars"),
                m.get("no_ask_dollars"),
                m.get("volume_fp"),
            ])

if __name__ == "__main__":
    markets = collect_all_tracked_markets()
    save_snapshot(markets)
    print(f"Saved {len(markets)} markets to {CSV_FILE}")
