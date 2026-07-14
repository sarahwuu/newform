import json
from pathlib import Path

PATH = Path("data/seen.json")


def load() -> set:
    if PATH.exists():
        return set(json.loads(PATH.read_text()))
    return set()


def save(seen: set) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(sorted(seen), indent=0) + "\n")


def is_first_run() -> bool:
    return not PATH.exists()
