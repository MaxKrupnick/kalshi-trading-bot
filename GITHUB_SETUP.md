# GitHub setup — the bits I can't do from here

Everything below needs your GitHub account, so it's a checklist rather than something I ran.

## 1. Make the repo public

It's currently private. A portfolio project nobody can open isn't doing portfolio work.

Before flipping it, here's the security check I already ran on the full history — every
commit, every branch:

- No `.env` was ever committed
- No `kalshi_private_key.pem` was ever committed
- No API keys, tokens, or `BEGIN PRIVATE KEY` blocks anywhere in history
- The only key in the repo is `kalshi_public_key.pem`, which is public by design

Settings → General → Danger Zone → Change visibility → Public.

## 2. Rename the account (do this first)

The account is currently `cktzjcrpdv-netizen`. This is the highest-value item on the page and
it has nothing to do with the code: a link to a random-string username reads as throwaway, and
it undercuts a project whose whole value is credibility.

GitHub renames are free, preserve your commit history and contribution graph, and redirect old
links. Settings → Account → Change username. Do it before the URL is on a résumé, not after.

## 3. Description and topics

Settings are on the repo home page, top right.

**Description:**

> A measurement study of whether Kalshi prediction-market prices can be beaten. Three
> strategies, three falsification tests, three negatives.

**Topics:** `data-science` `prediction-markets` `kalshi` `python` `statistics` `forecasting`
`brier-score` `bootstrap` `quantitative-finance`

## 4. Pin it

Your profile → Customize your pins → include this repo. With a good description it's the
first thing anyone sees.

## 5. What a reader should hit first

The README opens with the three-test results table and links to `FINDINGS.md`. That ordering
is deliberate — the negative result is the strongest thing here, so it leads. Don't bury it
under setup instructions later.
