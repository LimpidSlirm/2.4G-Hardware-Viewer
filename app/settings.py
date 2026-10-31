from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / ".window_state.json"


@dataclass(frozen=True)
class WindowState:
    x: int
    y: int
    compact: bool


def _state_path() -> Path:
    return STATE_FILE


def load_window_state() -> WindowState | None:
    """Return the last saved position, or None when nothing usable exists."""
    try:
        payload = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        x = int(payload["x"])
        y = int(payload["y"])
    except (KeyError, TypeError, ValueError):
        return None
    compact = bool(payload.get("compact", True))
    return WindowState(x=x, y=y, compact=compact)


def save_window_state(x: int, y: int, compact: bool) -> None:
    payload = {"x": int(x), "y": int(y), "compact": bool(compact)}
    try:
        _state_path().write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        pass


def clear_window_state() -> bool:
    try:
        _state_path().unlink()
        return True
    except OSError:
        return False
