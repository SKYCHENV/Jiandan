from __future__ import annotations

import base64
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import win32crypt


DEFAULT_AUTH_URL = "https://www.jiandan.qd.je/api/auth"
APP_DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Jiandan"
SESSION_PATH = APP_DATA_DIR / "session.bin"
DEVICE_PATH = APP_DATA_DIR / "device.bin"
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AuthError(RuntimeError):
    def __init__(self, message: str, code: str = "auth_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Session:
    email: str
    access_token: str
    refresh_token: str
    access_expires_at: int
    refresh_expires_at: int
    device_id: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Session":
        return cls(
            email=str(value["email"]),
            access_token=str(value["access_token"]),
            refresh_token=str(value["refresh_token"]),
            access_expires_at=int(value["access_expires_at"]),
            refresh_expires_at=int(value["refresh_expires_at"]),
            device_id=str(value["device_id"]),
        )


def normalize_email(email: str) -> str:
    normalized = email.strip().lower()
    if len(normalized) > 254 or not EMAIL_PATTERN.fullmatch(normalized):
        raise AuthError("请输入有效的邮箱地址", "invalid_email")
    return normalized


def _protect(data: bytes) -> bytes:
    protected = win32crypt.CryptProtectData(data, "Jiandan", None, None, None, 0)
    return protected[1] if isinstance(protected, tuple) else protected


def _unprotect(data: bytes) -> bytes:
    unprotected = win32crypt.CryptUnprotectData(data, None, None, None, 0)
    return unprotected[1] if isinstance(unprotected, tuple) else unprotected


def _write_private(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(base64.b64encode(_protect(encoded)))
    os.replace(temporary, path)


def _read_private(path: Path) -> dict[str, Any] | None:
    try:
        encoded = base64.b64decode(path.read_bytes(), validate=True)
        value = json.loads(_unprotect(encoded).decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
        return None


class SessionStore:
    def __init__(self, session_path: Path = SESSION_PATH, device_path: Path = DEVICE_PATH) -> None:
        self.session_path = session_path
        self.device_path = device_path

    def device_id(self) -> str:
        stored = _read_private(self.device_path)
        if stored and isinstance(stored.get("device_id"), str):
            return stored["device_id"]
        device_id = str(uuid.UUID(bytes=secrets.token_bytes(16)))
        _write_private(self.device_path, {"device_id": device_id})
        return device_id

    def load(self) -> Session | None:
        value = _read_private(self.session_path)
        if not value:
            return None
        try:
            return Session.from_dict(value)
        except (KeyError, TypeError, ValueError):
            return None

    def save(self, session: Session) -> None:
        _write_private(self.session_path, asdict(session))

    def clear(self) -> None:
        try:
            self.session_path.unlink()
        except FileNotFoundError:
            pass


class AuthClient:
    def __init__(
        self,
        base_url: str | None = None,
        store: SessionStore | None = None,
        timeout: float = 8.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("JIANDAN_AUTH_URL") or DEFAULT_AUTH_URL).rstrip("/")
        self.store = store or SessionStore()
        self.timeout = timeout

    def request_code(self, email: str) -> int:
        result = self._request("request-code", {"email": normalize_email(email)})
        return int(result.get("retry_after", 60))

    def verify_code(self, email: str, code: str) -> Session:
        normalized = normalize_email(email)
        clean_code = "".join(character for character in code if character.isdigit())
        if len(clean_code) != 6:
            raise AuthError("请输入 6 位验证码", "invalid_code")
        result = self._request(
            "verify",
            {
                "email": normalized,
                "code": clean_code,
                "device_id": self.store.device_id(),
                "device_name": os.environ.get("COMPUTERNAME", "Windows PC")[:80],
            },
        )
        session = Session.from_dict(result["session"])
        self.store.save(session)
        return session

    def restore(self) -> Session | None:
        session = self.store.load()
        if session is None or session.refresh_expires_at <= int(time.time()):
            self.store.clear()
            return None
        try:
            if session.access_expires_at > int(time.time()) + 30:
                self._request("session", {"access_token": session.access_token})
                return session
            return self.refresh(session)
        except AuthError as exc:
            if exc.code in {"network_error", "service_unavailable"} and session.access_expires_at > int(time.time()):
                return session
            if exc.code not in {"network_error", "service_unavailable"}:
                self.store.clear()
            return None

    def validate(self, session: Session | None = None) -> Session:
        current = session or self.store.load()
        if current is None or current.refresh_expires_at <= int(time.time()):
            self.store.clear()
            raise AuthError("登录已失效，请重新验证邮箱", "session_missing")
        if current.access_expires_at <= int(time.time()) + 5 * 60:
            return self.refresh(current)
        self._request("session", {"access_token": current.access_token})
        return current

    def refresh(self, session: Session | None = None) -> Session:
        current = session or self.store.load()
        if current is None:
            raise AuthError("登录已失效，请重新验证邮箱", "session_missing")
        result = self._request(
            "refresh",
            {"refresh_token": current.refresh_token, "device_id": current.device_id},
        )
        refreshed = Session.from_dict(result["session"])
        self.store.save(refreshed)
        return refreshed

    def logout(self) -> None:
        session = self.store.load()
        try:
            if session is not None:
                self._request("logout", {"refresh_token": session.refresh_token})
        finally:
            self.store.clear()

    def _request(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/{endpoint}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "Jiandan/0.2 Windows"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                body = json.loads(exc.read().decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                body = {}
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                raise AuthError(str(error.get("message", "登录服务暂时不可用")), str(error.get("code", "http_error")))
            raise AuthError("登录服务暂时不可用", "http_error") from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise AuthError("无法连接登录服务，请检查网络", "network_error") from exc
        except json.JSONDecodeError as exc:
            raise AuthError("登录服务返回了无效响应", "service_unavailable") from exc
        if not isinstance(body, dict) or not body.get("ok"):
            raise AuthError("登录服务暂时不可用", "service_unavailable")
        data = body.get("data", {})
        return data if isinstance(data, dict) else {}
