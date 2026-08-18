import csv
import os
from datetime import datetime, timezone

import requests

from weather_fair_value import CITIES

LOG_FILE = "forecast_log.csv"
FIELDNAMES = ["logged_at", "city", "forecast_issued_at", "target_date", "period_name", "forecast_high_f"]


def get_forecast_properties(city):
    c = CITIES[city]
    url = f"https://api.weather.gov/gridpoints/{c['office']}/{c['grid_x']},{c['grid_y']}/forecast"
    response = requests.get(url, headers={"User-Agent": "kalshi-trading-bot (personal project)"})
    response.raise_for_status()
    return response.json()["properties"]


def log_daytime_periods(writer, city, properties, logged_at):
    forecast_issued_at = properties["updateTime"]
    count = 0
    for period in properties["periods"]:
        if not period["isDaytime"]:
            continue
        target_date = datetime.fromisoformat(period["startTime"]).date().isoformat()
        writer.writerow([
            logged_at, city, forecast_issued_at, target_date,
            period["name"], period["temperature"],
        ])
        count += 1
    return count


if __name__ == "__main__":
    logged_at = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.isfile(LOG_FILE)
    total = 0

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(FIELDNAMES)
        for city in CITIES:
            properties = get_forecast_properties(city)
            total += log_daytime_periods(writer, city, properties, logged_at)

    print(f"Logged {total} daytime forecast periods across {len(CITIES)} cities to {LOG_FILE}")
