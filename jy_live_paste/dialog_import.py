from __future__ import annotations

import ctypes
import threading
import time
from ctypes import wintypes
from pathlib import Path

import win32con
import win32gui
import win32process

from .diagnostics import log


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_CONTROL = 0x11
VK_I = 0x49
BM_CLICK = 0x00F5
WM_CHAR = 0x0102
EVENT_OBJECT_SHOW = 0x8002
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000
OBJID_WINDOW = 0
WM_QUIT = 0x0012

user32 = ctypes.windll.user32
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
user32.SetWinEventHook.argtypes = (
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
)
user32.SetWinEventHook.restype = wintypes.HANDLE
user32.UnhookWinEvent.argtypes = (wintypes.HANDLE,)
user32.UnhookWinEvent.restype = wintypes.BOOL


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = (
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    )


class INPUT(ctypes.Structure):
    class _INPUTUNION(ctypes.Union):
        _fields_ = (
            ("mi", MOUSEINPUT),
            ("ki", KEYBDINPUT),
            ("hi", HARDWAREINPUT),
        )

    _anonymous_ = ("union",)
    _fields_ = (("type", wintypes.DWORD), ("union", _INPUTUNION))


def _send_import_shortcut() -> None:
    events = (INPUT * 4)(
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, 0, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_I, 0, 0, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_I, 0, KEYEVENTF_KEYUP, 0, 0)),
        INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)),
    )
    sent = ctypes.windll.user32.SendInput(4, events, ctypes.sizeof(INPUT))
    if sent != 4:
        # Release both keys even if Windows accepted only part of the batch.
        releases = (INPUT * 2)(
            INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_I, 0, KEYEVENTF_KEYUP, 0, 0)),
            INPUT(type=INPUT_KEYBOARD, ki=KEYBDINPUT(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0, 0)),
        )
        ctypes.windll.user32.SendInput(2, releases, ctypes.sizeof(INPUT))
        raise ctypes.WinError(ctypes.get_last_error())


def _find_dialog(pid: int) -> int | None:
    matches: list[int] = []

    def callback(hwnd: int, _: object) -> bool:
        try:
            _, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
            if (
                owner_pid == pid
                and win32gui.GetClassName(hwnd) == "#32770"
                and win32gui.IsWindowVisible(hwnd)
            ):
                matches.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return matches[-1] if matches else None


def _find_controls(dialog: int) -> tuple[int, int] | None:
    children: list[int] = []
    win32gui.EnumChildWindows(dialog, lambda hwnd, _: children.append(hwnd) or True, None)
    edits = [
        hwnd
        for hwnd in children
        if win32gui.GetClassName(hwnd) == "Edit" and win32gui.IsWindowVisible(hwnd)
    ]
    buttons = [
        hwnd
        for hwnd in children
        if win32gui.GetClassName(hwnd) == "Button" and win32gui.IsWindowVisible(hwnd)
    ]
    if not edits or len(buttons) < 2:
        return None
    # The standard chooser places Cancel at the far right and Open immediately
    # to its left. This is language-independent.
    buttons.sort(key=lambda hwnd: win32gui.GetWindowRect(hwnd)[0])
    return edits[0], buttons[-2]


def _send_edit_text(edit: int, value: str) -> None:
    # Explorer-style file dialogs reject cross-process WM_SETTEXT, but their
    # edit control accepts WM_CHAR. Character 1 selects the existing value.
    win32gui.SendMessage(edit, WM_CHAR, 1, 0)
    for character in value:
        win32gui.SendMessage(edit, WM_CHAR, ord(character), 0)


def _is_import_dialog(hwnd: int, pid: int) -> bool:
    try:
        _, owner_pid = win32process.GetWindowThreadProcessId(hwnd)
        return owner_pid == pid and win32gui.GetClassName(hwnd) == "#32770"
    except Exception:
        return False


def _cloak_dialog(dialog: int, editor_hwnd: int) -> None:
    if not win32gui.IsWindow(dialog):
        return
    ex_style = win32gui.GetWindowLong(dialog, win32con.GWL_EXSTYLE)
    win32gui.SetWindowLong(
        dialog,
        win32con.GWL_EXSTYLE,
        ex_style
        | win32con.WS_EX_LAYERED
        | win32con.WS_EX_TOOLWINDOW
        | win32con.WS_EX_NOACTIVATE,
    )
    win32gui.SetLayeredWindowAttributes(dialog, 0, 0, win32con.LWA_ALPHA)
    # Return focus as soon as the dialog is transparent. The remaining cloak
    # and control work can continue without extending Jianying's inactive time.
    win32gui.EnableWindow(editor_hwnd, True)
    if win32gui.GetForegroundWindow() == dialog:
        win32gui.SetForegroundWindow(editor_hwnd)
    try:
        win32gui.SetWindowPos(
            dialog,
            win32con.HWND_BOTTOM,
            -32000,
            -32000,
            0,
            0,
            win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE | win32con.SWP_NOOWNERZORDER,
        )
    except win32gui.error:
        # Duplicate WinEvent callbacks can arrive after the dialog has closed.
        return
    # A common file dialog is modal and briefly disables/dims its owner. Restore
    # only the editor that initiated this import, without touching window size.


