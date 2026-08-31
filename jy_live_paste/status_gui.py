from __future__ import annotations

import ctypes
import threading
import time
from collections import deque
from pathlib import Path

import win32clipboard
import win32con
import win32gui
from PySide6 import QtCore, QtGui, QtWidgets

from .auth import AuthClient, AuthError, Session
from .safe_hotkey import ConditionalRegisteredHotkey
from .importer import import_clipboard_image
from .diagnostics import log
from .win import find_jianying_window, foreground_is_jianying


SHOW_EVENT_NAME = "JianyingLiveImagePaste.ShowStatusWindow"
WAIT_OBJECT_0 = 0
EVENT_MODIFY_STATE = 0x0002
BRAND_BLUE = "#0A84FF"
STATUS_BLUE = BRAND_BLUE
APP_USER_MODEL_ID = "Jiandan.LiveImagePaste"
BRAND_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand"
BRAND_ICON_PATH = BRAND_ASSET_DIR / "jiandan.ico"
BRAND_LOGO_PATH = BRAND_ASSET_DIR / "jiandan.png"


def brand_icon(size: int = 128) -> QtGui.QIcon:
    for path in (BRAND_ICON_PATH, BRAND_LOGO_PATH):
        icon = QtGui.QIcon(str(path))
        if not icon.isNull():
            return icon

    # Keep a vector fallback so the app never falls back to Python's icon.
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    scale = size / 64.0
    painter.scale(scale, scale)

    def egg_path(x: float, y: float) -> QtGui.QPainterPath:
        path = QtGui.QPainterPath()
        path.moveTo(x + 16, y + 38)
        path.cubicTo(x + 6, y + 38, x + 3, y + 30, x + 5, y + 20)
        path.cubicTo(x + 7, y + 9, x + 12, y + 3, x + 16, y + 3)
        path.cubicTo(x + 21, y + 3, x + 26, y + 10, x + 28, y + 20)
        path.cubicTo(x + 30, y + 30, x + 27, y + 38, x + 16, y + 38)
        path.closeSubpath()
        return path

    painter.setBrush(QtCore.Qt.NoBrush)
    back_pen = QtGui.QPen(QtGui.QColor("#FFFFFF"), 3.4)
    back_pen.setCapStyle(QtCore.Qt.RoundCap)
    back_pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(back_pen)
    painter.drawPath(egg_path(11, 17))

    front_path = egg_path(22, 11)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
    painter.setPen(QtCore.Qt.NoPen)
    painter.setBrush(QtCore.Qt.transparent)
    painter.drawPath(front_path)
    painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
    painter.setBrush(QtCore.Qt.NoBrush)
    front_pen = QtGui.QPen(QtGui.QColor(BRAND_BLUE), 3.6)
    front_pen.setCapStyle(QtCore.Qt.RoundCap)
    front_pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(front_pen)
    painter.drawPath(front_path)
    painter.end()
    return QtGui.QIcon(pixmap)


class EggLogo(QtWidgets.QLabel):
    def __init__(self, size: int = 52) -> None:
        super().__init__()
        self.setFixedSize(size, size)
        self.setPixmap(brand_icon(size * 2).pixmap(size, size))


class ToggleSwitch(QtWidgets.QAbstractButton):
    def __init__(self) -> None:
        super().__init__()
        self.setCheckable(True)
        self.setFixedSize(40, 22)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, _event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtCore.Qt.NoPen)
        painter.setBrush(QtGui.QColor(BRAND_BLUE if self.isChecked() else "#3A3A3C"))
        painter.drawRoundedRect(QtCore.QRectF(0, 0, 40, 22), 11, 11)
        painter.setBrush(QtGui.QColor("#FFFFFF"))
        knob_x = 20 if self.isChecked() else 2
        painter.drawEllipse(QtCore.QRectF(knob_x, 2, 18, 18))


class Bridge(QtCore.QObject):
    request_import = QtCore.Signal()
    state_changed = QtCore.Signal(str, str, int)


