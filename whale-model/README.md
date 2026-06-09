# polywhale — finding value in Polymarket whales

A pipeline that tracks **whales** — wallets placing **≥ $10k** on outcomes priced
**below 20¢** (longshots), across every category — and answers the only question
that matters: *which of these whales actually beat the odds they pay, and where
are they positioned right now?*

Polymarket runs on Polygon, so every fill is public and attributable to a wallet.
This tool pulls the trade tape, joins it to market resolutions, separates skilled
whales from lucky ones statistically, and surfaces their live positions.

## The model

**Null hypothesis:** markets are efficient — a bet entered at price *p* wins with
probability *p*. A whale only has value if their longshots land **more often than
their entry prices imply**.

For each wallet, over its resolved sub-20¢ buys:

| quantity | meaning |
|---|---|
| `expected_wins = Σ pᵢ` | wins implied by entry prices under the null |
| `alpha = (wins + c) / (Σ pᵢ + c)` | outperformance ratio, shrunk toward 1 by prior strength *c* — kills small-sample flukes (a 2-for-2 whale can't outrank a 30-for-100 whale) |
| `z = (wins − Σ pᵢ) / √(Σ pᵢ(1−pᵢ))` | how many standard deviations the wallet beats the efficient-market null |

A wallet **qualifies as smart** when it has ≥ 5 resolved longshots, `alpha ≥ 1.15`,
and `z ≥ 1.0` (all configurable in `polywhale/config.py` or via CLI flags).

**Why not just rank by ROI?** Longshot ROI is brutally noisy — one 15¢ hit pays
+566% and dominates everything. Counting wins vs. price-implied wins is far more
stable, and the z-score tells you whether the record could plausibly be luck.

## Usage

```bash
pip install -r requirements.txt

python -m polywhale ingest      # pull recent ≥$10k trades + market resolutions
python -m polywhale rank        # open bets ranked by total whale dollars
python -m polywhale score       # rank whale wallets (alpha, z, ROI, smart flag)
python -m polywhale signals     # open markets where smart whales hold fresh longshots
python -m polywhale backtest    # walk-forward copy-trade simulation
```

Flags: `--min-cash 25000`, `--max-price 0.10`, `--db path.db` work on every command.

**`rank` is the consensus view:** every open market/outcome with criteria-fitting
trades (≥ $10k at < 20¢), ranked by **total notional wagered across all whales** —
with whale count, trade count, weighted average entry, and how much of the pile
comes from statistically qualified wallets (`[smart]`). `--days` controls the
lookback window, `--wallets` how many top wallets are shown per bet. `signals`
is the stricter cut of the same data: only bets backed by proven whales.

The **backtest** is strictly walk-forward: at each historical bet it asks whether
the wallet *already* qualified using only markets resolved before that moment,
then copies with a fixed stake. No hindsight leaks into the decision.

**Validation:** `python tests/smoke_test.py` runs the model on synthetic wallets
with known skill. Wallets with a true 2× edge all rank top and produce +50%+
walk-forward copy ROI; zero-edge wallets are rejected and their copy ROI is ≈ −fees.

## Operating it

- The Data API only pages back through a recent window of the tape. **Run
  `ingest` on a schedule** (e.g. cron every 15–60 min); the SQLite DB accumulates
  history and dedupes automatically. The more weeks of tape you collect, the more
  wallets clear the 5-resolved-bets bar.
- To backfill years of history at once, pull Polymarket's unified dataset on
  [Dune Analytics](https://dune.com/datadashboards/prediction-markets) and load it
  into the `trades` table — the model code doesn't care where rows came from.

## Honest caveats

- **Selection effects:** a whale buying 15¢ may be hedging an opposite position
  elsewhere, market-making, or exiting via a wash — the tape can't tell you intent.
- **Longshot bias is real:** the literature says retail *overpays* for longshots,
  so the average sub-20¢ buy is −EV. The whole edge here is conditioning on wallets
  with statistically proven records — copy the qualified set, never the firehose.
- **Capacity:** these books are thin; copying a $50k whale entry moves the price.
  Signals are best treated as research input, not auto-execution.
