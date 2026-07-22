from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from typing import Callable


WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000
VK_V = 0x56
HOTKEY_ID = 0x4A59


class ConditionalRegisteredHotkey:
    """Register Ctrl+V only while the eligibility predicate is true.

    RegisterHotKey is owned by this thread and cannot leave a keyboard hook or
    suppressed key behind after the process exits.
    """

    def __init__(self, should_register: Callable[[], bool], on_import: Callable[[], None]) -> None:
        self.should_register = should_register
        self.on_import = on_import
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._registered = False
        self._error: Exception | None = None
        self._cooldown_until = 0.0

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="registered-import-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(2.0):
            raise RuntimeError("安全导入热键启动超时。")
        if self._error is not None:
            raise RuntimeError("安全导入热键启动失败。") from self._error

    def stop(self) -> None:
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self._thread = None
        self._thread_id = 0

    def _set_registered(self, enabled: bool) -> None:
        user32 = ctypes.windll.user32
        if enabled and not self._registered:
            self._registered = bool(
                user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_NOREPEAT, VK_V)
            )
        elif not enabled and self._registered:
            user32.UnregisterHotKey(None, HOTKEY_ID)
            self._registered = False

    def _run(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        self._ready.set()
        message = wintypes.MSG()
        try:
            while True:
                while user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
                    if message.message == WM_QUIT:
                        return
                    if message.message == WM_HOTKEY and message.wParam == HOTKEY_ID:
                        self._set_registered(False)
                        self._cooldown_until = time.monotonic() + 1.0
                        try:
                            self.on_import()
                        except Exception:
                            pass
                try:
                    eligible = time.monotonic() >= self._cooldown_until and bool(
                        self.should_register()
                    )
                except Exception:
                    eligible = False
                self._set_registered(eligible)
                time.sleep(0.04)
        except Exception as exc:
            self._error = exc
        finally:
            self._set_registered(False)
