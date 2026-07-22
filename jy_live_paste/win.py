from __future__ import annotations

from dataclasses import dataclass

import win32api
import win32con
import win32gui
import win32process
from PIL import Image, ImageGrab


@dataclass(frozen=True)
class WindowRect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


def find_jianying_window() -> int:
    candidates: list[tuple[int, int, int]] = []

    def callback(hwnd: int, _: object) -> bool:
        title = win32gui.GetWindowText(hwnd)
        rect = get_window_rect(hwnd)
        if rect.width < 900 or rect.height < 600:
            return True
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        looks_like_jianying = title in {"剪映专业版", "JianyingPro"}
        if looks_like_jianying:
            candidates.append((hwnd, pid, rect.width * rect.height))
        return True

    win32gui.EnumWindows(callback, None)
    if not candidates:
        raise RuntimeError("没有找到已打开的剪映专业版编辑器窗口。")
    return max(candidates, key=lambda item: item[2])[0]


def foreground_is_jianying() -> bool:
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return False
    return is_jianying_window(hwnd)


def is_jianying_window(hwnd: int) -> bool:
    title = win32gui.GetWindowText(hwnd)
    if title in {"剪映专业版", "JianyingPro"}:
        return True
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
        try:
            exe = win32process.GetModuleFileNameEx(handle, 0)
        finally:
            win32api.CloseHandle(handle)
        return "jianyingpro" in exe.lower()
    except Exception:
        return False


def foreground_jianying_window() -> int | None:
    hwnd = win32gui.GetForegroundWindow()
    if hwnd and is_jianying_window(hwnd):
        rect = get_window_rect(hwnd)
        if rect.width > 900 and rect.height > 600:
            return hwnd
    return None


def window_placement(hwnd: int):
    return win32gui.GetWindowPlacement(hwnd)


def restore_window_placement(hwnd: int, placement) -> None:
    try:
        current = win32gui.GetWindowPlacement(hwnd)
        # If Jianying was maximized before, keep it maximized. This avoids the
        # Keep Jianying maximized if an internal child window changes its state.
        if placement[1] == win32con.SW_SHOWMAXIMIZED and current[1] != win32con.SW_SHOWMAXIMIZED:
            win32gui.ShowWindow(hwnd, win32con.SW_MAXIMIZE)
        elif placement[1] == win32con.SW_SHOWNORMAL and current[1] == win32con.SW_SHOWMINIMIZED:
            win32gui.SetWindowPlacement(hwnd, placement)
    except Exception:
        pass


def get_window_rect(hwnd: int) -> WindowRect:
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return WindowRect(left, top, right, bottom)


def screenshot_window(hwnd: int) -> Image.Image:
    rect = get_window_rect(hwnd)
    return ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom))
