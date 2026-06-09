"""Thin clients for Polymarket's public Data API and Gamma API.

No authentication is required for either endpoint.
- Data API  (https://data-api.polymarket.com)  -> trade tape, per-wallet fills
- Gamma API (https://gamma-api.polymarket.com) -> market metadata + resolutions
"""

import time

import requests

DATA_API = "https://data-api.polymarket.com"
GAMMA_API = "https://gamma-api.polymarket.com"


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
                    resp.raise_for_status()
                resp.raise_for_status()
                return resp.json()
            except (requests.RequestException, ValueError):
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(delay)
                delay *= 2

    def iter_large_trades(self, min_cash, page_size=500, max_pages=40, taker_only=True):
        """Yield recent trades with cash value >= min_cash, newest first.

        The Data API filters by notional server-side (filterType=CASH), so a
        $10k floor means almost every page row is relevant. Pagination only
        reaches back through the API's recent window; run ingest on a schedule
        to accumulate deeper history in the local DB.
        """
        for page in range(max_pages):
            batch = self._get(f"{DATA_API}/trades", {
                "limit": page_size,
                "offset": page * page_size,
                "takerOnly": str(bool(taker_only)).lower(),
                "filterType": "CASH",
                "filterAmount": int(min_cash),
            })
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
