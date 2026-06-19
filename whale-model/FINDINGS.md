# polywhale — final findings

A research project that asked a simple question: **can you make money on
Polymarket by finding and copying ("tailing") successful whales?** We built the
tooling to test it rigorously and ran the experiment four ways. This is the
record of what we found.

## The original thesis

Big money on small-odds (longshot) bets → those bettors must know something →
copy them → profit. Especially the "insider" shape: a fresh wallet dropping
large size on a longshot right before the market resolves.

## What we built

A Python package (`polywhale`) that:
- ingests Polymarket's public trade tape and per-wallet histories (`ingest`,
  `backfill`, `seed`), resolves market outcomes (`resolve`), into a local SQLite DB;
- scores wallets on **beat-the-odds** — wins vs. price-implied wins, a shrunken
  alpha ratio and a z-score against the efficient-market null — never on raw
  win rate (which just selects favorite-bettors);
- ranks live whale money (`rank`), an EV view (`ev`), a live insider-signature
  screen (`hunt`) with a prospective paper-trading ledger (`ledger`), and a
  per-category specialist test (`specialists`);
- runs unattended via GitHub Actions every ~15 min, alerting on new hits.

Every backtest is **walk-forward**: a wallet is judged using only information
that had resolved *before* each decision, so no hindsight leaks in.

## The four findings — all null

1. **Generalist track-record tailing: no edge.** Wallets that qualified as
   "skilled" performed at exactly the market-implied rate on their *next* bets:
   89 wins vs 89.1 implied over 151 copies.

2. **Insider-signature longshots: not tailable.** Every live hit the screen
   produced was a *sports* match (Australia, Spain, Iraq, Ecuador). Sports is
   where "insider" means match-fixing or a team-news leak — legally radioactive,
   frequently voided, and resolving too fast to act. The actionable *news*
   category produced **zero** hits. The frequency (multiple/day) also argues for
   gamblers, not rare insiders.

3. **Per-category specialists: no edge, at scale.** Scoring wallets per category
   (weather, politics, economy, crypto, sports) and tailing the qualified ones
   walk-forward lost or broke even in every category with a meaningful sample —
   sports 733 tailed bets at −0%, "other" 353 at −4% — while the model claimed
   a +24–28% edge that reality erased. That claim-vs-reality gap is the
   fingerprint of overfitting.

4. **Even the most extreme winners: noise.** Cranking the bar to "overwhelming"
   (≥20 resolved bets, z≥3, ≥$10k positions) produced **zero** specialists in
   weather, politics, economy, and crypto. The only survivors were noise: one
   "other" wallet that looked elite then lost 14% when tailed, and one sports
   wallet at +10% on 47 bets — under one standard deviation, i.e. chance.

## Why tailing structurally cannot work here

The bettors split three ways and none is copyable:
- **The genuinely informed use burner wallets** — one bet, cash out, gone. They
  leave no track record by design, so they can't be identified in advance.
- **The long winning records are mostly lucky survivors** — screen thousands of
  wallets and chance alone produces hot streaks; you find them *after*, and they
  revert to chance the moment you tail them (measured, repeatedly).
- **Genuine skill niches** (e.g. weather) are either too thin to bet, priced off
  public models, or self-erasing once a consistent wallet becomes visible.

The informed leave no trail; the trail-leavers are mostly lucky. Those two facts
are *why* copying fails — not because information doesn't exist, but because
information and copyability are structurally opposed. The market is efficient
against every visible tail-someone strategy.

## What's left running

The GitHub Actions loop still ingests, hunts, and updates `RANKBOARD.md` /
`LEDGER.md` every ~15 min, and alerts on new insider-signature hits. Keep it as
a **curiosity, not a bankroll** — the paper ledger is the only honest scoreboard,
and nothing here has earned real money.

## The real conclusion

The edge is never in copying — anything visible enough to tail is already priced
in. If an edge exists for you on Polymarket, it comes from **your own superior
information or model in a niche you genuinely know** — being the sharp, not
following one. This project's value was proving, for ~$0, which doors are closed.
