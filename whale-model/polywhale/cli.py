"""Command-line interface.

  python -m polywhale ingest     # pull the recent whale tape + market resolutions
  python -m polywhale backfill   # pull known wallets' PAST trades -> instant track records
  python -m polywhale rank       # open bets ranked by total whale dollars
  python -m polywhale ev         # open bets ranked by expected value (smart-whale basis)
  python -m polywhale report     # write the top-10 board to Markdown + HTML
  python -m polywhale score      # rank whale wallets by longshot skill
  python -m polywhale signals    # open markets where smart whales are positioned
  python -m polywhale backtest   # walk-forward copy-trade simulation
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone

from . import db
from .api import PolymarketClient
from .backtest import walk_forward
from .config import Config
from .model import score_wallets
from .rank import attach_live_prices, rank_bets
from .report import build_html, build_markdown
from .signals import generate


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def _refresh_markets(con, client):
    """Fetch resolution status for every market we lack, chunk by chunk.

    One bad chunk must never sink the rest: failures are skipped and counted,
    and everything fetched so far stays saved.
    """
    missing = db.condition_ids_missing_or_unresolved(con)
    if not missing:
        print("markets: nothing to refresh")
        return
    chunk, done, failed, found = 20, 0, 0, 0
    for i in range(0, len(missing), chunk):
        batch = missing[i:i + chunk]
        try:
            got = client.markets_by_condition_ids(batch)
            for m in got:
                db.upsert_market(con, m)
            found += len(got)
            done += len(batch)
        except Exception:
            failed += len(batch)
        if i and i % 2000 == 0:
            print(f"  markets: {i}/{len(missing)} checked, {found} found...")
    resolved_n = con.execute(
        "SELECT COUNT(*) c FROM markets WHERE resolved = 1").fetchone()["c"]
    print(f"markets: {done} checked, {found} returned by Gamma"
          + (f", {failed} failed (will retry next run)" if failed else "")
          + f"; db now has {resolved_n} resolved markets")


def cmd_ingest(con, cfg, args):
    client = PolymarketClient()
    try:
        added = db.upsert_trades(
            con, client.iter_large_trades(cfg.ingest_min_cash, max_pages=args.pages))
    except Exception as exc:
        con.commit()
        print(f"(trade fetch interrupted, keeping what we got: {exc})")
        added = "?"
    print(f"trades: +{added} new rows")
    _refresh_markets(con, client)
    total = con.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]
    print(f"db now holds {total} whale trades")


def cmd_resolve(con, cfg, args):
    """Just the market-resolution refresh — finishes an interrupted run."""
    _refresh_markets(con, PolymarketClient())


def cmd_backfill(con, cfg, args):
    """Pull full trade history for every wallet we've seen on the tape.

    This is the fast path to track records: instead of waiting weeks for
    whales' new bets to resolve, fetch their PAST bets (already resolved)
    and score those. Skips wallets backfilled within the last week.
    """
    client = PolymarketClient()
    wallets = db.wallets_needing_backfill(con, max_age_days=args.max_age_days)
    if args.limit:
        wallets = wallets[:args.limit]
    if not wallets:
        print("all known wallets already backfilled recently")
        return
    print(f"backfilling {len(wallets)} wallets "
          f"({args.pages} pages each, this can take a while)...")
    added_total = 0
    for i, wallet in enumerate(wallets, 1):
        try:
            added_total += db.upsert_trades(
                con, client.iter_large_trades(
                    cfg.ingest_min_cash, max_pages=args.pages, user=wallet))
            db.mark_backfilled(con, wallet)
        except Exception as exc:
            con.commit()
            print(f"  {wallet}: fetch failed, skipping ({exc})")
        if i % 25 == 0:
            print(f"  {i}/{len(wallets)} wallets, +{added_total} trades so far")
        time.sleep(args.pause)
    print(f"backfill: +{added_total} historical trades from {len(wallets)} wallets")
    _refresh_markets(con, client)
    print("now run: python3 -m polywhale score   (track records should appear)")


def cmd_stats(con, cfg, args):
    """X-ray every pipeline stage so an empty result can be localized."""
    def one(sql, *p):
        return con.execute(sql, p).fetchone()[0]

    print(f"trades (fills):            {one('SELECT COUNT(*) FROM trades'):,}")
    print(f"  distinct wallets:        {one('SELECT COUNT(DISTINCT wallet) FROM trades'):,}")
    print(f"  distinct markets:        "
          f"{one('SELECT COUNT(DISTINCT condition_id) FROM trades'):,}")
    print(f"  longshot BUY fills:      "
          f"{one('SELECT COUNT(*) FROM trades WHERE side = ? AND price >= ? AND price < ?', 'BUY', cfg.min_price, cfg.max_price):,}"
          f"  (side=BUY, price {cfg.min_price}-{cfg.max_price})")
    print(f"markets rows:              {one('SELECT COUNT(*) FROM markets'):,}")
    print(f"  closed:                  {one('SELECT COUNT(*) FROM markets WHERE closed = 1'):,}")
    print(f"  resolved:                {one('SELECT COUNT(*) FROM markets WHERE resolved = 1'):,}")
    print(f"fills matched to a market: "
          f"{one('SELECT COUNT(*) FROM trades t JOIN markets m ON m.condition_id = t.condition_id'):,}")
    print(f"fills on resolved markets: "
          f"{one('SELECT COUNT(*) FROM trades t JOIN markets m ON m.condition_id = t.condition_id WHERE m.resolved = 1'):,}")
    positions = db.resolved_buy_positions(con, cfg)
    print(f"resolved scoring positions >= ${cfg.scoring_min_cash:,.0f} (all prices): "
          f"{len(positions):,}")

    print("\nsample market rows (eyeball closed/resolved parsing):")
    for r in con.execute("SELECT condition_id, closed, resolved, winning_index "
                         "FROM markets LIMIT 3"):
        print(f"  {r['condition_id'][:20]}...  closed={r['closed']} "
              f"resolved={r['resolved']} winner={r['winning_index']}")
    print("sample trade condition_ids with NO market row (eyeball id format):")
    for r in con.execute(
            """SELECT DISTINCT t.condition_id FROM trades t
               LEFT JOIN markets m ON m.condition_id = t.condition_id
               WHERE m.condition_id IS NULL AND t.condition_id != '' LIMIT 3"""):
        print(f"  {r['condition_id']}")


def cmd_patterns(con, cfg, args):
    """Test the insider thesis on HISTORY: do longshot bets with insider
    signatures (fresh wallet, near close, news category) beat their odds?

    Cohorts are judged exactly like wallets: wins vs price-implied wins,
    shrunken alpha, z against the efficient-market null, realized ROI.
    """
    rows = con.execute(
        """SELECT t.wallet, t.condition_id,
                  SUM(t.cash) AS cash,
                  SUM(t.cash) / SUM(t.size) AS price,
                  MIN(t.ts) AS ts,
                  MAX(m.end_ts) AS end_ts,
                  MAX(m.category) AS category,
                  (t.outcome_index = m.winning_index) AS won,
                  MAX(w.first_ts) AS first_ts
           FROM trades t
           JOIN markets m ON m.condition_id = t.condition_id
           JOIN (SELECT wallet, MIN(ts) AS first_ts
                 FROM trades GROUP BY wallet) w ON w.wallet = t.wallet
           WHERE t.side = 'BUY' AND t.price >= ? AND t.price < ?
             AND m.resolved = 1
           GROUP BY t.wallet, t.condition_id, t.outcome_index
           HAVING SUM(t.cash) >= ?""",
        (cfg.min_price, cfg.max_price, args.patterns_min_cash),
    ).fetchall()
    if not rows:
        sys.exit("no resolved longshot positions at this --min-cash floor")

    day = 86400
    def near_close(r):
        return r["end_ts"] and -day <= r["end_ts"] - r["ts"] <= 7 * day

    def fresh(r):    # caveat: "first seen" is bounded by our backfill window
        return r["ts"] - r["first_ts"] <= 7 * day

    sports = {"Sports", "sports", "NBA", "NFL", "Soccer", "MLB", "NHL", "Esports"}
    def newsy(r):
        return (r["category"] or "") not in sports

    cohorts = [
        ("all longshot whale bets", rows),
        ("near close (<=7d to end)", [r for r in rows if near_close(r)]),
        ("fresh wallet (<=7d old)", [r for r in rows if fresh(r)]),
        ("non-sports category", [r for r in rows if newsy(r)]),
        ("fresh + near close", [r for r in rows if fresh(r) and near_close(r)]),
        ("fresh + near close + non-sports",
         [r for r in rows if fresh(r) and near_close(r) and newsy(r)]),
    ]
    print(f"insider-signature cohorts over resolved longshot positions "
          f">= ${args.patterns_min_cash:,.0f} "
          f"(price {cfg.min_price:.2f}-{cfg.max_price:.2f})\n")
    print(f"{'cohort':<34} {'n':>5} {'wins':>5} {'exp':>7} {'alpha':>6} "
          f"{'z':>6} {'roi':>8}")
    for name, grp in cohorts:
        if not grp:
            print(f"{name:<34} {0:>5}")
            continue
        n = len(grp)
        wins = sum(bool(r["won"]) for r in grp)
        exp = sum(r["price"] for r in grp)
        var = sum(r["price"] * (1 - r["price"]) for r in grp)
        staked = sum(r["cash"] for r in grp)
        payout = sum(r["cash"] / r["price"] for r in grp if r["won"])
        alpha = (wins + cfg.prior_strength) / (exp + cfg.prior_strength)
        z = (wins - exp) / (var ** 0.5) if var > 0 else 0.0
        roi = (payout - staked) / staked if staked else 0.0
        print(f"{name:<34} {n:>5} {wins:>5} {exp:>7.1f} {alpha:>6.2f} "
              f"{z:>6.2f} {roi:>8.1%}")
    print("\nread: alpha > 1 and z >= 2 in a cohort = that signature beats its "
          "odds; positive roi = it made money. 'fresh' is bounded by the "
          "backfill window, so treat it as approximate.")


def cmd_hunt(con, cfg, args):
    """Live insider-signature screen — the cohort that tested best on
    history: FRESH wallets holding BIG open longshots NEAR market close.

    Unlike rank (consensus dollars) this surfaces individual positions
    matching the signature, newest wallet money first.
    """
    now = int(time.time())
    since = now - cfg.signal_window_days * 86400
    day = 86400
    rows = con.execute(
        """SELECT t.wallet, MAX(t.pseudonym) AS pseudonym, t.condition_id,
                  MAX(t.outcome) AS outcome, t.outcome_index,
                  SUM(t.cash) AS cash,
                  SUM(t.cash) / SUM(t.size) AS price,
                  MIN(t.ts) AS ts,
                  MAX(t.title) AS title,
                  MAX(t.event_slug) AS event_slug,
                  MAX(m.end_ts) AS end_ts,
                  MAX(w.first_ts) AS first_ts
           FROM trades t
           LEFT JOIN markets m ON m.condition_id = t.condition_id
           JOIN (SELECT wallet, MIN(ts) AS first_ts
                 FROM trades GROUP BY wallet) w ON w.wallet = t.wallet
           WHERE t.side = 'BUY' AND t.price >= ? AND t.price < ?
             AND t.ts >= ? AND COALESCE(m.resolved, 0) = 0
           GROUP BY t.wallet, t.condition_id, t.outcome_index
           HAVING SUM(t.cash) >= ?""",
        (cfg.min_price, cfg.max_price, since, cfg.min_position_cash),
    ).fetchall()

    hits = [r for r in rows
            if r["ts"] - r["first_ts"] <= args.max_wallet_age * day
            and r["end_ts"] is not None
            and 0 <= r["end_ts"] - now <= args.days_to_end * day
            # Concentration: keep only burners that exist to make one bet.
            # A wallet sprayed across many markets is a volume/hedge bettor,
            # not insider conviction (see Aching-Frustration-Victim, 2026-06).
            and db.wallet_distinct_markets(con, r["wallet"]) <= args.max_markets]
    hits.sort(key=lambda r: -r["cash"])
    if not hits:
        print(f"no live signature hits (fresh wallet <= {args.max_wallet_age}d, "
              f"<= {args.max_markets} markets, "
              f"position >= ${cfg.min_position_cash:,.0f} at "
              f"{cfg.min_price:.2f}-{cfg.max_price:.2f}, "
              f"market ends <= {args.days_to_end}d) — re-run after the next ingest")
        return

    prices = {}
    try:
        client = PolymarketClient()
        for m in client.markets_by_condition_ids({r["condition_id"] for r in hits}):
            ps = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
            prices[m.get("conditionId")] = ps
    except Exception:
        pass

    recorded = 0
    for r in hits:    # every hit enters the prospective ledger, shown or not
        ps = prices.get(r["condition_id"]) or []
        rec = (ps[r["outcome_index"]]
               if 0 <= r["outcome_index"] < len(ps) else r["price"])
        recorded += db.record_paper_bet(con, r, rec, now)

    print(f"live insider-signature positions (historical cohort: alpha 1.37, "
          f"+150% roi on n=30 — suggestive, not proven)")
    print(f"ledger: {recorded} new paper bets recorded "
          f"(`ledger` shows the running record)\n")
    for i, r in enumerate(hits[:args.top], 1):
        ps = prices.get(r["condition_id"]) or []
        now_p = (f"{ps[r['outcome_index']]:.2f}"
                 if 0 <= r["outcome_index"] < len(ps) else "n/a")
        wallet_age = (r["ts"] - r["first_ts"]) / day
        ends_in = (r["end_ts"] - now) / day
        print(f"{i:>2}. {r['title']}  ->  {r['outcome']}")
        print(f"    {r['pseudonym'] or r['wallet']}: ${r['cash']:,.0f} @ "
              f"{r['price']:.2f} (now {now_p})"
              f" | wallet {wallet_age:.1f}d old at entry"
              f" | market ends in {ends_in:.1f}d")
        if r["event_slug"]:
            print(f"    https://polymarket.com/event/{r['event_slug']}")
        print()


def cmd_ledger(con, cfg, args):
    """The prospective record: every hunt hit, graded as markets resolve.

    This is the survivorship-free validation of the insider signature —
    judge the strategy on THESE numbers, not the historical cohorts.
    """
    graded_now = db.grade_paper_bets(con)
    if graded_now:
        print(f"(graded {graded_now} newly resolved bets)")
    rows = con.execute(
        "SELECT * FROM paper_bets ORDER BY recorded_ts").fetchall()

    lines = []
    if not rows:
        lines.append("ledger is empty — run `hunt` after each ingest; hits are "
                     "recorded automatically")
    else:
        graded = [r for r in rows if r["won"] is not None]
        pending = [r for r in rows if r["won"] is None]
        stake = args.stake
        if graded:
            wins = sum(r["won"] for r in graded)
            exp = sum(r["rec_price"] for r in graded)
            var = sum(r["rec_price"] * (1 - r["rec_price"]) for r in graded)
            profit = sum(stake * (1 / r["rec_price"] - 1) if r["won"] else -stake
                         for r in graded)
            alpha = (wins + cfg.prior_strength) / (exp + cfg.prior_strength)
            z = (wins - exp) / (var ** 0.5) if var > 0 else 0.0
            lines.append(f"graded: {len(graded)} bets | wins {wins} vs "
                         f"{exp:.1f} implied | alpha {alpha:.2f} | z {z:.2f}")
            lines.append(f"paper P&L at ${stake:,.0f}/bet: ${profit:,.0f} "
                         f"({profit / (stake * len(graded)):+.1%} ROI)")
            lines.append("")
            for r in graded[-10:]:
                mark = "WON " if r["won"] else "lost"
                lines.append(f"  {mark} {r['title']}  ->  {r['outcome']} "
                             f"@ {r['rec_price']:.2f}")
            lines.append("")
        if pending:
            lines.append(f"open: {len(pending)} bets awaiting resolution")
            for r in pending[-10:]:
                lines.append(f"  {_fmt_ts(r['recorded_ts'])}  {r['title']}  ->  "
                             f"{r['outcome']} @ {r['rec_price']:.2f} "
                             f"(whale ${r['whale_cash']:,.0f})")
        if not graded:
            lines.append("")
            lines.append("no graded bets yet — verdicts appear as markets resolve")

    print("\n".join(lines))
    if args.out:
        with open(args.out, "w") as f:
            f.write("# Paper-trading ledger (prospective, survivorship-free)\n\n"
                    f"_Updated {_fmt_ts(int(time.time()))} UTC_\n\n```\n"
                    + "\n".join(lines) + "\n```\n")
        print(f"\nwrote {args.out}")


def cmd_rank(con, cfg, args):
    bets = rank_bets(con, cfg, window_days=args.days)
    if not bets:
        print("no open whale longshot bets in window — run `ingest` first or widen --days")
        return
    shown = bets[:args.top]
    if not args.no_live:
        try:
            attach_live_prices(shown, PolymarketClient())
        except Exception as exc:
            print(f"(live prices unavailable: {exc})\n")
    print(f"open bets ranked by total whale notional "
          f"(positions >= ${cfg.min_position_cash:,.0f}, "
          f"entry {cfg.min_price:.2f}-{cfg.max_price:.2f}, "
          f"last {args.days or cfg.signal_window_days}d)\n")
    now_ts = int(time.time())
    for i, b in enumerate(shown, 1):
        if b.current_price is None:
            now = "now n/a"
        else:
            drift = b.current_price - b.weighted_entry
            now = f"now {b.current_price:.2f} ({drift:+.2f} vs whales)"
        print(f"{i:>2}. {b.title}  ->  {b.outcome}")
        print(f"    total ${b.total_notional:,.0f} across {b.n_whales} whales"
              f" ({b.n_trades} trades)"
              f" | smart money ${b.smart_notional:,.0f}"
              f" | avg entry {b.weighted_entry:.2f} | {now}"
              f" | latest {_fmt_ts(b.latest_ts)}")
        patterns = []
        if b.end_ts:
            days = (b.end_ts - now_ts) / 86400
            patterns.append(f"ends in {days:.1f}d" if days >= 0 else "past scheduled end")
        if b.total_notional:
            if b.burst_notional / b.total_notional >= 0.5:
                patterns.append(f"{b.burst_notional / b.total_notional:.0%} of money "
                                f"arrived in last {cfg.burst_hours}h")
            if b.fresh_notional / b.total_notional >= 0.3:
                patterns.append(f"{b.fresh_notional / b.total_notional:.0%} from "
                                f"fresh wallets")
        if patterns:
            print(f"    pattern: {' | '.join(patterns)}")
        for name, cash, is_smart, tags in b.top_wallets[:args.wallets]:
            labels = (["smart"] if is_smart else []) + ([tags] if tags else [])
            suffix = f"  [{', '.join(labels)}]" if labels else ""
            print(f"      {name:<24} ${cash:,.0f}{suffix}")
        if b.event_slug:
            print(f"    https://polymarket.com/event/{b.event_slug}")
        print()


def cmd_ev(con, cfg, args):
    """Rank open bets by expected value at the CURRENT price."""
    bets = [b for b in rank_bets(con, cfg, window_days=args.days)
            if b.q_smart is not None]
    if not bets:
        print("no EV-rated bets yet: EV needs qualified smart whales holding open\n"
              "positions, which needs resolved history in the DB — keep ingesting\n"
              "daily (or backfill from Dune), then re-run.")
        return
    try:
        attach_live_prices(bets, PolymarketClient())
    except Exception as exc:
        print(f"(live prices unavailable — EV needs current prices: {exc})")
        return
    rated = sorted(
        ((b.expected_value(), b) for b in bets if b.expected_value() is not None),
        key=lambda x: -x[0],
    )
    shown = [(ev, b) for ev, b in rated if ev >= args.min_ev]
    if not shown:
        best = rated[0][0] if rated else None
        print("no open bet clears the EV bar right now"
              + (f" (best is {best:+.0%})" if best is not None else ""))
        return
    print(f"open bets by expected value at current price "
          f"(smart-whale basis, min EV {args.min_ev:+.0%})")
    print("note: EV assumes wallets' past alpha persists — verify with "
          "`backtest --all-prices` before trusting\n")
    for i, (ev, b) in enumerate(shown[:args.top], 1):
        print(f"{i:>2}. EV {ev:+.0%}  {b.title}  ->  {b.outcome}")
        print(f"    model prob {b.q_smart:.2f} vs price {b.current_price:.2f}"
              f" | smart ${b.smart_notional:,.0f} of ${b.total_notional:,.0f}"
              f" | whales entered {b.weighted_entry:.2f}"
              f" | latest {_fmt_ts(b.latest_ts)}")
        for name, cash, is_smart, tags in b.top_wallets[:3]:
            if is_smart:
                print(f"      {name:<24} ${cash:,.0f}  [smart{',' + tags if tags else ''}]")
        if b.event_slug:
            print(f"    https://polymarket.com/event/{b.event_slug}")
        print()


def cmd_report(con, cfg, args):
    bets = rank_bets(con, cfg, window_days=args.days)[:args.top]
    if not args.no_live:
        try:
            attach_live_prices(bets, PolymarketClient())
        except Exception as exc:
            print(f"(live prices unavailable: {exc})")
    now_ts = int(time.time())
    with open(args.out_md, "w") as f:
        f.write(build_markdown(bets, cfg, now_ts))
    with open(args.out_html, "w") as f:
        f.write(build_html(bets, cfg, now_ts))
    print(f"wrote {len(bets)} bets -> {args.out_md}, {args.out_html}")


def cmd_score(con, cfg, args):
    scores = score_wallets(
        db.resolved_buy_positions(con, cfg), cfg.prior_strength)
    if not scores:
        sys.exit("no resolved positions yet — run `ingest`/`backfill` then `resolve`")
    # Wallets with real samples first: qualified, then by z among n >= min_n.
    scores.sort(key=lambda s: (not s.qualifies(cfg), s.n < args.min_n, -s.z))
    print(f"track records over ALL resolved buys (n = positions, "
          f"smart bar: n >= {cfg.min_resolved}, z >= {cfg.min_z}, "
          f"alpha >= {cfg.min_alpha})\n")
    print(f"{'wallet':<24} {'n':>4} {'wins':>5} {'exp':>6} {'alpha':>6} "
          f"{'z':>6} {'staked':>12} {'roi':>8}  smart")
    for s in scores[:args.top]:
        name = (s.pseudonym or s.wallet)[:24]
        print(f"{name:<24} {s.n:>4} {s.wins:>5} {s.expected_wins:>6.1f} "
              f"{s.alpha:>6.2f} {s.z:>6.2f} {s.staked:>12,.0f} {s.roi:>8.1%}"
              f"  {'YES' if s.qualifies(cfg) else ''}")


def cmd_signals(con, cfg, args):
    sigs = generate(con, cfg)
    if not sigs:
        print("no live smart-whale signals (need qualified wallets with fresh open bets)")
        return
    for s in sigs[:args.top]:
        url = f"https://polymarket.com/event/{s.event_slug}" if s.event_slug else ""
        print(f"\n  {s.title}  ->  {s.outcome}")
        print(f"  smart notional ${s.smart_notional:,.0f}"
              f" | avg entry {s.weighted_entry:.2f}"
              f" | latest {_fmt_ts(s.latest_ts)}")
        for name, z, cash in s.wallets[:5]:
            print(f"    {name:<24} z={z:<6} ${cash:,.0f}")
        if url:
            print(f"  {url}")


def cmd_backtest(con, cfg, args):
    rows = db.resolved_buy_positions(con, cfg)
    if not rows:
        sys.exit("no resolved positions yet — run `ingest`/`backfill` then `resolve`")
    res = walk_forward(rows, cfg, stake=args.stake,
                       copy_all_prices=args.all_prices)
    strategy = ("copy qualified whales at ALL prices" if args.all_prices
                else f"copy qualified whales' longshots only "
                     f"({cfg.min_price:.2f}-{cfg.max_price:.2f})")
    print(f"strategy:       {strategy}")
    print(f"copied bets:    {res.copied}")
    print(f"hit rate:       {res.wins}/{res.copied}"
          f" (implied {res.expected_wins:.1f})" if res.copied else "hit rate:       n/a")
    print(f"total staked:   ${res.staked:,.0f}")
    print(f"profit:         ${res.profit:,.0f}")
    print(f"ROI:            {res.roi:.1%}")
    gap = res.predicted_ev - res.roi
    verdict = ("EV claims SUPPORTED by realized results"
               if res.copied >= 50 and abs(gap) < 0.15 else
               "EV claims NOT supported — do not trust the ev screen"
               if res.copied >= 50 else
               "sample too small to judge calibration")
    print(f"model EV claim: {res.predicted_ev:.1%}  ({verdict})")
    top = sorted(res.by_wallet.items(), key=lambda kv: -kv[1]["profit"])[:10]
    if top:
        print("\ntop copied wallets:")
        for name, agg in top:
            print(f"  {name:<24} copied={agg['copied']:<4} pnl=${agg['profit']:,.0f}")


def main():
    parser = argparse.ArgumentParser(prog="polywhale")
    parser.add_argument("--db", default=None, help="sqlite path (default polywhale.db)")
    parser.add_argument("--min-cash", type=float, default=None,
                        help="whale position notional floor")
    parser.add_argument("--min-price", type=float, default=None, help="longshot price floor")
    parser.add_argument("--max-price", type=float, default=None, help="longshot price ceiling")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="pull recent large trades + resolutions")
    p.add_argument("--pages", type=int, default=40)

    p = sub.add_parser("backfill", help="pull trade history for known wallets")
    p.add_argument("--pages", type=int, default=4,
                   help="history pages per wallet (500 trades each)")
    p.add_argument("--limit", type=int, default=None, help="max wallets this run")
    p.add_argument("--max-age-days", type=int, default=7,
                   help="re-backfill wallets older than this")
    p.add_argument("--pause", type=float, default=0.2,
                   help="seconds between wallets (be polite to the API)")

    sub.add_parser("resolve", help="refresh market resolutions only")
    sub.add_parser("stats", help="pipeline diagnostics: counts at every stage")

    p = sub.add_parser("patterns", help="test insider signatures on history")
    p.add_argument("--min-cash", dest="patterns_min_cash", type=float,
                   default=5_000.0,
                   help="position floor for the cohort study (default $5k)")

    p = sub.add_parser("hunt", help="live insider-signature screen")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--max-wallet-age", type=float, default=7.0,
                   help="wallet age in days at entry to count as fresh")
    p.add_argument("--days-to-end", type=float, default=7.0,
                   help="market must end within this many days")
    p.add_argument("--max-markets", type=int, default=Config().burner_max_markets,
                   help="max distinct markets the wallet may have bet on (concentration)")

    p = sub.add_parser("ledger", help="prospective paper-trading record")
    p.add_argument("--stake", type=float, default=100.0)
    p.add_argument("--out", default=None, help="also write the record to a markdown file")

    p = sub.add_parser("rank", help="open bets ranked by total whale dollars")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--days", type=int, default=None, help="lookback window (default config)")
    p.add_argument("--wallets", type=int, default=3, help="top wallets shown per bet")
    p.add_argument("--no-live", action="store_true",
                   help="skip fetching current prices from Gamma")

    p = sub.add_parser("ev", help="open bets ranked by expected value")
    p.add_argument("--top", type=int, default=15)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--min-ev", type=float, default=0.10,
                   help="minimum EV per $1 to show (default +10%%)")

    p = sub.add_parser("report", help="write top-N board to Markdown + HTML")
    p.add_argument("--top", type=int, default=10)
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--out-md", default="RANKBOARD.md")
    p.add_argument("--out-html", default="board.html")
    p.add_argument("--no-live", action="store_true")

    p = sub.add_parser("score", help="rank whale wallets")
    p.add_argument("--top", type=int, default=30)
    p.add_argument("--min-n", type=int, default=5,
                   help="bury wallets with fewer resolved positions than this")

    p = sub.add_parser("signals", help="live smart-whale positions")
    p.add_argument("--top", type=int, default=15)

    p = sub.add_parser("backtest", help="walk-forward copy simulation")
    p.add_argument("--stake", type=float, default=100.0)
    p.add_argument("--all-prices", action="store_true",
                   help="copy qualified whales at all prices, not just longshots")

    args = parser.parse_args()
    cfg = Config()
    if args.db:
        cfg.db_path = args.db
    if args.min_cash is not None:
        cfg.min_position_cash = args.min_cash
    if args.min_price is not None:
        cfg.min_price = args.min_price
    if args.max_price is not None:
        cfg.max_price = args.max_price

    con = db.connect(cfg.db_path)
    {"ingest": cmd_ingest, "backfill": cmd_backfill, "resolve": cmd_resolve,
     "stats": cmd_stats, "patterns": cmd_patterns, "hunt": cmd_hunt,
     "ledger": cmd_ledger, "rank": cmd_rank, "ev": cmd_ev,
     "report": cmd_report, "score": cmd_score, "signals": cmd_signals,
     "backtest": cmd_backtest}[args.command](con, cfg, args)


if __name__ == "__main__":
    main()
