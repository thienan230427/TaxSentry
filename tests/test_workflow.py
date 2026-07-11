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
    def label(self, message_id, label): self.labels.append(label)
    def save(self, job_id, attachment, max_mb=25):
        path = self.root / attachment.name; path.write_bytes(attachment.data); return path
    def send_report(self, to, subject, html, pdf_path, **kwargs):
        self.outgoing.append((to, subject, pdf_path)); return "gmail-out-1"


def settings():
    return {
        "gmail": {"trusted_senders": ["accounting@example.com"]},
        "director": {"email": "director@example.com", "telegram_chat_ids": ["1"]},
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
    def fake_pdf(report, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output
    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 1
    assert asyncio.run(workflow.run_once()) == 0
    assert store.recent_jobs()[0]["state"] == "completed"
    assert gmail.labels[-1] == "TaxSentry/Completed"
    assert gmail.outgoing and telegram.sent


def test_low_ocr_confidence_requires_review(monkeypatch, tmp_path):
    message = GmailMessage("m2", "accounting@example.com", "Scan", [GmailAttachment("scan.png", "image/png", b"image")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("unclear", 0.4, "ocr"))
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 0
    assert store.recent_jobs()[0]["state"] == "needs_review"
    assert gmail.labels[-1] == "TaxSentry/NeedsReview"
    assert not gmail.outgoing

    job = store.recent_jobs()[0]
    store.requeue(job["id"], approved=True)
    assert asyncio.run(workflow.run_once()) == 1
    assert store.get(job["id"])["state"] == "completed"
    assert not store.is_approved(job["id"])


def test_worker_recovers_interrupted_job(monkeypatch, tmp_path):
    message = GmailMessage("m3", "accounting@example.com", "Recovery", [GmailAttachment("report.pdf", "application/pdf", b"%PDF-1.7")])
    gmail, telegram, store = FakeGmail(tmp_path, message), FakeTelegram(), JobStore(tmp_path / "state.db")
    job = store.create_job(message.id, message.sender, message.subject)
    store.transition(job["id"], "fetching")
    store.transition(job["id"], "extracting")
    store.transition(job["id"], "analyzing")
    monkeypatch.setattr("taxsentry.workflow.extract", lambda path, languages: Extraction("revenue 120", 0.95, "pdf-text"))

    def fake_pdf(report, output):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"%PDF")
        return output

    monkeypatch.setattr("taxsentry.workflow.render_pdf", fake_pdf)
    workflow = TaxSentryWorkflow(settings(), gmail=gmail, store=store, provider=FakeProvider(), telegram=telegram)
    assert asyncio.run(workflow.run_once()) == 1
    assert store.get(job["id"])["state"] == "completed"
