"""Settings and API-key storage.

The API key is stored in Windows Credential Manager (via `keyring`) and never
written to the repository or to a plain-text settings file. If keyring is
unavailable, we fall back to a file in the user's AppData folder.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

APP_NAME = "MapleAssistant"
KEYRING_SERVICE = "maple-assistant"
KEYRING_USER = "anthropic-api-key"

GITHUB_REPO = "michaelarnsb-stack/maple-assistant"
KNOWLEDGE_BRANCH = "main"


def data_dir() -> Path:
    """Per-user folder for settings, cached knowledge and logs."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Settings:
    # Hotkey as modifier names + key, e.g. ["ctrl", "shift"] + "A".
    hotkey_modifiers: list[str] = field(default_factory=lambda: ["ctrl", "shift"])
    hotkey_key: str = "A"
    # "fast" -> Haiku, "deep" -> Sonnet with web search.
    mode: str = "fast"
    attach_screenshot: bool = True
    # Window geometry (x, y, w, h); None = default placement.
    geometry: list[int] | None = None
    opacity: float = 0.92
    # Monthly budget warning in USD (local estimate only; the real cap is set
    # in the Anthropic Console).
    budget_warning_usd: float = 5.0

    @classmethod
    def load(cls) -> "Settings":
        path = data_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        known = {k: v for k, v in raw.items() if k in cls.__dataclass_fields__}
        return cls(**known)

    def save(self) -> None:
        path = data_dir() / "settings.json"
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")


# --- API key -----------------------------------------------------------------

def _fallback_key_path() -> Path:
    return data_dir() / "api_key.txt"


def load_api_key() -> str | None:
    env = os.environ.get("ANTHROPIC_API_KEY")
    if env:
        return env
    try:
        import keyring

        key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        if key:
            return key
    except Exception:  # keyring backend missing or broken
        pass
    path = _fallback_key_path()
    if path.exists():
        key = path.read_text(encoding="utf-8").strip()
        return key or None
    return None


def save_api_key(key: str) -> None:
    key = key.strip()
    try:
        import keyring

        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        # Remove any older plain-text copy once the secure store works.
        _fallback_key_path().unlink(missing_ok=True)
        return
    except Exception:
        pass
    _fallback_key_path().write_text(key, encoding="utf-8")


def delete_api_key() -> None:
    try:
        import keyring

        keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
    except Exception:
        pass
    _fallback_key_path().unlink(missing_ok=True)
