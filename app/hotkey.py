"""Global hotkey via the Win32 RegisterHotKey API.

Why RegisterHotKey and not a keyboard hook library:
- It is delivered even when the game window has focus, including when the game
  runs elevated (low-level hooks are blocked across integrity levels).
- It does not inject into or read input from other processes, so it looks like
  any normal desktop shortcut to anti-cheat software.
"""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from typing import Callable

MODIFIERS = {"alt": 0x0001, "ctrl": 0x0002, "shift": 0x0004, "win": 0x0008}
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

_SPECIAL_KEYS = {
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "PAUSE": 0x13,
    "SCROLLLOCK": 0x91, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
    **{f"F{i}": 0x6F + i for i in range(1, 13)},
}


def virtual_key(key: str) -> int:
    key = key.upper()
    if key in _SPECIAL_KEYS:
        return _SPECIAL_KEYS[key]
    if len(key) == 1 and (key.isalpha() or key.isdigit()):
        return ord(key)
    raise ValueError(f"Unsupported hotkey key: {key!r}")


def modifier_mask(modifiers: list[str]) -> int:
    mask = MOD_NOREPEAT
    for name in modifiers:
        mask |= MODIFIERS[name.lower()]
    return mask


def describe(modifiers: list[str], key: str) -> str:
    return "+".join([m.capitalize() for m in modifiers] + [key.upper()])


class GlobalHotkey:
    """Runs a message loop on a background thread and calls `callback(hwnd)`
    with the window that was in the foreground when the hotkey was pressed."""

    HOTKEY_ID = 1

    def __init__(self, modifiers: list[str], key: str, callback: Callable[[int | None], None]):
        self._mods = modifier_mask(modifiers)
        self._vk = virtual_key(key)
        self._callback = callback
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._registered = threading.Event()
        self.error: str | None = None

    def start(self) -> bool:
        if sys.platform != "win32":
            self.error = "unsupported"
            return False
        self._thread = threading.Thread(target=self._run, name="hotkey", daemon=True)
        self._thread.start()
        self._registered.wait(timeout=2)
        return self.error is None

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        if not user32.RegisterHotKey(None, self.HOTKEY_ID, self._mods, self._vk):
            self.error = "taken"
            self._registered.set()
            return
        self._registered.set()
        msg = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    hwnd = user32.GetForegroundWindow() or None
                    self._callback(hwnd)
        finally:
            user32.UnregisterHotKey(None, self.HOTKEY_ID)


def acquire_single_instance(name: str = "MapleAssistantSingleInstance") -> bool:
    """True if this is the only running copy. Keeps the mutex for the process lifetime."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    handle = kernel32.CreateMutexW(None, False, name)
    already = ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS
    globals()["_instance_mutex"] = handle  # keep the handle alive
    return not (handle and already)


def restore_focus(hwnd: int | None) -> None:
    """Give keyboard focus back to the game after the overlay hides."""
    if sys.platform == "win32" and hwnd:
        ctypes.windll.user32.SetForegroundWindow(hwnd)
