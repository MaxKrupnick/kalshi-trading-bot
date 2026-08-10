import requests
import csv
import os
from datetime import datetime, timezone

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
CSV_FILE = "market_data.csv"

def get_markets(limit=100):
    response = requests.get(f"{BASE_URL}/markets", params={"limit": limit, "status": "open"})
    response.raise_for_status()
    return response.json()["markets"]

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
                m.get("yes_bid"),
                m.get("yes_ask"),
                m.get("no_bid"),
                m.get("no_ask"),
                m.get("volume"),
            ])

if __name__ == "__main__":
    markets = get_markets()
    save_snapshot(markets)
    print(f"Saved {len(markets)} markets to {CSV_FILE}")