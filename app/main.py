"""Entry point."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

import threading

from . import config, desktop
from .ui import Overlay, StartupWorker, build_tray, make_icon


def main() -> int:
    if sys.platform == "win32":
        # Crisp text on high-DPI screens and our own taskbar identity.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("maple-assistant")

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setLayoutDirection(Qt.RightToLeft)
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(make_icon())

    instance = desktop.SingleInstance()
    if instance.notify_running_instance():
        return 0  # the running copy shows its window
    instance.listen()

    settings = config.Settings.load()
    overlay = Overlay(settings)

    if not config.load_api_key() and not overlay.open_settings(first_run=True):
        return 0

    overlay.register_hotkey()
    instance.show_requested.connect(overlay.show_overlay)

    if settings.desktop_shortcut:
        def make_shortcut() -> None:
            target = desktop.ensure_desktop_shortcut(settings.shortcut_target)
            if target:
                settings.shortcut_target = target
        threading.Thread(target=make_shortcut, name="shortcut", daemon=True).start()
    tray = build_tray(app, overlay)  # noqa: F841 - must stay referenced

    startup = StartupWorker()
    startup.knowledge_ready.connect(overlay.knowledge_loaded)
    startup.update_available.connect(overlay.show_update)
    startup.start()

    overlay.show_overlay()
    app.aboutToQuit.connect(overlay.shutdown)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
