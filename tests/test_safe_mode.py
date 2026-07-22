from jy_live_paste.safe_hotkey import ConditionalRegisteredHotkey


def test_registered_hotkey_can_start_and_stop_without_hook() -> None:
    hotkey = ConditionalRegisteredHotkey(lambda: False, lambda: None)
    hotkey.start()
    hotkey.stop()


def test_registered_hotkey_is_released_after_stop() -> None:
    hotkey = ConditionalRegisteredHotkey(lambda: True, lambda: None)
    hotkey.start()
    hotkey.stop()
    assert not hotkey._registered
