"""Render the whale rank board as Markdown (GitHub-viewable) and HTML."""

import html
from datetime import datetime, timezone

POLYMARKET_EVENT = "https://polymarket.com/event/"


def _now_label(ts=None):
    dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def _patterns(b, cfg, now_ts):
    out = []
    if b.end_ts:
        days = (b.end_ts - now_ts) / 86400
        out.append(f"ends {days:.1f}d" if days >= 0 else "past scheduled end")
    if b.total_notional:
        burst = b.burst_notional / b.total_notional
        fresh = b.fresh_notional / b.total_notional
        if burst >= 0.5:
            out.append(f"{burst:.0%} in last {cfg.burst_hours}h")
        if fresh >= 0.3:
            out.append(f"{fresh:.0%} fresh wallets")
    return out


def _now_cell(b):
    if b.current_price is None:
        return "n/a"
    return f"{b.current_price:.2f} ({b.current_price - b.weighted_entry:+.2f})"


def build_markdown(bets, cfg, now_ts):
    lines = [
        "# 🐋 Whale Rank Board — Top 10",
        "",
        f"_Updated {_now_label(now_ts)} · criteria: whale positions ≥ "
        f"${cfg.min_position_cash:,.0f} entered at {cfg.min_price:.2f}–"
        f"{cfg.max_price:.2f} · lookback {cfg.signal_window_days}d · "
        f"ranked by total whale notional_",
        "",
        "| # | Bet | Whale $ | Whales | Smart $ | Entry | Now | Patterns |",
        "|--:|-----|--------:|-------:|--------:|------:|----:|----------|",
    ]
    for i, b in enumerate(bets, 1):
        label = f"{b.title} — **{b.outcome}**"
        bet = f"[{label}]({POLYMARKET_EVENT}{b.event_slug})" if b.event_slug else label
        lines.append(
            f"| {i} | {bet} | ${b.total_notional:,.0f} | {b.n_whales} "
            f"| ${b.smart_notional:,.0f} | {b.weighted_entry:.2f} "
            f"| {_now_cell(b)} | {' · '.join(_patterns(b, cfg, now_ts)) or '—'} |"
        )
    if not bets:
        lines.append("| — | no open whale longshot bets in window | | | | | | |")
    lines += [
        "",
        "**Smart $** = money from wallets whose resolved longshot record beats "
        "their entry odds (z ≥ {:.1f}, ≥ {} positions). **Now** = live price "
        "(drift vs whales' avg entry — large positive drift means you'd be "
        "chasing). Patterns flag the burner-insider signature: money arriving "
        "suddenly, from fresh wallets, near scheduled close.".format(
            cfg.min_z, cfg.min_resolved),
        "",
        "_Research screener, not financial advice. Read each market's "
        "resolution rules before acting._",
    ]
    return "\n".join(lines) + "\n"


def build_html(bets, cfg, now_ts):
    rows = []
    for i, b in enumerate(bets, 1):
        title = html.escape(b.title)
        outcome = html.escape(b.outcome or "?")
        link = (f'<a href="{POLYMARKET_EVENT}{html.escape(b.event_slug)}">'
                f'{title}</a>' if b.event_slug else title)
        pats = " · ".join(html.escape(p) for p in _patterns(b, cfg, now_ts)) or "—"
        rows.append(f"""
        <tr>
          <td class="r">{i}</td>
          <td>{link} → <strong>{outcome}</strong><div class="pat">{pats}</div></td>
          <td class="r">${b.total_notional:,.0f}</td>
          <td class="r">{b.n_whales}</td>
          <td class="r">${b.smart_notional:,.0f}</td>
          <td class="r">{b.weighted_entry:.2f}</td>
          <td class="r">{html.escape(_now_cell(b))}</td>
        </tr>""")
    body = "".join(rows) or '<tr><td colspan="7">no open whale longshot bets in window</td></tr>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Whale Rank Board</title>
<style>
  body {{ background:#0d1117; color:#e6edf3; font:15px/1.5 -apple-system,Segoe UI,sans-serif;
         max-width:920px; margin:2rem auto; padding:0 1rem; }}
  h1 {{ font-size:1.4rem; }} a {{ color:#7ee0a3; text-decoration:none; }}
  .meta {{ color:#8b949e; font-size:.85rem; margin-bottom:1.2rem; }}
  table {{ width:100%; border-collapse:collapse; }}
  th, td {{ padding:.55rem .6rem; border-bottom:1px solid #21262d; text-align:left;
            vertical-align:top; }}
  th {{ color:#8b949e; font-size:.78rem; text-transform:uppercase; }}
  td.r, th.r {{ text-align:right; white-space:nowrap; }}
  .pat {{ color:#d29922; font-size:.8rem; }}
  .foot {{ color:#8b949e; font-size:.8rem; margin-top:1.2rem; }}
</style></head><body>
<h1>🐋 Whale Rank Board — Top 10</h1>
<div class="meta">Updated {_now_label(now_ts)} · whale positions ≥ ${cfg.min_position_cash:,.0f}
entered at {cfg.min_price:.2f}–{cfg.max_price:.2f} · lookback {cfg.signal_window_days}d · ranked by total whale notional</div>
<table>
<tr><th class="r">#</th><th>Bet</th><th class="r">Whale $</th><th class="r">Whales</th>
<th class="r">Smart $</th><th class="r">Entry</th><th class="r">Now</th></tr>
{body}
</table>
<div class="foot">Smart $ = wallets whose resolved longshot record beats their entry odds
(z ≥ {cfg.min_z:.1f}, ≥ {cfg.min_resolved} positions). Now = live price, drift vs whales'
average entry. Patterns flag fresh wallets, sudden inflows, and proximity to close —
the burner-insider signature. Research screener, not financial advice.</div>
</body></html>
"""
