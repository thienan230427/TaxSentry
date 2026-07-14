from __future__ import annotations

from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from taxsentry.chat_service import ChatService
from taxsentry.control_server import DashboardAuth, create_app
from taxsentry.events import AgentEvent, EventType
from taxsentry.onboarding_service import OnboardingService
from taxsentry.store import JobStore


class FakeProvider:
    def __init__(self):
        self.closed = False

    async def stream_turn(self, messages, output_schema=None):
        yield AgentEvent(EventType.TEXT_DELTA, text="Xin chào Sếp")
        yield AgentEvent(EventType.TURN_COMPLETED)

    async def close(self):
        self.closed = True


class FakeChat:
    def __init__(self):
        self.store = SimpleNamespace(close=lambda: None)

    async def close(self):
        pass


def test_dashboard_one_time_login_csrf_logout_and_rotation(monkeypatch):
    secrets = {}
    monkeypatch.setattr("taxsentry.control_server.get_secret", lambda name: secrets.get(name, ""))
    monkeypatch.setattr("taxsentry.control_server.set_secret", lambda name, value: secrets.__setitem__(name, value))
    monkeypatch.setattr("taxsentry.control_server.ChatService", lambda settings: FakeChat())
    monkeypatch.setattr("taxsentry.control_server.load_config", lambda: {"configured": False, "provider": {"kind": "lmstudio"}})
    auth = DashboardAuth()
    app = create_app(auth)

    with TestClient(app) as client:
        assert client.get("/api/bootstrap").json()["authenticated"] is False
        code = auth.issue_code()
        logged_in = client.post("/api/session", json={"credential": code})
        assert logged_in.status_code == 200
        csrf = logged_in.json()["csrf"]
        assert client.post("/api/session", json={"credential": code}).status_code == 401
        assert client.delete("/api/session").status_code == 403
        assert client.delete("/api/session", headers={"x-csrf-token": csrf}).status_code == 200

        client.post("/api/session", json={"credential": auth.token})
        auth.rotate()
        assert client.get("/api/overview").status_code == 401


@pytest.mark.asyncio
async def test_chat_service_persists_session_and_closes_provider(tmp_path):
    provider = FakeProvider()
    store = JobStore(tmp_path / "chat.db")
    settings = {"provider": {"kind": "lmstudio", "model": ""}}
    chat = ChatService(settings, store=store, provider_factory=lambda _: provider)

    events = [event async for event in chat.stream("Chào em")]

    assert [event.type for event in events] == [EventType.TEXT_DELTA, EventType.TURN_COMPLETED]
    assert [item["role"] for item in store.session_messages(chat.session_id)] == ["user", "assistant"]
    await chat.close()
    assert provider.closed
    store.close()


def test_onboarding_commit_requires_verification_and_rolls_config_once(monkeypatch):
    saved, keyring = [], {}
    settings = {
        "configured": False,
        "provider": {"kind": "lmstudio", "model": "model"},
        "gmail": {"enabled": False},
        "telegram": {"enabled": False},
    }
    monkeypatch.setattr("taxsentry.onboarding_service.get_secret", lambda name: keyring.get(name, ""))
    monkeypatch.setattr("taxsentry.onboarding_service.set_secret", lambda name, value: keyring.__setitem__(name, value))
    monkeypatch.setattr("taxsentry.onboarding_service.save_config", lambda config: saved.append(config.copy()))
    service = OnboardingService(settings)

    with pytest.raises(RuntimeError, match="Verify before commit"):
        service.commit()
    assert saved == []

    service.verified["provider"] = "ready"
    result = service.commit()
    assert result["configured"] is True
    assert len(saved) == 1
