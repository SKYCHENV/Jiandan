from __future__ import annotations

import datetime as _datetime
import threading
from pathlib import Path


LOG_PATH = Path(__file__).resolve().parents[1] / "import-debug.log"
_LOCK = threading.Lock()


def log(message: str) -> None:
    stamp = _datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    with _LOCK:
        with LOG_PATH.open("a", encoding="utf-8") as stream:
            stream.write(f"{stamp} {message}\n")
