import csv
import random

PAPER_TRADES_FILE = "paper_trades.csv"
N_SIMULATIONS = 20000

# Null hypothesis this tests: each trade's true win probability equals the
# price actually paid (entry_price) -- i.e. the market was fair at the
# moment of purchase and any "edge" the model saw was noise, not signal.
# If that's true, realized P&L is a random draw from the distribution below;
# if the model has real edge, realized P&L should land in the distribution's
# tail more often than chance. This is deliberately the skeptical null, not
# a test of whether the *model's own* probability was right -- we don't have
# enough resolved history yet to test that directly without just refitting
# to noise.


def load_resolved(source=None):
    with open(PAPER_TRADES_FILE, newline="") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "resolved"]
    if source:
        rows = [r for r in rows if r["source"] == source]
    return rows


def trade_payoffs(row):
    """(win_profit, lose_profit, p) for one trade, p = price paid = the null
    hypothesis's assumed true win probability."""
    p = float(row["entry_price"])
    size = float(row["position_size_dollars"])
    contracts = float(row["contracts"])
    win_profit = contracts - size
    lose_profit = -size
    return win_profit, lose_profit, p


def simulate_null_pnl(trades, rng):
    total = 0.0
    for win_profit, lose_profit, p in trades:
        total += win_profit if rng.random() < p else lose_profit
    return total


def actual_pnl(rows):
    return sum(float(r["pnl"]) for r in rows)


def run_test(name, rows):
    if not rows:
        print(f"{name}: no resolved trades, skipping")
        return

    trades = [trade_payoffs(r) for r in rows]
    actual = actual_pnl(rows)

    rng = random.Random(42)  # fixed seed -- reproducible, not cherry-picked
    sims = [simulate_null_pnl(trades, rng) for _ in range(N_SIMULATIONS)]
    sims.sort()

    mean_null = sum(sims) / len(sims)
    # two-sided: how often does the null produce a result at least as extreme as actual
    if actual <= mean_null:
        extreme = sum(1 for s in sims if s <= actual)
    else:
        extreme = sum(1 for s in sims if s >= actual)
    p_value = extreme / len(sims)
    percentile = sum(1 for s in sims if s <= actual) / len(sims) * 100

    variance = sum((s - mean_null) ** 2 for s in sims) / len(sims)
    std_null = variance ** 0.5
    z = (actual - mean_null) / std_null if std_null > 0 else float("nan")

    print(f"{name}: n={len(rows)} trades")
    print(f"  Actual P&L:        ${actual:+.2f}")
    print(f"  Null-hypothesis mean P&L (market was fair): ${mean_null:+.2f} (std ${std_null:.2f})")
    print(f"  Actual sits at the {percentile:.1f}th percentile of the null distribution (z={z:+.2f})")
    print(f"  Two-sided p-value: {p_value:.3f}"
          f"{'  <-- below 0.05, statistically notable' if p_value < 0.05 else ''}")
    print()


if __name__ == "__main__":
    all_resolved = load_resolved()
    print(f"Monte Carlo null test ({N_SIMULATIONS} simulations): if the market's price was exactly "
          f"the true probability at entry (i.e. no real edge), how often would we see P&L this "
          f"extreme by chance alone?\n")

    run_test("All sources", all_resolved)
    for source in sorted({r["source"] for r in all_resolved}):
        run_test(source.capitalize(), load_resolved(source))

    print("Caveat: with only a few dozen resolved trades this test has low statistical power -- "
          "a p-value here that isn't significant does NOT confirm there's no edge, only that "
          "there isn't yet enough evidence to distinguish edge from noise. Re-run as more trades "
          "resolve; the read gets more trustworthy with n, not with time.")
