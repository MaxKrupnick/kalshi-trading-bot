# Kalshi Trading Bot

A measurement study of whether [Kalshi](https://kalshi.com) prediction-market prices can be
beaten — built as my first data science / software project, in the shape of a trading bot.
Live data collection, two independent fair-value models, paper trading, and a dashboard.
Three weeks of continuous data, 838 paper trades, and three falsification tests.

**Every strategy I built or tested has been measured against the market, and all three lost.**

| Test | Result | Verdict |
|---|---|---|
| **Weather** — NWS forecasts vs Kalshi price (the thesis) | Brier +0.0010, CI **[−0.0020, +0.0042]** | No measurable advantage |
| **Momentum** — extrapolate recent price move (the control) | Brier +0.0034, CI **[+0.0014, +0.0055]** | Measurably **worse** than the price |
| **Longshot bias** — is the market itself mispriced? | EV +2.6¢/contract, CI **[−0.0133, +0.0592]** | Real pattern, not tradeable |

None of those verdicts comes from P&L. The first two score forecasts against real outcomes
with a Brier score, over every logged comparison rather than only the ones that became
trades. The third prices a structural anomaly at the real quoted ask and gives it an honest
error bar.

That is the actual output of this project: not a profitable bot, but a working instrument
for telling whether a strategy has any information advantage — and two strategies that
didn't. The bot is the apparatus; the measurements are the result.

No real money has ever been at risk. See [FINDINGS.md](FINDINGS.md) for the full write-up of
both tests.

## Why this approach

Kalshi's price *is* the market's implied probability. Trading on Kalshi's own price
momentum is a weak strategy — these markets are thin and usually already reflect public
information. The real edge comes from having a **better, independently-sourced probability
estimate** than the market, for markets where a good external predictor exists.

**Example:** NYC's Central Park high temperature. NWS publishes a public forecast. If NWS
forecasts an 80% chance of exceeding a strike price but Kalshi is only pricing it at 40%,
that gap is the edge.

> **Status of that premise: tested, and not supported — in either direction.** The argument
> above is reasonable, and it's why I built the thing. It is also just an argument. Measured
> against real outcomes, the NWS-derived model forecasts these markets *about as well as
> Kalshi's price does* — not better. And the momentum strategy the argument dismisses as
> "weak" turned out to be weak for real, but the argument's confidence in that was luck: it
> took a separate test to establish, and for three weeks the paper P&L pointed the other way.
> Both tests are below.

## Three tests, three negatives

### Test 1 — the thesis: does external data out-forecast the market?

Every diagnostic I'd built asked "did the trades make money." That question is downstream
of a more basic one I had never tested directly: **does the model actually know something
the market doesn't?** If it doesn't, then every "edge" the screen finds is noise, and
trading noise loses the bid/ask spread by construction — no bug required.

So I scored both forecasts against the same real outcomes, over **all 5,376 logged
comparisons** — not just the ~200 that cleared the edge threshold and became trades.
Scoring only the traded ones would select on the model's own opinion, which is exactly the
bias under investigation.

| Forecaster | Brier score (lower is better) |
|---|---|
| My NWS-derived model | 0.0891 |
| Kalshi's market price | 0.0881 |

95% bootstrap CI on the difference: **[−0.0020, +0.0042]** — straddles zero.

**The model has no measurable information advantage over the market.** Not worse. Not
better. Roughly the same information, which means there is nothing to trade on.

That single result explains what four earlier diagnostics couldn't:

- **Adverse selection.** On the trades the model *chose* to take, the market's Brier (0.146)
  beats the model's (0.177). The edge threshold selects precisely for the cases where the
  model is most wrong — a screen for model error, not for mispricing.
- **Uniform overconfidence.** Broken out by decile, the model's probability exceeded the
  realized outcome rate in **all ten buckets** on traded positions (it said 0.9–1.0 where
  reality was 0.69; said 0.1–0.2 where reality was 0.02).
- **Spread drag.** Paying the ask instead of the mid cost $137 — 24% of the weather arm's
  loss. Structural, paid on every trade, and exactly what a zero-edge strategy cannot afford.

**The obvious fix would not have worked, and I checked before making it.**
`calibrate_sigma.py` showed the model's assumed forecast uncertainty was far too wide
(measured RMSE ~1.9–3.4 °F against a hand-set 2.0–7.2 °F curve), which made "recalibrate
sigma" the clear next move. Before editing constants that every future trade depends on, I
replayed all 207 resolved weather trades with the measured values (`simulate_sigma_fix.py`):
**−$545 → −$395.** Better, still deeply negative. Too-wide sigma was a contributing cause,
not the explanation — and no amount of tuning a parameter creates an information advantage
that isn't there.

### Test 2 — the control: does price momentum out-forecast the price?

The momentum arm was built as a deliberate control: the project's premise says trading
Kalshi's own price movement should be weak, and that claim had never been measured either.
Its "model" is a deterministic function of the market's own mid —
`mid + 0.5 × (6h move)` — so the test reduces to a clean question: **does extrapolating half
the recent move beat simply quoting the current price?**

This test is why the gate exists. From 2026-08-26 the momentum arm was *profitable on paper*
— +$108.74 across 296 resolved trades, after being deeply negative before that. Under the
old gate ("wait for a positive result") that looks like a strategy graduating. So I ran the
same Brier test on it (`analyze_momentum_vs_market.py`), replaying the signal over three
weeks of price history on an hourly grid, scoring against real settlement:

| Forecaster | Brier score (lower is better) |
|---|---|
| Momentum signal | 0.1623 |
| Kalshi's market price | 0.1589 |

95% CI on the difference, **resampling whole tickers**: **[+0.0014, +0.0055]** — entirely
above zero.

**The momentum signal is a measurably worse forecaster than the price it is derived from.**
Not ambiguous like the weather result; definitely worse. The paper profit was luck, and the
gate caught it — which is the entire reason I wrote the gate down before I needed it.

It shows the same adverse selection as the weather arm, and more strongly: on the 1,094
snapshots that cleared `EDGE_THRESHOLD`, the gap widens from +0.0034 to **+0.0096**. The
screen preferentially selects the signal's worst calls in both arms.

It survives the obvious robustness checks. Seven of nine market series point the same
direction, and a 3-hour evaluation grid gives +0.0047 with the CI still clear of zero.

One methodological upgrade over Test 1: that test *reported* the clustering problem (repeated
snapshots of the same markets aren't independent draws) as a caveat. This one handles it, by
bootstrapping over whole tickers instead of individual rows. Worth knowing what the caveat was
hiding — the naive interval was [+0.0023, +0.0046], about half as wide as the honest one.

### What I'd claim from this

Not a profitable bot. A pipeline that collects real data continuously, two strategies
implemented faithfully, and — the part that matters — falsifiable tests of my own premises
that I built, ran, and believed when they came back negative. Twice, including once when the
P&L was telling me what I wanted to hear.

The measurement infrastructure is the durable artifact. It caught a strategy that was
*making money* and correctly said no.

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
2. **`log_forecast.py`** — pulls NWS's forecast for all 6 tracked cities every hour and logs
   it to `forecast_log.csv`, building a history to measure forecast accuracy over time.
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
11. **`build_dashboard.py`** — generates a live-updating `dashboard.html` from
    `paper_trades.csv` (summary stats, open positions, resolved trades). Regenerated every 5
    minutes via cron, auto-refreshes in the browser every 60 seconds — no server needed. Also
    watches each cron job's log file and shows a warning banner if one's gone quiet longer
    than its expected schedule — added after a real ~48-hour silent outage (see below).
12. **`calibrate_sigma.py`** — measures real forecast error (`forecast_log.csv` vs. actual
    recorded highs) bucketed by lead time, and compares it to the hand-set uncertainty curve
    `weather_fair_value.py` currently assumes — the first step toward replacing an
    NWS-national-average proxy with a value measured against this pipeline's own forecasts.
13. **`test_edge_significance.py`** — a Monte Carlo test of the skeptical null hypothesis
    "the market's price was exactly the true probability, i.e. there's no real edge at all."
    Simulates 20,000 parallel universes under that null using the actual bet sizes and
    outcomes, and checks whether the real paper-trading P&L is statistically distinguishable
    from ordinary variance — a real number to answer "is this working" instead of eyeballing
    a win rate.
14. **`analyze_edge_by_leadtime.py`** — breaks resolved paper trades down by lead time before
    resolution and by the model's claimed edge size, to test the strategy's own thesis
    (edge should be concentrated in longer-lead-time, higher-conviction trades) directly
    against real outcomes, instead of assuming the price-only backtest still applies once a
    specific model and threshold sit on top of it.
15. **`analyze_edge_vs_liquidity.py`** — checks whether the model's biggest claimed edges
    cluster in illiquid (wide bid/ask spread) markets, reconstructing real spread at trade
    time from `market_data.csv` where available and real historical candlesticks otherwise.
16. **`momentum_signal.py`** — a deliberate **control arm**: trades Kalshi's own recent price
    movement (extrapolating partial continuation of a 6-hour move) instead of external data.
    Runs as a third independent paper-trading strategy alongside weather and sports, so the
    fair-value approach is measured against a baseline rather than only against zero.
17. **`analyze_model_vs_market.py`** — the test that decided the project: scores my model and
    Kalshi's price against the *same* real outcomes with a Brier score, across every logged
    comparison rather than only the ones that became trades, with a bootstrap CI on the
    difference. Asks "does the external data actually know more than the market," which is
    the assumption everything else was built on top of. See the section above for the answer.
18. **`simulate_sigma_fix.py`** — replays every resolved weather trade with the *measured*
    forecast uncertainty from `calibrate_sigma.py`, to check whether recalibrating sigma would
    actually have prevented the losses before editing the live model constants. It wouldn't
    have. Written specifically to avoid "fix the obvious-looking thing and hope."

## Repository guide

Twenty-one scripts in the root is a lot to land on cold. Grouped by what they're for:

**The findings** — start here
| File | |
|---|---|
| `FINDINGS.md` | The write-up: both tests, method, limitations |
| `analyze_model_vs_market.py` | Test 1 — is the weather model a better forecaster than the market? |
| `analyze_momentum_vs_market.py` | Test 2 — is the momentum signal a better forecaster than the market? |
| `analyze_longshot_bias.py` | Test 3 — is the market's own price structurally mispriced at the extremes? |

**The live pipeline** — what cron runs, see `crontab.txt`
| File | |
|---|---|
| `collect_data.py` | Market prices → `market_data.csv`, every 15 min |
| `log_forecast.py` | NWS forecasts → `forecast_log.csv`, hourly |
| `paper_trade.py` | Opens paper positions from a signal's opportunities |
| `resolve_paper_trades.py` | Settles open positions against real outcomes |
| `build_dashboard.py` | Regenerates `dashboard.html` every 5 min |

**The strategies**
| File | |
|---|---|
| `weather_fair_value.py` | NWS forecast → probability, vs Kalshi's price *(arm disabled — no measured edge)* |
| `momentum_signal.py` | Recent price move → probability *(control arm — measured worse than the price)* |
| `sports_fair_value.py` | Sportsbook odds → probability *(disabled — Kalshi changed the title format)* |
| `log_weather_edge.py`, `log_sports_edge.py` | Cron entry points that log comparisons and feed paper trading |

**Diagnostics** — the questions asked along the way
| File | Question it answers |
|---|---|
| `calibrate_sigma.py` | How wrong are NWS forecasts, really? |
| `simulate_sigma_fix.py` | Would fixing that have saved the weather arm? *(no)* |
| `test_edge_significance.py` | Is the P&L distinguishable from luck? |
| `analyze_edge_by_leadtime.py` | Does edge concentrate in longer-dated trades? *(no — inverted)* |
| `analyze_edge_vs_liquidity.py` | Are the losses coming from illiquid markets? *(no)* |
| `backtest_calibration.py` | Is Kalshi's own price well calibrated? |
| `backfill_prices.py`, `backfill_settled.py`, `fetch_actual_temp.py` | Historical data pulls |

**`exploration/`** — the first scripts I wrote, kept as history. Nothing depends on them.

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

**A model bug a liquid market exposed.** Expanded weather from NYC alone to 6 cities
(Chicago, Miami, Denver, LA, Boston), each with its NWS grid point verified against
Kalshi's actual settlement station, not guessed from city coordinates. This surfaced a real
flaw: the sigma curve had a flat 5.4°F floor for anything under 48 hours out, treating a
same-day (~6h out) forecast the same as a 2-day-out one. A liquid, tightly-quoted Miami
market ($6,367 volume, 3-cent spread) showed a ~55-point "edge" — implausible for a market
that liquid, and a strong signal the *model* was wrong, not the market. Added a 12-hour
anchor so near-term forecasts get properly tighter uncertainty (2.0°F, a reasoned estimate,
not a verified citation like the other two anchors — flagged as such). Cleared all 30
previously-open paper trades (both the newest batch and the original 4 NYC ones, which
shared the identical flaw) and re-ran fresh under the corrected model: 21 trades, more
moderate edges.

**Correlated risk hiding behind a diversified-looking count.** With 21 simultaneous open
positions, noticed 5 of them were all Boston strikes for the same day — $50 total, but all
resolving off one real number (Boston's actual high temperature), not 5 independent bets.
Added edge-weighted position sizing ($5 at the minimum qualifying edge, scaling to a $20
cap) and a $30 exposure cap per underlying event, grouping contracts by their shared event
(derived from Kalshi's consistent ticker format, works for weather and sports alike without
new stored fields). Left the 21 pre-existing trades as-is rather than resetting again —
their edge calculations were correct, only the sizing discipline is new, and unwinding
already-placed paper trades every time risk logic improves isn't how real position
management works. New rules apply prospectively; several cities are already over the new
cap from those trades, so new opportunities there are correctly blocked until some resolve.

**The first real resolutions caught a real duplicate-bet bug.** 4 sports trades resolved
first: 0/4, -$25.12. Two of the four turned out to be the same bet placed twice — Team A
YES and Team B NO on the same 2-team MLB moneyline are economically identical (both only
pay off if Team A wins), but they're different Kalshi tickers, so the code opened both as
if they were independent opportunities. The per-event dollar cap kept it bounded ($12.20,
under the $30 cap), but it wasn't real diversification, just one view under two labels —
and both lost together, exactly as a duplicated bet would. Fixed by capping sports (not
weather, whose strike buckets are genuinely non-redundant) to one open position per event.

**A silent ~48-hour outage, and a wrong diagnosis worth recording.** Five of the six cron jobs
stopped writing new data for about two days. My first read was a transient network failure
affecting cron-launched processes — every silent job made outbound HTTP calls, and the one
that kept logging (`build_dashboard.py`) doesn't. That explanation fit the evidence I'd
looked at, and it was wrong.

The actual cause was mundane: the laptop was asleep or powered off (I was moving into
college). macOS `cron` doesn't run missed jobs on wake, so the schedule just silently skipped.
The tell I'd missed was a counting check I hadn't thought to do — `build_dashboard.log` had
344 lines where continuous 5-minute operation over that window would have produced ~1,126, and
`kern.boottime` showed a reboot mid-outage. The dashboard job hadn't survived the outage at
all; it had just run a few times on brief wakes, which was enough to make its log look current
while the slower-cadence jobs never happened to catch a boundary.

Worth keeping in the writeup rather than quietly editing away: a plausible mechanism that
explains the pattern isn't the same as the cause, and "which processes are still alive" was a
much weaker signal than "how many times did each one actually run." The monitoring fix that
came out of it stands either way — the dashboard now checks each cron's log-file mtime against
its expected cadence and shows a warning banner if any job goes quiet, which surfaces a
sleeping laptop exactly as well as it would have surfaced the network failure I'd assumed.

**A city that was never actually being logged.** While building `calibrate_sigma.py`,
found `log_forecast.py` was still hardcoded to NYC's single NWS grid point — a leftover from
before the 6-city expansion. `forecast_log.csv` had zero forecast history for the other 5
cities despite `weather_fair_value.py` actively trading all 6. Fixed to loop over the shared
`CITIES` config like the rest of the weather code already does, and generalized
`fetch_actual_temp.py` to take a station + timezone instead of assuming NYC/Eastern (Denver
and LA aren't Eastern time, which matters for correctly assigning a forecast to "today" vs.
"tomorrow"). First calibration read, NYC only (the other 5 cities are still building
history): measured forecast error (2.0–2.8°F RMSE, 12–120h out) came in well under the
5.4°F the model currently assumes, plus a consistent ~2°F warm bias — worth a second look
once there's more than one city and one week of data, not yet acted on.

**Tested the strategy's own thesis against the paper-trading data, not just the price
backtest.** The whole strategy rests on `backtest_calibration.py`'s original finding: Kalshi's
price is weakly predictive early and catches up fast, so real edge should be concentrated in
trades placed with more lead time before resolution, and the model's biggest claimed edges
should perform at least as well as its smaller ones. Built `analyze_edge_by_leadtime.py` to
check both directly against the 68 resolved paper trades, rather than assuming the price-only
backtest still holds once a specific model and trading threshold sit on top of it. Neither
pattern held up: ROI didn't improve with more lead time (the 24-72h bucket was the worst of
the three, not the best), and the trades where the model claimed the *biggest* edge (0.15+)
had the worst ROI of any bucket (-52.5%) and underperformed their own implied win rate. Too
small a sample to say the thesis is wrong, but it isn't confirming it either — and the
edge-size result specifically suggests the model's largest "edges" may disproportionately be
its own errors (bad forecast, stale odds line) rather than real mispricing, which is worth
investigating (e.g. whether they cluster in illiquid markets, the same failure mode as the
Miami sigma bug) before trusting them more.

*Follow-up: the hunch in that last sentence turned out to be right about the mechanism and
wrong about the cause. The biggest "edges" are indeed disproportionately model error — but
not because of illiquidity (checked next, and ruled out). It's adverse selection: an edge
screen run on a model with no real information advantage is a filter for that model's own
mistakes. See [The founding assumption, tested](#the-founding-assumption-tested).*

**A third city-list drift, this time in the price collector.** Building the liquidity check
below meant matching paper trades to real bid/ask spreads in `market_data.csv` — and only
16 of 68 resolved trades matched at all. Traced it to `collect_data.py`'s `SERIES_TO_TRACK`,
which had the exact same problem as `log_forecast.py` earlier this session: it only ever
listed `KXHIGHNY`, never updated for the other 5 cities. Fixed the immediate gap, and this
time fixed the *actual* root cause instead of just the symptom — the city list had been
copy-pasted into three separate places (`weather_fair_value.py`, `log_forecast.py`,
`collect_data.py`) and only the first one reliably got updated when a city was added.
`collect_data.py` now derives its weather series from `weather_fair_value.CITIES` directly,
so there's only one list left to maintain.

**Checking whether the model's biggest "edges" are just noise in thin markets.** Following
up on the lead-time/edge-size finding above: does the model's claimed edge size correlate
with how illiquid the market actually was, and does that illiquidity cost real ROI? Since
most already-resolved trades predate the `collect_data.py` fix, `analyze_edge_vs_liquidity.py`
falls back to fetching real historical candlesticks per-ticker for anything not in
`market_data.csv` (same API `backfill_prices.py` already uses, just targeted at one market
instead of a whole series, cached locally). Result: the biggest-edge bucket (0.15+) does have
the widest average spread (0.061 vs. 0.013–0.028 for the other two buckets) — partial support.
But spread doesn't explain the P&L: the *tight*-spread bucket holds 60 of the 68 trades and
all of the negative P&L (-42% ROI), while the handful of wider-spread trades were actually
profitable (too few, n=6 and n=2, to trust on their own). Rules out "it's just illiquid
markets" as a clean explanation — most of the losses happened in reasonably liquid ones.

**Testing the project's own core premise instead of assuming it.** This README has argued
from the start that price momentum is a weak strategy and real edge has to come from
independent external data. That was reasoned qualitatively and never measured — and with four
separate diagnostics unable to find edge in the fair-value arms, it stopped being safe to keep
assuming. So momentum now runs as a real third paper-trading arm, tracked separately. It costs
nothing extra to run (reads only the price data already being collected — no new API or key),
and it makes the result interpretable either way: if momentum also loses, that's evidence
these markets are simply hard rather than that the fair-value model is uniquely broken; if
momentum does *better*, the project's founding premise needs revisiting. Comparing against a
baseline beats comparing against zero.

Wiring it in surfaced a design problem worth fixing carefully: `paper_trade.py` tracked open
positions, per-event exposure, and duplicate-event checks globally, not per strategy. One arm
could consume another's exposure budget or block it from a ticker entirely — which would
contaminate a comparison between strategies rather than manage real risk. Since no capital is
at stake in paper trading, that state is now keyed per strategy (a single shared cap only
starts making sense once real money is involved). Also generalized the both-sides-of-one-game
duplicate check from `source == "sports"` to a property of the *market*, since momentum trades
those same game markets and would otherwise have hit the exact same redundancy bug the sports
arm already had fixed.

## Current status

*Updated 2026-09-02.*

- Data collection running continuously (market prices + weather forecasts, all 6 cities).
- **Paper trading track record: 790 resolved trades, 56% win rate, total P&L −$771.65
  (−10.7% ROI).** By strategy:

  | Arm | Resolved | Win rate | P&L | ROI | State |
  |---|---|---|---|---|---|
  | weather (the thesis) | 331 | 39% | −$666.56 | −21.2% | **disabled 2026-09-02** |
  | momentum (the control) | 449 | 70% | −$16.52 | −0.4% | running as the null |
  | sports | 10 | 0% | −$88.57 | −100% | disabled 2026-08-25 |

- **Both arms are now measured, and neither has an information advantage.** Weather: no
  measurable difference from the market (CI straddles zero). Momentum: measurably worse
  (CI entirely above zero). See [Three tests, three negatives](#three-tests-three-negatives).
- **The weather arm kept trading for a week after it was disproven, and that's on me.**
  The Brier test landed 2026-08-26 and the arm's cron wasn't stopped until 2026-09-02 — 124
  further trades, −$121.23, spent re-confirming a conclusion already reached properly. The
  finding and the shutdown should have been the same commit. Open positions were left to
  resolve normally rather than discarded, so the record stays complete.
- **Momentum stays running, as the null.** It is deliberately *not* being fixed or tuned —
  it costs nothing, it needs no API calls beyond the price log, and a growing sample under a
  known-negative strategy is exactly what a baseline is for.

- **The control arm beat the thesis arm on P&L, and it still had no edge.** That comparison
  was a pre-registered trigger: when I built the momentum arm I wrote down in advance what
  each outcome would mean, so I couldn't rationalize afterward. "Momentum does better ⇒ the
  founding premise needs revisiting." It did, so I revisited it — which produced both Brier
  tests. The follow-through matters more than the trigger did: momentum's P&L advantage
  (and later its outright profit) turned out to be noise on a signal that forecasts *worse*
  than the price. Caveat I'd still state in an interview: the arms don't trade the same
  opportunity set, so the P&L comparison was only ever directional. The Brier tests are the
  part that carries weight.
- **The significance test has crossed its own threshold, on the losing side.**
  `test_edge_significance.py` simulates 20,000 parallel universes under the null "the market
  price was exactly fair." Overall p-value went **0.18 → 0.049 → 0.018** across three weekly
  checks. This is now weak statistical evidence the strategies as built are *worse* than the
  market price, not merely unproven. (Weather alone p=0.061, momentum p=0.107 — neither is
  individually significant yet.)
- **The loss is concentrated in one bucket, and it's a leverage effect.** By entry price:
  **<$0.15 → −$501.83 (84 trades, 2% win rate vs ~6% implied)**; $0.15–0.75 roughly
  breakeven (−2.7%); ≥$0.75 → −$182.10 (70% win vs ~85% implied). At sub-$0.15 prices the
  payout leverage is ~6:1, so a small calibration miss becomes a large dollar loss.
  A `MIN_ENTRY_PRICE = 0.15` guardrail now blocks that bucket — a tourniquet while the real
  question was being answered, explicitly not a strategy.
- Weather sigma calibration measured across all 6 cities: real forecast error (RMSE
  1.9–3.4 °F by lead time) runs much tighter than the model's hand-set 2.0–7.2 °F curve.
  **Deliberately still not acted on** — `simulate_sigma_fix.py` shows correcting it would
  have moved the weather arm from −$545 to −$395, i.e. not the explanation. Fixing it now
  would be tuning a parameter on a strategy with no established edge.
- Sports edge appears structurally limited by data timing: the free odds-API tier only
  returns near-term games, and the original calibration backtest showed Kalshi's own price
  is already well-calibrated by then — so the theoretical inefficiency (Kalshi is close to a
  coin flip on sports a day out) may not be reachable with this data source. Deprioritized
  further sports build effort pending a paid tier being worth it.
- **Sports arm disabled 2026-08-25.** Kalshi changed the `KXMLBGAME` market title format
  (`"<A> vs <B> Winner?"` → `"<Team> wins"`), which broke `sports_fair_value.parse_matchup()`
  — every market was silently skipped and the arm logged zero comparisons from ~Aug 21 on.
  Its cron is commented out rather than left running as a no-op; the parser needs a rewrite
  (the title no longer carries the opponent) before it comes back. Given sports was already
  deprioritized, this is a low priority. Track record while it ran: 10 resolved, 0 wins,
  −$88.57.
- **Two candidate explanations were ruled out before the right one was found.** Worth
  recording because the wrong answers took real work: (1) *lead-time decay* — the thesis says
  edge should concentrate in longer-lead-time trades; measured, and the pattern is inverted
  (24–72h is the worst bucket at −35.6%, 6–24h roughly breakeven). (2) *illiquid-market
  noise* — the biggest claimed edges do sit in wider-spread markets, but 347 of 371 trades
  happened in tight-spread markets and carry essentially all the losses. Both plausible, both
  wrong. The Brier test above is what finally explained it.
- Live dashboard (`dashboard.html`) shows current positions, P&L, a per-strategy comparison
  table, and a staleness warning if any collection job has gone quiet, regenerating every 5
  minutes.
- **Not proceeding to live order execution (real money), and the gate is now stricter than
  it was.** It was "until the significance test shows a real positive result." It is now
  "until some strategy demonstrates a measurable forecasting advantage over the market price
  first" — P&L is too noisy to be the primary evidence at this sample size, and
  `analyze_model_vs_market.py` tests the thing that actually has to be true.
- **Known limitation: the pipeline runs on a laptop that sleeps.** macOS cron doesn't run
  missed jobs on wake, which has caused three multi-day data gaps. The dashboard's staleness
  banner catches it now, but the real fix is an always-on host — see `DEPLOY.md` for the
  migration plan (the architecture ports with zero code changes; the live loop uses only
  public endpoints and needs no credentials).

## Roadmap

- [x] Measure real forecast accuracy — `calibrate_sigma.py` built; NYC has ~1 week of data,
      other 5 cities still accumulating. Not yet acted on (see Current status).
- [x] First backtest (price calibration) — see above
- [ ] Backtest the weather fair-value strategy itself against historical data
- [x] Expand to sports (MLB) using the same external-data approach
- [x] See if a real sports edge shows up in the hourly logged data — likely structurally
      capped by free-tier data timing; see Current status
- [x] Paper trading (simulate trades without real money)
- [x] Resolve paper trades against actual outcomes, see how the track record looks — done,
      and followed up with an actual statistical test rather than eyeballing the number
- [x] Risk management (edge-weighted position sizing, per-event exposure caps)
- [x] Basic monitoring — dashboard staleness banner (passive; no active alert yet)
- [x] Run a control strategy (price momentum) in parallel, to measure the fair-value approach
      against a baseline instead of against zero
- [x] Compare the arms once momentum has enough resolved trades — done; the control arm is
      ahead, which triggered the premise review below
- [x] **Test the founding premise directly** (`analyze_model_vs_market.py`) — does the
      external model out-forecast the market at all? Answer for weather: no measurable
      difference. This reframed everything below it.
- [x] Check whether the obvious sigma fix would have helped before making it
      (`simulate_sigma_fix.py`) — it wouldn't have
- [x] **Run the same Brier test on the momentum arm** (`analyze_momentum_vs_market.py`) —
      answer: momentum forecasts measurably *worse* than the market price. The arm was
      profitable on paper at the time, and the gate correctly rejected it anyway.
- [ ] Live order execution — gated on a strategy first showing a **measurable forecasting
      advantage over the market price**, not on P&L and not on a timeline. **No candidate
      currently exists**: both strategies built have been measured and neither qualifies.
- [x] Dashboard (live-updating, via `build_dashboard.py`)

### Where this goes next

Both premises are answered, so the honest options are narrow — and "keep tuning" is not one
of them.

**The project is being finished as a measurement study rather than extended as a trading
bot.** That isn't a consolation framing; it's what the work actually produced. A bot that
found no edge in two independent strategies, and can show *why* with a scored test rather
than a shrug, is a more defensible artifact than one claiming a backtested profit. Anyone
who has looked at a few of these assumes the profitable ones are overfit — and at n=790 with
this variance, they would be right to.

What that means concretely:

1. **Keep the collectors running.** They cost nothing, need no credentials, and the sample
   compounds. Every question below gets easier with three months of data than with three
   weeks. This is the single highest-value thing to *not* stop doing.
2. **Write up the two tests properly** — done, in [FINDINGS.md](FINDINGS.md).
3. **Revisit with more data, not with more parameters.** The weather CI straddles zero at
   n=5,376 comparisons; a larger sample could resolve it in either direction. That is a real
   open question. Re-running an existing test on more data is legitimate; tuning the strategy
   to make the old data look better is not.

Deferred, with reasons rather than a shrug:

- **A category with a genuine access or latency asymmetry.** The weather result isn't that
  external data never helps — it's that NWS forecasts are already priced in by a market whose
  participants read the same forecast. Economics releases (CME FedWatch, nowcasts) were the
  strongest remaining candidate, but they fail the *same* test on inspection: also public,
  also read by everyone. Worth pursuing only with a source that isn't universally available,
  which I don't currently have.
- **Fixing the sports parser.** Kalshi changed the `KXMLBGAME` title format and the arm has
  been dark since 2026-08-21. Cheap to fix, but it would restart an arm that was already
  deprioritized on structural grounds (free odds tier only covers near-term games, by which
  point Kalshi is already well-calibrated).
- **Always-on hosting** (`DEPLOY.md`). The migration plan is written and the architecture
  ports without code changes. It mattered when a strategy was being evaluated against a
  deadline; with no live candidate, laptop-sleep gaps are a data-quality annoyance rather
  than a blocker.

Not on the list, and worth stating explicitly: recalibrating sigma, lowering the edge
threshold, adding cities, or increasing position size. All four tune strategies that have now
been measured and shown to have nothing to tune toward. The sigma one in particular was
checked before being applied (`simulate_sigma_fix.py`) and would not have worked.
