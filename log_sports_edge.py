import csv
import os
from datetime import datetime, timezone

from sports_fair_value import build_comparisons

LOG_FILE = "sports_edge_log.csv"


def log_comparisons():
    comparisons, unmatched = build_comparisons()
    logged_at = datetime.now(timezone.utc).isoformat()
    file_exists = os.path.isfile(LOG_FILE)

    with open(LOG_FILE, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(
                ["logged_at", "ticker", "team", "opponent", "fair_prob", "num_books", "market_mid", "edge"]
            )
        for r in comparisons:
            writer.writerow([
                logged_at, r["ticker"], r["team"], r["opponent"],
                r["fair_prob"], r["num_books"], r["market_mid"], r["edge"],
            ])
    return len(comparisons), unmatched


if __name__ == "__main__":
    count, unmatched = log_comparisons()
    print(f"Logged {count} MLB comparisons to {LOG_FILE} ({unmatched} unmatched)")
