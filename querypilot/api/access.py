"""Optional shared access keys for the HTTP API and Chat UI.

Keys come from ``QUERYPPILOT_ACCESS_KEYS`` (comma-separated) and ``access_keys.txt``
(one key per line). When both are empty, the API stays open.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import APIRouter

from querypilot.config import ROOT_DIR

HEADER = "X-Access-Key"
router = APIRouter()


def keys_path() -> Path:
    return ROOT_DIR / "access_keys.txt"


def access_keys() -> set[str]:
    found: set[str] = set()
    raw = os.getenv("QUERYPPILOT_ACCESS_KEYS", "")
    for part in raw.replace("\n", ",").split(","):
        item = part.strip()
        if item:
            found.add(item)
    path = keys_path()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            item = line.strip()
            if item and not item.startswith("#"):
                found.add(item)
    return found


def access_required() -> bool:
    return bool(access_keys())


def key_matches(presented: str | None) -> bool:
    keys = access_keys()
    if not keys:
        return True
    got = (presented or "").strip().encode()
    for key in keys:
        if hmac.compare_digest(got, key.encode()):
            return True
    return False


@router.get("/api/access")
def access_status() -> dict[str, bool]:
    return {"required": access_required()}


@router.post("/api/access")
def access_check() -> dict[str, bool]:
    return {"ok": True}
