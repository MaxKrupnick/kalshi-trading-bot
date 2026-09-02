# Can Kalshi's prices be beaten? Three tests, three negatives.

*Max Krupnick · September 2026 · [repo README](README.md)*

---

## The question

Kalshi is a prediction market. Its price for a contract *is* a probability — if "NYC high
temperature above 80°F" trades at 40¢, the market is saying 40%.

That makes a very direct question available, one that most trading projects can't ask
cleanly: **is my probability estimate better than the market's?** Not "did I make money" —
that's downstream, noisy, and takes a long time to answer. Just: given the same event and the
same moment, whose number lands closer to what actually happened?

I built two strategies on the assumption that mine would be better. This is the record of
measuring that assumption, being wrong both times, and then testing the one remaining idea
that needed no forecasting advantage at all — and being wrong a third time.

---

## The apparatus

Three weeks of continuous collection, on a cron schedule:

- **Prices** — every 15 minutes from the Kalshi API, ~1,800 distinct markets across weather,
  MLB, NFL, WNBA, CPI, payrolls, unemployment, PCE
- **Weather forecasts** — hourly from the National Weather Service for 6 cities
- **Paper trades** — 838 positions opened, sized by edge, resolved against real settlement
- **A dashboard** regenerated every 5 minutes, with a staleness banner

None of that is the finding. It's the instrument that made the finding possible, and it's
the part I'd rebuild the same way.

---

## Method

Both tests use the same design, and the design choices are most of the work.

**Brier score.** Mean squared error of a probability forecast against a 0/1 outcome. Lower
is better; a forecast of 0.7 on something that happens scores (0.7−1)² = 0.09. It rewards
being both accurate *and* appropriately confident, which is exactly the property under test —
a model that hedges everything to 0.5 scores badly, and so does one that's confidently wrong.

**Score every comparison, not just the traded ones.** This is the choice that matters most.
The strategies only trade when they think they've found a big enough edge, so scoring only
the traded snapshots would be scoring the model on cases it selected using its own opinion.
That's the exact bias under investigation. Both tests score the full population of logged
comparisons — 5,376 for weather, 6,353 for momentum — and report the traded subset separately
as a *diagnostic*, never as the headline.

**Bootstrap a CI on the difference.** Two Brier scores that differ in the fourth decimal mean
nothing on their own. Resampling the data 5,000 times gives a range for how much of that gap
is sampling noise.

**Cluster the bootstrap by market.** The comparisons are repeated snapshots of the same few
hundred markets, so they are nowhere near independent draws — if my model misjudges one NYC
weather market, it misjudges every hourly snapshot of that market. The first test noted this
as a caveat. The second one handles it, resampling *whole tickers* rather than individual
rows. That turned out to matter: the naive interval was about half as wide as the honest one.

---

## Test 1 — Weather: does external data out-forecast the market?

The thesis the project was founded on. The NWS publishes a public high-temperature forecast;
convert it to a probability with a normal distribution around the forecast; compare to
Kalshi's price; trade the gap.

| Forecaster | Brier |
|---|---|
| NWS-derived model | 0.0891 |
| Kalshi market price | 0.0881 |
| **difference** | **+0.0010** |

95% CI on the difference: **[−0.0020, +0.0042]** — straddles zero.

**No measurable information advantage.** Not worse, not better. Roughly the same information,
which means there is nothing to trade.

That single result explained three things I'd been chasing separately:

- **Adverse selection.** On the trades the model *chose*, the market's Brier (0.146) beat the
  model's (0.177). The edge threshold was functioning as a screen for the model's own largest
  errors.
- **Uniform overconfidence.** Broken into deciles, the model's probability exceeded the
  realized rate in all ten buckets — it said 0.9–1.0 where reality was 0.69, and 0.1–0.2
  where reality was 0.02.
- **Spread drag.** Paying the ask rather than the mid cost $137, 24% of the arm's total loss.
  Structural, paid on every trade, and precisely what a zero-edge strategy cannot afford.

**The obvious fix would not have worked, and I checked before making it.** Measured forecast
error (RMSE 1.9–3.4°F) ran much tighter than the model's hand-set 2.0–7.2°F uncertainty
curve, which made "recalibrate sigma" the clear next move. Before editing a constant every
future trade depends on, I replayed all 207 resolved weather trades with the measured values:
**−$545 → −$395.** Better, still deeply negative. A contributing cause, not the explanation.
No parameter creates an information advantage that isn't there.

