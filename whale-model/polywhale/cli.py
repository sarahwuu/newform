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
    chunk, done, failed = 20, 0, 0
    for i in range(0, len(missing), chunk):
        batch = missing[i:i + chunk]
        try:
            for m in client.markets_by_condition_ids(batch):
                db.upsert_market(con, m)
            done += len(batch)
        except Exception:
            failed += len(batch)
        if i and i % 2000 == 0:
            print(f"  markets: {i}/{len(missing)} checked...")
    print(f"markets: refreshed {done} of {len(missing)}"
          + (f" ({failed} failed, will retry next run)" if failed else ""))


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
          f"(smart-whale basis, min EV {args.min_ev:+.0%})\n")
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
        db.resolved_longshot_buys(con, cfg), cfg.prior_strength)
    if not scores:
        sys.exit("no resolved longshot bets yet — run `ingest` first (and let markets resolve)")
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
    rows = db.resolved_longshot_buys(con, cfg)
    if not rows:
        sys.exit("no resolved longshot bets yet — run `ingest` first")
    res = walk_forward(rows, cfg, stake=args.stake)
    print(f"copied bets:    {res.copied}")
    print(f"hit rate:       {res.wins}/{res.copied}"
          f" (implied {res.expected_wins:.1f})" if res.copied else "hit rate:       n/a")
    print(f"total staked:   ${res.staked:,.0f}")
    print(f"profit:         ${res.profit:,.0f}")
    print(f"ROI:            {res.roi:.1%}")
    print(f"model EV claim: {res.predicted_ev:.1%}  "
          f"(close to ROI = EV estimates are honest)")
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

    p = sub.add_parser("signals", help="live smart-whale positions")
    p.add_argument("--top", type=int, default=15)

    p = sub.add_parser("backtest", help="walk-forward copy simulation")
    p.add_argument("--stake", type=float, default=100.0)

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
     "rank": cmd_rank, "ev": cmd_ev, "report": cmd_report, "score": cmd_score,
     "signals": cmd_signals, "backtest": cmd_backtest}[args.command](con, cfg, args)


if __name__ == "__main__":
    main()
