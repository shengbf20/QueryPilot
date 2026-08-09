"""Cache key helpers: question normalization and metadata fingerprinting."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_WS_RE = re.compile(r"\s+")


def normalize_question(question: str) -> str:
    """Collapse whitespace for exact cache keys (phase-4 step 2/3)."""
    return _WS_RE.sub(" ", (question or "").strip())


def metadata_version(metadata_dir: Path) -> str:
    """Fingerprint metadata YAML tree via path + size + mtime (fast, process-local)."""
    root = Path(metadata_dir)
    if not root.is_dir():
        return f"missing:{root}"

    parts: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".yaml", ".yml"}:
            continue
        try:
            st = path.stat()
        except OSError:
            continue
        rel = path.relative_to(root).as_posix()
        parts.append(f"{rel}:{st.st_size}:{st.st_mtime_ns}")

    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]
    return digest
