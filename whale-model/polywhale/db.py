"""SQLite storage for whale trades and market resolutions."""

import json
import sqlite3
import time
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    tx_hash       TEXT NOT NULL,
    wallet        TEXT NOT NULL,
    pseudonym     TEXT,
    condition_id  TEXT NOT NULL,
    outcome_index INTEGER NOT NULL,
    outcome       TEXT,
    side          TEXT NOT NULL,
    price         REAL NOT NULL,
    size          REAL NOT NULL,
    cash          REAL NOT NULL,
    ts            INTEGER NOT NULL,
    title         TEXT,
    event_slug    TEXT,
    UNIQUE (tx_hash, wallet, condition_id, outcome_index, side, price, size, ts)
);
CREATE INDEX IF NOT EXISTS idx_trades_wallet ON trades (wallet);
CREATE INDEX IF NOT EXISTS idx_trades_condition ON trades (condition_id);
CREATE INDEX IF NOT EXISTS idx_trades_ts ON trades (ts);

CREATE TABLE IF NOT EXISTS backfills (
    wallet TEXT PRIMARY KEY,
    ts     INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_bets (
    wallet        TEXT NOT NULL,
    condition_id  TEXT NOT NULL,
    outcome_index INTEGER NOT NULL,
    outcome       TEXT,
    title         TEXT,
    event_slug    TEXT,
    whale_cash    REAL,
    whale_entry   REAL,
    rec_price     REAL,              -- live price when recorded (our entry)
    recorded_ts   INTEGER NOT NULL,
    end_ts        INTEGER,
    won           INTEGER,           -- NULL until the market resolves
    graded_ts     INTEGER,
    PRIMARY KEY (wallet, condition_id, outcome_index)
);

CREATE TABLE IF NOT EXISTS markets (
    condition_id  TEXT PRIMARY KEY,
    question      TEXT,
    category      TEXT,
    closed        INTEGER NOT NULL DEFAULT 0,
    resolved      INTEGER NOT NULL DEFAULT 0,
    winning_index INTEGER,
    end_ts        INTEGER,
    fetched_ts    INTEGER NOT NULL
);
"""


def connect(path):
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def upsert_trades(con, raw_trades):
    """Insert Data API trade rows, ignoring duplicates. Returns rows added.

    Commits every 500 rows so a network failure mid-stream never discards
    the trades already fetched.
    """
    inserted = 0
    seen = 0
    for t in raw_trades:
        if not t.get("conditionId") or not t.get("proxyWallet"):
            continue    # rows without a market or wallet id are unusable
        seen += 1
        if seen % 500 == 0:
            con.commit()
        price = float(t["price"])
        size = float(t["size"])
        cur = con.execute(
            """INSERT OR IGNORE INTO trades
               (tx_hash, wallet, pseudonym, condition_id, outcome_index, outcome,
                side, price, size, cash, ts, title, event_slug)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                t.get("transactionHash", ""),
                t["proxyWallet"].lower(),
                t.get("pseudonym"),
                t["conditionId"],
                int(t.get("outcomeIndex", 0)),
                t.get("outcome"),
                t.get("side", "BUY").upper(),
                price,
                size,
                price * size,
                int(t["timestamp"]),
                t.get("title"),
                t.get("eventSlug"),
            ),
        )
        inserted += cur.rowcount
    con.commit()
    return inserted


def _parse_iso_ts(value):
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00"))
                   .astimezone(timezone.utc).timestamp())
    except ValueError:
        return None


def upsert_market(con, m):
    """Store a Gamma API market row, deriving resolution state.

    Gamma encodes resolution in `outcomePrices` (a JSON string list): once a
    market resolves, the winning outcome's price is pinned to ~1. Callers
    batching many markets should con.commit() themselves periodically.
    """
    if not m.get("conditionId"):
        return
    prices = [float(p) for p in json.loads(m.get("outcomePrices") or "[]")]
    closed = bool(m.get("closed"))
    resolved = closed and bool(prices) and max(prices) >= 0.95
    winning_index = prices.index(max(prices)) if resolved else None
    con.execute(
        """INSERT INTO markets
           (condition_id, question, category, closed, resolved, winning_index,
            end_ts, fetched_ts)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT (condition_id) DO UPDATE SET
             question=excluded.question, category=excluded.category,
             closed=excluded.closed, resolved=excluded.resolved,
             winning_index=excluded.winning_index, end_ts=excluded.end_ts,
             fetched_ts=excluded.fetched_ts""",
        (
            m.get("conditionId"),
            m.get("question"),
            m.get("category"),
            int(closed),
            int(resolved),
            winning_index,
            _parse_iso_ts(m.get("endDate")),
            int(time.time()),
        ),
    )
    con.commit()


