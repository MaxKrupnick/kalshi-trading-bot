import csv
import os
from datetime import datetime, timezone

import requests

NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/34,45/forecast"
LOG_FILE = "forecast_log.csv"


def get_forecast():
    response = requests.get(
        NWS_FORECAST_URL,
        headers={"User-Agent": "kalshi-trading-bot (personal project)"},
    )
    response.raise_for_status()
    return response.json()["properties"]


def log_daytime_periods(properties):
    logged_at = datetime.now(timezone.utc).isoformat()
    forecast_issued_at = properties["updateTime"]
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "logged_at", "forecast_issued_at", "target_date",
                "period_name", "forecast_high_f",
            ])
        count = 0
        for period in properties["periods"]:
            if not period["isDaytime"]:
                continue
            target_date = datetime.fromisoformat(period["startTime"]).date().isoformat()
            writer.writerow([
                logged_at,
                forecast_issued_at,
                target_date,
                period["name"],
                period["temperature"],
            ])
            count += 1
        return count


if __name__ == "__main__":
    properties = get_forecast()
    count = log_daytime_periods(properties)
    print(f"Logged {count} daytime forecast periods to {LOG_FILE}")
