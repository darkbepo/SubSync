"""settings.json next to SubSync.exe (shared by the window and the command line)."""
from __future__ import annotations

import json
import os

from . import paths


def load() -> dict:
    try:
        with open(paths.SETTINGS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save(s: dict) -> None:
    tmp = paths.SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, paths.SETTINGS)


def update(**kw) -> None:
    s = load()
    s.update(kw)
    save(s)