def condition_ids_missing_or_unresolved(con, since_ts=None):
    """Condition ids we still need resolution for.

    With since_ts set, restrict to markets traded recently — the fast watch
    loop only needs to resolve markets in play, not re-check all history.
    """
    if since_ts is None:
        rows = con.execute(
            """SELECT DISTINCT t.condition_id FROM trades t
               LEFT JOIN markets m ON m.condition_id = t.condition_id
               WHERE t.condition_id != ''
                 AND (m.condition_id IS NULL OR m.resolved = 0)"""
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT DISTINCT t.condition_id FROM trades t
               LEFT JOIN markets m ON m.condition_id = t.condition_id
               WHERE t.condition_id != '' AND t.ts >= ?
                 AND (m.condition_id IS NULL OR m.resolved = 0)""",
            (since_ts,),
        ).fetchall()
    return [r["condition_id"] for r in rows]


def resolved_buy_positions(con, cfg):
    """ALL resolved BUY positions (any price band) — track-record evidence.

    Fills are aggregated per (wallet, market, outcome): a whale sweeping the
    book in ten fills made ONE bet, not ten. Treating fills as independent
    would inflate sample size and z-scores for exactly the wallets that trade
    biggest. `price` is the share-weighted average entry; `ts` is the first
    fill (when the information, if any, was acted on). Uses the scoring
    bounds, not the longshot signal band: skill is evidenced by every bet.
    """
    return con.execute(
        """SELECT t.wallet, MAX(t.pseudonym) AS pseudonym,
                  t.condition_id,
                  COUNT(*) AS fills,
                  SUM(t.cash) AS cash,
                  SUM(t.cash) / SUM(t.size) AS price,
                  MIN(t.ts) AS ts,
                  MAX(t.title) AS title,
                  m.end_ts,
                  (t.outcome_index = m.winning_index) AS won
           FROM trades t
           JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.side = 'BUY' AND t.price >= ? AND t.price < ?
             AND m.resolved = 1
           GROUP BY t.wallet, t.condition_id, t.outcome_index
           HAVING SUM(t.cash) >= ?
           ORDER BY MIN(t.ts)""",
        (cfg.scoring_min_price, cfg.scoring_max_price, cfg.scoring_min_cash),
    ).fetchall()


def resolved_positions_with_meta(con, min_cash):
    """All resolved BUY positions with title + event_slug, for per-category
    specialist analysis. Aggregated per (wallet, market, outcome); any price."""
    return con.execute(
        """SELECT t.wallet, MAX(t.pseudonym) AS pseudonym, t.condition_id,
                  COUNT(*) AS fills,
                  SUM(t.cash) AS cash,
                  SUM(t.cash) / SUM(t.size) AS price,
                  MIN(t.ts) AS ts,
                  MAX(t.title) AS title,
                  MAX(t.event_slug) AS event_slug,
                  MAX(m.end_ts) AS end_ts,
                  (t.outcome_index = m.winning_index) AS won
           FROM trades t
           JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.side = 'BUY' AND m.resolved = 1
           GROUP BY t.wallet, t.condition_id, t.outcome_index
           HAVING SUM(t.cash) >= ?
           ORDER BY MIN(t.ts)""",
        (min_cash,),
    ).fetchall()


def open_longshot_positions(con, cfg, since_ts, burst_cutoff):
    """Whale longshot POSITIONS on markets that have not resolved yet.

    Same aggregation and position-level whale bar as the resolved query, plus
    burst_cash (notional that arrived after burst_cutoff) for pattern flags.
    """
    return con.execute(
        """SELECT t.wallet, MAX(t.pseudonym) AS pseudonym,
                  t.condition_id, MAX(t.outcome) AS outcome, t.outcome_index,
                  COUNT(*) AS fills,
                  SUM(t.cash) AS cash,
                  SUM(t.cash) / SUM(t.size) AS price,
                  MIN(t.ts) AS first_ts,
                  MAX(t.ts) AS latest_ts,
                  SUM(CASE WHEN t.ts >= ? THEN t.cash ELSE 0 END) AS burst_cash,
                  MAX(t.title) AS title,
                  MAX(t.event_slug) AS event_slug,
                  MAX(m.end_ts) AS end_ts
           FROM trades t
           LEFT JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.side = 'BUY' AND t.price >= ? AND t.price < ?
             AND t.ts >= ?
             AND COALESCE(m.resolved, 0) = 0
           GROUP BY t.wallet, t.condition_id, t.outcome_index
           HAVING SUM(t.cash) >= ?
           ORDER BY MAX(t.ts) DESC""",
        (burst_cutoff, cfg.min_price, cfg.max_price, since_ts,
         cfg.min_position_cash),
    ).fetchall()


def wallets_needing_backfill(con, max_age_days=7):
    """Wallets we've seen trade but haven't pulled history for recently."""
    cutoff = int(time.time()) - max_age_days * 86400
    rows = con.execute(
        """SELECT DISTINCT t.wallet FROM trades t
           LEFT JOIN backfills b ON b.wallet = t.wallet
           WHERE b.wallet IS NULL OR b.ts < ?""",
        (cutoff,),
    ).fetchall()
    return [r["wallet"] for r in rows]


def mark_backfilled(con, wallet):
    con.execute(
        """INSERT INTO backfills (wallet, ts) VALUES (?, ?)
           ON CONFLICT (wallet) DO UPDATE SET ts=excluded.ts""",
        (wallet, int(time.time())),
    )
    con.commit()


def record_paper_bet(con, hit, rec_price, now_ts):
    """Log a hunt hit to the prospective ledger. Returns 1 if new.

    Prospective bets are the survivorship-free test of the insider
    signature: recorded the moment the model surfaces them, graded only
    by what happens afterwards.
    """
    cur = con.execute(
        """INSERT OR IGNORE INTO paper_bets
           (wallet, condition_id, outcome_index, outcome, title, event_slug,
            whale_cash, whale_entry, rec_price, recorded_ts, end_ts)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (hit["wallet"], hit["condition_id"], hit["outcome_index"],
         hit["outcome"], hit["title"], hit["event_slug"], hit["cash"],
         hit["price"], rec_price, now_ts, hit["end_ts"]),
    )
    con.commit()
    return cur.rowcount


