import zipfile
from contextlib import nullcontext
from datetime import datetime
from email.message import EmailMessage
from io import BytesIO
from types import SimpleNamespace

import pytest

from taxsentry.extraction import extract
from taxsentry.gmail import GmailAttachment, GmailClient, natural_gmail_query, validate_attachment
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
    client = GmailClient({"gmail": {"account": "boss@gmail.com", "process_after_uid": 0}}, imap=imap)
    received = client.messages()[0]
    client.label(received.id, "TaxSentry/Completed")

    assert received.subject == "Báo cáo" and received.attachments[0].data == b"%PDF-1.7"
    assert len(imap.stores) == len(("TaxSentry/Processing", "TaxSentry/Completed", "TaxSentry/NeedsReview", "TaxSentry/Failed"))


def test_gmail_search_caps_results_and_reads_message_body():
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = "bank@example.com", "boss@gmail.com", "Giao dịch"
    message["Date"] = "Tue, 14 Jul 2026 09:30:00 +0700"
    message.set_content("Số dư cuối ngày")

    class Imap:
        def select(self, mailbox): return "OK", []
        def uid(self, command, uid=None, *args):
            if command == "search": return "OK", [b"1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25"]
            return "OK", [(f"{uid} (RFC822)".encode(), message.as_bytes())]

    client = GmailClient({"gmail": {"account": "boss@gmail.com"}}, imap=Imap())
    found = client.search("in:inbox", limit=99)
    assert len(found) == 20 and found[0].id == "25" and found[0].body == "Số dư cuối ngày"
    assert client.read("7").recipient == "boss@gmail.com"


def test_natural_gmail_query_maps_common_vietnamese_intents():
    query = natural_gmail_query("Gmail hôm nay có thư chưa đọc, có file từ MB Bank?", now=datetime(2026, 7, 14))
    assert query == 'in:inbox after:2026/07/14 is:unread has:attachment from:"MB Bank"'


def test_open_xml_office_extracts_text_without_new_dependencies(tmp_path):
    docx = tmp_path / "memo.docx"
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("word/document.xml", '<w:document xmlns:w="w"><w:t>Doanh thu tăng</w:t></w:document>')
    pptx = tmp_path / "brief.pptx"
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr("[Content_Types].xml", "types")
        archive.writestr("ppt/presentation.xml", "presentation")
        archive.writestr("ppt/slides/slide1.xml", '<a:sld xmlns:a="a"><a:t>Rủi ro thuế</a:t></a:sld>')

    assert extract(docx, ["vie"]).content == "Doanh thu tăng"
    assert extract(pptx, ["vie"]).content == "Rủi ro thuế"
    validate_attachment(GmailAttachment("memo.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", docx.read_bytes()))
    validate_attachment(GmailAttachment("brief.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation", pptx.read_bytes()))


def test_legacy_office_requires_libreoffice(monkeypatch, tmp_path):
    legacy = tmp_path / "old.doc"
    legacy.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1data")
    monkeypatch.setattr("taxsentry.extraction.shutil.which", lambda name: None)
    validate_attachment(GmailAttachment("old.doc", "application/msword", legacy.read_bytes()))
    with pytest.raises(ValueError, match="LibreOffice"):
        extract(legacy, ["vie"])


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


@pytest.mark.asyncio
async def test_worker_initializes_missing_uid_without_processing_history(monkeypatch):
    settings = {"gmail": {"enabled": True, "account": "boss@gmail.com", "process_after_uid": None}, "worker": {"poll_seconds": 60}}
    saved = []

    class Gmail:
        def __init__(self, value): pass
        def latest_uid(self): return 88

    class Workflow:
        def __init__(self, value): self.value = value
        async def run_once(self): return 0
        async def close(self): pass

    monkeypatch.setattr("taxsentry.worker.load_config", lambda: settings)
    monkeypatch.setattr("taxsentry.worker.save_config", lambda value: saved.append(value.copy()))
    monkeypatch.setattr("taxsentry.worker.GmailClient", Gmail)
    monkeypatch.setattr("taxsentry.worker.TaxSentryWorkflow", Workflow)
    monkeypatch.setattr("taxsentry.worker.single_instance", lambda: nullcontext())

    assert await run_worker(once=True) == 0
    assert settings["gmail"]["process_after_uid"] == 88 and saved
