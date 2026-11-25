# zetech_bot.py
# Email sign-in -> one-time M-Pesa access -> VS Code project scaffolder.
# Requires: pip install PySide6 pywin32 psutil requests
# Run:      python zetech_bot.py

import os
import sys
import time
import json
import random
import shutil
import zipfile
import tempfile
import threading
import subprocess
from pathlib import Path

import requests
import psutil
import win32gui
import win32api
import win32con
import ctypes
from ctypes import wintypes

from PySide6.QtCore import Qt, Signal, QObject, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QWidget, QStackedWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QPlainTextEdit, QComboBox,
    QCheckBox, QSpinBox, QMessageBox, QFileDialog, QListWidget, QGroupBox,
    QFormLayout, QSplitter, QStatusBar
)

# ============================================================================
# CONFIG  --  edit this block for your environment
# ============================================================================
CONFIG = {
    "API_URL":   "http://127.0.0.1:8000",
    "HTTP_TIMEOUT": 15,
    # typing knobs
    "DEFAULT_DELAY_MIN_MS": 15,
    "DEFAULT_DELAY_MAX_MS": 45,
    "DEFAULT_JITTER_ENABLED": False,
    "DEFAULT_JITTER_RADIUS_PX": 2,
    # project
    "PROJECT_DIR_NAME": "MY Site",
}

# ============================================================================


# ----------------------------------------------------------------------------
# Win32 SendInput plumbing
# ----------------------------------------------------------------------------
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                ("dwExtraInfo", ULONG_PTR)]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD)]

class _INPUTunion(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]

class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTunion)]

INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_MOVE = 0x0001

_send_input = ctypes.windll.user32.SendInput
_send_input.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)

def _send_inputs(inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    return _send_input(n, arr, ctypes.sizeof(INPUT))

def send_unicode_char(ch: str):
    """Send a single unicode character as a key press+release via SendInput."""
    code = ord(ch)
    down = INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0)))
    up = INPUT(type=INPUT_KEYBOARD,
               u=_INPUTunion(ki=KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0)))
    _send_inputs([down, up])

def send_enter_key():
    """Send a real Enter key press so the editor starts a new line."""
    down = INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTunion(ki=KEYBDINPUT(win32con.VK_RETURN, 0, 0, 0, 0)))
    up = INPUT(type=INPUT_KEYBOARD,
               u=_INPUTunion(ki=KEYBDINPUT(
                   win32con.VK_RETURN, 0, KEYEVENTF_KEYUP, 0, 0)))
    _send_inputs([down, up])

def send_mouse_relative(dx, dy):
    mi = INPUT(type=INPUT_MOUSE,
               u=_INPUTunion(mi=MOUSEINPUT(dx, dy, 0, MOUSEEVENTF_MOVE, 0, 0)))
    _send_inputs([mi])

def get_foreground_window_info():
    hwnd = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(hwnd) if hwnd else ""
    return hwnd, title

def is_vscode_foreground():
    _, title = get_foreground_window_info()
    return "Visual Studio Code" in title or title.endswith(" - Code")

def is_project_vscode_foreground(project_name):
    _, title = get_foreground_window_info()
    is_vscode = "Visual Studio Code" in title or title.endswith(" - Code")
    return is_vscode and project_name.casefold() in title.casefold()

def process_elevated(pid=None):
    """Rough check: is our process running elevated? Used to warn on SendInput failures."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


# ----------------------------------------------------------------------------
# Template storage
# ----------------------------------------------------------------------------
TEMPLATES_DIR = Path(__file__).parent / "templates"
TEMPLATES_DIR.mkdir(exist_ok=True)

REQUIRED_FILES = ("index.html", "index.css", "script.js")

DEFAULT_BUNDLE = {
    "index.html": """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>MY Site</title>
  <link rel="stylesheet" href="index.css" />
</head>
<body>
  <header class="hero">
    <h1>Welcome to MY Site</h1>
    <p>A starter project generated by zetech_bot.</p>
  </header>
  <script src="script.js"></script>
</body>
</html>
""",
    "index.css": """* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, sans-serif;
  background: #0f172a;
  color: #e2e8f0;
}
.hero { padding: 4rem 2rem; text-align: center; }
.hero h1 { font-size: 2.5rem; margin: 0 0 0.5rem; }
""",
    "script.js": """console.log("MY Site loaded.");
