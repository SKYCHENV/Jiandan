from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageGrab

from . import win
from .diagnostics import log
from .dialog_import import choose_file_invisible
from .vision import find_new_media_box, find_selected_media_box


PROJECT_DIR = Path(__file__).resolve().parents[1]
ASSET_ROOT = PROJECT_DIR / "a"


@dataclass(frozen=True)
class ImportReport:
    image_path: Path
    image_hash: str
    media_box: tuple[int, int, int, int] | None
    elapsed_ms: int


def _clipboard_image() -> Image.Image:
    image = ImageGrab.grabclipboard()
    if image is None or isinstance(image, list):
        raise RuntimeError("剪贴板中没有图片。")
    return image.convert("RGB")


def _save_isolated(image: Image.Image) -> tuple[Path, str]:
    digest = hashlib.sha256(image.tobytes()).hexdigest()
    batch_dir = ASSET_ROOT / uuid.uuid4().hex[:16]
    batch_dir.mkdir(parents=True, exist_ok=False)
    image_path = batch_dir / "i.png"
    image.save(image_path, "PNG", compress_level=1)
    return image_path, digest


def _boxes_overlap(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def import_clipboard_image() -> ImportReport:
    started = time.perf_counter()
    marks: list[tuple[str, int]] = []

    def mark(name: str) -> None:
        marks.append((name, int((time.perf_counter() - started) * 1000)))

    hwnd = win.foreground_jianying_window()
    if hwnd is None:
        raise RuntimeError("剪映不是当前前台窗口。")

    image = _clipboard_image()
    mark("clipboard")
    image_path, image_hash = _save_isolated(image)
    mark("saved")
    before = win.screenshot_window(hwnd)
    mark("before-shot")
    before_selected = find_selected_media_box(before)
    mark("before-vision")
    choose_file_invisible(hwnd, image_path)
    mark("imported")

    media_box = None
    selected_box = None
    # Jianying may reuse the same visible grid slot for the newly selected item,
    # so an unchanged selection rectangle is still a valid successful import.
    # The chooser has already accepted the exact file; this loop is telemetry.
    deadline = time.monotonic() + 0.8
    while time.monotonic() < deadline:
        after = win.screenshot_window(hwnd)
        media_box = find_new_media_box(before, after)
        selected_box = find_selected_media_box(after)
        selected_changed = selected_box is not None and selected_box != before_selected
        if selected_box is not None and (
            selected_changed or media_box is None or _boxes_overlap(media_box, selected_box)
        ):
            media_box = selected_box
            break
        time.sleep(0.04)

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    log(
        f"import preview complete image={image_path} sha256={image_hash} "
        f"media_box={media_box} elapsed_ms={elapsed_ms} profile="
        + " ".join(f"{name}={elapsed}" for name, elapsed in marks)
    )
    return ImportReport(image_path, image_hash, media_box, elapsed_ms)
