import csv
import math
from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from fetch_actual_temp import get_actual_high
from weather_fair_value import CITIES, SIGMA_AT_12H_F, SIGMA_AT_48H_F, SIGMA_AT_120H_F

FORECAST_LOG_FILE = "forecast_log.csv"

# Same breakpoints as weather_fair_value.forecast_sigma_f, so the measured
# curve lines up against the current proxy curve bucket-for-bucket.
BUCKETS = [
    ("<=12h", 0, 12),
    ("12-48h", 12, 48),
    ("48-120h", 48, 120),
    (">120h", 120, float("inf")),
]
PROXY_SIGMA = {"<=12h": SIGMA_AT_12H_F, "12-48h": SIGMA_AT_48H_F, "48-120h": SIGMA_AT_48H_F, ">120h": SIGMA_AT_120H_F}


def load_deduped_forecasts():
    """One row per (city, target_date, forecast_issued_at) -- forecast_log.csv
    is logged hourly, but NWS doesn't update that often, so consecutive
    logged_at ticks frequently carry the identical forecast_issued_at.
    Counting each repeat as an independent data point would overweight
    whichever forecasts happened to sit unchanged the longest."""
    seen = set()
    rows = []
    with open(FORECAST_LOG_FILE, newline="") as f:
        for r in csv.DictReader(f):
            city = r.get("city", "NYC")  # pre-migration rows predate the city column and are all NYC
            key = (city, r["target_date"], r["forecast_issued_at"])
            if key in seen:
                continue
            seen.add(key)
            r["city"] = city
            rows.append(r)
    return rows


def lead_hours_for(city, target_date_str, forecast_issued_at_str):
    """Approximates the daytime period's start as noon local time (in that
    city's own timezone) on target_date -- the exact period start isn't
    persisted in forecast_log.csv, only the date, and NWS daytime periods
    (afternoon/day) cluster close to midday. Coarse, but fine for bucketing
    into the wide ranges above."""
    tz = ZoneInfo(CITIES[city]["tz"])
    target = date.fromisoformat(target_date_str)
    target_noon = datetime.combine(target, time(12, 0), tzinfo=tz)
    issued = datetime.fromisoformat(forecast_issued_at_str)
    return (target_noon - issued).total_seconds() / 3600


def bucket_for(lead_hours):
    for name, lo, hi in BUCKETS:
        if lo <= lead_hours < hi:
            return name
    return None


def main():
    rows = load_deduped_forecasts()
    today = date.today()

    actual_high_cache = {}
    errors_by_bucket = defaultdict(list)
    errors_by_city = defaultdict(list)
    skipped_future, skipped_no_actual = 0, 0

    unique_city_dates = sorted({(r["city"], r["target_date"]) for r in rows})
    print(f"{len(rows)} deduped forecast snapshots across {len(unique_city_dates)} (city, date) pairs "
          f"-- fetching actual highs...")

    for city, target_date_str in unique_city_dates:
        target = date.fromisoformat(target_date_str)
        if target >= today:
            continue  # can't score a forecast against a high that hasn't happened (or is still in progress) yet
        c = CITIES[city]
        actual_high_cache[(city, target_date_str)] = get_actual_high(target, station=c["station"], tz=ZoneInfo(c["tz"]))

    for r in rows:
        city = r["city"]
        target_date_str = r["target_date"]
        if date.fromisoformat(target_date_str) >= today:
            skipped_future += 1
            continue
        actual = actual_high_cache.get((city, target_date_str))
        if actual is None:
            skipped_no_actual += 1
            continue

        lead_hours = lead_hours_for(city, target_date_str, r["forecast_issued_at"])
        if lead_hours < 0:
            continue  # forecast logged after its own target period started -- stale row, skip
        bucket = bucket_for(lead_hours)
        error = actual - float(r["forecast_high_f"])
        errors_by_bucket[bucket].append(error)
        errors_by_city[city].append(error)

    print(f"Skipped {skipped_future} rows (target date not yet resolved), "
          f"{skipped_no_actual} rows (no NWS observation found for that date)\n")

    print(f"{'Lead time':<10} {'n':>4} {'Measured RMSE':>14} {'Mean error':>11} {'Current proxy':>14}")
    for name, _, _ in BUCKETS:
        errors = errors_by_bucket.get(name, [])
        if not errors:
            print(f"{name:<10} {'0':>4} {'--':>14} {'--':>11} {PROXY_SIGMA[name]:>14.1f}")
            continue
        rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))
        mean_err = sum(errors) / len(errors)
        print(f"{name:<10} {len(errors):>4} {rmse:>14.2f} {mean_err:>+11.2f} {PROXY_SIGMA[name]:>14.1f}")

    print(f"\n{'City':<6} {'n':>4} {'RMSE':>8} {'Mean error':>11}")
    for city in CITIES:
        errors = errors_by_city.get(city, [])
        if not errors:
            print(f"{city:<6} {'0':>4} {'--':>8} {'--':>11}")
            continue
        rmse = math.sqrt(sum(e ** 2 for e in errors) / len(errors))
        mean_err = sum(errors) / len(errors)
        print(f"{city:<6} {len(errors):>4} {rmse:>8.2f} {mean_err:>+11.2f}")

    print("\nMean error far from 0 would suggest a consistent bias (forecast running hot/cold), "
          "not just noise -- worth a second look if so. Per-city n is still small for the 5 cities "
          "added to log_forecast.py this session; NYC has the deepest history (logging since 2026-08-11).")


if __name__ == "__main__":
    main()
