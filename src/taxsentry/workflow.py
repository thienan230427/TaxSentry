from __future__ import annotations

import asyncio
import json
from typing import Any

from .config import DOWNLOAD_DIR
from .events import EventType
from .extraction import extract
from .gmail import GmailClient, GmailMessage, trusted_sender
from .providers import create_provider
from .reporting import REPORT_SCHEMA, html_summary, markdown, parse_report, render_pdf
from .store import JobStore
from .telegram import TelegramDirector

SYSTEM_PROMPT = """Bạn là TaxSentry, chuyên gia CFO và tuân thủ thuế Việt Nam. Chỉ dựa trên dữ liệu được cung cấp. Trả về đúng một JSON theo schema; nêu dữ liệu thiếu, căn cứ, độ tin cậy và khuyến nghị để Giám đốc quyết định. Không tự nhận đã khai thuế hay thực hiện quyết định kinh doanh."""


class TaxSentryWorkflow:
    def __init__(self, settings: dict[str, Any], *, gmail: GmailClient | None = None, store: JobStore | None = None, provider=None, telegram: TelegramDirector | None = None):
        self.settings = settings
        self.gmail = gmail or GmailClient(settings)
        self.store = store or JobStore()
        self.provider = provider or create_provider(settings)
        self.telegram = telegram or TelegramDirector(settings)

    async def run_once(self) -> int:
        completed = 0
        for message in self.gmail.messages():
            if not trusted_sender(message.sender, self.settings["gmail"].get("trusted_senders", [])):
                self.store.event(None, "untrusted_sender", {"message_id": message.id, "sender": message.sender})
                continue
            job = self.store.create_job(message.id, message.sender, message.subject)
            if not job:
                job = self.store.by_message(message.id)
                if not job:
                    continue
                if job["state"] == "completed":
                    self.gmail.label(message.id, "TaxSentry/Completed")
                    continue
                if job["state"] not in {"queued", "fetching", "extracting", "analyzing", "rendering", "delivering"}:
                    continue
                if job["state"] != "queued":
                    self.store.requeue(job["id"])
            if await self._with_retries(job["id"], message):
                completed += 1
        return completed

    async def _with_retries(self, job_id: str, message: GmailMessage) -> bool:
        maximum = int(self.settings["worker"].get("max_retries", 3))
        for attempt in range(maximum):
            try:
                self.gmail.label(message.id, "TaxSentry/Processing")
                return await self._process(job_id, message)
            except Exception as exc:
                retries = self.store.increment_retry(job_id, str(exc))
                if retries >= maximum:
                    self.store.transition(job_id, "failed", error=str(exc))
                    try:
                        self.gmail.label(message.id, "TaxSentry/Failed")
                    except Exception as label_exc:
                        self.store.event(job_id, "label_pending", {"label": "TaxSentry/Failed", "error": str(label_exc)})
                    try:
                        await self.telegram.notify(f"❌ TaxSentry xử lý thất bại: {message.subject}\n{exc}")
                    except Exception as telegram_exc:
                        self.store.event(job_id, "notification_failed", {"channel": "telegram", "error": str(telegram_exc)})
                    return False
                if self.store.get(job_id)["state"] != "queued":
                    self.store.requeue(job_id)
                await asyncio.sleep(2**attempt)
        return False

    async def _process(self, job_id: str, message: GmailMessage) -> bool:
        self.store.transition(job_id, "fetching")
        if not message.attachments:
            raise ValueError("Email has no supported attachment")
        extracted, confidence = [], 1.0
        self.store.transition(job_id, "extracting")
        for attachment in message.attachments:
            path = self.gmail.save(job_id, attachment, int(self.settings["worker"].get("max_attachment_mb", 25)))
            self.store.attachment(job_id, name=attachment.name, path=str(path), sha256=attachment.sha256, mime_type=attachment.mime_type)
            result = extract(path, self.settings["ocr"].get("languages", ["vie", "eng"]))
            extracted.append({"file": attachment.name, "source": result.source, "content": result.content})
            confidence = min(confidence, result.confidence)
        minimum_ocr = float(self.settings["ocr"].get("minimum_confidence", 70)) / 100
        approved = self.store.is_approved(job_id)
        if not extracted or (confidence < minimum_ocr and not approved):
            self.store.transition(job_id, "needs_review", error=f"Extraction confidence {confidence:.0%}")
            self.gmail.label(message.id, "TaxSentry/NeedsReview")
            await self.telegram.notify(f"⚠️ Báo cáo cần Giám đốc/Kế toán kiểm tra: {message.subject}\nOCR confidence: {confidence:.0%}")
            return False

        self.store.transition(job_id, "analyzing")
        prompt = f"{SYSTEM_PROMPT}\n\nSchema: {json.dumps(REPORT_SCHEMA, ensure_ascii=False)}\n\nDữ liệu: {json.dumps(extracted, ensure_ascii=False, default=str)[:120000]}"
        output = []
        async for event in self.provider.stream_turn([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}], output_schema=REPORT_SCHEMA):
            if event.type == EventType.TEXT_DELTA:
                output.append(event.text)
            elif event.type == EventType.ERROR:
                raise RuntimeError(event.text)
        report = parse_report("".join(output))
        threshold = float(self.settings["report"].get("minimum_confidence", 0.7))
        if report["confidence"] < threshold and not approved:
            self.store.report(job_id, report, report["confidence"])
            self.store.transition(job_id, "needs_review", error=f"Analysis confidence {report['confidence']:.0%}")
            self.gmail.label(message.id, "TaxSentry/NeedsReview")
            await self.telegram.notify(f"⚠️ Phân tích cần duyệt: {message.subject}\nTin cậy: {report['confidence']:.0%}")
            return False

        self.store.transition(job_id, "rendering")
        pdf = render_pdf(report, DOWNLOAD_DIR / job_id / "TaxSentry-report.pdf")
        self.store.report(job_id, report, report["confidence"], str(pdf))
        self.store.transition(job_id, "delivering", report_path=str(pdf))
        director = self.settings["director"].get("email", "")
        if not director:
            raise ValueError("director.email is not configured")
        if not self.store.delivered(job_id, "gmail"):
            outgoing = self.gmail.send_report(director, f"TaxSentry: {message.subject}", html_summary(report), pdf, idempotency_key=job_id)
            self.store.delivery(job_id, "gmail", "sent", outgoing)
        if not self.store.delivered(job_id, "telegram"):
            telegram_ids = await self.telegram.notify(f"✅ {report['executive_summary']}\nTin cậy: {report['confidence']:.0%}", pdf)
            for external_id in telegram_ids:
                self.store.delivery(job_id, "telegram", "sent", external_id)
        self.store.transition(job_id, "completed", report_path=str(pdf))
        if approved:
            self.store.consume_approval(job_id)
        try:
            self.gmail.label(message.id, "TaxSentry/Completed")
        except Exception as exc:
            self.store.event(job_id, "label_pending", {"label": "TaxSentry/Completed", "error": str(exc)})
        return True

    def latest_markdown(self) -> str:
        latest = self.store.latest_report()
        return markdown(latest["payload"]) if latest else "Chưa có báo cáo."
