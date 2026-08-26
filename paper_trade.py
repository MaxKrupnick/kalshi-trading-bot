import csv
import os
from collections import defaultdict
from datetime import datetime, timezone

import weather_fair_value
import sports_fair_value
import momentum_signal

PAPER_TRADES_FILE = "paper_trades.csv"
EDGE_THRESHOLD = 0.05  # minimum edge (vs actual ask price, not mid) to "trade"

# Don't take a position priced below this. Guardrail, not a strategy choice:
# the first ~350 resolved paper trades lost -$419 almost entirely on weather
# longshots that entered under $0.15 (79 trades, 3% actual win rate vs ~6%
# implied by what was paid). At those prices the payout leverage is ~6:1, so
# the model's calibration error in the tails swamps its estimated edge and the
# expected value goes negative even though the "edge" screen passes. The real
# fix is recalibrating the forecast sigma (roadmap step 4) -- once that lands
# and post-fix trades show the tails are trustworthy, this floor can be
# lowered or removed.
MIN_ENTRY_PRICE = 0.15

# Series whose contracts are a 2-outcome market (one game, two teams), where
# "team A yes" and "team B no" are the same directional bet under different
# tickers. Keyed off the series rather than the trading source, because more
# than one strategy can trade the same underlying market -- the momentum arm
# trades these too, and hit the identical redundancy the sports fair-value
# arm did before it was fixed.
TWO_OUTCOME_SERIES = ("KXMLBGAME", "KXNFLGAME", "KXWNBAGAME")

# Edge-weighted position sizing: $5 at the minimum qualifying edge, scaling
# linearly up to a $20 cap so one high-conviction trade can't dominate.
MIN_POSITION_DOLLARS = 5
MAX_POSITION_DOLLARS = 20

# Cap total exposure per underlying event (e.g. all of Boston's Aug-14 strike
# markets share one real event: what the actual high temperature turns out to
# be). Multiple bucket bets on the same city/game aren't independent -- they
# all win or lose together off a single draw -- so sizing them as if they
# were N separate risks understates real concentration. Found the gap when 5
# simultaneous Boston positions ($50 total) turned out to be 5 correlated
# bets on one number, not 5 diversified ones.
MAX_EXPOSURE_PER_EVENT_DOLLARS = 30


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


def get_momentum_opportunities():
    """The control arm -- reads only already-collected market_data.csv, so
    it costs no API calls and can run as often as the collector does."""
    for c in momentum_signal.build_comparisons():
        yield {
            "source": "momentum",
            "ticker": c["ticker"],
            "description": c["description"],
            "model_prob": c["model_prob"],
            "yes_bid": c["yes_bid"],
            "yes_ask": c["yes_ask"],
        }


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


def event_key(ticker):
    """The shared underlying event for a contract ticker, e.g.
    "KXHIGHNY-26AUG14-B85.5" -> "KXHIGHNY-26AUG14". Kalshi's ticker format is
    consistently event_ticker + "-" + contract-specific suffix, so this
    groups all contracts that resolve off the same single real-world draw
    (same city+day for weather, same game for sports)."""
    return ticker.rsplit("-", 1)[0]


def position_size_for_edge(edge):
    if edge <= EDGE_THRESHOLD:
        return MIN_POSITION_DOLLARS
    # linear ramp: threshold -> MIN, 4x threshold -> MAX, capped beyond that
    scale = edge / EDGE_THRESHOLD
    size = MIN_POSITION_DOLLARS * scale
    return round(min(size, MAX_POSITION_DOLLARS), 2)


def is_two_outcome(ticker):
    return ticker.startswith(TWO_OUTCOME_SERIES)


def load_open_state():
    """All state is keyed by (source, ...) so each strategy is tracked
    independently. That isolation is deliberate: these strategies are being
    compared against each other, so one arm consuming another's exposure
    budget -- or blocking it from a ticker it independently wants -- would
    contaminate the comparison rather than just managing risk. No real
    capital is at stake in paper trading, so there's no reason to share a
    budget across arms; a single combined cap would only make sense once
    real money is on the line.

    Returns (set of (source, ticker) with an open position, dict of
    (source, event_key) -> dollars committed, set of (source, event_key)
    that already have an open position in a 2-outcome game market)."""
    open_positions = set()
    exposure_by_event = defaultdict(float)
    game_events_taken = set()
    if not os.path.isfile(PAPER_TRADES_FILE):
        return open_positions, exposure_by_event, game_events_taken

    with open(PAPER_TRADES_FILE, newline="") as f:
        for row in csv.DictReader(f):
            if row["status"] == "open":
                source = row["source"]
                open_positions.add((source, row["ticker"]))
                key = (source, event_key(row["ticker"]))
                exposure_by_event[key] += float(row["position_size_dollars"])
                if is_two_outcome(row["ticker"]):
                    game_events_taken.add(key)
    return open_positions, exposure_by_event, game_events_taken


