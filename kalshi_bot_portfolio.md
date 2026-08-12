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
5. **`backfill_prices.py`** — pulls ~30 days of real historical price data from Kalshi's
   `candlesticks` API, so backtesting doesn't have to wait weeks for the live collector to
   accumulate history from scratch.

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

## Current status

- Data collection running continuously (market prices + weather forecasts).
- First fair-value signal (weather) built and working.
- Forecast uncertainty currently uses NWS's published national accuracy stats as a
  starting estimate; collecting forecast-vs-actual data to replace it with a real
  measured value specific to this pipeline.

## Roadmap

- [ ] Measure real forecast accuracy, calibrate the weather model
- [ ] Backtest the strategy against historical data
- [ ] Paper trading (simulate trades without real money)
- [ ] Risk management (position sizing, stop-loss)
- [ ] Live order execution
- [ ] Dashboard (earnings, trade history, performance over time)
- [ ] Expand to sports markets using the same external-data approach
