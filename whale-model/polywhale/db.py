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
    """Insert Data API trade rows, ignoring duplicates. Returns rows added."""
    inserted = 0
    for t in raw_trades:
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
    market resolves, the winning outcome's price is pinned to ~1.
    """
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


def condition_ids_missing_or_unresolved(con):
    rows = con.execute(
        """SELECT DISTINCT t.condition_id FROM trades t
           LEFT JOIN markets m ON m.condition_id = t.condition_id
           WHERE m.condition_id IS NULL OR m.resolved = 0"""
    ).fetchall()
    return [r["condition_id"] for r in rows]


def resolved_longshot_buys(con, max_price):
    """Whale longshot BUYs joined to their market's final outcome."""
    return con.execute(
        """SELECT t.wallet, t.pseudonym, t.price, t.cash, t.ts, t.title,
                  m.end_ts,
                  (t.outcome_index = m.winning_index) AS won
           FROM trades t
           JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.side = 'BUY' AND t.price < ? AND m.resolved = 1
           ORDER BY t.ts""",
        (max_price,),
    ).fetchall()


def open_longshot_buys(con, max_price, since_ts):
    """Recent whale longshot BUYs on markets that have not resolved yet."""
    return con.execute(
        """SELECT t.wallet, t.pseudonym, t.condition_id, t.outcome,
                  t.outcome_index, t.price, t.cash, t.ts, t.title, t.event_slug
           FROM trades t
           LEFT JOIN markets m ON m.condition_id = t.condition_id
           WHERE t.side = 'BUY' AND t.price < ?
             AND t.ts >= ?
             AND COALESCE(m.resolved, 0) = 0
           ORDER BY t.ts DESC""",
        (max_price, since_ts),
    ).fetchall()
