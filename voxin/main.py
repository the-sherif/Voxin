import sys
import os
import signal
import threading
import subprocess
import tempfile
import wave

import numpy as np
import pyaudio
import evdev
from evdev import ecodes

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 16000
PID_FILE = os.path.expanduser("~/.voxin.pid")

HOTKEY         = {ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL}
HOTKEY_SHIFT   = {ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT}
HOTKEY_TRIGGER = ecodes.KEY_SPACE

SOUND_START    = "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"
SOUND_COMPLETE = "/usr/share/sounds/freedesktop/stereo/complete.oga"
SOUND_ERROR    = "/usr/share/sounds/freedesktop/stereo/dialog-error.oga"


def play_sound(path):
    subprocess.Popen(["paplay", path],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def copy_to_clipboard(text):
    if os.environ.get("WAYLAND_DISPLAY"):
        subprocess.run(["wl-copy"], input=text.encode(), check=True)
    elif os.environ.get("DISPLAY"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=True)
    else:
        raise RuntimeError("Нет дисплея (ни Wayland, ни X11)")


# ── Фоновые потоки ──────────────────────────────────────────────────────

class WorkerLoader(QThread):
    """Запускает transcriber.py subprocess и ждёт 'ready'."""
    loaded = pyqtSignal(object)   # передаёт subprocess.Popen

    def run(self):
        venv_python = sys.executable
        transcriber = os.path.join(os.path.dirname(os.path.abspath(__file__)), "transcriber.py")
        proc = subprocess.Popen(
            [venv_python, transcriber],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        proc.stdout.readline()   # ждём "ready"
        self.loaded.emit(proc)


class TranscriptionWorker(QThread):
    done  = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, proc, frames):
        super().__init__()
        self.proc   = proc
        self.frames = frames

    def run(self):
        wav_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                wav_path = f.name
            with wave.open(wav_path, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)
                wf.setframerate(RATE)
                wf.writeframes(b"".join(self.frames))

            self.proc.stdin.write(wav_path + "\n")
            self.proc.stdin.flush()
            line = self.proc.stdout.readline().strip()

            if line.startswith("ERROR:"):
                self.error.emit(line[6:])
            else:
                self.done.emit(line)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)