""",
}


def save_template(name: str, files: dict):
    safe = "".join(c for c in name if c.isalnum() or c in " _-").strip()
    if not safe:
        raise ValueError("Template name must contain letters or digits.")
    dest = TEMPLATES_DIR / safe
    dest.mkdir(parents=True, exist_ok=True)
    for fname, content in files.items():
        (dest / fname).write_text(content, encoding="utf-8")
    return safe


def list_templates():
    return sorted([p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir()])


def load_template(name: str) -> dict:
    src = TEMPLATES_DIR / name
    out = {}
    for fname in REQUIRED_FILES:
        p = src / fname
        out[fname] = p.read_text(encoding="utf-8") if p.exists() else ""
    return out


def import_bundle_from_path(path: Path) -> dict:
    """Accept either a folder containing the 3 files, or a .zip of them."""
    files = {}
    if path.is_file() and path.suffix.lower() == ".zip":
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(path) as z:
                z.extractall(td)
            root = Path(td)
            for fname in REQUIRED_FILES:
                matches = list(root.rglob(fname))
                if not matches:
                    raise FileNotFoundError(f"Zip is missing {fname}")
                files[fname] = matches[0].read_text(encoding="utf-8")
        return files
    if path.is_dir():
        for fname in REQUIRED_FILES:
            p = path / fname
            if not p.exists():
                raise FileNotFoundError(f"Folder is missing {fname}")
            files[fname] = p.read_text(encoding="utf-8")
        return files
    raise ValueError("Select a folder or .zip containing index.html/index.css/script.js")


# ----------------------------------------------------------------------------
# Auth client
# ----------------------------------------------------------------------------
class AuthClient:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = None

    def _post(self, path, payload, authenticated=False):
        headers = {"Authorization": f"Bearer {self.token}"} if authenticated and self.token else {}
        response = requests.post(self.cfg["API_URL"].rstrip("/") + path,
                                 json=payload, headers=headers,
                                 timeout=self.cfg["HTTP_TIMEOUT"])
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.ok:
            raise RuntimeError(body.get("detail", f"Backend returned HTTP {response.status_code}"))
        return body

    def request_email_code(self, email: str):
        return self._post("/api/auth/email/request", {"email": email})

    def verify_email_code(self, email: str, code: str):
        body = self._post("/api/auth/email/verify", {"email": email, "code": code})
        self.token = body["access_token"]
        return body

    def start_payment(self, phone: str):
        return self._post("/api/payments/stk-push", {"phone": phone}, authenticated=True)

    def payment_status(self, payment_id: str):
        response = requests.get(self.cfg["API_URL"].rstrip("/") + "/api/payments/" + payment_id,
                                headers={"Authorization": f"Bearer {self.token}"},
                                timeout=self.cfg["HTTP_TIMEOUT"])
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not response.ok:
            raise RuntimeError(body.get("detail", f"Backend returned HTTP {response.status_code}"))
        return body


# ----------------------------------------------------------------------------
# Typing worker
# ----------------------------------------------------------------------------
class TypingWorker(QObject):
    progress = Signal(int, int)          # current, total
    finished = Signal()
    aborted  = Signal(str)

    def __init__(self, text: str, delay_min_ms: int, delay_max_ms: int,
                 jitter_enabled: bool, jitter_radius: int):
        super().__init__()
        # Convert CRLF/CR to one logical newline so each becomes one Enter press.
        self.text = text.replace("\r\n", "\n").replace("\r", "\n")
        self.delay_min = max(0, delay_min_ms) / 1000.0
        self.delay_max = max(self.delay_min, delay_max_ms / 1000.0)
        self.jitter_enabled = jitter_enabled
        self.jitter_radius = max(0, jitter_radius)
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            total = len(self.text)
            for i, ch in enumerate(self.text):
                if self._stop.is_set():
                    self.aborted.emit("Stopped by user.")
                    return
                if not is_project_vscode_foreground(CONFIG["PROJECT_DIR_NAME"]):
                    self.aborted.emit(
                        "The new project window lost focus. Typing stopped.")
                    return
                if ch == "\n":
                    send_enter_key()
                elif ch == "\t":
                    send_unicode_char("\t")
                else:
                    send_unicode_char(ch)
                if self.jitter_enabled and self.jitter_radius > 0:
                    dx = random.randint(-self.jitter_radius, self.jitter_radius)
                    dy = random.randint(-self.jitter_radius, self.jitter_radius)
                    send_mouse_relative(dx, dy)
                    send_mouse_relative(-dx, -dy)
                time.sleep(random.uniform(self.delay_min, self.delay_max))
                if i % 25 == 0:
                    self.progress.emit(i, total)
            self.progress.emit(total, total)
            self.finished.emit()
        except Exception as e:
            self.aborted.emit(f"Typing failed: {e}")


# ----------------------------------------------------------------------------
# Global hotkey: Esc -> stop typing (registered only while typing)
# ----------------------------------------------------------------------------
class EscHotkey(threading.Thread):
    """Polls Esc key state; fires callback once. Cheap and dependency-free."""
    def __init__(self, on_esc):
        super().__init__(daemon=True)
        self.on_esc = on_esc
        self._stop = threading.Event()
        self._armed = threading.Event()

    def stop(self):
        self._stop.set()

    def arm(self):
        self._armed.set()

    def run(self):
        was_down = False
        while not self._stop.is_set():
            if self._armed.is_set():
                down = (win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000) != 0
                if down and not was_down:
                    self._armed.clear()
                    try:
                        self.on_esc()
                    except Exception:
                        pass
                was_down = down
            time.sleep(0.02)


# ----------------------------------------------------------------------------
# UI: Auth screen
# ----------------------------------------------------------------------------
# Email and payment screens
# ----------------------------------------------------------------------------
class EmailAuthScreen(QWidget):
    authed = Signal(bool)

    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.email = ""
        self.stage = 1
        lay = QVBoxLayout(self)
        lay.setContentsMargins(60, 60, 60, 60)
        title = QLabel("Zetech Learning — Access")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        lay.addWidget(title)
        self.hint = QLabel("Enter your email address to receive a sign-in code.")
        self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        self.input = QLineEdit()
        self.input.setPlaceholderText("you@example.com")
        lay.addWidget(self.input)
        self.button = QPushButton("Send code")
        self.button.clicked.connect(self._submit)
        lay.addWidget(self.button)
        self.status = QLabel("")
        self.status.setStyleSheet("color: #b91c1c;")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _submit(self):
        self.status.setText("")
        self.button.setEnabled(False)
        try:
            if self.stage == 1:
                self.email = self.input.text().strip()
                self.auth.request_email_code(self.email)
                self.stage = 2
                self.hint.setText("Enter the 6-digit code sent to your email.")
                self.input.clear()
                self.input.setPlaceholderText("6-digit code")
                self.button.setText("Verify")
            else:
                result = self.auth.verify_email_code(self.email, self.input.text().strip())
                self.authed.emit(bool(result.get("has_access")))
        except Exception as error:
            self.status.setText(str(error))
        finally:
            self.button.setEnabled(True)


class PaymentScreen(QWidget):
    paid = Signal()

    def __init__(self, auth):
        super().__init__()
        self.auth = auth
        self.payment_id = None
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(3000)
        self.poll_timer.timeout.connect(self._check_payment)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(60, 60, 60, 60)
        title = QLabel("One-time access payment")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        lay.addWidget(title)
        info = QLabel("Enter the M-Pesa number to receive a payment prompt. Access unlocks after Daraja confirms payment.")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.phone = QLineEdit()
        self.phone.setPlaceholderText("07XX XXX XXX or 2547XX XXX XXX")
        lay.addWidget(self.phone)
        self.button = QPushButton("Pay with M-Pesa")
        self.button.clicked.connect(self._start_payment)
        lay.addWidget(self.button)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        lay.addStretch(1)

    def _start_payment(self):
        self.status.setText("")
        self.button.setEnabled(False)
        try:
            result = self.auth.start_payment(self.phone.text().strip())
            if result.get("has_access") or result.get("status") == "paid":
                self.paid.emit()
                return
            self.payment_id = result["payment_id"]
            self.status.setText(f"{result.get('message', 'Check your phone to complete payment.')} Amount: KES {result['amount_kes']}.")
            self.poll_timer.start()
        except Exception as error:
            self.status.setText(str(error))
            self.button.setEnabled(True)

    def _check_payment(self):
        if not self.payment_id:
            return
        try:
            result = self.auth.payment_status(self.payment_id)
            if result.get("has_access"):
                self.poll_timer.stop()
                self.status.setText("Payment confirmed. Access unlocked.")
                self.paid.emit()
            elif result.get("status") == "failed":
                self.poll_timer.stop()
                self.payment_id = None
                self.button.setEnabled(True)
                self.status.setText("Payment was not completed. You can try again.")
        except Exception as error:
            self.status.setText(f"Checking payment status: {error}")


# UI: Main screen
# ----------------------------------------------------------------------------
class MainScreen(QWidget):
    def __init__(self):
        super().__init__()
        self.current_files = dict(DEFAULT_BUNDLE)
        self.typing_thread = None
        self.typing_worker = None
        self.esc = EscHotkey(self._on_esc)
        self.esc.start()
        self._build()
        self._refresh_templates()

    # ---- layout ----
    def _build(self):
        root = QVBoxLayout(self)

        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        lv = QVBoxLayout(left)

        tpl_box = QGroupBox("Templates")
        tv = QVBoxLayout(tpl_box)
        self.tpl_list = QListWidget()
        self.tpl_list.currentTextChanged.connect(self._on_template_selected)
        tv.addWidget(self.tpl_list)
        row = QHBoxLayout()
        self.btn_import = QPushButton("Import bundle…")
        self.btn_import.clicked.connect(self._on_import)
        self.btn_save = QPushButton("Save current as template")
        self.btn_save.clicked.connect(self._on_save_template)
        row.addWidget(self.btn_import)
        row.addWidget(self.btn_save)
        tv.addLayout(row)
        lv.addWidget(tpl_box)

        cfg_box = QGroupBox("Typing config")
        form = QFormLayout(cfg_box)
        self.spin_dmin = QSpinBox(); self.spin_dmin.setRange(0, 5000)
        self.spin_dmin.setValue(CONFIG["DEFAULT_DELAY_MIN_MS"])
        self.spin_dmax = QSpinBox(); self.spin_dmax.setRange(0, 5000)
        self.spin_dmax.setValue(CONFIG["DEFAULT_DELAY_MAX_MS"])
        self.chk_jitter = QCheckBox("Mouse jitter")
        self.chk_jitter.setChecked(CONFIG["DEFAULT_JITTER_ENABLED"])
        self.spin_jr = QSpinBox(); self.spin_jr.setRange(0, 20)
        self.spin_jr.setValue(CONFIG["DEFAULT_JITTER_RADIUS_PX"])
        form.addRow("Delay min (ms)", self.spin_dmin)
        form.addRow("Delay max (ms)", self.spin_dmax)
        form.addRow(self.chk_jitter)
        form.addRow("Jitter radius (px)", self.spin_jr)
        lv.addWidget(cfg_box)

        lv.addStretch(1)

        self.btn_run = QPushButton("Create project & type into VS Code")
        self.btn_run.setStyleSheet("padding: 10px; font-weight: 600;")
        self.btn_run.clicked.connect(self._on_run)
        lv.addWidget(self.btn_run)

        self.btn_stop = QPushButton("STOP (Esc)")
        self.btn_stop.setStyleSheet("padding: 10px; background: #b91c1c; color: white;")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_esc)
        lv.addWidget(self.btn_stop)

        splitter.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.addWidget(QLabel("Preview — this is exactly what will be typed:"))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        rv.addWidget(self.preview, 1)
        self.status = QStatusBar()
        rv.addWidget(self.status)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        root.addWidget(splitter, 1)
        self._render_preview()

    # ---- data ----
    def _render_preview(self):
        parts = []
        for fname in REQUIRED_FILES:
            parts.append(f"// ===== {fname} =====\n")
            parts.append(self.current_files.get(fname, ""))
            if not parts[-1].endswith("\n"):
                parts.append("\n")
        self.preview.setPlainText("".join(parts))

    def _refresh_templates(self):
        self.tpl_list.blockSignals(True)
        self.tpl_list.clear()
        names = list_templates()
        self.tpl_list.addItems(names)
        self.tpl_list.blockSignals(False)
        if names:
            self.tpl_list.setCurrentRow(0)

    def _on_template_selected(self, name):
        if not name:
            return
        try:
            self.current_files = load_template(name)
            self._render_preview()
            self.status.showMessage(f"Loaded template: {name}")
        except Exception as e:
            QMessageBox.warning(self, "Template", str(e))

    def _on_import(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder with the 3 files")
        if not path:
            # also allow zip
            zpath, _ = QFileDialog.getOpenFileName(self, "…or select a .zip", "", "Zip (*.zip)")
            if not zpath:
                return
            path = zpath
        try:
            self.current_files = import_bundle_from_path(Path(path))
            self._render_preview()
            self.status.showMessage("Imported bundle into preview (not yet saved).")
        except Exception as e:
            QMessageBox.warning(self, "Import failed", str(e))

    def _on_save_template(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Save template", "Template name:")
        if not ok or not name.strip():
            return
        try:
            saved = save_template(name, self.current_files)
            self._refresh_templates()
            idx = self.tpl_list.findItems(saved, Qt.MatchExactly)
            if idx:
                self.tpl_list.setCurrentItem(idx[0])
            self.status.showMessage(f"Saved template: {saved}")
        except Exception as e:
            QMessageBox.warning(self, "Save failed", str(e))

    # ---- run flow ----
    def _on_run(self):
        if not process_elevated():
            # Not fatal, but warn because SendInput into an elevated VS Code will fail.
            pass
        try:
            self._create_project_and_open_vscode()
        except Exception as e:
            QMessageBox.critical(self, "Project", f"Failed to create project: {e}")
            return
        self._start_typing()

    def _create_project_and_open_vscode(self):
        target = Path(__file__).resolve().parent.parent / CONFIG["PROJECT_DIR_NAME"]
        target.mkdir(parents=True, exist_ok=True)
        for fname in REQUIRED_FILES:
            # Create empty placeholders; typing will fill them.
            (target / fname).write_text("", encoding="utf-8")
        # Open a separate VS Code window with index.html selected in the editor.
        subprocess.Popen(
            ["code", "--new-window", str(target), str(target / "index.html")],
            cwd=str(target), shell=True)
        deadline = time.time() + 15
        while time.time() < deadline:
            if is_project_vscode_foreground(target.name):
                return target
            time.sleep(0.2)
        raise RuntimeError(
            "The new VS Code project window did not become active. "
            "Make sure `code` is on PATH and try again.")

    def _start_typing(self):
        # We type into the currently-focused editor. Give VS Code a moment.
        time.sleep(0.8)
        text = self.preview.toPlainText()
        worker = TypingWorker(
            text,
            self.spin_dmin.value(),
            self.spin_dmax.value(),
            self.chk_jitter.isChecked(),
            self.spin_jr.value(),
        )
        thread = threading.Thread(target=worker.run, daemon=True)
        worker.progress.connect(self._on_progress)
        worker.finished.connect(self._on_finished)
        worker.aborted.connect(self._on_aborted)
        self.typing_worker = worker
        self.typing_thread = thread
        self.btn_run.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.esc.arm()
        self.status.showMessage("Typing… press Esc or STOP to abort.")
        thread.start()

    def _on_progress(self, cur, total):
        self.status.showMessage(f"Typing… {cur}/{total}")

    def _on_finished(self):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.showMessage("Done.")

    def _on_aborted(self, msg):
        self.btn_run.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status.showMessage(msg)
        QMessageBox.information(self, "Typing", msg)

    def _on_esc(self):
        if self.typing_worker:
            self.typing_worker.stop()
        self.status.showMessage("Stop requested…")


# ----------------------------------------------------------------------------
# App shell
# ----------------------------------------------------------------------------
class App(QStackedWidget):
    def __init__(self):
        super().__init__()
        self.auth = AuthClient(CONFIG)
        self.auth_screen = EmailAuthScreen(self.auth)
        self.payment_screen = PaymentScreen(self.auth)
        self.main_screen = MainScreen()
        self.addWidget(self.auth_screen)
        self.addWidget(self.payment_screen)
        self.addWidget(self.main_screen)
        self.auth_screen.authed.connect(self._after_auth)
        self.payment_screen.paid.connect(lambda: self.setCurrentWidget(self.main_screen))

    def _after_auth(self, has_access):
        self.setCurrentWidget(self.main_screen if has_access else self.payment_screen)


def main():
    app = QApplication(sys.argv)
    win = App()
    win.resize(1100, 700)
    win.setWindowTitle("Zetech Learning — Site Scaffolder")
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
