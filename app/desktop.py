"""Desktop integration: single running instance and a desktop shortcut."""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

SHORTCUT_NAME = "Maple Assistant.lnk"


def _server_name() -> str:
    return f"maple-assistant-{getpass.getuser()}"


class SingleInstance(QObject):
    """First copy listens on a local pipe. A second copy (e.g. a click on the
    desktop icon while the app is already running) asks the first copy to show
    its window, then exits."""

    show_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._server: QLocalServer | None = None

    def notify_running_instance(self) -> bool:
        """True if another copy is running (and was told to show itself)."""
        sock = QLocalSocket()
        sock.connectToServer(_server_name())
        if not sock.waitForConnected(500):
            return False
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def listen(self) -> None:
        QLocalServer.removeServer(_server_name())  # clear a stale pipe after a crash
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(_server_name())

    def _on_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
        self.show_requested.emit()


def exe_path() -> Path | None:
    """Path of the packaged .exe, or None when running from source."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


_PS_SCRIPT = (
    "$d=[Environment]::GetFolderPath('Desktop');"
    "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d $env:MA_LNK));"
    "$s.TargetPath=$env:MA_EXE;"
    "$s.WorkingDirectory=$env:MA_DIR;"
    "$s.IconLocation=$env:MA_EXE+',0';"
    "$s.Description='Maple Assistant';"
    "$s.Save()"
)


def ensure_desktop_shortcut(last_target: str | None) -> str | None:
    """Create or re-point the desktop shortcut when the exe moved or the
    shortcut is missing. Returns the target written, or None if nothing was done.

    Paths are passed through environment variables, never spliced into the
    PowerShell command, so odd folder names can't break or inject into it."""
    exe = exe_path()
    if sys.platform != "win32" or exe is None:
        return None
    desktop_guess = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop" / SHORTCUT_NAME
    if last_target == str(exe) and desktop_guess.exists():
        return None
    env = {**os.environ, "MA_EXE": str(exe), "MA_DIR": str(exe.parent), "MA_LNK": SHORTCUT_NAME}
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", _PS_SCRIPT],
            env=env, timeout=20, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return None
    return str(exe)