# ── Главное окно ────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    toggle_signal = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.worker_proc         = None   # subprocess
        self.recording           = False
        self.frames              = []
        self.stream              = None
        self.p_audio             = None
        self.transcription_worker = None

        self._setup_ui()
        self.toggle_signal.connect(self.toggle_recording)
        self._load_worker()
        self._start_hotkey_listener()

        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))

    # ── UI ──────────────────────────────────────────────────────────────

    def _setup_ui(self):
        self.setWindowTitle("Voxin")
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Window
        )
        self.setMinimumWidth(340)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        self.status_label = QLabel("Загружаю модель Whisper...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.record_btn = QPushButton("🎙  Начать запись")
        self.record_btn.setEnabled(False)
        self.record_btn.setMinimumHeight(42)
        self.record_btn.clicked.connect(self.toggle_recording)
        layout.addWidget(self.record_btn)

        self.text_edit = QTextEdit()
        self.text_edit.setPlaceholderText("Распознанный текст появится здесь...")
        self.text_edit.setMinimumHeight(110)
        layout.addWidget(self.text_edit)

        btn_row = QHBoxLayout()
        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.clicked.connect(self._copy_text)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.clicked.connect(self.text_edit.clear)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.clear_btn)
        layout.addLayout(btn_row)

    # ── Загрузка subprocess ─────────────────────────────────────────────

    def _load_worker(self):
        self.loader = WorkerLoader()
        self.loader.loaded.connect(self._on_worker_loaded)
        self.loader.start()

    def _on_worker_loaded(self, proc):
        self.worker_proc = proc
        self.status_label.setText("Готов  •  Ctrl+Shift+Space")
        self.record_btn.setEnabled(True)

    # ── Хоткей (evdev) ──────────────────────────────────────────────────

    def _start_hotkey_listener(self):
        threading.Thread(target=self._hotkey_loop, daemon=True).start()

    def _hotkey_loop(self):
        keyboards = []
        for path in evdev.list_devices():
            try:
                dev = evdev.InputDevice(path)
                caps = dev.capabilities()
                if ecodes.EV_KEY in caps and HOTKEY_TRIGGER in caps[ecodes.EV_KEY]:
                    keyboards.append(dev)
            except Exception:
                pass

        pressed = set()

        def watch(dev):
            try:
                for event in dev.read_loop():
                    if event.type != ecodes.EV_KEY:
                        continue
                    ke = evdev.categorize(event)
                    if ke.keystate == evdev.KeyEvent.key_down:
                        pressed.add(ke.scancode)
                    elif ke.keystate == evdev.KeyEvent.key_up:
                        pressed.discard(ke.scancode)

                    if (ke.keystate == evdev.KeyEvent.key_down
                            and ke.scancode == HOTKEY_TRIGGER
                            and pressed & HOTKEY
                            and pressed & HOTKEY_SHIFT):
                        self.toggle_signal.emit()
            except Exception:
                pass

        for dev in keyboards:
            threading.Thread(target=watch, args=(dev,), daemon=True).start()

    # ── Запись ──────────────────────────────────────────────────────────

    def toggle_recording(self):
        if not self.worker_proc:
            return
        if self.recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self.recording   = True
        self.frames      = []
        self._loop_done  = threading.Event()
        self.p_audio     = pyaudio.PyAudio()
        self.stream      = self.p_audio.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            input=True, frames_per_buffer=CHUNK
        )
        self.record_btn.setText("⏹  Стоп")
        self.status_label.setText("🔴  Запись...")
        play_sound(SOUND_START)

        def loop():
            try:
                while self.recording:
                    data = self.stream.read(CHUNK, exception_on_overflow=False)
                    self.frames.append(data)
            finally:
                self._loop_done.set()

        threading.Thread(target=loop, daemon=True).start()

    def _stop_recording(self):
        self.recording = False
        if hasattr(self, "_loop_done"):
            self._loop_done.wait(timeout=1.0)
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.p_audio:
            self.p_audio.terminate()

        self.record_btn.setEnabled(False)
        self.record_btn.setText("🎙  Начать запись")
        self.status_label.setText("⏳  Распознаю...")

        if not self.frames:
            self.status_label.setText("Запись пустая")
            self.record_btn.setEnabled(True)
            return

        self.transcription_worker = TranscriptionWorker(self.worker_proc, list(self.frames))
        self.transcription_worker.done.connect(self._on_transcription_done)
        self.transcription_worker.error.connect(self._on_transcription_error)
        self.transcription_worker.start()

    # ── Результат ───────────────────────────────────────────────────────

    def _on_transcription_done(self, text):
        play_sound(SOUND_COMPLETE)
        if text:
            current = self.text_edit.toPlainText()
            self.text_edit.setPlainText((current + "\n\n" + text).lstrip())
            try:
                copy_to_clipboard(text)
                self.status_label.setText("✓  Скопировано в буфер")
            except Exception:
                self.status_label.setText("✓  Готово (буфер недоступен)")
        else:
            self.status_label.setText("Пустой результат — попробуй ещё раз")
        self.record_btn.setEnabled(True)

    def _on_transcription_error(self, err):
        play_sound(SOUND_ERROR)
        self.status_label.setText(f"Ошибка: {err}")
        self.record_btn.setEnabled(True)

    def _copy_text(self):
        text = self.text_edit.toPlainText()
        if text:
            try:
                copy_to_clipboard(text)
                self.status_label.setText("✓  Скопировано в буфер")
            except Exception as e:
                self.status_label.setText(f"Ошибка копирования: {e}")

    def closeEvent(self, event):
        if self.worker_proc:
            self.worker_proc.terminate()
        if os.path.exists(PID_FILE):
            os.unlink(PID_FILE)
        event.accept()


# ── Точка входа ─────────────────────────────────────────────────────────

def main():
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    app = QApplication(sys.argv)
    app.setApplicationName("Voxin")
    app.setApplicationDisplayName("Voxin")
    app.setDesktopFileName("voxin")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
