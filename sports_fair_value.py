import os
import re
from datetime import datetime

import requests
from dotenv import load_dotenv

load_dotenv()

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
ODDS_BASE_URL = "https://api.theoddsapi.com"
ODDS_API_KEY = os.environ.get("ODDS_API_KEY")

MAX_MATCH_HOURS = 3  # how close a Kalshi game time and an Odds API game time must be to call it the same game

# Kalshi's short city/team labels (yes_sub_title / no_sub_title) -> Odds API's
# full team names. Built explicitly rather than guessed/fuzzy-matched, since
# Kalshi already disambiguates multi-team cities itself (e.g. "Los Angeles D"
# vs "Los Angeles A"), and a wrong silent match would produce a nonsense edge.
MLB_TEAM_MAP = {
    "Seattle": "Seattle Mariners",
    "Houston": "Houston Astros",
    "Colorado": "Colorado Rockies",
    "San Francisco": "San Francisco Giants",
    "Milwaukee": "Milwaukee Brewers",
    "Los Angeles D": "Los Angeles Dodgers",
    "Texas": "Texas Rangers",
    "A's": "Athletics",
    "Kansas City": "Kansas City Royals",
    "Los Angeles A": "Los Angeles Angels",
    "St. Louis": "St. Louis Cardinals",
    "Chicago C": "Chicago Cubs",
    "Philadelphia": "Philadelphia Phillies",
    "Minnesota": "Minnesota Twins",
    "Boston": "Boston Red Sox",
    "Pittsburgh": "Pittsburgh Pirates",
    "Miami": "Miami Marlins",
    "Cincinnati": "Cincinnati Reds",
    "San Diego": "San Diego Padres",
    "Cleveland": "Cleveland Guardians",
    "New York Y": "New York Yankees",
    "Toronto": "Toronto Blue Jays",
    "Washington": "Washington Nationals",
    "New York M": "New York Mets",
    "Arizona": "Arizona Diamondbacks",
    "Atlanta": "Atlanta Braves",
    "Chicago WS": "Chicago White Sox",
    "Detroit": "Detroit Tigers",
    "Baltimore": "Baltimore Orioles",
    "Tampa Bay": "Tampa Bay Rays",
}


def get_kalshi_mlb_markets():
    response = requests.get(f"{KALSHI_BASE_URL}/markets", params={"series_ticker": "KXMLBGAME", "status": "open"})
    response.raise_for_status()
    return response.json()["markets"]


def get_odds_mlb_games():
    response = requests.get(
        f"{ODDS_BASE_URL}/odds",
        params={"sport_key": "baseball_mlb", "markets": "h2h", "oddsFormat": "american", "regions": "us"},
        headers={"x-api-key": ODDS_API_KEY},
    )
    response.raise_for_status()
    return response.json()["data"]


def american_to_prob(price):
    if price > 0:
        return 100 / (price + 100)
    return -price / (-price + 100)


def consensus_fair_prob(game, team_name):
    """Average the no-vig (de-margined) implied probability for team_name
    across every book quoting this game -- a single book's price includes
    its own profit margin, so this is a more robust fair-value estimate."""
    probs = []
    for book in game["books"]:
        if book["market"] != "h2h":
            continue
        outcomes = {o["name"]: o["price"] for o in book["outcomes"]}
        if team_name not in outcomes:
            continue
        others = [t for t in outcomes if t != team_name]
        if not others:
            continue
        p_team = american_to_prob(outcomes[team_name])
        p_other = american_to_prob(outcomes[others[0]])
        probs.append(p_team / (p_team + p_other))  # normalize away the vig
    if not probs:
        return None, 0
    return sum(probs) / len(probs), len(probs)


def parse_matchup(title, team):
    """Return (team, opponent) using yes_sub_title as the authoritative team
    for *this* contract -- title alone doesn't say which side a given
    ticker (-MIN vs -PHI) represents, only who's playing."""
    match = re.match(r"^(.+) vs (.+) Winner\?$", title)
    if not match:
        return None, None
    a, b = match.group(1), match.group(2)
    if team == a:
        return a, b
    if team == b:
        return b, a
    return None, None


def find_odds_game(team_full, opponent_full, kalshi_time, odds_games):
    for game in odds_games:
        teams = {game["home_team"], game["away_team"]}
        if team_full not in teams or opponent_full not in teams:
            continue
        game_time = datetime.fromisoformat(game["start_time"].replace("Z", "+00:00"))
        if abs((game_time - kalshi_time).total_seconds()) <= MAX_MATCH_HOURS * 3600:
            return game
    return None


def to_float_or_none(value):
    if value in (None, "", "None"):
        return None
    return float(value)


def build_comparisons():
    markets = get_kalshi_mlb_markets()
    odds_games = get_odds_mlb_games()

    rows = []
    unmatched = 0
    for m in markets:
        team, opponent = parse_matchup(m["title"], m["yes_sub_title"])
        if team is None:
            print(f"  Could not determine team for '{m['title']}' (yes_sub_title={m['yes_sub_title']!r}) -- skipping")
            continue
        team_full = MLB_TEAM_MAP.get(team)
        opponent_full = MLB_TEAM_MAP.get(opponent)
        if team_full is None or opponent_full is None:
            print(f"  Unknown team name in '{m['title']}' -- skipping (check MLB_TEAM_MAP)")
            continue

        kalshi_time = datetime.fromisoformat(m["occurrence_datetime"].replace("Z", "+00:00"))
        game = find_odds_game(team_full, opponent_full, kalshi_time, odds_games)
        if game is None:
            unmatched += 1
            continue

        fair_prob, num_books = consensus_fair_prob(game, team_full)
        if fair_prob is None:
            continue

        yes_bid = to_float_or_none(m.get("yes_bid_dollars"))
        yes_ask = to_float_or_none(m.get("yes_ask_dollars"))
        if yes_bid is None or yes_ask is None:
            continue
        market_mid = (yes_bid + yes_ask) / 2

        rows.append({
            "ticker": m["ticker"],
            "team": team_full,
            "opponent": opponent_full,
            "fair_prob": fair_prob,
            "num_books": num_books,
            "yes_bid": yes_bid,
            "yes_ask": yes_ask,
            "market_mid": market_mid,
            "edge": fair_prob - market_mid,
        })

    rows.sort(key=lambda r: abs(r["edge"]), reverse=True)
    return rows, unmatched


if __name__ == "__main__":
    if not ODDS_API_KEY:
        raise SystemExit("ODDS_API_KEY not set in .env")

    comparisons, unmatched = build_comparisons()
    print(f"Matched {len(comparisons)} Kalshi markets to odds-API games ({unmatched} Kalshi markets had no odds match -- likely too far out for the free tier's game list)\n")

    if comparisons:
        print(f"{'Ticker':<32} {'Team':<22} {'Books':>5} {'FairP':>6} {'MktMid':>7} {'Edge':>7}")
        for r in comparisons:
            print(
                f"{r['ticker']:<32} {r['team']:<22} {r['num_books']:>5} "
                f"{r['fair_prob']:>6.2f} {r['market_mid']:>7.2f} {r['edge']:>+7.2f}"
            )
