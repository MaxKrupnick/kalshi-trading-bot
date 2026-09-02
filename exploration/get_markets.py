import requests

BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

def get_markets(limit=5):
    response = requests.get(f"{BASE_URL}/markets", params={"limit": limit})
    response.raise_for_status()  # will throw an error if something went wrong
    data = response.json()
    return data["markets"]

if __name__ == "__main__":
    markets = get_markets()
    for market in markets:
        print(f"{market['ticker']}: {market['title']}")
        print(f"  Yes price: {market.get('yes_bid')} | No price: {market.get('no_bid')}")
        print()