def grade_paper_bets(con):
    """Mark ledger entries won/lost once their market resolves."""
    pending = con.execute(
        """SELECT p.rowid, p.outcome_index, m.winning_index
           FROM paper_bets p
           JOIN markets m ON m.condition_id = p.condition_id
           WHERE p.won IS NULL AND m.resolved = 1"""
    ).fetchall()
    now = int(time.time())
    for r in pending:
        con.execute(
            "UPDATE paper_bets SET won = ?, graded_ts = ? WHERE rowid = ?",
            (int(r["outcome_index"] == r["winning_index"]), now, r["rowid"]),
        )
    con.commit()
    return len(pending)


def wallet_fill_count(con, wallet):
    """Total fills we have ever seen from this wallet (any side, any price)."""
    return con.execute(
        "SELECT COUNT(*) c FROM trades WHERE wallet = ?", (wallet,)
    ).fetchone()["c"]


def wallet_distinct_markets(con, wallet):
    """Distinct markets this wallet has placed BUY positions on.

    A concentrated burner — the insider profile — touches very few markets:
    the wallet exists to make one bet. A volume or hedge bettor (e.g. someone
    spraying money across every World Cup team) touches many, and should not
    be mistaken for insider conviction even when one of its bets is a fresh,
    big longshot near close.
    """
    return con.execute(
        "SELECT COUNT(DISTINCT condition_id) c FROM trades "
        "WHERE wallet = ? AND side = 'BUY'", (wallet,)
    ).fetchone()["c"]


def wallet_other_bets_in_event(con, wallet, event_slug, condition_id,
                               outcome_index, since_ts):
    """Fills by the same wallet on OTHER outcomes of the same event.

    Non-zero means the 'conviction' bet may be one leg of a hedge or a
    sum-of-longshots arbitrage rather than a directional view.
    """
    if not event_slug:
        return 0
    return con.execute(
        """SELECT COUNT(*) c FROM trades
           WHERE wallet = ? AND event_slug = ? AND ts >= ?
             AND (condition_id != ? OR outcome_index != ?)""",
        (wallet, event_slug, since_ts, condition_id, outcome_index),
    ).fetchone()["c"]
