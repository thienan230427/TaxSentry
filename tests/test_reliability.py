import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from taxsentry.gmail import GmailAttachment, GmailClient, validate_attachment
from taxsentry.service_control import artifact
from taxsentry.store import JobStore
from taxsentry.telegram import TelegramDirector
from taxsentry.worker import run_worker


def test_attachment_validates_mime_and_magic_bytes():
    validate_attachment(GmailAttachment("report.pdf", "application/pdf", b"%PDF-1.7"))
    with pytest.raises(ValueError):
        validate_attachment(GmailAttachment("report.pdf", "image/png", b"%PDF-1.7"))
    with pytest.raises(ValueError):
        validate_attachment(GmailAttachment("report.pdf", "application/pdf", b"not-a-pdf"))
    fake_xlsx = BytesIO()
    with zipfile.ZipFile(fake_xlsx, "w") as archive:
        archive.writestr("random.txt", "not a workbook")
    with pytest.raises(ValueError):
        validate_attachment(GmailAttachment("report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", fake_xlsx.getvalue()))


def test_approval_is_consumed_and_delivery_is_idempotent(tmp_path):
    store = JobStore(tmp_path / "state.db")
    job = store.create_job("gmail-1", "accounting@example.com", "Báo cáo")
    store.transition(job["id"], "fetching")
    store.transition(job["id"], "extracting")
    store.transition(job["id"], "needs_review")
    store.requeue(job["id"], approved=True)
    assert store.is_approved(job["id"])
    store.consume_approval(job["id"])
    assert not store.is_approved(job["id"])
    store.delivery(job["id"], "gmail", "sent", "out-1")
    assert store.delivered(job["id"], "gmail")
    with pytest.raises(ValueError):
        store.transition(job["id"], "completed")


@pytest.mark.parametrize("system", ["Windows", "Darwin", "Linux"])
def test_native_service_runs_worker_with_gateway(monkeypatch, system):
    monkeypatch.setattr("taxsentry.service_control.platform.system", lambda: system)
    path, content = artifact()
    assert isinstance(path, Path)
    assert "worker" in content and "--gateway" in content


class _Call:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class _Messages:
    def __init__(self, existing=None):
        self.existing, self.sent = existing or [], 0

    def list(self, **kwargs):
        return _Call({"messages": self.existing})

    def send(self, **kwargs):
        self.sent += 1
        return _Call({"id": "new-message"})


class _Service:
    def __init__(self, messages):
        self._messages = messages

    def users(self):
        return self

    def messages(self):
        return self._messages


def test_gmail_delivery_uses_stable_message_id(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    messages = _Messages([{"id": "already-sent"}])
    client = GmailClient({}, service=_Service(messages))
    result = client.send_report("director@example.com", "Report", "<p>ok</p>", pdf, idempotency_key="job-1")
    assert result == "already-sent"
    assert messages.sent == 0


class _Bot:
    def __init__(self):
        self.chats = []

    async def send_message(self, **kwargs):
        self.chats.append(kwargs["chat_id"])
        return SimpleNamespace(message_id=1)

    async def send_document(self, **kwargs):
        return SimpleNamespace(message_id=2)


@pytest.mark.asyncio
async def test_telegram_delivery_only_targets_director_ids():
    bot = _Bot()
    director = TelegramDirector({"telegram": {"enabled": True}, "director": {"telegram_chat_ids": ["10", "20"]}}, bot=bot)
    assert await director.notify("status") == ["1", "1"]
    assert bot.chats == ["10", "20"]


@pytest.mark.asyncio
async def test_worker_rejects_chat_only_profile(monkeypatch):
    monkeypatch.setattr("taxsentry.worker.load_config", lambda: {"gmail": {"enabled": False}})
    assert await run_worker(once=True) == 2
