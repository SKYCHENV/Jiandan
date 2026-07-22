from jy_live_paste import win


def test_status_window_is_not_mistaken_for_jianying(monkeypatch) -> None:
    monkeypatch.setattr(win.win32gui, "GetWindowText", lambda _hwnd: "剪映图片导入")
    monkeypatch.setattr(win.win32process, "GetWindowThreadProcessId", lambda _hwnd: (1, 2))
    monkeypatch.setattr(win.win32api, "OpenProcess", lambda *_args: (_ for _ in ()).throw(OSError()))
    assert not win.is_jianying_window(100)


def test_exact_editor_title_is_jianying(monkeypatch) -> None:
    monkeypatch.setattr(win.win32gui, "GetWindowText", lambda _hwnd: "剪映专业版")
    assert win.is_jianying_window(100)
