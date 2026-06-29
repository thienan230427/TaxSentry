from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from taxsentry.database.memory_store import TaxSentryMemoryStore
from taxsentry.database.session_store import TaxSentrySessionStore


@dataclass
class RuntimeMessage:
    role: str
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RuntimeSession:
    session_id: str
    entry_point: str
    user_identity: str | None
    mode: str
    started_at: str
    title: str | None = None
    summary: str | None = None
    outcome: str | None = None
    ended_at: str | None = None
    messages: list[RuntimeMessage] = field(default_factory=list)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    final_response: str | None = None


@dataclass
class RuntimeResponse:
    text: str
    route: str
    confidence: float = 1.0
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceEnvelope:
    session_id: str
    event_id: str
    trace_id: str
    source_file: str = ""
    source_path: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entry_point: str = "unknown"
    mode: str = "unknown"
    title: str | None = None


@dataclass
class ReplayBundle:
    session: RuntimeSession | None
    session_record: dict[str, Any] | None
    events: list[dict[str, Any]]
    reports: list[dict[str, Any]]
    evidence_context: dict[str, Any]
    trace: TraceEnvelope | None


class SessionManager:
    """Normalize session records and keep a live session snapshot."""

    def __init__(self, store: TaxSentrySessionStore | None = None):
        self.store = store or TaxSentrySessionStore()
        self._sessions: dict[str, RuntimeSession] = {}

    def start_session(
        self,
        *,
        entry_point: str,
        mode: str,
        user_identity: str | None = None,
        title: str | None = None,
    ) -> RuntimeSession:
        session_id = self.store.start_session(entry_point=entry_point, mode=mode, title=title)
        started_at = datetime.now(timezone.utc).isoformat()
        session = RuntimeSession(
            session_id=session_id,
            entry_point=entry_point,
            user_identity=user_identity,
            mode=mode,
            started_at=started_at,
            title=title,
        )
        self._sessions[session_id] = session
        self.record_event(
            session_id=session_id,
            event_type="session_start",
            actor=entry_point,
            action=f"start {mode}",
            result="started",
            payload={"user_identity": user_identity, "title": title},
        )
        return session

    def record_message(self, session_id: str, role: str, content: str, *, tool_calls: list[dict[str, Any]] | None = None) -> None:
        session = self._sessions.get(session_id)
        if session is None:
            session = self._rebuild_session_stub(session_id=session_id)
            self._sessions[session_id] = session
        message = RuntimeMessage(role=role, content=content, tool_calls=tool_calls or [])
        session.messages.append(message)
        if tool_calls:
            session.tool_calls.extend(tool_calls)
        self.record_event(
            session_id=session_id,
            event_type="message",
            actor=role,
            action="append message",
            result="stored",
            payload={"content": content, "tool_calls": tool_calls or []},
        )

    def record_tool_event(
        self,
        session_id: str,
        *,
        tool_name: str,
        action: str,
        result: str | None = None,
        payload: dict[str, Any] | None = None,
        latency_ms: float | None = None,
        error_message: str | None = None,
        actor: str = "tool_dispatcher",
    ) -> str:
        """Record a normalized trace row for a tool or capability step."""
        session = self._sessions.get(session_id)
        if session is None:
            session = self._rebuild_session_stub(session_id=session_id)
            self._sessions[session_id] = session
        trace_payload = {"tool_name": tool_name, **(payload or {})}
        return self.record_event(
            session_id=session_id,
            event_type="tool_dispatch",
            actor=actor,
            action=action,
            result=result,
            latency_ms=latency_ms,
            error_message=error_message,
            payload=trace_payload,
        )

    def record_event(
        self,
        *,
        session_id: str,
        event_type: str,
        actor: str,
        action: str,
        result: str | None = None,
        latency_ms: float | None = None,
        error_message: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> str:
        return self.store.log_event(
            session_id=session_id,
            event_type=event_type,
            actor=actor,
            action=action,
            result=result,
            latency_ms=latency_ms,
            error_message=error_message,
            payload=payload,
        )

    def finish_session(
        self,
        session_id: str,
        *,
        final_response: str | None = None,
        outcome: str | None = None,
        summary: str | None = None,
        event_result: str | None = None,
    ) -> bool:
        session = self._sessions.get(session_id)
        if session is None:
            session = self._rebuild_session_stub(session_id=session_id)
            self._sessions[session_id] = session

        session.final_response = final_response
        session.summary = summary or session.summary
        session.outcome = outcome or session.outcome
        session.ended_at = datetime.now(timezone.utc).isoformat()
        if final_response:
            session.messages.append(RuntimeMessage(role="assistant", content=final_response))
        self.record_event(
            session_id=session_id,
            event_type="session_end",
            actor="runtime",
            action="finish session",
            result=event_result or outcome or "completed",
            payload={"summary": summary, "final_response": final_response},
        )
        return self.store.end_session(session_id, summary=summary, outcome=outcome)

    def snapshot(self, session_id: str) -> RuntimeSession | None:
        session = self._sessions.get(session_id)
        if session is not None:
            return session
        return self.load_session(session_id)

    def load_session(self, session_id: str) -> RuntimeSession | None:
        session = self._sessions.get(session_id)
        if session is not None:
            return session

        session_record = self.store.get_session(session_id)
        if not session_record:
            return None

        events = self.store.get_session_events(session_id)
        messages: list[RuntimeMessage] = []
        tool_calls: list[dict[str, Any]] = []
        user_identity = None
        title = session_record.get("title")
        summary = session_record.get("summary")
        outcome = session_record.get("outcome")
        final_response = None

        for event in events:
            payload = event.get("payload") or {}
            if event.get("event_type") == "session_start":
                user_identity = payload.get("user_identity", user_identity)
                title = payload.get("title") or title
            elif event.get("event_type") == "message":
                message = RuntimeMessage(
                    role=str(event.get("actor") or payload.get("role") or "unknown"),
                    content=str(payload.get("content") or ""),
                    created_at=event.get("created_at") or datetime.now(timezone.utc).isoformat(),
                    tool_calls=list(payload.get("tool_calls") or []),
                )
                messages.append(message)
                if message.tool_calls:
                    tool_calls.extend(message.tool_calls)
            elif event.get("event_type") == "session_end":
                summary = payload.get("summary") or summary
                final_response = payload.get("final_response") or final_response
                outcome = event.get("result") or outcome

        session = RuntimeSession(
            session_id=session_record["session_id"],
            entry_point=session_record.get("entry_point", "unknown"),
            user_identity=user_identity,
            mode=session_record.get("mode", "unknown"),
            started_at=session_record.get("started_at") or datetime.now(timezone.utc).isoformat(),
            title=title,
            summary=summary,
            outcome=outcome,
            ended_at=session_record.get("ended_at"),
            messages=messages,
            tool_calls=tool_calls,
            final_response=final_response,
        )
        self._sessions[session_id] = session
        return session

    def build_trace_envelope(
        self,
        *,
        session_id: str,
        event_id: str | None = None,
        trace_id: str | None = None,
        source_file: str | None = None,
        source_path: str | None = None,
    ) -> TraceEnvelope:
        session = self.snapshot(session_id)
        return TraceEnvelope(
            session_id=session_id,
            event_id=event_id or "",
            trace_id=trace_id or "",
            source_file=source_file or "",
            source_path=source_path or "",
            entry_point=(session.entry_point if session else "unknown"),
            mode=(session.mode if session else "unknown"),
            title=(session.title if session else None),
        )

    def build_replay_bundle(
        self,
        session_id: str,
        *,
        db_path: str | None = None,
        evidence_path: Any | None = None,
    ) -> ReplayBundle | None:
        session_record = self.store.get_session(session_id)
        session = self.load_session(session_id)
        if session is None and not session_record:
            return None

        events = self.store.get_session_events(session_id)

        reports: list[dict[str, Any]] = []
        try:
            from taxsentry.database.db_manager import TaxSentryDBManager

            db_manager = TaxSentryDBManager(db_path)
            reports = db_manager.get_reports_for_session(session_id)
        except Exception:
            reports = []

        evidence_context: dict[str, Any] = {}
        try:
            from taxsentry.core.evidence_preview import load_evidence_context

            loaded = load_evidence_context(evidence_path)
            if loaded.get("session_id") == session_id:
                evidence_context = loaded
        except Exception:
            evidence_context = {}

        trace: TraceEnvelope | None = None
        if evidence_context:
            trace_context = evidence_context.get("trace_context") or {}
            trace = TraceEnvelope(
                session_id=session_id,
                event_id=str(trace_context.get("event_id") or evidence_context.get("event_id") or ""),
                trace_id=str(trace_context.get("trace_id") or evidence_context.get("trace_id") or ""),
                source_file=str(evidence_context.get("source_file") or ""),
                source_path=str(evidence_context.get("source_path") or ""),
                generated_at=str(evidence_context.get("generated_at") or datetime.now(timezone.utc).isoformat()),
                entry_point=(session.entry_point if session else session_record.get("entry_point", "unknown")),
                mode=(session.mode if session else session_record.get("mode", "unknown")),
                title=(session.title if session else session_record.get("title")),
            )
        elif session_record:
            trace = self.build_trace_envelope(session_id=session_id)

        return ReplayBundle(
            session=session,
            session_record=session_record,
            events=events,
            reports=reports,
            evidence_context=evidence_context,
            trace=trace,
        )

    def _rebuild_session_stub(self, session_id: str) -> RuntimeSession:
        now = datetime.now(timezone.utc).isoformat()
        return RuntimeSession(
            session_id=session_id,
            entry_point="unknown",
            user_identity=None,
            mode="unknown",
            started_at=now,
        )


class MemoryManager:
    """Facade over persistent memory and compact recall formatting."""

    def __init__(self, store: TaxSentryMemoryStore | None = None):
        self.store = store or TaxSentryMemoryStore()

    def remember(
        self,
        *,
        memory_type: str,
        subject: str,
        summary: str,
        payload: dict[str, Any] | None = None,
        tags: list[str] | tuple[str, ...] | None = None,
        confidence: float = 1.0,
        importance: float = 0.5,
        source_ref: str | None = None,
    ) -> str:
        return self.store.remember(
            memory_type=memory_type,
            subject=subject,
            summary=summary,
            payload=payload,
            tags=tags,
            confidence=confidence,
            importance=importance,
            source_ref=source_ref,
        )

    def recall(self, query: str, *, scope: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        return self.store.recall(query, scope=scope, limit=limit)

    def recall_compact(self, query: str, *, scope: str | None = None, limit: int = 5) -> list[dict[str, Any]]:
        memories = self.recall(query, scope=scope, limit=limit)
        return [
            {
                "memory_id": memory["memory_id"],
                "memory_type": memory["memory_type"],
                "subject": memory["subject"],
                "summary": memory["summary"],
                "confidence": memory["confidence"],
                "importance": memory["importance"],
                "source_ref": memory["source_ref"],
                "tags": memory["tags"],
            }
            for memory in memories
        ]

    def forget(self, memory_id: str) -> bool:
        return self.store.forget(memory_id)

    def close(self) -> None:
        close_method = getattr(self.store, "close", None)
        if callable(close_method):
            close_method()


__all__ = [
    "ReplayBundle",
    "RuntimeMessage",
    "RuntimeResponse",
    "RuntimeSession",
    "SessionManager",
    "TraceEnvelope",
    "MemoryManager",
]
