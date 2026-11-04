"""Checks GitHub Releases for a newer version. Never downloads or runs anything
by itself: the overlay just shows a link to the release page."""

from __future__ import annotations

import json
import urllib.request

from . import __version__
from .config import GITHUB_REPO

LATEST_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"


def parse_version(tag: str) -> tuple[int, ...]:
    tag = tag.strip().lstrip("vV")
    parts = []
    for piece in tag.split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def is_newer(remote_tag: str, local: str = __version__) -> bool:
    return parse_version(remote_tag) > parse_version(local)


def check() -> tuple[str, str] | None:
    """Return (tag, page_url) if a newer release exists, else None."""
    req = urllib.request.Request(LATEST_URL, headers={
        "User-Agent": "maple-assistant",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    tag = data.get("tag_name") or ""
    if tag and is_newer(tag):
        return tag, data.get("html_url") or f"https://github.com/{GITHUB_REPO}/releases/latest"
    return None
