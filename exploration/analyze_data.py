import csv
from collections import Counter

CSV_FILE = "market_data.csv"

def count_rows_per_ticker():
    counts = Counter()
    with open(CSV_FILE, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            counts[row["ticker"]] += 1
    return counts

if __name__ == "__main__":
    counts = count_rows_per_ticker()
    print(f"Total unique tickers: {len(counts)}")
    print("\nTop 10 most-logged markets:\n")
    for ticker, count in counts.most_common(10):
        print(f"{count:4d} rows | {ticker}")