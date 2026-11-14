"""Persistent watchlist stored in watchlist.json."""
import json
import re
from pathlib import Path

FILE = Path(__file__).parent / "watchlist.json"
VALID = re.compile(r"^[A-Z0-9&-]{1,20}$")


def clean(raw: str) -> str:
    s = raw.strip().upper()
    for suffix in (".NS", ".BO", "-EQ"):
        s = s.removesuffix(suffix)
    return s


def load() -> list[str]:
    try:
        return json.loads(FILE.read_text())
    except (OSError, ValueError):
        return []


def _save(items: list[str]) -> None:
    FILE.write_text(json.dumps(items))


def add(symbol: str) -> list[str]:
    items = load()
    if symbol not in items:
        items.append(symbol)
        _save(items)
    return items


def remove(symbol: str) -> list[str]:
    items = [s for s in load() if s != symbol]
    _save(items)
    return items