class AuthBridge(QtCore.QObject):
    restored = QtCore.Signal(object)
    code_sent = QtCore.Signal(int)
    authenticated = QtCore.Signal(object)
    failed = QtCore.Signal(str, str)
    signed_out = QtCore.Signal()
    session_checked = QtCore.Signal(object)
    session_rejected = QtCore.Signal(str)


class LoginWindow(QtWidgets.QWidget):
    authenticated = QtCore.Signal(object)

    def __init__(self, client: AuthClient) -> None:
        super().__init__()
        self.client = client
        self.bridge = AuthBridge()
        self.bridge.restored.connect(self._finish_restore)
        self.bridge.code_sent.connect(self._finish_code_request)
        self.bridge.authenticated.connect(self._finish_verification)
        self.bridge.failed.connect(self._show_error)
        self.cooldown_remaining = 0
        self._build_ui()
        self.cooldown_timer = QtCore.QTimer(self)
        self.cooldown_timer.timeout.connect(self._tick_cooldown)
        QtCore.QTimer.singleShot(0, self._start_restore)

    def _build_ui(self) -> None:
        self.setWindowTitle("登录剪蛋")
        self.setWindowIcon(brand_icon())
        self.setFixedSize(440, 520)
        self.setStyleSheet("""
            QWidget { background: #000000; color: #F5F5F7; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
            QLabel { background: transparent; }
            QLabel#loginTitle { font-size: 26px; font-weight: 700; }
            QLabel#loginDetail { color: #98989D; font-size: 13px; }
            QLabel#loginStatus { color: #98989D; font-size: 12px; }
            QLineEdit { background: #141416; border: 1px solid #2C2C2E; border-radius: 8px; padding: 0 13px; min-height: 44px; selection-background-color: #0A84FF; }
            QLineEdit:focus { border-color: #0A84FF; }
            QPushButton { background: #0A84FF; border: none; border-radius: 8px; min-height: 44px; font-weight: 700; }
            QPushButton:hover { background: #2997FF; }
            QPushButton:disabled { background: #1C1C1E; color: #636366; }
            QPushButton#quietButton { background: transparent; color: #0A84FF; font-weight: 600; }
        """)
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(42, 34, 42, 34)
        root.setSpacing(14)
        root.addWidget(EggLogo(62), 0, QtCore.Qt.AlignHCenter)
        root.addSpacing(6)
        title = QtWidgets.QLabel("登录剪蛋")
        title.setObjectName("loginTitle")
        title.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(title)
        detail = QtWidgets.QLabel("输入邮箱，我们会发送一个 6 位验证码")
        detail.setObjectName("loginDetail")
        detail.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(detail)
        root.addSpacing(14)

        self.email_input = QtWidgets.QLineEdit()
        self.email_input.setPlaceholderText("邮箱地址")
        self.email_input.setClearButtonEnabled(True)
        self.email_input.returnPressed.connect(self.request_code)
        root.addWidget(self.email_input)
        self.send_button = QtWidgets.QPushButton("发送验证码")
        self.send_button.clicked.connect(self.request_code)
        root.addWidget(self.send_button)

        self.code_input = QtWidgets.QLineEdit()
        self.code_input.setPlaceholderText("6 位验证码")
        self.code_input.setMaxLength(6)
        self.code_input.setAlignment(QtCore.Qt.AlignCenter)
        self.code_input.setValidator(QtGui.QRegularExpressionValidator(QtCore.QRegularExpression(r"\d{0,6}"), self))
        self.code_input.returnPressed.connect(self.verify_code)
        root.addWidget(self.code_input)
        self.verify_button = QtWidgets.QPushButton("登录")
        self.verify_button.clicked.connect(self.verify_code)
        root.addWidget(self.verify_button)

        self.status_label = QtWidgets.QLabel("登录后将在这台设备保持登录")
        self.status_label.setObjectName("loginStatus")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(self.status_label)
        root.addStretch()
        privacy = QtWidgets.QLabel("剪蛋只使用账号确认登录状态，图片与剪贴板内容不会上传。")
        privacy.setObjectName("loginDetail")
        privacy.setWordWrap(True)
        privacy.setAlignment(QtCore.Qt.AlignCenter)
        root.addWidget(privacy)

    def _set_busy(self, busy: bool, text: str | None = None) -> None:
        self.email_input.setEnabled(not busy)
        self.code_input.setEnabled(not busy)
        self.send_button.setEnabled(not busy and self.cooldown_remaining == 0)
        self.verify_button.setEnabled(not busy)
        if text:
            self.status_label.setText(text)
            self.status_label.setStyleSheet("color: #98989D;")

    def _start_restore(self) -> None:
        self._set_busy(True, "正在确认登录状态…")

        def worker() -> None:
            try:
                self.bridge.restored.emit(self.client.restore())
            except Exception:
                self.bridge.restored.emit(None)

        threading.Thread(target=worker, name="auth-restore", daemon=True).start()

    @QtCore.Slot(object)
    def _finish_restore(self, session) -> None:
        if isinstance(session, Session):
            self.authenticated.emit(session)
            return
        self._set_busy(False, "登录后将在这台设备保持登录")
        self.email_input.setFocus()

    def request_code(self) -> None:
        email = self.email_input.text()
        if not email.strip() or self.cooldown_remaining:
            return
        self._set_busy(True, "正在发送验证码…")

        def worker() -> None:
            try:
                retry_after = self.client.request_code(email)
                self.bridge.code_sent.emit(retry_after)
            except AuthError as exc:
                self.bridge.failed.emit(exc.code, str(exc))

        threading.Thread(target=worker, name="auth-request-code", daemon=True).start()

    @QtCore.Slot(int)
    def _finish_code_request(self, retry_after: int) -> None:
        self.cooldown_remaining = max(1, retry_after)
        self._set_busy(False, "验证码已发送，请检查邮箱")
        self.code_input.setFocus()
        self.cooldown_timer.start(1000)
        self._tick_cooldown()

    def _tick_cooldown(self) -> None:
        if self.cooldown_remaining <= 0:
            self.cooldown_timer.stop()
            self.send_button.setText("重新发送验证码")
            self.send_button.setEnabled(True)
            return
        self.send_button.setText(f"{self.cooldown_remaining} 秒后可重发")
        self.send_button.setEnabled(False)
        self.cooldown_remaining -= 1

    def verify_code(self) -> None:
        if not self.code_input.text().strip():
            return
        self._set_busy(True, "正在登录…")
        email = self.email_input.text()
        code = self.code_input.text()

        def worker() -> None:
            try:
                self.bridge.authenticated.emit(self.client.verify_code(email, code))
            except AuthError as exc:
                self.bridge.failed.emit(exc.code, str(exc))

        threading.Thread(target=worker, name="auth-verify", daemon=True).start()

    @QtCore.Slot(object)
    def _finish_verification(self, session) -> None:
        if isinstance(session, Session):
            self.authenticated.emit(session)

    @QtCore.Slot(str, str)
    def _show_error(self, _code: str, message: str) -> None:
        self._set_busy(False)
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #FF453A;")

    def reset(self) -> None:
        self.code_input.clear()
        self.cooldown_remaining = 0
        self.cooldown_timer.stop()
        self.send_button.setText("发送验证码")
        self._set_busy(False, "已退出登录")
        self.show()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event) -> None:
        event.accept()
        QtWidgets.QApplication.quit()


