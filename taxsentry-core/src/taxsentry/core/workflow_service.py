from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from taxsentry.config import load_config
from taxsentry.config.paths import EVIDENCE_CONTEXT_PATH
from taxsentry.runtime.session import JobManager, SessionManager, RuntimeJob


@dataclass
class WorkflowFlags:
    tracking_enabled: bool = True
    retry_limit: int = 2
    default_state: str = "pending"
    needs_review_on_missing_data: bool = True
    auto_send_email: bool = True
    auto_send_telegram: bool = True


class TaxSentryWorkflowService:
    """Thin orchestration helper for automation lifecycle and notifications."""

    def __init__(
        self,
        *,
        session_manager: SessionManager,
        job_manager: JobManager | None = None,
        settings: dict[str, Any] | None = None,
        log_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.settings = settings or load_config()
        jobs = self.settings.get("jobs", {}) or {}
        self.flags = WorkflowFlags(
            tracking_enabled=bool(jobs.get("tracking_enabled", True)),
            retry_limit=int(jobs.get("retry_limit", 2) or 2),
            default_state=str(jobs.get("default_state", "pending")),
            needs_review_on_missing_data=bool(jobs.get("needs_human_review_on_missing_data", True)),
            auto_send_email=bool(jobs.get("auto_send_email", True)),
            auto_send_telegram=bool(jobs.get("auto_send_telegram", True)),
        )
        self.session_manager = session_manager
        self.job_manager = job_manager or JobManager()
        self.log = log_callback or (lambda _message: None)

    def create_job_for_file(
        self,
        *,
        session_id: str,
        file_path: Path,
        file_context: dict[str, Any] | None,
        trace_context: dict[str, Any],
    ) -> RuntimeJob | None:
        if not self.flags.tracking_enabled:
            return None

        job = self.job_manager.start_job(
            job_type="report_processing",
            session_id=session_id,
            state=self.flags.default_state,
            source_file=file_path.name,
            source_path=str(file_path),
            email_id=(file_context or {}).get("email_id"),
            event_id=trace_context.get("event_id"),
            trace_id=trace_context.get("trace_id"),
            metadata={
                "suffix": file_path.suffix.lower(),
                "mode": "automation",
            },
        )
        if job:
            self.session_manager.record_event(
                session_id=session_id,
                event_type="job_start",
                actor="automation",
                action="start report job",
                result=job.state,
                payload={
                    "job_id": job.job_id,
                    "job_type": job.job_type,
                    "source_file": job.source_file,
                },
            )
            self.log(f"🧾 Job {job.job_id} đã khởi tạo với state '{job.state}'.")
        return job

    def mark_missing_data(self, *, session_id: str, job: RuntimeJob | None, file_path: Path) -> None:
        if not job:
            return
        job_state = "needs_review" if self.flags.needs_review_on_missing_data else "failed"
        self.job_manager.update_job_state(
            job.job_id,
            job_state,
            error_message="Excel file missing meaningful accounting data",
            metadata={"reason": "missing_meaningful_data"},
        )
        self.session_manager.record_event(
            session_id=session_id,
            event_type="job_update",
            actor="automation",
            action="mark job on missing data",
            result=job_state,
            payload={"job_id": job.job_id, "source_file": file_path.name},
        )

    def mark_processing(self, job: RuntimeJob | None, *, phase: str) -> None:
        if not job:
            return
        self.job_manager.update_job_state(job.job_id, "processing", metadata={"phase": phase})

    def mark_db_failure(self, *, session_id: str, job: RuntimeJob | None, file_path: Path) -> None:
        if not job:
            return
        self.job_manager.update_job_state(
            job.job_id,
            "failed",
            error_message="Database sync failed",
            metadata={"phase": "database_sync"},
        )
        self.session_manager.record_event(
            session_id=session_id,
            event_type="job_update",
            actor="automation",
            action="mark job on db failure",
            result="failed",
            payload={"job_id": job.job_id, "source_file": file_path.name},
        )

    def mark_notification_failure(
        self,
        *,
        session_id: str,
        job: RuntimeJob | None,
        file_path: Path,
        error: Exception,
        channel: str,
    ) -> None:
        if not job:
            return
        self.job_manager.update_job_state(
            job.job_id,
            "failed",
            error_message=str(error),
            metadata={"phase": channel},
        )
        self.session_manager.record_event(
            session_id=session_id,
            event_type="job_update",
            actor="automation",
            action=f"mark job on {channel} failure",
            result="failed",
            payload={"job_id": job.job_id, "source_file": file_path.name, "error": str(error)},
        )

    def mark_completed(
        self,
        *,
        session_id: str,
        job: RuntimeJob | None,
        file_path: Path,
        pdf_report_path: Path,
        email_sent: bool,
        telegram_sent: bool,
    ) -> None:
        if not job:
            return
        self.job_manager.update_job_state(
            job.job_id,
            "completed",
            metadata={
                "phase": "completed",
                "report_pdf": str(pdf_report_path),
                "email_sent": email_sent,
                "telegram_sent": telegram_sent,
            },
        )
        self.session_manager.record_event(
            session_id=session_id,
            event_type="job_update",
            actor="automation",
            action="mark job completed",
            result="completed",
            payload={
                "job_id": job.job_id,
                "source_file": file_path.name,
                "report_pdf": str(pdf_report_path),
            },
        )

    def send_email_report(self, sender, pdf_report_path: Path, summary_text: str) -> bool:
        if not self.flags.auto_send_email:
            self.log("ℹ️ Cờ AUTO_SEND_EMAIL đang tắt, bỏ qua bước gửi email.")
            return True
        return sender.send_report(str(pdf_report_path), summary_text)

    def send_telegram_report(
        self,
        *,
        pdf_report_path: Path,
        summary_text: str,
        evidence_context_path: str | None = None,
    ) -> bool:
        if not self.flags.auto_send_telegram:
            self.log("ℹ️ Cờ AUTO_SEND_TELEGRAM đang tắt, bỏ qua bước gửi Telegram.")
            return True

        from taxsentry.bot.telegram_bot import send_active_report_to_director

        import asyncio

        return asyncio.run(
            send_active_report_to_director(
                str(pdf_report_path),
                summary_text,
                evidence_context_path=evidence_context_path or str(EVIDENCE_CONTEXT_PATH),
            )
        )
