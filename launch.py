from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

import shiboken6


def main():
    data = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Jiandan"
    data.mkdir(parents=True, exist_ok=True)
    def report(kind, value, tb):
        with (data / "login-startup.log").open("a", encoding="utf-8") as stream:
            traceback.print_exception(kind, value, tb, file=stream)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "剪蛋", "启动遇到问题：" + str(value))
    sys.excepthook = report
    from jy_live_paste import diagnostics, importer
    diagnostics.LOG_PATH = data / "import-debug.log"
    importer.PROJECT_DIR = data
    importer.ASSET_ROOT = data / "captured"
    from jy_live_paste.status_gui import run_gui
    run_gui()


if __name__ == "__main__":
    main()
