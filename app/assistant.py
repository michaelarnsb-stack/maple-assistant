"""Conversation with Claude.

Design rules (see DECISIONS.md):
- History is append-only. The API rejects edited history once it holds
  thinking blocks, and appending keeps prompt caching effective.
- The system prompt (instructions + knowledge base) is fixed per conversation.
- "fast" mode = Claude Haiku 5.5, no web search. "deep" mode = Claude Sonnet 5.5
  with web search restricted to MapleStory sites, and server-side refusal
  fallbacks enabled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from .config import data_dir
from .knowledge import KnowledgeBase
from .prompts import SYSTEM_INSTRUCTIONS

FAST_MODEL = "claude-haiku-5-5"
DEEP_MODEL = "claude-sonnet-5-5"

# USD per million tokens: (input, output, cache_read, cache_write_5m)
PRICES = {
    FAST_MODEL: (0.10, 0.50, 0.01, 0.125),
    DEEP_MODEL: (2.00, 10.00, 0.20, 2.50),
}
# Haiku 5.5 switches to a higher rate card above 100K prompt tokens.
HAIKU_LONG_PROMPT = 100_000
HAIKU_LONG_PRICES = (0.50, 2.50, 0.05, 0.625)
WEB_SEARCH_USD = 0.01  # $10 per 1,000 searches

# Start a fresh conversation before the prompt gets expensive.
MAX_PROMPT_TOKENS = 80_000
MAX_PAUSE_RESUMES = 3

SEARCH_DOMAINS = [
    "meowdb.com",
    "maplestory.nexon.net",
    "nexon.com",
    "reddit.com",
    "mscwhub.com",
]

MODES = {
    "fast": {"model": FAST_MODEL, "effort": "low", "max_tokens": 4096, "web": False},
    "deep": {"model": DEEP_MODEL, "effort": "medium", "max_tokens": 8192, "web": True},
}


@dataclass
class TurnResult:
    text: str
    cost_usd: float
    prompt_tokens: int
    model: str
    stop_reason: str | None
    searches: int = 0


@dataclass
class Callbacks:
    on_text: Callable[[str], None] = lambda _t: None
    on_status: Callable[[str], None] = lambda _s: None


def cost_of(model: str, usage: Any) -> tuple[float, int]:
    """Return (usd, total_prompt_tokens) for one API response's usage."""
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    c_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    c_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    prompt_tokens = inp + c_read + c_write

    key = model if model in PRICES else next((m for m in PRICES if model.startswith(m)), DEEP_MODEL)
    p_in, p_out, p_read, p_write = PRICES[key]
    if key == FAST_MODEL and prompt_tokens > HAIKU_LONG_PROMPT:
        p_in, p_out, p_read, p_write = HAIKU_LONG_PRICES

    usd = (inp * p_in + out * p_out + c_read * p_read + c_write * p_write) / 1_000_000
    server = getattr(usage, "server_tool_use", None)
    searches = (getattr(server, "web_search_requests", 0) or 0) if server else 0
    return usd + searches * WEB_SEARCH_USD, prompt_tokens


class UsageLedger:
    """Local month-by-month spend estimate, shown in the overlay."""

    def __init__(self) -> None:
        self.path = data_dir() / "usage.json"
        try:
            self.data: dict[str, float] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    @staticmethod
    def _month() -> str:
        return datetime.now().strftime("%Y-%m")

    def add(self, usd: float) -> None:
        month = self._month()
        self.data[month] = round(self.data.get(month, 0.0) + usd, 6)
        try:
            self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def this_month(self) -> float:
        return self.data.get(self._month(), 0.0)


@dataclass
class Conversation:
    client: Any
    knowledge: KnowledgeBase
    messages: list[dict] = field(default_factory=list)
    last_prompt_tokens: int = 0

    def system_blocks(self) -> list[dict]:
        return [
            {"type": "text", "text": SYSTEM_INSTRUCTIONS},
            {"type": "text", "text": self.knowledge.text, "cache_control": {"type": "ephemeral"}},
        ]

    @property
    def is_full(self) -> bool:
        return self.last_prompt_tokens > MAX_PROMPT_TOKENS

    def request_params(self, mode: str) -> dict:
        cfg = MODES[mode]
        params: dict[str, Any] = {
            "model": cfg["model"],
            "max_tokens": cfg["max_tokens"],
            "system": self.system_blocks(),
            "messages": self.messages,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": cfg["effort"]},
            # Auto-cache the growing conversation as well as the system prompt.
            "cache_control": {"type": "ephemeral"},
        }
        if cfg["web"]:
            params["tools"] = [{
                "type": "web_search_20260209",
                "name": "web_search",
                "max_uses": 3,
                "allowed_domains": SEARCH_DOMAINS,
            }]
            # Re-run on another model if a safety classifier declines a
            # harmless game question (false positive).
            params["betas"] = ["server-side-fallback-2026-07-01"]
            params["fallbacks"] = "default"
        return params

    def ask(self, question: str, image_block: dict | None, mode: str,
            callbacks: Callbacks | None = None) -> TurnResult:
        cb = callbacks or Callbacks()
        content: list[dict] = []
        if image_block:
            content.append(image_block)
        content.append({"type": "text", "text": question})
        self.messages.append({"role": "user", "content": content})
        user_index = len(self.messages) - 1

        total_cost = 0.0
        searches = 0
        texts: list[str] = []
        final = None
        try:
            for _ in range(MAX_PAUSE_RESUMES + 1):
                final = self._stream_once(mode, cb)
                if final.content:
                    self.messages.append({"role": "assistant", "content": final.content})
                usd, prompt_tokens = cost_of(final.model, final.usage)
                total_cost += usd
                self.last_prompt_tokens = prompt_tokens
                server = getattr(final.usage, "server_tool_use", None)
                searches += (getattr(server, "web_search_requests", 0) or 0) if server else 0
                texts.extend(b.text for b in final.content if getattr(b, "type", None) == "text")
                # Server-side tool loop hit its limit: resend as-is to resume.
                if final.stop_reason != "pause_turn":
                    break
        except Exception:
            # Nothing was answered: drop the unanswered question so a retry
            # doesn't send it twice. Earlier history is untouched.
            if len(self.messages) - 1 == user_index:
                self.messages.pop()
            raise

        text = "".join(texts).strip()
        if final is not None and final.stop_reason == "refusal":
            text = (text + "\n\n" if text else "") + "_המודל סירב לענות על השאלה הזו. נסה לנסח אותה אחרת._"
        elif final is not None and final.stop_reason == "max_tokens":
            text += "\n\n_(התשובה נקטעה - בקש המשך)_"
        return TurnResult(text, total_cost, self.last_prompt_tokens,
                          final.model if final else MODES[mode]["model"],
                          final.stop_reason if final else None, searches)

    def _stream_once(self, mode: str, cb: Callbacks):
        params = self.request_params(mode)
        with self.client.beta.messages.stream(**params) as stream:
            for event in stream:
                etype = getattr(event, "type", None)
                if etype == "content_block_start":
                    block_type = getattr(event.content_block, "type", None)
                    if block_type == "server_tool_use":
                        cb.on_status("מחפש באינטרנט...")
                    elif block_type == "thinking":
                        cb.on_status("חושב...")
                elif etype == "content_block_delta":
                    delta = event.delta
                    if getattr(delta, "type", None) == "text_delta":
                        cb.on_text(delta.text)
            return stream.get_final_message()
