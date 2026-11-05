"""LOOP: screen-based UI recognition and session monitoring."""

from pathlib import Path

__version__ = "0.1.0"
APP_NAME = "LOOP"  # internal name: app data folder, lock file, taskbar identity
DISPLAY_NAME = "Loopter"  # the name people see
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
