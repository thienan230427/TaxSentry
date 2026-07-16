from __future__ import annotations

import asyncio
import json
from pathlib import Path

from taxsentry.events import AgentEvent, EventType
from taxsentry.extraction import Extraction
from taxsentry.gmail import GmailAttachment, GmailMessage
from taxsentry.store import JobStore
from taxsentry.workflow import TaxSentryWorkflow

REPORT = {
    "executive_summary": "Hoạt động ổn định, cần kiểm soát chi phí.",
    "performance": [{"metric": "Doanh thu", "value": "120 triệu", "assessment": "tăng"}],
    "tax_risks": [], "missing_data": [],
    "recommendations": [{"priority": "high", "action": "Rà soát chi phí"}], "confidence": 0.9,
}


class FakeProvider:
    async def stream_turn(self, messages, output_schema=None):
        yield AgentEvent(EventType.TEXT_DELTA, text=json.dumps(REPORT, ensure_ascii=False))
        yield AgentEvent(EventType.TURN_COMPLETED)


class FakeTelegram:
    def __init__(self): self.sent = []
    async def notify(self, text, pdf=None):
        self.sent.append((text, pdf))
        return ["telegram-1"] if pdf else []


class FakeGmail:
    def __init__(self, root: Path, message: GmailMessage):
        self.root, self.message, self.labels, self.outgoing = root, message, [], []
    def messages(self): return [self.message]
    def label(self, message_id, label, **kwargs): self.labels.append(label)
    def save(self, job_id, attachment, max_mb=25):
        path = self.root / attachment.name; path.write_bytes(attachment.data); return path
    def send_report(self, to, subject, html, pdf_path, **kwargs):
        self.outgoing.append((to, subject, pdf_path)); return "gmail-out-1"


class FlakyGmail(FakeGmail):
    def __init__(self, root, message):
        super().__init__(root, message)
        self.attempts = 0

    def send_report(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise TimeoutError
        return super().send_report(*args, **kwargs)


class FlakyTelegram(FakeTelegram):
    def __init__(self):
        super().__init__()
        self.document_attempts = 0

    async def notify(self, text, pdf=None):
        if pdf:
            self.document_attempts += 1
            if self.document_attempts == 1:
                raise TimeoutError
        return await super().notify(text, pdf)


def settings():
    return {
        "gmail": {"account": "director@example.com", "process_after_uid": 0},
        "director": {"telegram_chat_ids": ["1"]},
        "telegram": {"enabled": True},
        "worker": {"max_retries": 1, "max_attachment_mb": 25},
        "ocr": {"languages": ["vie", "eng"], "minimum_confidence": 70},
        "report": {"minimum_confidence": 0.7},
        "provider": {"kind": "lmstudio", "model": "fake", "base_url": "http://localhost"},
    }


def test_e2e_deduplicates_and_delivers(monkeypatch, tmp_path):
    message = GmailMessage("m1", "Kế toán <accounting@example.com>", "Tháng 5", [GmailAttachment("report.pdf", "application/pdf", b"pdf")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("revenue 120", 0.95, "pdf-text"))
    def fake_pdf(report, output, warning=""):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output
    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 1
    assert asyncio.run(workflow.run_once()) == 0
    assert store.recent_jobs()[0]["state"] == "completed"
    assert gmail.labels[-1] == "TaxSentry/Completed"
    assert gmail.outgoing[0][0] == "director@example.com" and telegram.sent


def test_delivery_retry_does_not_repeat_pipeline_or_successful_channel(monkeypatch, tmp_path):
    message = GmailMessage("m-retry", "accounting@example.com", "Retry", [GmailAttachment("report.pdf", "application/pdf", b"%PDF")])
    gmail, telegram, store = FlakyGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "retry.db")
    calls = {"extract": 0, "render": 0}

    def fake_extract(path, languages):
        calls["extract"] += 1
        return Extraction("revenue 120", 0.95, "pdf-text")

    def fake_pdf(report, output, warning=""):
        calls["render"] += 1
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output

    monkeypatch.setattr("taxsentry.workflow.extract", fake_extract)
    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr("taxsentry.workflow.BACKOFF_SECONDS", (0, 0, 0))
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)

    assert asyncio.run(workflow.run_once()) == 1
    assert calls == {"extract": 1, "render": 1} and gmail.attempts == 2
    assert len([document for _, document in telegram.sent if document]) == 1


