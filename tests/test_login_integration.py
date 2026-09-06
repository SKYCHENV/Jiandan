import time

from PySide6 import QtWidgets

from jy_live_paste import status_gui as gui
from jy_live_paste.auth import AuthClient, Session, SessionStore


def test_authenticated_window_starts_and_logout_stops_service(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(gui.StatusWindow, '_install_hotkey', lambda self: None)
    session = Session('test@example.com', 'a', 'r', int(time.time()) + 900,
                      int(time.time()) + 86400, 'device')
    signed_out = []
    window = gui.StatusWindow(0, session, signed_out.append)
    window.show_monitor.stop()
    assert window.account_button.text() == session.email
    assert window.service_enabled
    assert [a.text() for a in window.tray.contextMenu().actions()] == ['显示剪蛋', '退出']
    assert '退出登录' in [a.text() for a in window.account_button.menu().actions()]
    window.logout()
    assert signed_out == [window]
    window.shutdown()
    assert not window.monitor.isActive()
    assert not window.service_enabled
    window.deleteLater()
    app.processEvents()


def test_invalid_private_session_returns_to_login(tmp_path):
    store = SessionStore(tmp_path / 'session.bin', tmp_path / 'device.bin')
    store.session_path.write_bytes(b'YWJj')
    assert store.load() is None


def test_restore_only_shows_login_when_required(monkeypatch):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    monkeypatch.setattr(gui.LoginWindow, '_start_restore', lambda self: None)
    login = gui.LoginWindow(AuthClient())
    assert not login.isVisible()
    session = Session('test@example.com', 'a', 'r', int(time.time()) + 900,
                      int(time.time()) + 86400, 'device')
    received = []
    login.authenticated.connect(received.append)
    login._finish_restore(session)
    assert received == [session]
    assert not login.isVisible()
    login._finish_restore(None)
    assert login.isVisible()
    login.hide()
    login.deleteLater()
    app.processEvents()