---

## Test 2 — Momentum: does the recent price move out-forecast the price?

The control arm. The project's premise says trading Kalshi's own price movement should be
weak — but that was an assertion, never measured, so I built it as a real tracked strategy to
find out.

Its "model" is a deterministic function of the market's own price:

```
model_prob = clamp(last_mid + 0.5 × (last_mid − first_mid))    # over a 6h window
```

So the test reduces to something very clean: **does extrapolating half the recent move beat
simply quoting the current mid?**

**This is where the method earned its keep.** From August 26 the momentum arm was
*profitable* — +$108.74 over 296 resolved trades, having been deeply negative before. Under
the gate I'd originally written ("wait for a positive result") that reads as a strategy
graduating toward real money.

| Forecaster | Brier |
|---|---|
| Momentum signal | 0.1623 |
| Kalshi market price | 0.1589 |
| **difference** | **+0.0034** |

95% CI, clustered by ticker: **[+0.0014, +0.0055]** — entirely above zero.
(Naive, unclustered: [+0.0023, +0.0046] — visibly overstating precision.)

**The momentum signal is a measurably worse forecaster than the price it's derived from.**
Unlike the weather result, this one isn't ambiguous. The profit was luck.

**Robustness.** 6,353 comparisons across 910 settled markets. Seven of nine market series
point the same direction. A 3-hour evaluation grid instead of hourly gives +0.0047, CI still
clear of zero.

| Series | n | Brier model | Brier market | diff |
|---|---|---|---|---|
| KXMLBGAME | 1,165 | 0.2153 | 0.2080 | +0.0073 |
| KXHIGHNY | 788 | 0.1291 | 0.1234 | +0.0057 |
| KXNFLGAME | 709 | 0.2492 | 0.2483 | +0.0010 |
| KXWNBAGAME | 672 | 0.1912 | 0.1877 | +0.0035 |
| KXHIGHDEN | 640 | 0.1270 | 0.1252 | +0.0018 |
| KXHIGHTBOS | 577 | 0.0872 | 0.0894 | −0.0022 |
| KXHIGHLAX | 569 | 0.1473 | 0.1488 | −0.0016 |
| KXHIGHCHI | 559 | 0.1258 | 0.1226 | +0.0032 |
| KXHIGHMIA | 545 | 0.1382 | 0.1349 | +0.0033 |

**Same adverse selection, stronger.** On the 1,094 snapshots that cleared the edge threshold,
the gap widens from +0.0034 to **+0.0096**. Both arms independently show the screen
preferentially selecting the signal's worst calls — which is what an edge filter *becomes*
when the underlying signal has no edge.

---

## Test 3 — Longshots: is the market itself structurally mispriced?

The first two tests asked whether *my* forecast beat the price. Both said no. This one drops
my models entirely and asks a question about the market: **do cheap contracts settle YES less
often than their price implies?**

That pattern — longshots overpriced, favourites underpriced — is the favourite-longshot bias,
documented in betting markets since the 1940s. If it's present, exploiting it needs no
information advantage over anyone. You just sell the longshot.

It's also personal to this project: the weather arm's worst bucket by far was entries under
$0.15 — 84 trades, 2% win rate against ~6% implied, −$501.83. That *is* this bias, and the
arm was on the wrong side of it, buying the overpriced longshots its model liked. "Was the
right trade simply the opposite of what I was doing?" deserved a real answer.

**The bias is clearly there.** Across all settled markets, one observation per market per hour:

| yes-mid bucket | n | markets | avg price | actual YES | gap |
|---|---|---|---|---|---|
| 0.01–0.05 | 2,428 | 394 | 0.025 | 0.012 | −0.013 |
| 0.05–0.10 | 1,100 | 273 | 0.072 | 0.034 | **−0.038** |
| 0.10–0.15 | 760 | 221 | 0.122 | 0.101 | −0.021 |
| 0.15–0.25 | 1,292 | 280 | 0.200 | 0.156 | **−0.043** |
| 0.40–0.60 | 20,060 | 800 | 0.497 | 0.502 | +0.005 |
| 0.90–0.95 | 246 | 95 | 0.921 | 0.951 | +0.030 |
| 0.95–0.99 | 299 | 111 | 0.968 | 0.997 | +0.028 |