class StatusWindow(QtWidgets.QWidget):
    def __init__(self, show_event: int, session: Session, on_logout) -> None:
        super().__init__()
        self.session = session
        self.on_logout = on_logout
        self.bridge = Bridge()
        self.bridge.request_import.connect(self.start_hotkey_import)
        self.bridge.state_changed.connect(self.apply_state)
        self.busy_lock = threading.Lock()
        self.events: deque[str] = deque(maxlen=5)
        self.hotkey_handle: ConditionalRegisteredHotkey | None = None
        self.service_enabled = True
        self.show_event = show_event
        self._build_ui()
        self._build_tray()
        self._install_hotkey()
        self.monitor = QtCore.QTimer(self)
        self.monitor.timeout.connect(self.refresh_status)
        self.monitor.start(350)
        self.show_monitor = QtCore.QTimer(self)
        self.show_monitor.timeout.connect(self.check_show_request)
        self.show_monitor.start(150)
        self.refresh_status()

    def _build_ui(self) -> None:
        self.setWindowTitle("剪蛋")
        self.setWindowIcon(brand_icon())
        self.setMinimumSize(460, 500)
        self.resize(480, 520)
        self.setStyleSheet("""
            QWidget { background: #000000; color: #F5F5F7; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
            QLabel { background: transparent; }
            QLabel#title { font-size: 22px; font-weight: 700; }
            QLabel#subtitle { color: #98989D; font-size: 12px; }
            QLabel#section { color: #8E8E93; font-size: 12px; font-weight: 600; }
            QLabel#hero { font-size: 17px; font-weight: 700; }
            QLabel#heroDetail { color: #98989D; font-size: 12px; }
            QLabel#metric { color: #0A84FF; font-size: 15px; font-weight: 700; }
            QLabel#key { color: #8E8E93; font-size: 12px; }
            QLabel#value { font-weight: 600; }
            QLabel#serviceLabel { color: #C7C7CC; font-size: 12px; }
            QFrame#statusPanel { background: #141416; border: 1px solid #2C2C2E; border-radius: 8px; }
            QFrame#separator { background: #2C2C2E; max-height: 1px; }
            QFrame#verticalSeparator { background: #2C2C2E; max-width: 1px; }
            QListWidget { background: #0C0C0E; border: 1px solid #242426; border-radius: 8px; padding: 5px; outline: none; }
            QListWidget::item { min-height: 26px; padding: 5px 7px; color: #C7C7CC; border-bottom: 1px solid #1C1C1E; }
            QListWidget::item:selected { background: #16263A; color: #F5F5F7; }
        """)

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(16)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(12)
        header.addWidget(EggLogo(52))
        brand = QtWidgets.QVBoxLayout()
        brand.setSpacing(2)
        title = QtWidgets.QLabel("剪蛋")
        title.setObjectName("title")
        subtitle = QtWidgets.QLabel("简单复制到剪映")
        subtitle.setObjectName("subtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        self.account_button = QtWidgets.QPushButton(session.email)
        self.account_button.setFlat(True)
        self.account_button.setCursor(QtCore.Qt.PointingHandCursor)
        self.account_button.setToolTip("账号")
        self.account_button.setStyleSheet("QPushButton { color: #8E8E93; border: none; padding: 6px; } QPushButton:hover { color: #F5F5F7; }")
        account_menu = QtWidgets.QMenu(self.account_button)
        logout_action = account_menu.addAction("退出登录")
        logout_action.triggered.connect(self.logout)
        self.account_button.setMenu(account_menu)
        header.addWidget(self.account_button)
        service = QtWidgets.QVBoxLayout()
        service.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        service.setSpacing(4)
        self.service_label = QtWidgets.QLabel("已开启")
        self.service_label.setObjectName("serviceLabel")
        self.service_label.setAlignment(QtCore.Qt.AlignCenter)
        self.master_toggle = ToggleSwitch()
        self.master_toggle.setToolTip("开启或暂停剪蛋")
        self.master_toggle.setChecked(True)
        self.master_toggle.toggled.connect(self.set_service_enabled)
        service.addWidget(self.service_label)
        service.addWidget(self.master_toggle, 0, QtCore.Qt.AlignCenter)
        header.addLayout(service)
        root.addLayout(header)

        status_panel = QtWidgets.QFrame()
        status_panel.setObjectName("statusPanel")
        panel_layout = QtWidgets.QHBoxLayout(status_panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(12)
        self.hero_dot = QtWidgets.QLabel()
        self.hero_dot.setFixedSize(10, 10)
        self._set_dot(self.hero_dot, BRAND_BLUE)
        panel_layout.addWidget(self.hero_dot, 0, QtCore.Qt.AlignTop)
        hero_text = QtWidgets.QVBoxLayout()
        hero_text.setSpacing(3)
        self.operation_value = QtWidgets.QLabel("检测中")
        self.operation_value.setObjectName("hero")
        self.hero_detail = QtWidgets.QLabel("正在读取当前状态")
        self.hero_detail.setObjectName("heroDetail")
        hero_text.addWidget(self.operation_value)
        hero_text.addWidget(self.hero_detail)
        panel_layout.addLayout(hero_text, 1)
        self.speed_value = QtWidgets.QLabel("—")
        self.speed_value.setObjectName("metric")
        self.speed_value.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        panel_layout.addWidget(self.speed_value)
        root.addWidget(status_panel)

        signals = QtWidgets.QHBoxLayout()
        signals.setSpacing(18)
        self.jianying_dot, self.jianying_value, jianying_group = self._signal_group("剪映")
        self.clipboard_dot, self.clipboard_value, clipboard_group = self._signal_group("剪贴板")
        signals.addLayout(jianying_group, 1)
        vertical = QtWidgets.QFrame()
        vertical.setObjectName("verticalSeparator")
        signals.addWidget(vertical)
        signals.addLayout(clipboard_group, 1)
        root.addLayout(signals)

        recent = QtWidgets.QLabel("最近活动")
        recent.setObjectName("section")
        root.addWidget(recent)
        self.log_list = QtWidgets.QListWidget()
        self.log_list.setMinimumHeight(150)
        self.log_list.setFocusPolicy(QtCore.Qt.NoFocus)
        self.log_list.addItem("暂无活动")
        root.addWidget(self.log_list, 1)

    @staticmethod
    def _set_dot(label: QtWidgets.QLabel, color: str) -> None:
        label.setStyleSheet(f"background: {color}; border-radius: 5px;")

    def _signal_group(self, label: str):
        layout = QtWidgets.QHBoxLayout()
        layout.setSpacing(9)
        dot = QtWidgets.QLabel()
        dot.setFixedSize(8, 8)
        self._set_dot(dot, "#48484A")
        text = QtWidgets.QVBoxLayout()
        text.setSpacing(2)
        key = QtWidgets.QLabel(label)
        key.setObjectName("key")
        value = QtWidgets.QLabel("检测中")
        value.setObjectName("value")
        text.addWidget(key)
        text.addWidget(value)
        layout.addWidget(dot)
        layout.addLayout(text)
        layout.addStretch()
        return dot, value, layout

    def _build_tray(self) -> None:
        self.tray = QtWidgets.QSystemTrayIcon(brand_icon(), self)
        menu = QtWidgets.QMenu()
        show_action = menu.addAction("显示剪蛋")
        show_action.triggered.connect(self.show_normal)
        quit_action = menu.addAction("退出")
        quit_action.triggered.connect(QtWidgets.QApplication.quit)
        menu.addSeparator()
        logout_action = menu.addAction("退出登录")
        logout_action.triggered.connect(self.logout)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal() if reason == QtWidgets.QSystemTrayIcon.Trigger else None)
        self.tray.show()

    def _install_hotkey(self) -> None:
        if self.hotkey_handle is not None or not self.service_enabled:
            return
        self.hotkey_handle = ConditionalRegisteredHotkey(
            should_register=self._should_register_import,
            on_import=lambda: self.bridge.request_import.emit(),
        )
        self.hotkey_handle.start()

    def _remove_hotkey(self) -> None:
        if self.hotkey_handle is not None:
            self.hotkey_handle.stop()
            self.hotkey_handle = None

    def _clipboard_has_image(self) -> bool:
        return any(win32clipboard.IsClipboardFormatAvailable(fmt) for fmt in (win32con.CF_DIB, 17))

    def _should_register_import(self) -> bool:
        return (
            self.service_enabled
            and not self.busy_lock.locked()
            and foreground_is_jianying()
            and self._clipboard_has_image()
        )

    def set_service_enabled(self, enabled: bool) -> None:
        self.service_enabled = enabled
        self.service_label.setText("已开启" if enabled else "已暂停")
        if enabled:
            self._install_hotkey()
        else:
            self._remove_hotkey()
        if not enabled:
            self.operation_value.setText("已暂停")
            self.hero_detail.setText("剪蛋不会接管粘贴")
            self._set_dot(self.hero_dot, "#48484A")

    def refresh_status(self) -> None:
        focused = foreground_is_jianying()
        try:
            find_jianying_window()
            available = True
        except RuntimeError:
            available = False
        self.jianying_value.setText("已聚焦" if focused else ("已打开" if available else "未运行"))
        self._set_dot(self.jianying_dot, BRAND_BLUE if focused else ("#64D2FF" if available else "#48484A"))
        image_ready = self._clipboard_has_image()
        self.clipboard_value.setText("图片就绪" if image_ready else "无图片")
        self._set_dot(self.clipboard_dot, BRAND_BLUE if image_ready else "#48484A")
        if self.busy_lock.locked() or not self.service_enabled:
            return
        if not available:
            self.operation_value.setText("等待剪映")
            self.hero_detail.setText("打开一个剪映草稿")
            self._set_dot(self.hero_dot, "#48484A")
        elif not focused:
            self.operation_value.setText("剪映已打开")
            self.hero_detail.setText("切换到剪映后即可使用")
            self._set_dot(self.hero_dot, STATUS_BLUE)
        elif image_ready:
            self.operation_value.setText("准备就绪")
            self.hero_detail.setText("已识别图片剪贴板")
            self._set_dot(self.hero_dot, BRAND_BLUE)
        else:
            self.operation_value.setText("等待图片")
            self.hero_detail.setText("剪贴板中还没有图片")
            self._set_dot(self.hero_dot, "#48484A")
    @QtCore.Slot()
    def start_hotkey_import(self) -> None:
        if not foreground_is_jianying():
            return
        self._begin_import()

    def _begin_import(self) -> None:
        if not self.service_enabled or not self.busy_lock.acquire(blocking=False):
            return
        self.operation_value.setText("正在粘贴")
        self.hero_detail.setText("正在加入播放头上方轨道")
        self._set_dot(self.hero_dot, BRAND_BLUE)
        log("gui begin")
        threading.Thread(target=self._import_worker, daemon=True).start()

    def _import_worker(self) -> None:
        started = time.perf_counter()
        try:
            import_clipboard_image()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.bridge.state_changed.emit("成功", "图片已粘贴到播放头", elapsed_ms)
        except Exception as exc:
            log(f"import failed: {exc!r}")
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            self.bridge.state_changed.emit("失败", str(exc), elapsed_ms)
        finally:
            self.busy_lock.release()

    @QtCore.Slot(str, str, int)
    def apply_state(self, state: str, message: str, elapsed_ms: int) -> None:
        success = state == "成功"
        self.operation_value.setText("粘贴完成" if success else "粘贴失败")
        self.hero_detail.setText(message)
        self._set_dot(self.hero_dot, BRAND_BLUE if success else "#FF453A")
        self.speed_value.setText(f"{elapsed_ms} ms")
        stamp = time.strftime("%H:%M:%S")
        self.events.appendleft(f"{stamp}    {'已粘贴' if success else '失败'}    {message}")
        self.log_list.clear()
        self.log_list.addItems(list(self.events))
        self.refresh_status()

    def show_normal(self) -> None:
        self.show()
        self.setWindowState(self.windowState() & ~QtCore.Qt.WindowMinimized)
        hwnd = int(self.winId())
        flags = win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW
        win32gui.SetWindowPos(hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0, flags)
        win32gui.SetWindowPos(hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        self.raise_()
        self.activateWindow()

    def check_show_request(self) -> None:
        if ctypes.windll.kernel32.WaitForSingleObject(self.show_event, 0) == WAIT_OBJECT_0:
            self.show_normal()

    def closeEvent(self, event) -> None:
        event.ignore()
        self.hide()
        self.tray.showMessage("剪蛋", "已在后台继续运行", QtWidgets.QSystemTrayIcon.Information, 1200)

    def shutdown(self) -> None:
        self._remove_hotkey()
        self.tray.hide()

    def logout(self) -> None:
        self._remove_hotkey()
        self.service_enabled = False
        self.tray.hide()
        self.hide()
        self.on_logout(self)


def run_gui() -> None:
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateEventW.argtypes = (
        ctypes.c_void_p,
        ctypes.c_bool,
        ctypes.c_bool,
        ctypes.c_wchar_p,
    )
    kernel32.CreateEventW.restype = ctypes.c_void_p
    kernel32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p)
    kernel32.OpenEventW.restype = ctypes.c_void_p
    kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
    kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    mutex = kernel32.CreateMutexW(None, False, "JianyingLiveImagePaste.StatusWindow")
    if ctypes.get_last_error() == 183:
        show_event = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT_NAME)
        if show_event:
            kernel32.SetEvent(show_event)
            kernel32.CloseHandle(show_event)
        kernel32.CloseHandle(mutex)
        return
    show_event = kernel32.CreateEventW(None, False, False, SHOW_EVENT_NAME)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName("剪蛋")
    app.setApplicationDisplayName("剪蛋")
    app.setWindowIcon(brand_icon())
    app.setQuitOnLastWindowClosed(False)
    auth_client = AuthClient()
    login = LoginWindow(auth_client)
    active_window: dict[str, StatusWindow | None] = {"window": None}
    session_check_lock = threading.Lock()
    session_timer = QtCore.QTimer()
    session_timer.setInterval(90_000)

    def reject_session(message: str) -> None:
        window = active_window["window"]
        if window is None:
            return
        window.shutdown()
        window.hide()
        window.deleteLater()
        active_window["window"] = None
        auth_client.store.clear()
        login.reset()
        login.status_label.setText(message)
        login.status_label.setStyleSheet("color: #FF453A;")

    def apply_checked_session(session) -> None:
        window = active_window["window"]
        if window is not None and isinstance(session, Session):
            window.session = session

    def check_session() -> None:
        window = active_window["window"]
        if window is None or not session_check_lock.acquire(blocking=False):
            return
        session = window.session

        def worker() -> None:
            try:
                login.bridge.session_checked.emit(auth_client.validate(session))
            except AuthError as exc:
                if exc.code in {"network_error", "service_unavailable"} and session.access_expires_at > int(time.time()):
                    return
                login.bridge.session_rejected.emit(str(exc))
            finally:
                session_check_lock.release()

        threading.Thread(target=worker, name="auth-session-check", daemon=True).start()

    def finish_logout(window: StatusWindow) -> None:
        window.shutdown()
        active_window["window"] = None
        session_timer.stop()

        def worker() -> None:
            try:
                auth_client.logout()
            finally:
                login.bridge.signed_out.emit()

        threading.Thread(target=worker, name="auth-logout", daemon=True).start()

    def show_status(session) -> None:
        if not isinstance(session, Session):
            return
        login.hide()
        current = active_window["window"]
        if current is not None:
            current.shutdown()
            current.deleteLater()
        window = StatusWindow(show_event, session, finish_logout)
        active_window["window"] = window
        window.show()
        session_timer.start()

    login.authenticated.connect(show_status)
    login.bridge.signed_out.connect(login.reset)
    login.bridge.session_checked.connect(apply_checked_session)
    login.bridge.session_rejected.connect(reject_session)
    session_timer.timeout.connect(check_session)
    app.aboutToQuit.connect(lambda: active_window["window"].shutdown() if active_window["window"] else None)
    login.show()
    app.exec()
    kernel32.CloseHandle(show_event)
    kernel32.CloseHandle(mutex)
