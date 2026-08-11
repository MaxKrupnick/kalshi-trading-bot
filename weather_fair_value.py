import math
import re
from datetime import datetime, timezone

import requests

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# NWS grid point covering Central Park, NYC (office OKX, grid 34,45).
# Looked up once via https://api.weather.gov/points/40.7829,-73.9654 --
# NWS grid assignments essentially never change, so it's fine to hardcode.
NWS_FORECAST_URL = "https://api.weather.gov/gridpoints/OKX/34,45/forecast"

# Forecast-error std dev (degrees F), by lead time, anchored to NWS's own
# published NDFD verification: RMSE ~3C (5.4F) under 48h out, >4C (7.2F)
# beyond 120h out. Linearly interpolated between; still a rough proxy for a
# true std dev (RMSE, not calibrated per-station/per-season) until we log our
# own forecast-vs-actual data and replace this with a measured value.
SIGMA_AT_48H_F = 5.4
SIGMA_AT_120H_F = 7.2


def forecast_sigma_f(lead_hours):
    if lead_hours <= 48:
        return SIGMA_AT_48H_F
    if lead_hours >= 120:
        return SIGMA_AT_120H_F
    fraction = (lead_hours - 48) / (120 - 48)
    return SIGMA_AT_48H_F + fraction * (SIGMA_AT_120H_F - SIGMA_AT_48H_F)


def normal_cdf(x, mean, sigma):
    return 0.5 * (1 + math.erf((x - mean) / (sigma * math.sqrt(2))))


def get_kxhighny_markets():
    response = requests.get(
        f"{KALSHI_BASE_URL}/markets",
        params={"series_ticker": "KXHIGHNY", "status": "open"},
    )
    response.raise_for_status()
    markets = response.json()["markets"]
    # only "above X degrees" markets for now -- range/bucket markets need different math
    return [m for m in markets if m.get("strike_type") == "greater"]


def get_nws_forecast_periods():
    response = requests.get(
        NWS_FORECAST_URL,
        headers={"User-Agent": "kalshi-trading-bot (personal project)"},
    )
    response.raise_for_status()
    return response.json()["properties"]["periods"]


def parse_event_date(event_ticker):
    # e.g. "KXHIGHNY-26AUG12" -> date(2026, 8, 12)
    match = re.search(r"-(\d{2})([A-Z]{3})(\d{2})$", event_ticker)
    if not match:
        return None
    year, month_abbr, day = match.groups()
    return datetime.strptime(f"20{year}-{month_abbr}-{day}", "%Y-%b-%d").date()


def find_daytime_period(periods, target_date):
    for period in periods:
        start = datetime.fromisoformat(period["startTime"]).date()
        if start == target_date and period["isDaytime"]:
            return period
    return None


def model_probability(forecast_high, floor_strike, sigma):
    # market resolves YES if actual high > floor_strike (integer degrees),
    # so use floor_strike + 0.5 as the continuity-corrected cutoff
    return 1 - normal_cdf(floor_strike + 0.5, forecast_high, sigma)


def to_float_or_none(value):
    if value in (None, "", "None"):
        return None
    return float(value)


def build_comparisons(markets, forecast_periods, now=None):
    now = now or datetime.now(timezone.utc)
    rows = []
    for m in markets:
        event_date = parse_event_date(m["event_ticker"])
        period = find_daytime_period(forecast_periods, event_date) if event_date else None
        if period is None:
            continue  # no forecast this far out yet, or date parsing failed

        forecast_high = period["temperature"]
        lead_hours = (datetime.fromisoformat(period["startTime"]) - now).total_seconds() / 3600
        sigma = forecast_sigma_f(max(lead_hours, 0))

        yes_bid = to_float_or_none(m.get("yes_bid_dollars"))
        yes_ask = to_float_or_none(m.get("yes_ask_dollars"))
        if yes_bid is None or yes_ask is None:
            continue  # unquoted market, no meaningful market price to compare against

        market_mid = (yes_bid + yes_ask) / 2
        model_prob = model_probability(forecast_high, m["floor_strike"], sigma)

        rows.append({
            "ticker": m["ticker"],
            "event_date": event_date,
            "floor_strike": m["floor_strike"],
            "forecast_high": forecast_high,
            "sigma": round(sigma, 1),
            "model_prob": model_prob,
            "market_mid": market_mid,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "edge": model_prob - market_mid,
        })

    rows.sort(key=lambda r: abs(r["edge"]), reverse=True)
    return rows


if __name__ == "__main__":
    markets = get_kxhighny_markets()
    forecast_periods = get_nws_forecast_periods()
    comparisons = build_comparisons(markets, forecast_periods)

    if not comparisons:
        print("No comparable markets right now (either out of NWS forecast range or unquoted).")
    else:
        print("Sigma = lead-time-scaled forecast uncertainty, anchored to NWS's published RMSE "
              f"({SIGMA_AT_48H_F}F under 48h, {SIGMA_AT_120H_F}F beyond 120h) -- still a proxy, not yet\n"
              "measured against this pipeline's own forecast-vs-actual history.\n")
        print(f"{'Ticker':<28} {'Date':<12} {'Strike':>7} {'FcstHigh':>9} {'Sigma':>6} {'ModelP':>7} {'MktMid':>7} {'Edge':>7}")
        for r in comparisons:
            print(
                f"{r['ticker']:<28} {str(r['event_date']):<12} {r['floor_strike']:>7} "
                f"{r['forecast_high']:>9} {r['sigma']:>6} {r['model_prob']:>7.2f} {r['market_mid']:>7.2f} {r['edge']:>+7.2f}"
            )