Cheap contracts settle YES about half as often as their price says. Expensive ones settle YES
more often. Textbook shape, right direction, in my own three weeks of data.

**And it survives the spread — as a point estimate.** The failure mode that killed the earlier
arms was paying the ask instead of the mid, so this is priced at the real quoted `no_ask`:

| yes-mid bucket | pay (no_ask) | P(no) | EV/contract |
|---|---|---|---|
| 0.05–0.10 | 0.939 | 0.966 | **+0.027** |
| 0.15–0.25 | 0.810 | 0.844 | **+0.033** |

+2.6¢ per contract across the 0.05–0.25 range. That is the number that would have started a
three-week build three weeks ago.

**It does not survive an honest error bar.**

```
3,152 observations across 493 distinct markets
point EV per contract       : +0.0256
95% CI, clustered by market : [-0.0133, +0.0592]
```

Straddles zero. 493 markets is not 3,152 independent draws, and once the bootstrap respects
that, the edge is indistinguishable from noise. The payoff shape makes it worse rather than
better: 10% of these positions lose ~87¢ each, so the strategy is frequent small wins against
rare large losses — the configuration that most needs a large sample before anyone sizes it,
and least tolerates being wrong about the tail.

This is the same shape of result as momentum's profitable month. A positive number that looks
like an edge right up until it's given a confidence interval.

---

## What all three tests have in common

1. **The encouraging number came first and was wrong every time.** Weather's losses looked
   like a bug for two weeks. Momentum's profit looked like success for one. The longshot
   bias's +2.6¢ looked like a free structural edge for about twenty minutes. In all three
   cases the point estimate arrived before the interval did, and in all three cases the
   interval is what was true.
2. **The edge screen inverts when there's no edge.** A threshold that selects the largest
   disagreements between model and market selects the model's worst errors, not the market's.
3. **Costs finish the job.** With no information advantage, paying the spread makes the
   expected value negative by construction, before any variance.

The general form: **an edge filter is only a filter for mispricing if you have already
established that your estimate is better. Otherwise it's a filter for your own mistakes.**
I would not have predicted that going in, and it's the thing I'd carry to the next project.

---

## Limitations

Stated plainly, because the tests are only worth what their weaknesses allow:

- **Three weeks is short.** The weather CI straddles zero; a larger sample could resolve it
  either way. The momentum result is cleaner, but the effect is small in absolute terms.
- **Settlement coverage is partial.** 1,391 of 1,765 tickers had finalized settlement at
  analysis time; unsettled markets are dropped, which skews toward shorter-dated contracts.
- **Clustering is handled but not eliminated.** Resampling by ticker addresses repeated
  snapshots of one market; it doesn't address correlation *between* markets on the same day
  in the same city, which is real.
- **Momentum's parameters were set once and never tuned** (6h lookback, 0.5 continuation,
  0.03 minimum move). Deliberate — tuning them against the same outcomes used for evaluation
  would be curve-fitting. But it means the test rejects *this* momentum specification, not
  momentum in general.
- **Paper trading assumes fills at the quoted ask** with no market impact. Fine at $5
  positions; wrong at any size that would matter.

---

## What I'd do differently

- **Test the premise first.** The Brier test is ~200 lines and could have been written in
  week one, before the fair-value model, the sizing logic, or the sports arm. I built the
  machinery for two weeks before asking whether the idea underneath it was true.
- **Shut down a disproven arm the same day.** The weather test landed August 26; its cron
  wasn't stopped until September 2. That week cost 124 further trades and −$121.23, all of it
  re-confirming something already known.
- **Write the gate before the result, always.** This one I did get right, and it's the reason
  the momentum arm didn't advance on the strength of a profitable month. Deciding in advance
  what would count as evidence is what let me disbelieve a number I wanted to believe.

---

## Reproducing

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python analyze_model_vs_market.py       # Test 1 — weather vs market
python analyze_momentum_vs_market.py    # Test 2 — momentum vs market
python analyze_longshot_bias.py         # Test 3 — is the market itself mispriced?
```

Both read the collected CSVs in the repo root and fetch settlement from Kalshi's public
API (no credentials needed). `analyze_momentum_vs_market.py` caches settlement lookups to
`settlement_cache.csv`, so the first run is slow and later ones are fast; run it before
`analyze_longshot_bias.py`, which reads that cache. Bootstrap seeds are
fixed, so the reported intervals reproduce exactly.
