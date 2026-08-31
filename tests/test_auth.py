import json
import time
import urllib.error

import pytest

from jy_live_paste.auth import AuthClient, AuthError, Session, SessionStore, normalize_email


class MemoryStore:
    def __init__(self) -> None:
        self.session = None
        self.cleared = False

    def device_id(self) -> str:
        return "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    def load(self):
        return self.session

    def save(self, session) -> None:
        self.session = session

    def clear(self) -> None:
        self.session = None
        self.cleared = True


def session_payload() -> dict:
    now = int(time.time())
    return {
        "email": "person@example.com",
        "access_token": "access",
        "refresh_token": "refresh",
        "access_expires_at": now + 900,
        "refresh_expires_at": now + 86_400,
        "device_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    }


def test_normalize_email() -> None:
    assert normalize_email(" Person@Example.COM ") == "person@example.com"
    with pytest.raises(AuthError) as error:
        normalize_email("not-an-email")
    assert error.value.code == "invalid_email"


def test_session_store_dpapi_round_trip(tmp_path) -> None:
    store = SessionStore(tmp_path / "session.bin", tmp_path / "device.bin")
    session = Session.from_dict(session_payload())

    store.save(session)

    assert store.load() == session
    assert store.session_path.read_bytes()


def test_verify_saves_session(monkeypatch) -> None:
    store = MemoryStore()
    client = AuthClient("https://example.test/api/auth", store=store)
    monkeypatch.setattr(client, "_request", lambda endpoint, payload: {"session": session_payload()})

    session = client.verify_code("person@example.com", "123456")

    assert isinstance(session, Session)
    assert store.session == session


def test_restore_clears_server_rejected_session(monkeypatch) -> None:
    store = MemoryStore()
    store.session = Session.from_dict(session_payload())
    client = AuthClient("https://example.test/api/auth", store=store)

    def rejected(_endpoint, _payload):
        raise AuthError("expired", "session_invalid")

    monkeypatch.setattr(client, "_request", rejected)
    assert client.restore() is None
    assert store.cleared


def test_restore_keeps_unexpired_session_during_network_outage(monkeypatch) -> None:
    store = MemoryStore()
    store.session = Session.from_dict(session_payload())
    client = AuthClient("https://example.test/api/auth", store=store)
    monkeypatch.setattr(
        client,
        "_request",
        lambda _endpoint, _payload: (_ for _ in ()).throw(AuthError("offline", "network_error")),
    )
    assert client.restore() == store.session


def test_validate_refreshes_session_near_access_expiry(monkeypatch) -> None:
    store = MemoryStore()
    payload = session_payload()
    payload["access_expires_at"] = int(time.time()) + 120
    store.session = Session.from_dict(payload)
    client = AuthClient("https://example.test/api/auth", store=store)
    refreshed_payload = session_payload()
    refreshed_payload["access_token"] = "refreshed-access"

    monkeypatch.setattr(client, "_request", lambda endpoint, payload: {"session": refreshed_payload})

    validated = client.validate(store.session)
    assert validated.access_token == "refreshed-access"
    assert store.session == validated


def test_validate_rejects_expired_refresh_session() -> None:
    store = MemoryStore()
    payload = session_payload()
    payload["refresh_expires_at"] = int(time.time()) - 1
    store.session = Session.from_dict(payload)
    client = AuthClient("https://example.test/api/auth", store=store)

    with pytest.raises(AuthError) as error:
        client.validate(store.session)
    assert error.value.code == "session_missing"
    assert store.cleared


def test_http_error_surfaces_server_message(monkeypatch) -> None:
    client = AuthClient("https://example.test/api/auth", store=MemoryStore())
    payload = json.dumps({"error": {"code": "invalid_code", "message": "验证码错误"}}).encode()

    class FakeError(urllib.error.HTTPError):
        def read(self):
            return payload

    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FakeError("url", 401, "bad", {}, None)),
    )
    with pytest.raises(AuthError) as error:
        client._request("verify", {})
    assert error.value.code == "invalid_code"
