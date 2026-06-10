"""Thin clients for Polymarket's public Data API and Gamma API.

No authentication is required for either endpoint.
- Data API  (https://data-api.polymarket.com)  -> trade tape, per-wallet fills
- Gamma API (https://gamma-api.polymarket.com) -> market metadata + resolutions
"""

import time
import warnings

# macOS system Python links LibreSSL; urllib3's warning about it is noise here.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import requests

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


class ClientError(Exception):
    """Non-retryable 4xx from the API (bad params, pagination depth cap)."""


class PolymarketClient:
    def __init__(self, session=None, timeout=20, max_retries=4):
        self.http = session or requests.Session()
        self.http.headers.update({"User-Agent": "polywhale/0.1"})
        self.timeout = timeout
        self.max_retries = max_retries

    def _get(self, url, params):
        delay = 1.0
        for attempt in range(self.max_retries):
            try:
                resp = self.http.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 429 or resp.status_code >= 500:
                    resp.raise_for_status()          # retryable
                if 400 <= resp.status_code < 500:
                    raise ClientError(f"{resp.status_code} for {resp.url}")
                return resp.json()
            except ClientError:
                raise
            except (requests.RequestException, ValueError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    def iter_large_trades(self, min_cash, page_size=500, max_pages=40,
                          taker_only=True, user=None):
        """Yield recent trades with cash value >= min_cash, newest first.

        With `user` set, returns that wallet's own trade history instead of
        the global tape — this is how `backfill` reconstructs track records
        for wallets we've already seen, without waiting for new bets to
        resolve. The Data API filters by notional server-side (filterType=
        CASH) and caps pagination depth (~3,500 trades); when we hit the cap
        we stop cleanly with whatever the API allowed.
        """
        for page in range(max_pages):
            params = {
                "limit": page_size,
                "offset": page * page_size,
                "takerOnly": str(bool(taker_only)).lower(),
                "filterType": "CASH",
                "filterAmount": int(min_cash),
            }
            if user:
                params["user"] = user
            try:
                batch = self._get(f"{DATA_API}/trades", params)
            except ClientError:
                if page == 0:
                    raise
                return    # pagination depth cap reached
            if not batch:
                return
            yield from batch
            if len(batch) < page_size:
                return

    def markets_by_condition_ids(self, condition_ids, chunk=20):
        """Fetch Gamma market metadata for a set of conditionIds."""
        out = []
        ids = list(condition_ids)
        for i in range(0, len(ids), chunk):
            params = [("condition_ids", c) for c in ids[i:i + chunk]]
            out.extend(self._get(f"{GAMMA_API}/markets", params) or [])
        return out
