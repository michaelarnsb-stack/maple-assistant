"""Game knowledge base loader.

Knowledge lives as Markdown files in `knowledge/` with a `manifest.json`
listing them in order. At startup we try, in order:

1. The latest copy from the public GitHub repo (so knowledge updates reach the
   player without a new .exe).
2. The last copy we downloaded successfully (offline fallback).
3. The copy bundled inside the .exe.

The loaded text is frozen for the whole conversation: changing the system
prompt mid-conversation would break prompt caching and the API's
history-editing check.
"""

from __future__ import annotations

import json
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .config import GITHUB_REPO, KNOWLEDGE_BRANCH, data_dir

RAW_BASE = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{KNOWLEDGE_BRANCH}/knowledge"
FETCH_TIMEOUT_S = 4


@dataclass(frozen=True)
class KnowledgeBase:
    text: str
    version: str
    source: str  # "remote" | "cache" | "bundled" | "empty"
    files: tuple[str, ...]


def bundled_dir() -> Path:
    """Folder that holds the knowledge files shipped with the app."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base / "knowledge"


def cache_dir() -> Path:
    path = data_dir() / "knowledge"
    path.mkdir(parents=True, exist_ok=True)
    return path


def assemble(files: dict[str, str], version: str) -> str:
    """Join knowledge files into one block with clear file boundaries."""
    parts = [f"<knowledge_base version=\"{version}\">"]
    for name, body in files.items():
        parts.append(f"<file name=\"{name}\">\n{body.strip()}\n</file>")
    parts.append("</knowledge_base>")
    return "\n\n".join(parts)


def _read_local(folder: Path) -> tuple[dict[str, str], str] | None:
    manifest_path = folder / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        files = {
            name: (folder / name).read_text(encoding="utf-8")
            for name in manifest["files"]
            if (folder / name).exists()
        }
    except (OSError, KeyError, json.JSONDecodeError):
        return None
    return files, str(manifest.get("version", "unknown"))


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "maple-assistant"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_S) as resp:
        return resp.read().decode("utf-8")


def _read_remote() -> tuple[dict[str, str], str, str] | None:
    try:
        manifest_text = _fetch(f"{RAW_BASE}/manifest.json")
        manifest = json.loads(manifest_text)
        files = {name: _fetch(f"{RAW_BASE}/{name}") for name in manifest["files"]}
    except Exception:
        return None
    return files, str(manifest.get("version", "unknown")), manifest_text


def _write_cache(files: dict[str, str], manifest_text: str) -> None:
    folder = cache_dir()
    try:
        for name, body in files.items():
            target = folder / name
            # Never write outside the cache folder, whatever the manifest says.
            if folder.resolve() not in target.resolve().parents:
                continue
            target.write_text(body, encoding="utf-8")
        (folder / "manifest.json").write_text(manifest_text, encoding="utf-8")
    except OSError:
        pass


def load(allow_remote: bool = True) -> KnowledgeBase:
    if allow_remote:
        remote = _read_remote()
        if remote:
            files, version, manifest_text = remote
            _write_cache(files, manifest_text)
            return KnowledgeBase(assemble(files, version), version, "remote", tuple(files))

    for source, folder in (("cache", cache_dir()), ("bundled", bundled_dir())):
        local = _read_local(folder)
        if local and local[0]:
            files, version = local
            return KnowledgeBase(assemble(files, version), version, source, tuple(files))

    return KnowledgeBase("<knowledge_base version=\"none\"></knowledge_base>", "none", "empty", ())
