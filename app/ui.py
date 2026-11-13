"""Overlay window, settings dialog and tray icon (PySide6)."""

from __future__ import annotations

import anthropic
from PySide6.QtCore import QObject, QPoint, Qt, QThread, QTimer, Signal
from PySide6.QtGui import (QAction, QColor, QDesktopServices, QFont, QIcon, QPainter,
                           QPixmap, QTextBlockFormat, QTextCursor)
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMenu, QMessageBox,
                               QPushButton, QSizeGrip, QSlider, QSystemTrayIcon,
                               QTextBrowser, QVBoxLayout, QWidget)

from . import __version__, capture, config, hotkey, knowledge, updater
from .assistant import FAST_MODEL, Callbacks, Conversation, TurnResult, UsageLedger

HOTKEY_PRESETS = [
    (["ctrl", "shift"], "A"),
    (["ctrl", "shift"], "Q"),
    (["ctrl", "alt"], "A"),
    ([], "SCROLLLOCK"),
    ([], "PAUSE"),
    ([], "F12"),
]

STYLE = """
#panel { background: rgba(24, 26, 33, 235); border: 1px solid #3a3f4b; border-radius: 10px; }
QLabel, QCheckBox { color: #e6e6e6; }
#title { font-weight: bold; color: #ffb347; }
#status { color: #9aa3b2; font-size: 9pt; }
#banner { background: #2e5a2e; color: #e6ffe6; border-radius: 6px; padding: 4px; }
QTextBrowser { background: transparent; color: #f0f0f0; border: none; font-size: 10.5pt; }
QLineEdit { background: #11131a; color: #ffffff; border: 1px solid #4a5060;
            border-radius: 6px; padding: 6px; font-size: 10.5pt; }
QPushButton { background: #2c313c; color: #e6e6e6; border: 1px solid #444b59;
              border-radius: 6px; padding: 3px 8px; }
QPushButton:hover { background: #3a4150; }
QPushButton#mode[deep="true"] { background: #4a3a7a; }
"""


DIALOG_STYLE = """
QDialog, QMessageBox { background: #20232b; }
QLabel { color: #e6e6e6; }
QLineEdit, QComboBox, QDoubleSpinBox { background: #11131a; color: #ffffff;
    border: 1px solid #4a5060; border-radius: 4px; padding: 4px; }
QPushButton { background: #2c313c; color: #e6e6e6; border: 1px solid #444b59;
    border-radius: 4px; padding: 4px 12px; }
QPushButton:hover { background: #3a4150; }
"""


def message(kind: str, title: str, text: str) -> int:
    """Top-level, always-on-top, opaque message box.

    Never parented to the overlay: the overlay is a translucent, topmost tool
    window, and children of it can render see-through or end up behind it."""
    icons = {"info": QMessageBox.Information, "warn": QMessageBox.Warning,
             "ask": QMessageBox.Question}
    box = QMessageBox(icons[kind], title, text)
    box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    box.setStyleSheet(DIALOG_STYLE)
    box.setLayoutDirection(Qt.RightToLeft)
    if kind == "ask":
        box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    box.raise_()
    box.activateWindow()
    return box.exec()


def make_icon() -> QIcon:
    pix = QPixmap(64, 64)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor("#ff8c1a"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(4, 4, 56, 56)
    p.setPen(QColor("white"))
    p.setFont(QFont("Segoe UI", 28, QFont.Bold))
    p.drawText(pix.rect(), Qt.AlignCenter, "M")
    p.end()
    return QIcon(pix)


# --- background workers ---------------------------------------------------------

class AskWorker(QThread):
    text_delta = Signal(str)
    status = Signal(str)
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, conversation: Conversation, question: str, image: dict | None, mode: str):
        super().__init__()
        self.conversation, self.question, self.image, self.mode = conversation, question, image, mode

    def run(self) -> None:
        cb = Callbacks(on_text=self.text_delta.emit, on_status=self.status.emit)
        try:
            result = self.conversation.ask(self.question, self.image, self.mode, cb)
        except anthropic.AuthenticationError:
            self.failed.emit("מפתח ה-API לא תקין. פתח הגדרות (⚙) והדבק מפתח חדש.")
        except anthropic.PermissionDeniedError:
            self.failed.emit("למפתח אין הרשאה. בדוק את החשבון ב-console.anthropic.com.")
        except anthropic.RateLimitError:
            self.failed.emit("יותר מדי בקשות ברגע זה. נסה שוב בעוד דקה.")
        except anthropic.BadRequestError as e:
            msg = str(getattr(e, "message", e))
            if "credit" in msg.lower() or "balance" in msg.lower():
                self.failed.emit("נגמר הקרדיט בחשבון. טען קרדיט ב-console.anthropic.com → Billing.")
            else:
                self.failed.emit(f"שגיאה בבקשה: {msg}")
        except anthropic.APIStatusError as e:
            self.failed.emit(f"שגיאת שרת ({e.status_code}). נסה שוב בעוד רגע.")
        except anthropic.APIConnectionError:
            self.failed.emit("אין חיבור לאינטרנט או לשרתי Claude.")
        except Exception as e:  # keep the overlay alive whatever happens
            self.failed.emit(f"שגיאה לא צפויה: {e}")
        else:
            self.done.emit(result)