def test_telegram_retry_does_not_resend_gmail(monkeypatch, tmp_path):
    message = GmailMessage("m-telegram", "accounting@example.com", "Retry", [GmailAttachment("report.pdf", "application/pdf", b"%PDF")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FlakyTelegram(), JobStore(tmp_path / "telegram.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("revenue 120", 0.95, "pdf-text"))

    def fake_pdf(report, output, warning=""):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output

    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    monkeypatch.setattr("taxsentry.workflow.BACKOFF_SECONDS", (0, 0, 0))
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)

    assert asyncio.run(workflow.run_once()) == 1
    assert len(gmail.outgoing) == 1 and telegram.document_attempts == 2


def test_each_attachment_gets_an_independent_job(monkeypatch, tmp_path):
    message = GmailMessage("m-many", "accounting@example.com", "Tháng 6", [GmailAttachment("a.pdf", "application/pdf", b"%PDF-a"), GmailAttachment("b.pdf", "application/pdf", b"%PDF-b")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "many.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("revenue 120", 0.95, "pdf-text"))

    def fake_pdf(report, output, warning=""):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output

    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)

    assert asyncio.run(workflow.run_once()) == 2
    assert len(store.recent_jobs()) == 2
    assert len(gmail.outgoing) == 2


def test_low_ocr_confidence_delivers_with_warning(monkeypatch, tmp_path):
    message = GmailMessage("m2", "accounting@example.com", "Scan", [GmailAttachment("scan.png", "image/png", b"image")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("unclear", 0.4, "ocr"))
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 1
    assert store.recent_jobs()[0]["state"] == "completed"
    assert gmail.labels[-1] == "TaxSentry/Completed"
    assert gmail.outgoing


def test_worker_recovers_interrupted_job(monkeypatch, tmp_path):
    message = GmailMessage("m3", "accounting@example.com", "Recovery", [GmailAttachment("report.pdf", "application/pdf", b"%PDF-1.7")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    source = f"INBOX:{message.id}:{message.attachments[0].sha256}"
    job = store.create_job(source, message.sender, message.subject)
    store.transition(job["id"], "fetching")
    store.transition(job["id"], "extracting")
    store.transition(job["id"], "analyzing")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("revenue 120", 0.95, "pdf-text"))

    def fake_pdf(report, output, warning=""):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output

    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    monkeypatch.setattr("taxsentry.workflow.DOWNLOAD_DIR", tmp_path)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 1
    assert store.get(job["id"])["state"] == "completed"


def test_legacy_office_problem_fails_without_retry(monkeypatch, tmp_path):
    message = GmailMessage("m4", "unknown@example.com", "Legacy", [GmailAttachment("old.doc", "application/msword", b"legacy")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: (_ for _ in ()).throw(ValueError("LibreOffice is required")))
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)

    assert asyncio.run(workflow.run_once()) == 0
    job = store.recent_jobs()[0]
    assert job["state"] == "failed" and job["retries"] == 0
    assert gmail.labels[-1] == "TaxSentry/Failed"


def test_cancelled_queued_job_never_starts(monkeypatch, tmp_path):
    message = GmailMessage("m-cancel", "accounting@example.com", "Cancel", [GmailAttachment("report.pdf", "application/pdf", b"%PDF-1.7")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "cancel.db")
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    job_id = workflow.queue_messages([message])[0]
    workflow.cancel(job_id)

    assert asyncio.run(workflow.run_once()) == 0
    assert store.get(job_id)["state"] == "cancelled"
    assert not gmail.outgoing