def log_trade(writer, opp, side, entry_price, edge, position_size):
    contracts = round(position_size / entry_price, 2) if entry_price > 0 else 0
    writer.writerow([
        datetime.now(timezone.utc).isoformat(),
        opp["source"],
        opp["ticker"],
        opp["description"],
        side,
        entry_price,
        edge,
        position_size,
        contracts,
        "open",
        "",  # result, filled in once resolved
        "",  # pnl, filled in once resolved
    ])


def evaluate_and_log(opportunity_iterables):
    open_positions, exposure_by_event, game_events_taken = load_open_state()
    file_exists = os.path.isfile(PAPER_TRADES_FILE)
    new_trades = 0

    # Collect and rank all qualifying candidates by edge first, so when
    # several compete for the same event's exposure budget, the strongest
    # edge gets priority rather than whichever happened to be listed first.
    candidates = []
    for opportunities in opportunity_iterables:
        for opp in opportunities:
            if (opp["source"], opp["ticker"]) in open_positions:
                continue  # this strategy already has an open position here
            if opp["yes_bid"] is None or opp["yes_ask"] is None:
                continue

            side, entry_price, edge = best_side(opp)
            if edge < EDGE_THRESHOLD:
                continue
            if entry_price < MIN_ENTRY_PRICE:
                continue  # see MIN_ENTRY_PRICE -- edge estimate isn't reliable this deep in the tail
            candidates.append((edge, opp, side, entry_price))

    candidates.sort(key=lambda c: c[0], reverse=True)

    with open(PAPER_TRADES_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow([
                "opened_at", "source", "ticker", "description", "side",
                "entry_price", "edge_at_entry", "position_size_dollars",
                "contracts", "status", "result", "pnl",
            ])

        for edge, opp, side, entry_price in candidates:
            key = (opp["source"], event_key(opp["ticker"]))

            # A 2-team moneyline only has 2 possible outcomes, so "team A
            # yes" and "team B no" are the same directional bet, not
            # diversification -- taking both just doubles one view under two
            # ticker labels. Weather doesn't have this problem: its multiple
            # strike buckets are genuinely different, non-redundant views on
            # the distribution, so only game markets are restricted to one
            # position per event.
            if is_two_outcome(opp["ticker"]) and key in game_events_taken:
                continue

            remaining_budget = MAX_EXPOSURE_PER_EVENT_DOLLARS - exposure_by_event[key]
            if remaining_budget <= 0:
                continue  # this event's exposure cap is already full

            position_size = min(position_size_for_edge(edge), remaining_budget)

            log_trade(writer, opp, side, entry_price, edge, position_size)
            open_positions.add((opp["source"], opp["ticker"]))
            exposure_by_event[key] += position_size
            if is_two_outcome(opp["ticker"]):
                game_events_taken.add(key)
            new_trades += 1
            print(f"  OPENED {opp['source']}/{side}: {opp['description']} @ {entry_price:.2f} "
                  f"(edge {edge:+.2f}, size ${position_size:.2f})")

    return new_trades


def run_weather_only():
    """Cheap, no odds-API cost -- safe to run frequently via cron."""
    return evaluate_and_log([get_weather_opportunities()])


def run_momentum_only():
    """Control arm -- reads only local market_data.csv, costs no API calls."""
    return evaluate_and_log([get_momentum_opportunities()])


def run_all():
    """Standalone/manual use only -- costs one odds-API request for sports."""
    return evaluate_and_log([
        get_weather_opportunities(),
        get_sports_opportunities(),
        get_momentum_opportunities(),
    ])


if __name__ == "__main__":
    import sys

    if "--weather-only" in sys.argv:
        count = run_weather_only()
    elif "--momentum-only" in sys.argv:
        count = run_momentum_only()
    else:
        count = run_all()
    print(f"\n{count} new paper trade(s) opened, logged to {PAPER_TRADES_FILE}")
