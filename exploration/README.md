# Early exploration

The first things I wrote on this project, kept deliberately rather than deleted.

None of them feed the live pipeline or any published finding — they're where I was learning
the API and getting a feel for the data. `get_markets.py` is the first thing that ever worked:
fifteen lines that fetch five markets and print them.

| Script | What it does |
|---|---|
| `get_markets.py` | First Kalshi API call. Fetch a handful of markets, print them. |
| `analyze_data.py` | Count collected snapshots per ticker — a sanity check that collection was working. |
| `analyze_momentum.py` | First look at how prices move over time. Later became the real `momentum_signal.py`. |
| `analyze_features.py` | First look at spreads and volatility across markets. |

Run from the repo root so they find the CSVs:

```bash
python exploration/analyze_data.py
```
