from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import requests

NYC_TZ = ZoneInfo("America/New_York")  # kept as the default/original behavior; each city uses its own tz below


def celsius_to_fahrenheit(c):
    return c * 9 / 5 + 32


def get_actual_high(target_date, station="KNYC", tz=NYC_TZ, max_retries=5):
    """Actual recorded high (F) for target_date, a date in the given
    station's local time (defaults to NYC/KNYC, the original single-city
    behavior).

    Uses raw station observations (max of hourly readings), which is a
    close proxy for NWS's official Daily Climatological Report high --
    the two can differ slightly due to rounding/methodology, but this is
    good enough to measure forecast error against.

    NOTE (confirmed 2026-08-14): Kalshi's actual settlement source for
    KXHIGHNY is "The Weather Company" via weather.com/kalshi's Daily
    Climate Report for Central Park -- not raw NWS station observations
    directly. Still the same underlying station/location, so the core
    forecast-vs-price strategy is unaffected, but this proxy has a real
    (not just theoretical) gap vs. Kalshi's true settlement value. Worth
    revisiting if sigma calibration numbers look off later.
    """
    station_url = f"https://api.weather.gov/stations/{station}/observations"
    start_local = datetime.combine(target_date, time.min, tzinfo=tz)
    end_local = start_local + timedelta(days=1)
    params = {
        "start": start_local.astimezone(ZoneInfo("UTC")).isoformat(),
        "end": end_local.astimezone(ZoneInfo("UTC")).isoformat(),
    }

    for attempt in range(max_retries):
        response = requests.get(
            station_url, params=params,
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