class _DialogCloaker:
    def __init__(self, pid: int, editor_hwnd: int) -> None:
        self.pid = pid
        self.editor_hwnd = editor_hwnd
        self.dialog: int | None = None
        self.dialog_ready = threading.Event()
        self.hook_ready = threading.Event()
        self.thread_id = 0
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._callback = WINEVENTPROC(self._on_event)

    def start(self) -> None:
        self._thread.start()
        if not self.hook_ready.wait(0.5):
            raise RuntimeError("无法启动导入窗口监听。")

    def stop(self) -> None:
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)
        self._thread.join(timeout=0.5)

    def _on_event(
        self,
        _hook: int,
        _event: int,
        hwnd: int,
        object_id: int,
        child_id: int,
        _event_thread: int,
        _event_time: int,
    ) -> None:
        if object_id != OBJID_WINDOW or child_id != 0 or not hwnd:
            return
        if not _is_import_dialog(hwnd, self.pid):
            return
        self.dialog = hwnd
        try:
            _cloak_dialog(hwnd, self.editor_hwnd)
        except Exception:
            return
        self.dialog_ready.set()

    def _run(self) -> None:
        self.thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        hooks = [
            user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND,
                EVENT_SYSTEM_FOREGROUND,
                None,
                self._callback,
                self.pid,
                0,
                WINEVENT_OUTOFCONTEXT,
            ),
            user32.SetWinEventHook(
            EVENT_OBJECT_SHOW,
            EVENT_OBJECT_SHOW,
            None,
            self._callback,
            self.pid,
            0,
            WINEVENT_OUTOFCONTEXT,
            ),
        ]
        self.hook_ready.set()
        if not all(hooks):
            for hook in hooks:
                if hook:
                    user32.UnhookWinEvent(hook)
            return
        message = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
        for hook in hooks:
            user32.UnhookWinEvent(hook)


def choose_file_invisible(editor_hwnd: int, image_path: Path) -> None:
    profiled_at = time.perf_counter()
    marks: list[tuple[str, int]] = []

    def mark(name: str) -> None:
        marks.append((name, int((time.perf_counter() - profiled_at) * 1000)))

    _, pid = win32process.GetWindowThreadProcessId(editor_hwnd)
    cloaker = _DialogCloaker(pid, editor_hwnd)
    dialog = None
    cloaker.start()
    mark("hook")
    try:
        _send_import_shortcut()
        mark("shortcut")

        deadline = time.monotonic() + 2.0
        cloaker.dialog_ready.wait(0.5)
        dialog = cloaker.dialog
        while dialog is None and time.monotonic() < deadline:
            dialog = _find_dialog(pid)
            if dialog:
                _cloak_dialog(dialog, editor_hwnd)
                break
            time.sleep(0.002)
        if dialog is None:
            raise RuntimeError("剪映没有打开导入窗口。")
        mark("dialog")

        controls = None
        while time.monotonic() < deadline:
            controls = _find_controls(dialog)
            if controls:
                break
            time.sleep(0.002)
        if controls is None:
            raise RuntimeError("剪映导入窗口尚未就绪。")
        mark("controls")

        edit, open_button = controls
        exact_path = str(image_path)
        if not image_path.is_file():
            raise RuntimeError("待导入的图片文件不存在。")
        edit_thread, _ = win32process.GetWindowThreadProcessId(edit)
        button_thread, _ = win32process.GetWindowThreadProcessId(open_button)
        if edit_thread != button_thread:
            raise RuntimeError("剪映导入控件不在同一消息队列。")
        _send_edit_text(edit, exact_path)
        mark("path")
        win32gui.PostMessage(open_button, BM_CLICK, 0, 0)
        mark("invoke")

        while time.monotonic() < deadline and win32gui.IsWindow(dialog):
            time.sleep(0.005)
        if win32gui.IsWindow(dialog):
            raise RuntimeError("剪映没有完成文件导入。")
        mark("closed")
    except Exception:
        if dialog and win32gui.IsWindow(dialog):
            win32gui.PostMessage(dialog, win32con.WM_CLOSE, 0, 0)
            win32gui.EnableWindow(editor_hwnd, True)
            if win32gui.GetForegroundWindow() == dialog:
                win32gui.SetForegroundWindow(editor_hwnd)
        raise
    finally:
        cloaker.stop()
        mark("hook-stopped")
        log("dialog profile " + " ".join(f"{name}={elapsed}" for name, elapsed in marks))
