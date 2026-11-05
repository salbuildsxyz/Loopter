"""Logging to a rotating file and to the in-app activity log."""

from __future__ import annotations

import logging
import sys
import time
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QObject, Signal

FILE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class LogBridge(QObject):
    """Carries log records to the UI thread; emitting from worker threads is safe.

    Keeps a short history so records logged before the UI exists can be shown.
    """

    record = Signal(str, str, str)  # time, level, message

    def __init__(self) -> None:
        super().__init__()
        self.history: deque[tuple[str, str, str]] = deque(maxlen=200)


class _BridgeHandler(logging.Handler):
    def __init__(self, bridge: LogBridge) -> None:
        super().__init__(logging.INFO)
        self._bridge = bridge

    def emit(self, record: logging.LogRecord) -> None:
        try:
            stamp = time.strftime("%H:%M:%S", time.localtime(record.created))
            entry = (stamp, record.levelname, record.getMessage())
            self._bridge.history.append(entry)
            self._bridge.record.emit(*entry)
        except Exception:
            self.handleError(record)


def setup_logging(log_dir: Path) -> LogBridge:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stderr = logging.StreamHandler(sys.stderr) if sys.stderr else None
    if stderr:
        stderr.setFormatter(logging.Formatter(FILE_FORMAT))
        root.addHandler(stderr)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "loop.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT))
        root.addHandler(file_handler)
    except OSError as exc:
        logging.getLogger(__name__).warning("File logging is unavailable (%s)", exc)
    bridge = LogBridge()
    root.addHandler(_BridgeHandler(bridge))
    return bridge
