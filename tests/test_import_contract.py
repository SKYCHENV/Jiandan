import ctypes
from pathlib import Path

from PIL import Image

from jy_live_paste import dialog_import, importer, status_gui, win


def test_windows_input_structure_has_native_size() -> None:
    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
    assert ctypes.sizeof(dialog_import.INPUT) == expected


def test_each_image_uses_an_isolated_directory(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(importer, "ASSET_ROOT", tmp_path)
    image = Image.new("RGB", (12, 12), "red")

    first, first_hash = importer._save_isolated(image)
    second, second_hash = importer._save_isolated(image)

    assert first.parent != second.parent
    assert first.name == second.name
    assert first_hash == second_hash
    assert first.exists() and second.exists()


def test_importer_imports_then_invokes_native_add(monkeypatch, tmp_path) -> None:
    before = Image.new("RGB", (700, 500), (25, 25, 25))
    after = before.copy()
    screenshots = iter((before, after))
    image_path = tmp_path / "only-this-file.png"
    Image.new("RGB", (10, 10), "red").save(image_path)
    calls = []

    monkeypatch.setattr(importer.win, "foreground_jianying_window", lambda: 7)
    monkeypatch.setattr(importer, "_clipboard_image", lambda: Image.new("RGB", (10, 10), "red"))
    monkeypatch.setattr(importer, "_save_isolated", lambda _image: (image_path, "abc"))
    monkeypatch.setattr(importer.win, "screenshot_window", lambda _hwnd: next(screenshots))
    monkeypatch.setattr(importer, "choose_file_invisible", lambda hwnd, path: calls.append(("import", hwnd, path)))
    monkeypatch.setattr(importer, "find_new_media_box", lambda _before, _after: (120, 150, 236, 228))
    monkeypatch.setattr(importer, "find_selected_media_box", lambda _image: (120, 150, 236, 228))
    monkeypatch.setattr(importer, "_invoke_native_add", lambda hwnd, box: calls.append(("add", hwnd, box)))

    report = importer.import_clipboard_image()

    assert report.image_path == image_path
    assert calls == [("import", 7, image_path), ("add", 7, (120, 150, 236, 228))]


def test_runtime_contains_no_low_level_hook_or_physical_cursor_motion() -> None:
    runtime = Path(importer.__file__).parent
    source = "\n".join(path.read_text(encoding="utf-8") for path in runtime.glob("*.py"))
    assert "WH_KEYBOARD_LL" not in source
    assert "SetWindowsHookEx" not in source
    assert "SetCursorPos" not in source
    assert "mouse_event" not in source
    assert "choose_file_hidden" not in source


def test_runtime_invokes_native_add_without_physical_pointer() -> None:
    source = Path(importer.__file__).read_text(encoding="utf-8")
    assert "_invoke_native_add" in source
    assert "PostMessage" in source
    assert "SetCursorPos" not in source
    assert "mouse_event" not in source


def test_foreground_restore_is_scoped_to_the_import_dialog() -> None:
    source = Path(dialog_import.__file__).read_text(encoding="utf-8")
    assert "EVENT_OBJECT_SHOW" in source
    assert "EVENT_SYSTEM_FOREGROUND" in source
    assert "SetLayeredWindowAttributes" in source
    assert "SetForegroundWindow(editor_hwnd)" in source
    assert "ShowWindow(dialog" not in source


def test_dialog_submits_only_the_exact_path_with_native_messages() -> None:
    source = Path(dialog_import.__file__).read_text(encoding="utf-8")
    assert "WM_CHAR" in source
    assert "_send_edit_text(edit, exact_path)" in source
    assert "PostMessage(open_button, BM_CLICK" in source
    assert "uiautomation" not in source
    assert "PostMessage(dialog, win32con.WM_CLOSE" in source


def test_gui_uses_registered_hotkey_and_importer() -> None:
    source = Path(status_gui.__file__).read_text(encoding="utf-8")
    assert "ConditionalRegisteredHotkey" in source
    assert "import_clipboard_image" in source
    assert "paste_clipboard_image" not in source


def test_gui_uses_jiandan_brand_system() -> None:
    source = Path(status_gui.__file__).read_text(encoding="utf-8")
    assert 'setWindowTitle("剪蛋")' in source
    assert "简单复制到剪映" in source
    assert 'BRAND_BLUE = "#0A84FF"' in source
    assert "class EggLogo" in source
    assert "class ToggleSwitch" in source


def test_win_module_has_no_keyboard_package() -> None:
    source = Path(win.__file__).read_text(encoding="utf-8")
    assert "import keyboard" not in source