class StartupWorker(QThread):
    knowledge_ready = Signal(object)
    update_available = Signal(str, str)

    def run(self) -> None:
        self.knowledge_ready.emit(knowledge.load())
        found = updater.check()
        if found:
            self.update_available.emit(*found)


class HotkeyBridge(QObject):
    """Moves hotkey events from the Win32 thread onto the Qt thread."""
    pressed = Signal(object)


# --- settings ----------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: config.Settings, parent=None, first_run: bool = False):
        super().__init__(None)
        self.settings = settings
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setStyleSheet(DIALOG_STYLE)
        self.setWindowTitle("הגדרות - עוזר מייפל")
        self.setLayoutDirection(Qt.RightToLeft)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        if first_run:
            intro = QLabel(
                "ברוך הבא! כדי להתחיל, הדבק כאן מפתח API של Anthropic.\n"
                "יוצרים אותו ב-console.anthropic.com ← API Keys ← Create Key.\n"
                "המפתח נשמר רק במחשב שלך (Windows Credential Manager)."
            )
            intro.setWordWrap(True)
            layout.addWidget(intro)

        form = QFormLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.Password)
        self.key_edit.setLayoutDirection(Qt.LeftToRight)
        self.key_edit.setPlaceholderText("sk-ant-..." if first_run else "השאר ריק כדי לא לשנות")
        form.addRow("מפתח API:", self.key_edit)

        self.hotkey_combo = QComboBox()
        for mods, key in HOTKEY_PRESETS:
            self.hotkey_combo.addItem(hotkey.describe(mods, key), (mods, key))
        current = (settings.hotkey_modifiers, settings.hotkey_key)
        idx = next((i for i, p in enumerate(HOTKEY_PRESETS) if p == current), 0)
        self.hotkey_combo.setCurrentIndex(idx)
        form.addRow("מקש קיצור:", self.hotkey_combo)

        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(50, 100)
        self.opacity.setValue(int(settings.opacity * 100))
        form.addRow("שקיפות חלון:", self.opacity)

        self.budget = QDoubleSpinBox()
        self.budget.setRange(0.5, 500)
        self.budget.setPrefix("$")
        self.budget.setValue(settings.budget_warning_usd)
        form.addRow("התראה כשההוצאה החודשית עוברת:", self.budget)
        self.shortcut_box = QCheckBox("אייקון בשולחן העבודה")
        self.shortcut_box.setChecked(settings.desktop_shortcut)
        form.addRow("", self.shortcut_box)
        layout.addLayout(form)

        note = QLabel("ההתראה היא הערכה מקומית בלבד. תקרת הוצאה אמיתית מגדירים ב-console.anthropic.com ← Limits.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._first_run = first_run

    def _save(self) -> None:
        key = self.key_edit.text().strip()
        if key:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                anthropic.Anthropic(api_key=key, timeout=15, max_retries=1).models.retrieve(FAST_MODEL)
            except anthropic.AuthenticationError:
                QApplication.restoreOverrideCursor()
                message("warn", "מפתח לא תקין", "המפתח נדחה על ידי Anthropic. בדוק שהעתקת אותו במלואו.")
                return
            except Exception as e:
                QApplication.restoreOverrideCursor()
                if message("ask", "לא הצלחתי לבדוק",
                                        f"לא הצלחתי לאמת את המפתח ({e}).\nלשמור בכל זאת?") != QMessageBox.Yes:
                    return
            QApplication.restoreOverrideCursor()
            config.save_api_key(key)
        elif self._first_run:
            message("warn", "חסר מפתח", "צריך מפתח API כדי שהעוזר יעבוד.")
            return
        mods, hk = self.hotkey_combo.currentData()
        self.settings.hotkey_modifiers, self.settings.hotkey_key = list(mods), hk
        self.settings.opacity = self.opacity.value() / 100
        self.settings.budget_warning_usd = self.budget.value()
        self.settings.desktop_shortcut = self.shortcut_box.isChecked()
        self.settings.save()
        self.accept()


# --- overlay -----------------------------------------------------------------------

class Overlay(QWidget):
    def __init__(self, settings: config.Settings):
        # Not a Tool window: the player wants a taskbar button. The minimize
        # hint lets Windows minimize/restore a frameless window from the taskbar.
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.WindowMinimizeButtonHint)
        self.settings = settings
        self.ledger = UsageLedger()
        self.kb: knowledge.KnowledgeBase | None = None
        self.conversation: Conversation | None = None
        self.worker: AskWorker | None = None
        self.game_hwnd: int | None = None
        self.pending_image: dict | None = None
        self.turns: list[tuple[str, str]] = []
        self._streaming = ""
        self._drag_from: QPoint | None = None
        self._hotkey: hotkey.GlobalHotkey | None = None
        self._bridge = HotkeyBridge()
        self._bridge.pressed.connect(self.on_hotkey)

        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("עוזר מייפל")
        self.setWindowOpacity(settings.opacity)
        self._build()
        self._restore_geometry()

        self._render_timer = QTimer(self, interval=60, singleShot=True)
        self._render_timer.timeout.connect(self._render)

    # layout
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame(objectName="panel")
        outer.addWidget(panel)
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 8, 10, 8)

        header = QHBoxLayout()
        title = QLabel("🍁 עוזר מייפל", objectName="title")
        header.addWidget(title)
        header.addStretch()
        self.mode_btn = QPushButton(objectName="mode")
        self.mode_btn.setToolTip("מהיר: Claude Haiku, זול מאוד.\nמעמיק: Claude Sonnet + חיפוש באינטרנט.\nהחלפת מצב פותחת שיחה חדשה.")
        self.mode_btn.clicked.connect(self.toggle_mode)
        header.addWidget(self.mode_btn)
        self.shot_box = QCheckBox("📷")
        self.shot_box.setToolTip("צרף צילום מסך של המשחק לשאלה")
        self.shot_box.setChecked(self.settings.attach_screenshot)
        self.shot_box.toggled.connect(self._shot_toggled)
        header.addWidget(self.shot_box)
        for text, tip, slot in (("🆕", "שיחה חדשה", self.new_conversation),
                                ("⚙", "הגדרות", self.open_settings),
                                ("—", "מזער (Esc) - חוזרים בלחיצה על האייקון בשורת המשימות", self.hide_overlay),
                                ("✕", "סגור את העוזר לגמרי", self.quit_app)):
            btn = QPushButton(text)
            btn.setToolTip(tip)
            btn.setFixedWidth(34)
            btn.clicked.connect(slot)
            header.addWidget(btn)
        v.addLayout(header)

        self.banner = QPushButton(objectName="banner")
        self.banner.hide()
        v.addWidget(self.banner)

        self.view = QTextBrowser()
        self.view.setOpenExternalLinks(True)
        self.view.setLayoutDirection(Qt.RightToLeft)
        v.addWidget(self.view, 1)

        self.status = QLabel(objectName="status")
        v.addWidget(self.status)

        bottom = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText("שאל שאלה ולחץ Enter  ·  Esc להסתרה")
        self.input.returnPressed.connect(self.send)
        bottom.addWidget(self.input, 1)
        bottom.addWidget(QSizeGrip(self), 0, Qt.AlignBottom)
        v.addLayout(bottom)

        self.setStyleSheet(STYLE)
        self._update_mode_button()
        self._set_status("טוען מאגר ידע...")

    def _restore_geometry(self) -> None:
        if self.settings.geometry:
            x, y, w, h = self.settings.geometry
            self.setGeometry(x, y, w, h)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.setGeometry(screen.right() - 470, screen.top() + 80, 440, 520)

    # hotkey
    def register_hotkey(self) -> None:
        """Register the chosen hotkey; if another program owns it, fall back to
        the first free preset and tell the player which one is active."""
        if self._hotkey:
            self._hotkey.stop()
            self._hotkey = None
        wanted = (list(self.settings.hotkey_modifiers), self.settings.hotkey_key)
        candidates = [wanted] + [(list(m), k) for m, k in HOTKEY_PRESETS if (list(m), k) != wanted]
        for mods, key in candidates:
            hk = hotkey.GlobalHotkey(mods, key, self._bridge.pressed.emit)
            if hk.start():
                self._hotkey = hk
                break
            if hk.error == "unsupported":
                return
        if self._hotkey is None:
            message("warn", "מקש קיצור",
                                "כל מקשי הקיצור האפשריים תפוסים על ידי תוכנות אחרות.\n"
                                "אפשר לפתוח את העוזר מהאייקון הכתום M שליד השעון.")
            return
        name = hotkey.describe(mods, key)
        if (mods, key) != wanted:
            old_name = hotkey.describe(*wanted)
            self.settings.hotkey_modifiers, self.settings.hotkey_key = mods, key
            self.settings.save()
            message("info", "מקש קיצור",
                                    f"{old_name} תפוס על ידי תוכנה אחרת במחשב.\n"
                                    f"עברתי ל-{name}. אפשר לשנות בהגדרות (⚙).")
        self.input.setPlaceholderText(f"שאל שאלה ולחץ Enter  ·  Esc להסתרה  ·  {name} לפתיחה")

    def on_hotkey(self, hwnd: int | None) -> None:
        own = int(self.winId())
        if self._is_open() and self.isActiveWindow():
            self.hide_overlay()
            return
        if hwnd and hwnd != own:
            self.game_hwnd = hwnd
        if self._is_open():
            # Get out of the way first so the overlay itself isn't in the screenshot
            # (minimizing animates, so give it a moment).
            self.showMinimized()
            QTimer.singleShot(300, self._capture_and_show)
        else:
            self._capture_and_show()

    def _capture_and_show(self) -> None:
        self.pending_image = None
        if self.shot_box.isChecked():
            try:
                self.pending_image = capture.to_image_block(capture.grab(self.game_hwnd))
            except Exception as e:
                self._set_status(f"צילום המסך נכשל ({e}). השאלה תישלח בלי תמונה.")
        self.show_overlay()

    def _is_open(self) -> bool:
        return self.isVisible() and not self.isMinimized()

    def show_overlay(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus()

    def hide_overlay(self) -> None:
        # Minimize rather than hide, so the taskbar button stays and one click
        # brings the assistant back.
        self.showMinimized()
        hotkey.restore_focus(self.game_hwnd)

    # conversation
    def knowledge_loaded(self, kb: knowledge.KnowledgeBase) -> None:
        self.kb = kb
        labels = {"remote": "עדכני", "cache": "מהעותק האחרון", "bundled": "מובנה", "empty": "ריק"}
        self._set_status(f"מאגר ידע {kb.version} ({labels[kb.source]}) · {self._month_text()}")
        self.new_conversation(quiet=True)

    def new_conversation(self, quiet: bool = False) -> None:
        key = config.load_api_key()
        if not key or self.kb is None:
            return
        client = anthropic.Anthropic(api_key=key, max_retries=2)
        self.conversation = Conversation(client=client, knowledge=self.kb)
        self.turns = []
        self._render()
        if not quiet:
            self._set_status("שיחה חדשה התחילה.")

    def send(self) -> None:
        question = self.input.text().strip()
        if not question or (self.worker and self.worker.isRunning()):
            return
        if self.conversation is None:
            self.new_conversation(quiet=True)
            if self.conversation is None:
                self._set_status("חסר מפתח API או שמאגר הידע עוד נטען.")
                return
        if self.conversation.is_full:
            self.new_conversation(quiet=True)
            self._set_status("השיחה הקודמת התארכה, אז פתחתי חדשה כדי לחסוך בעלות.")
        self.input.clear()
        self.turns.append((question, ""))
        self._streaming = ""
        self._render()
        self._set_status("שולח...")
        image, self.pending_image = self.pending_image, None
        self.worker = AskWorker(self.conversation, question, image, self.settings.mode)
        self.worker.text_delta.connect(self._on_delta)
        self.worker.status.connect(self._set_status)
        self.worker.done.connect(self._on_done)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()

    def _on_delta(self, text: str) -> None:
        if not self._streaming:
            self._set_status("עונה...")
        self._streaming += text
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _on_done(self, result: TurnResult) -> None:
        q, _ = self.turns[-1]
        self.turns[-1] = (q, result.text)
        self._streaming = ""
        self._render()
        self.ledger.add(result.cost_usd)
        extra = f" · {result.searches} חיפושים" if result.searches else ""
        self._set_status(f"עלות התשובה: {result.cost_usd * 100:.2f}¢{extra} · {self._month_text()}")

    def _on_failed(self, message: str) -> None:
        q, _ = self.turns[-1]
        self.turns[-1] = (q, f"⚠️ {message}")
        self._streaming = ""
        self._render()
        self._set_status("השאלה לא נשלחה. אפשר לנסות שוב.")
        self.input.setText(q)

    def _month_text(self) -> str:
        spent = self.ledger.this_month()
        warn = " ⚠️ עברת את תקציב ההתראה" if spent > self.settings.budget_warning_usd else ""
        return f"החודש: ${spent:.2f}{warn}"

    def _render(self) -> None:
        parts = []
        for i, (q, a) in enumerate(self.turns):
            if i == len(self.turns) - 1 and not a:
                a = self._streaming or "_..._"
            parts.append(f"**❓ {q}**\n\n{a}")
        if not parts:
            parts.append("_לחץ על מקש הקיצור בזמן המשחק, שאל שאלה ולחץ Enter._")
        self.view.setMarkdown("\n\n---\n\n".join(parts))
        # Force right-to-left paragraphs even when a line starts with an English name.
        cursor = QTextCursor(self.view.document())
        cursor.select(QTextCursor.Document)
        fmt = QTextBlockFormat()
        fmt.setLayoutDirection(Qt.RightToLeft)
        cursor.mergeBlockFormat(fmt)
        self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().maximum())

    def _set_status(self, text: str) -> None:
        self.status.setText(text)

    # controls
    def toggle_mode(self) -> None:
        self.settings.mode = "deep" if self.settings.mode == "fast" else "fast"
        self.settings.save()
        self._update_mode_button()
        # Different model and tools: start clean rather than mix histories.
        self.new_conversation(quiet=True)
        self._set_status("עברתי מצב ופתחתי שיחה חדשה.")

    def _update_mode_button(self) -> None:
        deep = self.settings.mode == "deep"
        self.mode_btn.setText("🔍 מעמיק" if deep else "⚡ מהיר")
        self.mode_btn.setProperty("deep", "true" if deep else "false")
        self.mode_btn.style().unpolish(self.mode_btn)
        self.mode_btn.style().polish(self.mode_btn)

    def _shot_toggled(self, on: bool) -> None:
        self.settings.attach_screenshot = on
        self.settings.save()
        if not on:
            self.pending_image = None

    def open_settings(self, first_run: bool = False) -> bool:
        was_visible = self.isVisible()
        self.hide()  # avoid two topmost windows fighting over focus
        dlg = SettingsDialog(self.settings, first_run=first_run)
        dlg.raise_()
        dlg.activateWindow()
        ok = dlg.exec() == QDialog.Accepted
        if ok:
            self.setWindowOpacity(self.settings.opacity)
            self.register_hotkey()
            self.new_conversation(quiet=True)
        if was_visible or first_run:
            self.show_overlay()
        return ok

    def show_update(self, tag: str, url: str) -> None:
        self.banner.setText(f"⬆️ גרסה חדשה {tag} זמינה - לחץ להורדה")
        self.banner.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(url)))
        self.banner.show()

    # window behaviour
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key_Escape:
            self.hide_overlay()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
        self._save_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._save_geometry()

    def _save_geometry(self) -> None:
        g = self.geometry()
        self.settings.geometry = [g.x(), g.y(), g.width(), g.height()]

    def quit_app(self) -> None:
        self.hide()
        hotkey.restore_focus(self.game_hwnd)
        QApplication.quit()

    def shutdown(self) -> None:
        self._save_geometry()
        self.settings.save()
        if self._hotkey:
            self._hotkey.stop()


def build_tray(app: QApplication, overlay: Overlay) -> QSystemTrayIcon:
    tray = QSystemTrayIcon(make_icon(), app)
    tray.setToolTip(f"עוזר מייפל {__version__}")
    menu = QMenu()
    for text, slot in (("הצג", overlay.show_overlay), ("הגדרות", overlay.open_settings),
                       ("יציאה", app.quit)):
        act = QAction(text, menu)
        act.triggered.connect(slot)
        menu.addAction(act)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: overlay.show_overlay()
                           if reason == QSystemTrayIcon.Trigger else None)
    tray.show()
    return tray
