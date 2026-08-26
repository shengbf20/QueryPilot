"""Process-local session memory for the strong-agent path (not query cache)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class SessionState:
    session_id: str
    turns: list[dict[str, str]] = field(default_factory=list)
    last_sql: str = ""
    last_tables: list[str] = field(default_factory=list)
    last_probe: str = ""
    constraints: list[str] = field(default_factory=list)
    last_rationale: str = ""
    messages: list[dict[str, str]] = field(default_factory=list)


class SessionMemory:
    """In-process map: session_id → SessionState."""

    def __init__(self) -> None:
        self._store: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        sid = (session_id or "").strip() or "default"
        state = self._store.get(sid)
        if state is None:
            state = SessionState(session_id=sid)
            self._store[sid] = state
        return state

    def reset(self, session_id: str) -> None:
        sid = (session_id or "").strip() or "default"
        self._store.pop(sid, None)


_MEMORY = SessionMemory()


def get_memory() -> SessionMemory:
    return _MEMORY


def reset_memory() -> None:
    """Test helper: drop all sessions."""
    _MEMORY._store.clear()
