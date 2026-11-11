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


def test_hotkey_falls_back_when_taken(monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    from app import hotkey, ui
    from app.config import Settings

    app = QApplication.instance() or QApplication([])
    taken = {("ctrl", "shift", "A")}

    class FakeHotkey:
        def __init__(self, mods, key, cb):
            self.combo = (*mods, key)
            self.error = None

        def start(self):
            if self.combo in taken:
                self.error = "taken"
                return False
            return True

        def stop(self):
            pass

    shown = []
    monkeypatch.setattr(hotkey, "GlobalHotkey", FakeHotkey)
    monkeypatch.setattr(ui, "message", lambda kind, title, text: shown.append(text))

    overlay = ui.Overlay(Settings())
    overlay.register_hotkey()
    assert (overlay.settings.hotkey_modifiers, overlay.settings.hotkey_key) == (["ctrl", "shift"], "Q")
    assert shown and "Ctrl+Shift+Q" in shown[0]
    app.processEvents()


def test_settings_dialog_is_top_level_and_on_top():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from app import ui
    from app.config import Settings

    app = QApplication.instance() or QApplication([])
    dlg = ui.SettingsDialog(Settings())
    assert dlg.parent() is None
    assert dlg.windowFlags() & Qt.WindowStaysOnTopHint
    assert "background" in dlg.styleSheet()
    app.processEvents()


def test_second_launch_asks_first_to_show(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from app import desktop

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(desktop, "_server_name", lambda: f"ma-test-{tmp_path.name}")
    first = desktop.SingleInstance()
    assert not first.notify_running_instance()
    first.listen()
    shown = []
    first.show_requested.connect(lambda: shown.append(True))
    second = desktop.SingleInstance()
    assert second.notify_running_instance()
    for _ in range(50):
        app.processEvents()
        if shown:
            break
    assert shown


def test_close_button_quits(monkeypatch):
    from PySide6.QtWidgets import QApplication

    from app import ui
    from app.config import Settings

    app = QApplication.instance() or QApplication([])
    quits = []
    monkeypatch.setattr(QApplication, "quit", staticmethod(lambda: quits.append(True)))
    overlay = ui.Overlay(Settings())
    overlay.quit_app()
    assert quits


def test_shortcut_is_noop_outside_packaged_windows_app():
    from app import desktop

    assert desktop.ensure_desktop_shortcut(None) is None
