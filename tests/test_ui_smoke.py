"""Builds the overlay offscreen and drives one fake question through it."""

import os
from types import SimpleNamespace as NS

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")


def test_overlay_renders_answer(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from app import knowledge, ui
    from app.assistant import TurnResult
    from app.config import Settings

    app = QApplication.instance() or QApplication([])
    overlay = ui.Overlay(Settings())
    overlay.knowledge_loaded(knowledge.load(allow_remote=False))
    assert overlay.conversation is not None

    overlay.turns.append(("איפה מתאמנים ברמה 15?", ""))
    overlay._on_delta("**Henesys")
    overlay._on_done(TurnResult("**Henesys Hunting Ground** - תשובה", 0.0012, 1000,
                                "claude-haiku-5-5", "end_turn"))
    html = overlay.view.toPlainText()
    assert "Henesys Hunting Ground" in html and "איפה מתאמנים" in html
    assert "0.12¢" in overlay.status.text()

    mode_before = overlay.settings.mode
    overlay.toggle_mode()
    assert overlay.settings.mode != mode_before and overlay.turns == []
    overlay.shutdown()
    app.processEvents()
