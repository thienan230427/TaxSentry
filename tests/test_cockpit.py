from __future__ import annotations

import pytest

from taxsentry.cockpit import SYSTEM, Cockpit


class FakeProvider:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeStore:
    def __init__(self):
        self.job = {"id": "job-123456", "state": "needs_review"}
        self.requeued = []

    def resolve(self, prefix=""):
        return self.job

    def requeue(self, job_id, *, approved=False):
        self.requeued.append((job_id, approved))


class FakePrompt:
    def __init__(self, **kwargs):
        pass


@pytest.mark.asyncio
async def test_cockpit_switches_provider_and_closes_previous(monkeypatch):
    old, new = FakeProvider(), FakeProvider()
    monkeypatch.setattr("taxsentry.cockpit.JobStore", FakeStore)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: new if settings["provider"]["kind"] == "codex" else old)
    monkeypatch.setattr("taxsentry.cockpit.save_config", lambda settings: None)
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})

    await cockpit._command("/provider codex")

    assert old.closed
    assert cockpit.provider is new


@pytest.mark.asyncio
async def test_cockpit_approve_and_clear(monkeypatch):
    provider, store = FakeProvider(), FakeStore()
    monkeypatch.setattr("taxsentry.cockpit.JobStore", lambda: store)
    monkeypatch.setattr("taxsentry.cockpit.PromptSession", FakePrompt)
    monkeypatch.setattr("taxsentry.cockpit.create_provider", lambda settings: provider)
    cockpit = Cockpit({"configured": True, "provider": {"kind": "lmstudio", "model": ""}})
    cockpit.history.append({"role": "user", "content": "test"})

    await cockpit._command("/approve job-123")
    await cockpit._command("/clear")

    assert store.requeued == [("job-123456", True)]
    assert cockpit.history == [{"role": "system", "content": SYSTEM}]
