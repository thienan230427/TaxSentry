from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Callable

from taxsentry.config import describe_config, load_config
from taxsentry.config.paths import EVIDENCE_CONTEXT_PATH
from taxsentry.core.evidence_preview import build_trace_replay_text
from taxsentry.database.db_manager import TaxSentryDBManager
from taxsentry.database.session_store import TaxSentrySessionStore
from taxsentry.providers import from_settings, health_check

from .session import JobManager, SessionManager


@dataclass
class RuntimeEvent:
    kind: str
    title: str
    detail: str = ""
    status: str = "info"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RuntimeEventBus:
    """Simple in-process event bus for runtime snapshots and UI updates."""

    def __init__(self) -> None:
        self._events: list[RuntimeEvent] = []
        self._subscribers: list[Callable[[RuntimeEvent], None]] = []

    def publish(
        self,
        kind: str,
        title: str,
        *,
        detail: str = "",
        status: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        event = RuntimeEvent(
            kind=kind,
            title=title,
            detail=detail,
            status=status,
            metadata=metadata or {},
        )
        self._events.append(event)
        self._events = self._events[-50:]
        for handler in list(self._subscribers):
            try:
                handler(event)
            except Exception:
                continue
        return event

    def subscribe(self, handler: Callable[[RuntimeEvent], None]) -> None:
        self._subscribers.append(handler)

    def recent(self, limit: int = 10) -> list[RuntimeEvent]:
        return self._events[-limit:]


class TaxSentryRuntimeService:
    """Facade for status, replay, job and session snapshots."""

    def __init__(
        self,
        settings: dict[str, Any] | None = None,
        *,
        event_bus: RuntimeEventBus | None = None,
        session_store: TaxSentrySessionStore | None = None,
        db_manager: TaxSentryDBManager | None = None,
    ) -> None:
        self.settings = settings or load_config()
        self.event_bus = event_bus or RuntimeEventBus()
        self.db_manager = db_manager or TaxSentryDBManager()
        self.session_store = session_store or TaxSentrySessionStore(self.db_manager.db_path)
        self.session_manager = SessionManager(self.session_store)
        self.job_manager = JobManager(self.db_manager)
        self.session_store.connect()
        self.db_manager.connect()

    def provider_health(self) -> tuple[bool, str]:
        provider = from_settings(self.settings)
        return health_check(provider)

    def status_text(self) -> str:
        ok, message = self.provider_health()
        recent_jobs = self.recent_jobs(limit=3)
        recent_sessions = self.recent_sessions(limit=3)
        lines = [
            describe_config(self.settings),
            f"Provider health: {'OK' if ok else 'FAIL'} — {message}",
            f"Recent sessions: {len(recent_sessions)}",
            f"Recent jobs: {len(recent_jobs)}",
        ]
        if recent_jobs:
            top = recent_jobs[0]
            lines.append(
                f"Last job: {top.job_id} | {top.job_type} | {top.state} | {top.source_file or 'n/a'}"
            )
        return "\n".join(lines)

    def snapshot(self, *, session_id: str | None = None, limit: int = 5) -> dict[str, Any]:
        ok, message = self.provider_health()
        session = self.session_manager.snapshot(session_id) if session_id else None
        return {
            "settings": self.settings,
            "provider_health": (ok, message),
            "recent_sessions": self.recent_sessions(limit=limit),
            "recent_jobs": self.recent_jobs(limit=limit),
            "recent_reports": self.recent_reports(limit=limit),
            "events": [asdict(event) for event in self.event_bus.recent(limit=limit)],
            "trace_replay": self.replay_session(session_id) if session_id else "",
            "session": session,
        }

    def recent_sessions(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            return self.session_store.get_recent_sessions(limit=limit)
        except Exception:
            return []

    def recent_jobs(self, limit: int = 5):
        try:
            return self.job_manager.get_recent_jobs(limit=limit)
        except Exception:
            return []

    def recent_reports(self, limit: int = 5) -> list[dict[str, Any]]:
        try:
            return self.db_manager.get_recent_logs(limit=limit)
        except Exception:
            return []

    def replay_session(self, session_id: str) -> str:
        session = self.session_manager.load_session(session_id)
        if session is None:
            session_record = self.session_store.get_session(session_id)
            if not session_record:
                return ""

        bundle = self.session_manager.build_replay_bundle(
            session_id,
            db_path=self.db_manager.db_path,
            evidence_path=EVIDENCE_CONTEXT_PATH,
        )
        if bundle is None:
            return ""

        replay = build_trace_replay_text(
            bundle.evidence_context,
            session_events=bundle.events,
            artifacts=[],
        )
        if not replay:
            replay_lines = [
                f"Trace replay for session {bundle.session.session_id if bundle.session else session_id}",
                f"- entry_point: {bundle.session.entry_point if bundle.session else 'unknown'}",
                f"- mode: {bundle.session.mode if bundle.session else 'unknown'}",
                f"- events: {len(bundle.events)}",
                f"- reports: {len(bundle.reports)}",
            ]
            replay = "\n".join(replay_lines)

        jobs = self.job_manager.get_jobs_for_session(session_id)
        if jobs:
            replay += "\n- jobs:\n"
            for job in jobs[:8]:
                replay += (
                    f"  • {job.job_id} | {job.job_type} | {job.state} | "
                    f"{job.source_file or 'n/a'} | retry={job.retry_count}\n"
                )
        if bundle.reports:
            replay += "\n- reports:\n"
            for report in bundle.reports[:8]:
                replay += (
                    f"  • {report.get('file_name', 'n/a')} | {report.get('tax_risk_status', 'n/a')} | "
                    f"{report.get('status', 'n/a')}\n"
                )
        return replay.strip()

    def publish_event(
        self,
        kind: str,
        title: str,
        *,
        detail: str = "",
        status: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> RuntimeEvent:
        return self.event_bus.publish(kind, title, detail=detail, status=status, metadata=metadata)
