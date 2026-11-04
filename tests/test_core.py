import base64
import io
import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "cfg"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)


# --- knowledge ---------------------------------------------------------------

def test_bundled_knowledge_loads_in_manifest_order():
    from app import knowledge

    kb = knowledge.load(allow_remote=False)
    manifest = json.loads((knowledge.bundled_dir() / "manifest.json").read_text())
    assert kb.source == "bundled"
    assert list(kb.files) == manifest["files"]
    positions = [kb.text.index(f'name="{n}"') for n in manifest["files"]]
    assert positions == sorted(positions)


def test_cache_write_refuses_paths_outside_cache(tmp_path):
    from app import knowledge

    knowledge._write_cache({"../evil.md": "x", "ok.md": "y"}, '{"files": []}')
    assert (knowledge.cache_dir() / "ok.md").exists()
    assert not (knowledge.cache_dir().parent / "evil.md").exists()


def test_cache_preferred_over_bundled():
    from app import knowledge

    folder = knowledge.cache_dir()
    (folder / "a.md").write_text("cached body", encoding="utf-8")
    (folder / "manifest.json").write_text('{"version": "c1", "files": ["a.md"]}')
    kb = knowledge.load(allow_remote=False)
    assert kb.source == "cache" and kb.version == "c1" and "cached body" in kb.text


# --- cost --------------------------------------------------------------------

def usage(inp=0, out=0, read=0, write=0, searches=0):
    return NS(input_tokens=inp, output_tokens=out, cache_read_input_tokens=read,
              cache_creation_input_tokens=write,
              server_tool_use=NS(web_search_requests=searches))


def test_cost_haiku_and_sonnet():
    from app.assistant import DEEP_MODEL, FAST_MODEL, cost_of

    usd, _ = cost_of(FAST_MODEL, usage(inp=50_000, out=1_000))
    assert usd == pytest.approx((50_000 * 0.10 + 1_000 * 0.50) / 1e6)
    usd, _ = cost_of(DEEP_MODEL, usage(read=20_000, out=500, searches=2))
    assert usd == pytest.approx((20_000 * 0.20 + 500 * 10) / 1e6 + 0.02)


def test_haiku_long_prompt_rate_card():
    from app.assistant import FAST_MODEL, cost_of

    usd, prompt = cost_of(FAST_MODEL, usage(inp=120_000))
    assert prompt == 120_000
    assert usd == pytest.approx(120_000 * 0.50 / 1e6)


# --- conversation --------------------------------------------------------------

class FakeStream:
    def __init__(self, final, events=()):
        self.final, self.events = final, list(events)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self.events)

    def get_final_message(self):
        return self.final


class FakeClient:
    def __init__(self, finals, error=None):
        self.finals = list(finals)
        self.error = error
        self.calls = []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **params):
        # Snapshot: the real SDK serializes at call time.
        self.calls.append({**params, "messages": [dict(m) for m in params["messages"]]})
        if self.error:
            raise self.error
        final = self.finals.pop(0)
        events = [NS(type="content_block_delta", delta=NS(type="text_delta", text=b.text))
                  for b in final.content if b.type == "text"]
        return FakeStream(final, events)


def final(text, stop="end_turn", model="claude-haiku-5-5"):
    return NS(content=[NS(type="thinking", thinking="", signature="s"), NS(type="text", text=text)],
              stop_reason=stop, model=model, usage=usage(inp=100, out=10))


def make_conv(client):
    from app import knowledge
    from app.assistant import Conversation

    return Conversation(client=client, knowledge=knowledge.load(allow_remote=False))


def test_history_is_append_only_across_turns():
    client = FakeClient([final("one"), final("two")])
    conv = make_conv(client)
    deltas = []
    from app.assistant import Callbacks

    r1 = conv.ask("q1", None, "fast", Callbacks(on_text=deltas.append))
    first_snapshot = [dict(m) for m in conv.messages]
    r2 = conv.ask("q2", {"type": "image", "source": {}}, "fast")
    assert r1.text == "one" and r2.text == "two" and deltas == ["one"]
    assert conv.messages[: len(first_snapshot)] == first_snapshot
    assert [m["role"] for m in conv.messages] == ["user", "assistant", "user", "assistant"]
    # Thinking blocks are kept, not stripped.
    assert conv.messages[1]["content"][0].type == "thinking"
    # Image goes before the question text.
    assert conv.messages[2]["content"][0]["type"] == "image"
    # System prompt is byte-identical between turns (cache + history check).
    assert client.calls[0]["system"] == client.calls[1]["system"]


def test_failed_request_drops_only_the_unanswered_question():
    client = FakeClient([final("one")])
    conv = make_conv(client)
    conv.ask("q1", None, "fast")
    client.error = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        conv.ask("q2", None, "fast")
    assert [m["role"] for m in conv.messages] == ["user", "assistant"]


def test_pause_turn_resumes_without_new_user_message():
    client = FakeClient([final("part1 ", stop="pause_turn", model="claude-sonnet-5-5"),
                         final("part2", model="claude-sonnet-5-5")])
    conv = make_conv(client)
    r = conv.ask("q", None, "deep")
    assert r.text == "part1 part2"
    assert len(client.calls) == 2
    assert client.calls[1]["messages"][-1]["role"] == "assistant"


def test_mode_params():
    conv = make_conv(FakeClient([]))
    fast = conv.request_params("fast")
    deep = conv.request_params("deep")
    assert fast["model"] == "claude-haiku-5-5" and "tools" not in fast and "fallbacks" not in fast
    assert deep["model"] == "claude-sonnet-5-5"
    assert deep["tools"][0]["type"] == "web_search_20260209"
    assert deep["fallbacks"] == "default" and deep["betas"] == ["server-side-fallback-2026-07-01"]
    for p in (fast, deep):
        assert "temperature" not in p and p["thinking"] == {"type": "adaptive"}


def test_refusal_message_appended():
    conv = make_conv(FakeClient([final("", stop="refusal")]))
    assert "סירב" in conv.ask("q", None, "fast").text


# --- capture / updater / hotkey -------------------------------------------------

def test_image_block_is_downscaled_jpeg():
    from app import capture

    block = capture.to_image_block(Image.new("RGB", (3840, 2160), "red"))
    img = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert block["source"]["media_type"] == "image/jpeg"
    assert max(img.size) == capture.MAX_LONG_EDGE
    assert capture.downscale(Image.new("RGB", (800, 600))).size == (800, 600)


def test_version_compare():
    from app import updater

    assert updater.is_newer("v0.2.0", "0.1.9")
    assert updater.is_newer("v0.10.0", "0.9.0")
    assert not updater.is_newer("v0.1.0", "0.1.0")


def test_hotkey_keys():
    from app import hotkey

    assert hotkey.virtual_key("a") == ord("A")
    assert hotkey.virtual_key("F12") == 0x7B
    assert hotkey.modifier_mask(["ctrl", "shift"]) & 0x0006 == 0x0006
    with pytest.raises(ValueError):
        hotkey.virtual_key("??")


def test_settings_roundtrip_ignores_unknown_fields():
    from app import config

    s = config.Settings(mode="deep")
    s.save()
    path = config.data_dir() / "settings.json"
    data = json.loads(path.read_text())
    data["bogus"] = 1
    path.write_text(json.dumps(data))
    assert config.Settings.load().mode == "deep"
