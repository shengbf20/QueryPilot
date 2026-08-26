"""Read / apply DeepSeek-compatible LLM settings (env + optional .env persist)."""

from __future__ import annotations

import os
from pathlib import Path

from querypilot.config import ROOT_DIR, get_settings


def mask_api_key(key: str) -> str:
    raw = (key or "").strip()
    if not raw:
        return ""
    if len(raw) <= 8:
        return "••••"
    return f"{raw[:3]}••••{raw[-4:]}"


def current_llm_settings() -> dict[str, str | bool]:
    s = get_settings()
    key = s.deepseek_api_key
    return {
        "api_key_set": bool(key.strip()),
        "api_key_masked": mask_api_key(key),
        "base_url": s.deepseek_base_url,
        "model": s.deepseek_model,
    }


def apply_llm_settings(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    persist: bool = True,
    env_path: Path | None = None,
) -> dict[str, str | bool]:
    updates: dict[str, str] = {}
    if api_key is not None and api_key.strip():
        updates["DEEPSEEK_API_KEY"] = api_key.strip()
    if base_url is not None and base_url.strip():
        updates["DEEPSEEK_BASE_URL"] = base_url.strip().rstrip("/")
    if model is not None and model.strip():
        updates["DEEPSEEK_MODEL"] = model.strip()
    for name, value in updates.items():
        os.environ[name] = value
    if persist and updates:
        write_env_keys(updates, env_path or (ROOT_DIR / ".env"))
    return current_llm_settings()


def write_env_keys(updates: dict[str, str], path: Path) -> None:
    """Upsert given keys in a dotenv file; leave other lines untouched."""
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in updates:
            out.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in seen:
            out.append(f"{key}={value}")
    text = "\n".join(out)
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text, encoding="utf-8")
