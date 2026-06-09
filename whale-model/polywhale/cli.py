"""Command-line interface.

  python -m polywhale ingest     # pull recent >=$10k trades + market resolutions
  python -m polywhale rank       # open bets ranked by total whale dollars
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
from .signals import generate


def _fmt_ts(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def cmd_ingest(con, cfg, args):
    client = PolymarketClient()
    added = db.upsert_trades(
        con, client.iter_large_trades(cfg.min_cash, max_pages=args.pages))
    print(f"trades: +{added} new rows")

    missing = db.condition_ids_missing_or_unresolved(con)
    if missing:
        markets = client.markets_by_condition_ids(missing)
        for m in markets:
            db.upsert_market(con, m)
        print(f"markets: refreshed {len(markets)} of {len(missing)} unresolved")
    total = con.execute("SELECT COUNT(*) c FROM trades").fetchone()["c"]
    print(f"db now holds {total} whale trades")


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
          f"(>= ${cfg.min_cash:,.0f}/trade, entry < {cfg.max_price:.2f}, "
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


def cmd_score(con, cfg, args):
    scores = score_wallets(
        db.resolved_longshot_buys(con, cfg.max_price), cfg.prior_strength)
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
    rows = db.resolved_longshot_buys(con, cfg.max_price)
    if not rows:
        sys.exit("no resolved longshot bets yet — run `ingest` first")
    res = walk_forward(rows, cfg, stake=args.stake)
    print(f"copied bets:    {res.copied}")
    print(f"hit rate:       {res.wins}/{res.copied}"
          f" (implied {res.expected_wins:.1f})" if res.copied else "hit rate:       n/a")
    print(f"total staked:   ${res.staked:,.0f}")
    print(f"profit:         ${res.profit:,.0f}")
    print(f"ROI:            {res.roi:.1%}")
    top = sorted(res.by_wallet.items(), key=lambda kv: -kv[1]["profit"])[:10]
    if top:
        print("\ntop copied wallets:")
        for name, agg in top:
            print(f"  {name:<24} copied={agg['copied']:<4} pnl=${agg['profit']:,.0f}")


def main():
    parser = argparse.ArgumentParser(prog="polywhale")
    parser.add_argument("--db", default=None, help="sqlite path (default polywhale.db)")
    parser.add_argument("--min-cash", type=float, default=None, help="whale notional floor")
    parser.add_argument("--max-price", type=float, default=None, help="longshot price ceiling")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("ingest", help="pull recent large trades + resolutions")
    p.add_argument("--pages", type=int, default=40)

    p = sub.add_parser("rank", help="open bets ranked by total whale dollars")
    p.add_argument("--top", type=int, default=20)
    p.add_argument("--days", type=int, default=None, help="lookback window (default config)")
    p.add_argument("--wallets", type=int, default=3, help="top wallets shown per bet")
    p.add_argument("--no-live", action="store_true",
                   help="skip fetching current prices from Gamma")

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
        cfg.min_cash = args.min_cash
    if args.max_price is not None:
        cfg.max_price = args.max_price

    con = db.connect(cfg.db_path)
    {"ingest": cmd_ingest, "rank": cmd_rank, "score": cmd_score,
     "signals": cmd_signals, "backtest": cmd_backtest}[args.command](con, cfg, args)


if __name__ == "__main__":
    main()
