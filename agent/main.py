"""One scan cycle: fetch all sources -> filter -> dedupe -> alert."""
import yaml

from . import filters, store
from .notify import notify
from .sources import REGISTRY


def run() -> None:
    cfg = yaml.safe_load(open("config.yaml"))
    first_run = store.is_first_run()
    seen = store.load()

    all_jobs = []
    for name, fetch in REGISTRY.items():
        src_cfg = cfg["sources"].get(name, {})
        if not src_cfg.get("enabled", False):
            continue
        print(f"checking {name}...")
        try:
            jobs = fetch(src_cfg)
        except Exception as e:
            print(f"  [warn] {name} failed entirely: {type(e).__name__}: {e}")
            continue
        matched = [j for j in jobs if filters.matches(j, cfg)]
        print(f"  {len(jobs)} postings, {len(matched)} match your filters")
        all_jobs.extend(matched)

    # dedupe within this run and against history
    fresh, run_seen = [], set()
    for j in all_jobs:
        if j.uid in seen or j.uid in run_seen:
            continue
        run_seen.add(j.uid)
        fresh.append(j)

    if first_run and fresh:
        limit = cfg.get("alerts", {}).get("first_run_alert_limit", 25)
        fresh.sort(key=lambda j: j.posted_at or "", reverse=True)
        skipped = fresh[limit:]
        fresh = fresh[:limit]
        print(f"first run: alerting the {len(fresh)} newest matches, "
              f"marking {len(skipped)} older ones as seen silently")

    print(f"\n{len(fresh)} new job(s) since last check")

    if fresh:
        for j in fresh:
            print(f"  - {j.title} @ {j.company} ({j.source}) {j.url}")
        notify(fresh)

    seen.update(j.uid for j in all_jobs)
    store.save(seen)
    print("done.")


if __name__ == "__main__":
    run()
