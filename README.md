# Kalshi Trading Bot

A data-driven trading bot for [Kalshi](https://kalshi.com) prediction markets, built as my
first data science / software project. Goal: combine independent external data sources
(weather forecasts, sports odds, economic data) with Kalshi's live market prices to find
mispriced markets — rather than just guessing from price movement alone.

## Why this approach

Kalshi's price *is* the market's implied probability. Trading on Kalshi's own price
momentum is a weak strategy — these markets are thin and usually already reflect public
information. The real edge comes from having a **better, independently-sourced probability
estimate** than the market, for markets where a good external predictor exists.

**Example:** NYC's Central Park high temperature. NWS publishes a public forecast. If NWS
forecasts an 80% chance of exceeding a strike price but Kalshi is only pricing it at 40%,
that gap is the edge.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Needs a Kalshi API key (`.env`: `KALSHI_API_KEY_ID`) and, for the sports side, a free
[The Odds API](https://theoddsapi.com) key (`.env`: `ODDS_API_KEY`).

## How it works

1. **`collect_data.py`** — pulls live prices for tracked markets from the Kalshi API every
   15 minutes (via cron) and logs snapshots to `market_data.csv`.
2. **`log_forecast.py`** — pulls NWS's forecast for NYC every hour and logs it to
   `forecast_log.csv`, building a history to measure forecast accuracy over time.
3. **`weather_fair_value.py`** — converts NWS's point forecast into a probability estimate
   (using a normal distribution around the forecast, with uncertainty scaled by how far out
   the forecast is), compares it to Kalshi's price, and surfaces the edge.
4. **`analyze_momentum.py` / `analyze_features.py`** — supporting analysis (price movement,
   bid-ask spread, volatility) over the collected data.
5. **`backfill_prices.py`** / **`backfill_settled.py`** — pull ~30 days of real historical
   price data (and, for settled markets, the actual yes/no outcome) from Kalshi's
   `candlesticks` API, so backtesting doesn't have to wait weeks for the live collector to
   accumulate history from scratch.
6. **`fetch_actual_temp.py`** — pulls the real recorded high temperature from NWS's Central
   Park station, to eventually measure how accurate the logged forecasts actually were.
7. **`backtest_calibration.py`** — the first real backtest: checks whether Kalshi's own
   price was a well-calibrated probability, using the settled-markets data.
8. **`sports_fair_value.py`** — the second fair-value signal: pulls real sportsbook odds
   (via The Odds API), de-vigs and averages them across books into a consensus probability,
   and compares it to Kalshi's MLB game markets. **`log_sports_edge.py`** logs this hourly,
   so a real edge (if one shows up before Kalshi's price catches up to a freshly-posted
   sportsbook line) can actually be caught over time, not just guessed at from one snapshot.
9. **`paper_trade.py`** — watches both fair-value signals and opens a fixed-size ($10
   notional) hypothetical trade whenever the edge (measured against the actual price you'd
   pay, not the mid) clears a 5-point threshold. No real money moves; this is for building a
   track record before ever considering that.
10. **`resolve_paper_trades.py`** — checks each open paper trade against Kalshi's actual
    settlement, computes real P&L, and prints a running win-rate/total-P&L summary. Runs
    every 30 minutes. Without this, paper trades would just sit as "open" forever with no
    feedback loop.

## Notable problems I caught

**Silently empty price data.** Kalshi's API returns price fields as `yes_bid_dollars`,
`yes_ask_dollars`, etc. — not `yes_bid`, `yes_ask` like an earlier version of the script
assumed. Every price collected before the fix was silently empty (the script never errored,
it just recorded nothing useful). Caught it by checking the raw API response directly
instead of trusting the script was working, then fixed the collector and reprocessed the
analysis scripts to match.

**Same column name, different meaning across data sources.** `collect_data.py`'s `volume`
column is cumulative volume since the market opened (from Kalshi's `/markets` endpoint).
`backfill_prices.py`'s `volume` column is *per-hour* trading volume (from the
`candlesticks` endpoint) — often legitimately 0 for illiquid hours. Both files use the same
column name for genuinely different metrics; merging or comparing them directly without
accounting for that would produce misleading results. Documented in `backfill_prices.py`
and here rather than "fixed," since both values are correct for their own source — the
risk is conflating them, not a bug in either.

**Lookahead bias, avoided rather than caught.** Considered backfilling weather-forecast
accuracy the same way as prices, but NWS's API only returns the *current* forecast, not
what was forecast in the past. Substituting actual historical outcomes as a stand-in for
"what the forecast said" would make the calibration look artificially good — it's
information that wouldn't have been available at the time. That piece has to accumulate in
real time via `log_forecast.py` instead; no shortcut.

**A settlement artifact that broke the first backtest.** The first run of
`backtest_calibration.py` had every single market's "price right before settlement" land in
the exact same bucket (55% every time) — obviously wrong. Traced it to Kalshi's
`candlesticks` API reporting a degenerate `yes_bid=0 / yes_ask=1` placeholder for the candle
right after a market closes (the order book is empty, not actually priced at 50/50). Fixed
by excluding those placeholder quotes before picking the latest real price. Result after the
fix: early prices are only modestly predictive (Brier score 0.218, barely better than a
0.25 coin-flip baseline), but prices right before settlement are well-calibrated (Brier
0.066) — real evidence that any edge has to come from information the market hasn't priced
in yet, not from trading close to resolution.

**A confound in the category comparison, caught before drawing a conclusion from it.**
Breaking calibration down by category (weather/sports/economics) showed sports as the least
well-calibrated early on — a good sign for building a sports model next. But "early" meant
"first observed price," and different market types have very different lifespans (weather
markets exist ~1-2 days, sports/economics markets exist for weeks) — so the comparison could
have just been measuring "how far out Kalshi lists the market," not real mispricing. Fixed
by comparing at a fixed lead time (24h before close) instead, with a fallback-rate check to
confirm each category actually had enough history for that to be meaningful. The finding
held up: sports is still barely better than a coin flip 24h out (Brier 0.234, only 1%
fallback), weather is well-calibrated even a day out (Brier 0.100) — real evidence, not an
artifact, that sports is the strongest next category to build a fair-value model for.

**Comparing the wrong side of the same game.** The first run of `sports_fair_value.py` had
both teams in the same matchup showing the *same* fair probability (e.g. both Philadelphia
and Minnesota at 90%) — impossible, since two-outcome probabilities have to sum to ~100%.
Traced it to always taking the *first*-listed team from the market title, regardless of
which contract (`-MIN` vs `-PHI`) was actually being priced. Fixed by using
`yes_sub_title`, which Kalshi already provides per-contract, instead of assuming position
in the title. After the fix, the pairs correctly sum to ~1.0 and edges are small (~1-2
cents) for the games currently matchable — expected, since the free odds-API tier only
covers near-term games, and the calibration backtest already showed Kalshi is well-priced
close to game time. The real test is whether an edge shows up *earlier*, which is what the
hourly logging is for.

**A quiet API-budget bug, caught before it happened.** Almost gave `paper_trade.py` its own
hourly cron job to check sports opportunities — but it independently calls the odds API,
and `log_sports_edge.py` already does too, so that would've silently doubled the free
tier's usage (24 → 48 requests/day, over the 25/day limit) the first time a game slate was
busy enough to hit it. Caught before wiring up the cron job, not after it started failing.
Fixed by having `log_sports_edge.py` feed its already-fetched comparisons into paper
trading directly, so there's only ever one odds-API call per hour, not two.

**A real coverage gap, not a signal-quality problem.** Only ever saw 1 open paper trade at
a time, because `weather_fair_value.py` only handled `strike_type == "greater"` markets —
ignoring 10 of NYC's 12 currently open markets ("less than X" and "between X and Y" types).
Rather than lower the trading threshold (which would add noise, not real opportunities),
added the correct probability math for the other two strike types. Sanity-checked: the 6
currently-quoted markets' probabilities for the same day sum to 1.00, confirming the
partition is mutually exclusive and exhaustive. Result: 1 open trade → 4, from real added
coverage, not lowered standards. Separately confirmed (while reading the rules text) that
Kalshi's actual settlement source is "The Weather Company" via a weather.com portal, not
NWS directly — same Central Park location, so the core strategy holds, but it sharpens an
existing caveat that `fetch_actual_temp.py`'s raw-NWS-observation proxy has a real gap
versus Kalshi's true settlement value, worth revisiting when sigma calibration happens.

## Current status

- Data collection running continuously (market prices + weather forecasts).
- First fair-value signal (weather) built and working.
- Forecast uncertainty currently uses NWS's published national accuracy stats as a
  starting estimate; collecting forecast-vs-actual data to replace it with a real
  measured value specific to this pipeline.
- First real backtest (price calibration) done — see finding above. Confirms the strategy
  direction; doesn't yet test the weather fair-value model itself (still waiting on
  forecast-accuracy data).
- Second fair-value signal (MLB, via real sportsbook odds) built and logging hourly.
- Weather now covers all 3 NYC strike types (above/below/range), not just "above X".
- Paper trading is live: both signals feed into it, hypothetical trades logged when edge
  clears the threshold. No trades have resolved yet (needs time), so no track record to
  evaluate yet — that's the next thing to watch for.

## Roadmap

- [ ] Measure real forecast accuracy, calibrate the weather model
- [x] First backtest (price calibration) — see above
- [ ] Backtest the weather fair-value strategy itself against historical data
- [x] Expand to sports (MLB) using the same external-data approach
- [ ] See if a real sports edge shows up in the hourly logged data
- [x] Paper trading (simulate trades without real money)
- [ ] Resolve paper trades against actual outcomes, see how the track record looks
- [ ] Risk management (position sizing, stop-loss)
- [ ] Live order execution
- [ ] Dashboard (earnings, trade history, performance over time)
