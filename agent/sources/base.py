import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def get(url: str, timeout: int = 30, **kw):
    """GET that returns None instead of raising, so one bad endpoint never kills a run."""
    try:
        resp = requests.get(url, timeout=timeout, headers={**UA, **kw.pop("headers", {})}, **kw)
        if resp.status_code == 200:
            return resp
        print(f"  [warn] {resp.status_code} from {url}")
    except requests.RequestException as e:
        print(f"  [warn] {type(e).__name__} fetching {url}")
    return None
