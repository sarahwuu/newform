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
comes from statistically qualified wallets (`[smart]`). It also fetches the
**current Gamma price** and shows the drift vs. the whales' average entry, so you
can tell a bet you can still join from one you'd be chasing (`--no-live` skips
the fetch). `--days` controls the lookback window, `--wallets` how many top
wallets are shown per bet. `signals` is the stricter cut of the same data: only
bets backed by proven whales.

**Freshness:** the Data API is the live tape — fills appear within seconds — so
the board is as current as your last `ingest`. Run it on a schedule and re-run
`rank` whenever you're about to act; the current-price column is fetched at
display time, not ingest time.

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

## Nuances & threat model

The thesis "big money on small odds = someone knows something" is *sometimes*
right (documented cases exist: pre-announcement buying on Nobel Peace Prize and
pardon markets). But the tape is full of things that look like insider conviction
and aren't. What the model does about each:

**Fills are not bets.** A whale sweeping the book in 10 fills made one decision.
Scoring aggregates fills into positions per (wallet, market, outcome) with a
share-weighted entry — otherwise the biggest traders get fake sample sizes and
inflated z-scores.

**Luck looks like skill at scale.** Scan 10,000 wallets and z ≥ 1 anoints ~1,600
zero-edge gamblers. Defaults are min 8 resolved positions and z ≥ 2.0; raise
them further as your DB grows. This is also the direct answer to "rich idiots
who gamble": they fail the z-test, because winning *a lot by count* is not the
bar — winning **more than entry prices imply** is. (A great longshot whale still
loses most bets; 30% hits on 10¢ entries is a 3× edge.)

**Insiders use burner wallets.** A track-record filter can never catch the
sharpest pattern: fresh wallet, one huge longshot, right before resolution.
`rank` flags it instead of filtering for it — `fresh` wallet tags, the share of
money that arrived in the last 24h, and time until the market's scheduled end.
Fresh + late + concentrated is the burner-insider signature. (Caveat: "fresh"
is judged against your local DB window, so backfill history before trusting it.)

**Conviction can be a hedge.** Buying 15¢ on one outcome while holding other
outcomes of the same event is rebalancing or sum-of-longshots arbitrage, not a
view. Wallets that also traded other outcomes of the event get a `hedged` tag.

**A sub-20¢ "BUY" isn't always an entry.** On a binary CLOB, buying YES at 12¢
is mechanically selling NO at 88¢ — some prints are unwinds of the other side.
Cross-checking the Data API `/positions` endpoint to confirm the wallet still
holds the position is the upgrade path here.

**Whale-watching is reflexive.** Copy-trading tools mean one whale's entry gets
echoed by bots within minutes (inflating "distinct whale" counts), and the
strategy can be deliberately baited: pump a longshot to create the appearance of
smart money, then exit into the copiers. Entry-time clustering across wallets is
a warning sign, and the drift-vs-entry column tells you when you're the exit
liquidity.

**Resolution is a rules game.** Some whales buy cheap YES because they've read
the resolution criteria and see a technicality, and UMA disputes can resolve
against the spirit of the question. Never copy a bet without reading the rules.

**Statistical honesty.** Bets within one event resolve together (correlated, so
z is overstated for event-concentrated wallets); the backtest uses scheduled end
date as the resolution timestamp; and your DB only sees the tape since you
started ingesting — early losses of "proven" wallets may be invisible
(survivorship). Backfilling from Dune mitigates the last one.

**Execution.** Books are thin — the whale's entry already moved the price, and
your size will too. Polymarket access is geo-restricted in some jurisdictions;
trading on copied signals that ultimately derive from material non-public
information can carry legal risk depending on where you are and the market.
Treat the board as a screener for homework, size small, never auto-execute.
