import zipfile
from email.message import EmailMessage
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


def test_gmail_delivery_uses_stable_message_id(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7")

    class Imap:
        def select(self, mailbox):
            return "OK", []

        def uid(self, *args):
            return "OK", [b"123"]

    client = GmailClient({"gmail": {"account": "boss@gmail.com"}}, imap=Imap())
    result = client.send_report("director@example.com", "Report", "<p>ok</p>", pdf, idempotency_key="job-1")
    assert result == "123"


def test_gmail_app_password_is_verified_before_keyring_storage(monkeypatch):
    calls = []

    class Imap:
        def login(self, account, password):
            calls.append((account, password))

    monkeypatch.setattr("taxsentry.gmail.imaplib.IMAP4_SSL", lambda *args: Imap())
    monkeypatch.setattr("taxsentry.gmail.set_secret", lambda *args: calls.append(args))
    client = GmailClient({"gmail": {"account": "boss@gmail.com"}})
    client.authenticate(app_password="abcd efgh ijkl mnop")

    assert calls == [
        ("boss@gmail.com", "abcdefghijklmnop"),
        ("gmail-app-password:boss@gmail.com", "abcdefghijklmnop"),
    ]


def test_gmail_imap_reads_attachments_and_applies_workflow_label():
    message = EmailMessage()
    message["From"], message["Subject"] = "accounting@example.com", "Báo cáo"
    message.set_content("attached")
    message.add_attachment(b"%PDF-1.7", maintype="application", subtype="pdf", filename="report.pdf")

    class Imap:
        def __init__(self):
            self.stores = []

        def select(self, mailbox):
            return "OK", []

        def uid(self, command, uid=None, *args):
            if command == "search":
                return "OK", [b"42"]
            if command == "fetch":
                return "OK", [(b"42 (RFC822)", message.as_bytes())]
            self.stores.append((uid, args))
            return "OK", []

    imap = Imap()
    client = GmailClient({"gmail": {"account": "boss@gmail.com"}}, imap=imap)
    received = client.messages()[0]
    client.label(received.id, "TaxSentry/Completed")

    assert received.subject == "Báo cáo" and received.attachments[0].data == b"%PDF-1.7"
    assert len(imap.stores) == len(("TaxSentry/Processing", "TaxSentry/Completed", "TaxSentry/NeedsReview", "TaxSentry/Failed"))


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
