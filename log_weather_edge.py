import csv
import os
from datetime import datetime, timezone

import weather_fair_value
from paper_trade import evaluate_and_log, weather_comparisons_to_opportunities

LOG_FILE = "weather_edge_log.csv"


def log_comparisons():
    markets = weather_fair_value.get_kxhighny_markets()
    forecast_periods = weather_fair_value.get_nws_forecast_periods()
    comparisons = weather_fair_value.build_comparisons(markets, forecast_periods)

    logged_at = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "logged_at", "ticker", "strike_type", "floor_strike", "cap_strike",
                "description", "forecast_high", "sigma", "model_prob", "market_mid", "edge",
            ])
        for r in comparisons:
            writer.writerow([
                logged_at, r["ticker"], r["strike_type"], r["floor_strike"], r["cap_strike"],
                r["description"], r["forecast_high"], r["sigma"], r["model_prob"], r["market_mid"], r["edge"],
            ])

    # Reuse this same fetch for paper trading instead of a second, redundant
    # fetch+compute -- same pattern as log_sports_edge.py.
    new_trades = evaluate_and_log([weather_comparisons_to_opportunities(comparisons)])

    return len(comparisons), new_trades


if __name__ == "__main__":
    count, new_trades = log_comparisons()
    print(f"Logged {count} weather comparisons to {LOG_FILE}, {new_trades} new paper trade(s)")
