"""Application entry point."""

from __future__ import annotations

import ctypes
import logging
import sys
from pathlib import Path
from types import TracebackType

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from loop import APP_NAME, ASSETS_DIR, DISPLAY_NAME, __version__, win32
from loop.config import app_data_dir, load_settings, logs_dir
from loop.logging_setup import setup_logging
from loop.ui import theme
from loop.ui.main_window import MainWindow

log = logging.getLogger("loop")


def _log_unhandled(kind: type[BaseException], value: BaseException, tb: TracebackType | None) -> None:
    log.critical("Unhandled error: %s", value, exc_info=(kind, value, tb))


def acquire_instance_lock(directory: Path) -> QLockFile | None:
    """Holds the single-instance lock, or returns None if another LOOP already holds it.

    Two copies would each write their own settings on exit, so the last one to close
    would silently discard the other's templates. Only one can own the emergency stop
    shortcut, too. A lock left behind by a crashed copy is detected and taken over.
    """
    directory.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(directory / "loop.lock"))
    lock.setStaleLockTime(0)  # never expire the lock of a copy that is still running
    return lock if lock.tryLock(0) else None


def main(argv: list[str] | None = None) -> int:
    if win32.IS_WINDOWS:
        # Gives LOOP its own taskbar identity (and icon) instead of python.exe's.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LOOP.Desktop")

    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(DISPLAY_NAME)
    app.setApplicationVersion(__version__)
    theme.apply(app)

    lock = acquire_instance_lock(app_data_dir())
    if lock is None:
        QMessageBox.information(None, DISPLAY_NAME, "Loopter is already running. Switch to the open window.")
        return 1

    bridge = setup_logging(logs_dir())
    sys.excepthook = _log_unhandled
    settings = load_settings()

    icon = QIcon(str(ASSETS_DIR / "loop.png"))
    app.setWindowIcon(icon)
    window = MainWindow(settings, bridge, icon)
    window.show()
    log.info("Loopter %s started", __version__)
    return app.exec()
