import csv
import os
from datetime import datetime, timezone

import weather_fair_value
import sports_fair_value

PAPER_TRADES_FILE = "paper_trades.csv"
EDGE_THRESHOLD = 0.05  # minimum edge (vs actual ask price, not mid) to "trade"
POSITION_SIZE_DOLLARS = 10  # fixed notional per paper trade -- simplest possible sizing


def weather_comparisons_to_opportunities(comparisons):
    """Normalize weather_fair_value comparisons that were ALREADY fetched
    elsewhere (e.g. by log_weather_edge.py), instead of fetching again here."""
    for c in comparisons:
        yield {
            "source": "weather",
            "ticker": c["ticker"],
            "description": f"{c['ticker']} {c['description']}",
            "model_prob": c["model_prob"],
            "yes_bid": c["yes_bid"],
            "yes_ask": c["yes_ask"],
        }


def get_weather_opportunities():
    """Standalone fetch, for manual/ad-hoc runs only. Cron should use
    weather_comparisons_to_opportunities() with data log_weather_edge.py
    already fetched instead, to avoid a redundant fetch+compute."""
    comparisons = weather_fair_value.build_all_cities_comparisons()
    yield from weather_comparisons_to_opportunities(comparisons)


def sports_comparisons_to_opportunities(comparisons):
    """Normalize sports_fair_value comparisons that were ALREADY fetched
    elsewhere (e.g. by log_sports_edge.py), instead of calling the odds API
    again here -- the free tier is only 25 requests/day, and log_sports_edge
    already uses one call/hour, so a second independent fetch would double
    that budget for no reason."""
    for c in comparisons:
        yield {
            "source": "sports",
            "ticker": c["ticker"],
            "description": f"{c['team']} vs {c['opponent']}",
            "model_prob": c["fair_prob"],
            "yes_bid": c["yes_bid"],
            "yes_ask": c["yes_ask"],
        }


def get_sports_opportunities():
    """Standalone fetch, for manual/ad-hoc runs only -- costs one odds-API
    request. Cron should use sports_comparisons_to_opportunities() with data
    log_sports_edge.py already fetched instead."""
    comparisons, _ = sports_fair_value.build_comparisons()
    yield from sports_comparisons_to_opportunities(comparisons)


def best_side(opp):
    """Compare the model's probability to the actual price you'd pay (the
    ask), not the mid -- mid is fine for exploratory display, but a real
    trade decision has to use the price you'd actually get filled at."""
    yes_edge = opp["model_prob"] - opp["yes_ask"]
    no_ask = 1 - opp["yes_bid"]  # Yes + No = $1 on Kalshi
    no_edge = (1 - opp["model_prob"]) - no_ask

    if yes_edge >= no_edge:
        return "yes", opp["yes_ask"], yes_edge
    return "no", no_ask, no_edge


def load_open_tickers():
    if not os.path.isfile(PAPER_TRADES_FILE):
        return set()
    open_tickers = set()
    with open(PAPER_TRADES_FILE, newline="") as f:
        for row in csv.DictReader(f):
            if row["status"] == "open":
                open_tickers.add(row["ticker"])
    return open_tickers


def log_trade(writer, opp, side, entry_price, edge):
    contracts = round(POSITION_SIZE_DOLLARS / entry_price, 2) if entry_price > 0 else 0
    writer.writerow([
        datetime.now(timezone.utc).isoformat(),
        opp["source"],
        opp["ticker"],
        opp["description"],
        side,
        entry_price,
        edge,
        POSITION_SIZE_DOLLARS,
        contracts,
        "open",
        "",  # result, filled in once resolved
        "",  # pnl, filled in once resolved
    ])


def evaluate_and_log(opportunity_iterables):
    already_open = load_open_tickers()
    file_exists = os.path.isfile(PAPER_TRADES_FILE)
    new_trades = 0

    with open(PAPER_TRADES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "opened_at", "source", "ticker", "description", "side",
                "entry_price", "edge_at_entry", "position_size_dollars",
                "contracts", "status", "result", "pnl",
            ])

        for opportunities in opportunity_iterables:
            for opp in opportunities:
                if opp["ticker"] in already_open:
                    continue  # already have an open paper position here
                if opp["yes_bid"] is None or opp["yes_ask"] is None:
                    continue

                side, entry_price, edge = best_side(opp)
                if edge < EDGE_THRESHOLD:
                    continue

                log_trade(writer, opp, side, entry_price, edge)
                already_open.add(opp["ticker"])
                new_trades += 1
                print(f"  OPENED {opp['source']}/{side}: {opp['description']} @ {entry_price:.2f} (edge {edge:+.2f})")

    return new_trades


def run_weather_only():
    """Cheap, no odds-API cost -- safe to run frequently via cron."""
    return evaluate_and_log([get_weather_opportunities()])


def run_all():
    """Standalone/manual use only -- costs one odds-API request for sports."""
    return evaluate_and_log([get_weather_opportunities(), get_sports_opportunities()])


if __name__ == "__main__":
    import sys

    if "--weather-only" in sys.argv:
        count = run_weather_only()
    else:
        count = run_all()
    print(f"\n{count} new paper trade(s) opened, logged to {PAPER_TRADES_FILE}")
