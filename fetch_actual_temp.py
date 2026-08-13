from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

STATION_URL = "https://api.weather.gov/stations/KNYC/observations"
NYC_TZ = ZoneInfo("America/New_York")


def celsius_to_fahrenheit(c):
    return c * 9 / 5 + 32


def get_actual_high(target_date, max_retries=5):
    """Actual recorded high (F) for target_date, a date in NYC local time.

    Uses raw station observations (max of hourly readings), which is a
    close proxy for NWS's official Daily Climatological Report high --
    the two can differ slightly due to rounding/methodology, but this is
    good enough to measure forecast error against.
    """
    start_local = datetime.combine(target_date, time.min, tzinfo=NYC_TZ)
    end_local = start_local + timedelta(days=1)
    params = {
        "start": start_local.astimezone(ZoneInfo("UTC")).isoformat(),
        "end": end_local.astimezone(ZoneInfo("UTC")).isoformat(),
    }

    for attempt in range(max_retries):
        response = requests.get(
            STATION_URL, params=params,
            headers={"User-Agent": "kalshi-trading-bot (personal project)"},
        )
        if response.status_code == 200:
            break
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 2 ** attempt))
            print(f"  Rate limited fetching observations, waiting {wait}s")
            import time as time_module
            time_module.sleep(wait)
            continue
        response.raise_for_status()
    else:
        raise RuntimeError(f"Giving up on {target_date} after {max_retries} rate-limit retries")

    observations = response.json().get("features", [])
    temps_c = [
        o["properties"]["temperature"]["value"]
        for o in observations
        if o["properties"]["temperature"]["value"] is not None
    ]
    if not temps_c:
        return None
    return round(celsius_to_fahrenheit(max(temps_c)), 1)


if __name__ == "__main__":
    import sys
    from datetime import date

    target = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today() - timedelta(days=1)
    high = get_actual_high(target)
    if high is None:
        print(f"No observations found for {target}")
    else:
        print(f"Actual recorded high for {target} (Central Park): {high}F")
