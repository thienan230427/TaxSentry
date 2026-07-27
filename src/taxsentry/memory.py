from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import APP_HOME
from .prompt import safe_company_id
from .security import contains_secret, redact_secrets
from .store import JobStore

GLOBAL_MEMORY_SCOPE = "__global__"
_TRUSTED_SOURCES = {"terminal", "telegram", "user", "system"}
_SENSITIVITY = {"public", "internal", "confidential", "restricted"}
_REMEMBER = re.compile(
    r"^\s*(?:hãy\s+nhớ|ghi\s+nhớ|remember|quy\s+ước|sở\s+thích)\s*:?\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)
_AUTO_MEMORY = (
    (
        "preference",
        re.compile(
            r"^\s*(?:sở\s+thích|(?:tôi|mình|chúng\s+ta|công\s+ty)\s+"
            r"(?:thích|ưu\s+tiên)|i\s+prefer)\s*:?\s*(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "decision",
        re.compile(
            r"^\s*(?:quyết\s+định|đã\s+chốt|chúng\s+ta\s+chốt|we\s+decided)"
            r"\s*:?\s*(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "convention",
        re.compile(
            r"^\s*(?:quy\s+ước|convention)\s*:?\s*(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
    (
        "lesson",
        re.compile(
            r"^\s*(?:bài\s+học|rút\s+kinh\s+nghiệm|lesson\s+learned)"
            r"\s*:?\s*(.+)$",
            re.IGNORECASE | re.DOTALL,
        ),
    ),
)


def trusted_source(source: str) -> bool:
    return source.strip().lower().split(":", 1)[0] in _TRUSTED_SOURCES


class MemoryService:
    """Curated memory with strict scope, provenance, retention, and deletion."""

    def __init__(
        self,
        store: JobStore,
        settings: Mapping[str, Any] | None = None,
        *,
        home: Path | None = None,
    ):
        self.store = store
        self.settings = settings or {}
        paths = self.settings.get("paths", {}) if isinstance(self.settings.get("paths"), Mapping) else {}
        self.home = Path(home or paths.get("home") or APP_HOME)
        memory = self.settings.get("memory", {})
        self.retention_days = int(memory.get("retention_days", 90)) if isinstance(memory, Mapping) else 90
        self.max_facts = int(memory.get("max_facts", 50)) if isinstance(memory, Mapping) else 50

    def remember(
        self,
        content: str,
        *,
        company_id: str = "default",
        kind: str = "fact",
        provenance: str | Mapping[str, Any] = "user",
        sensitivity: str = "internal",
        effective_date: str = "",
        pinned: bool = False,
        trusted: bool = True,
        memory_id: str | None = None,
    ) -> dict[str, Any]:
        content = " ".join(content.split()).strip()
        if not content:
            raise ValueError("Memory content cannot be empty")
        if not trusted:
            raise ValueError("Untrusted content cannot become curated memory")
        if contains_secret(content):
            raise ValueError("Secret-like content cannot become curated memory")
        if sensitivity not in _SENSITIVITY:
            raise ValueError(f"Unknown sensitivity: {sensitivity}")
        company_id = GLOBAL_MEMORY_SCOPE if company_id == GLOBAL_MEMORY_SCOPE else safe_company_id(company_id)
        provenance_text = (
            json.dumps(provenance, ensure_ascii=False, sort_keys=True)
            if isinstance(provenance, Mapping)
            else str(provenance)
        )
        provenance_text = redact_secrets(provenance_text)
        item = self.store.save_memory(
            content,
            company_id=company_id,
            kind=kind.strip() or "fact",
            provenance=provenance_text,
            sensitivity=sensitivity,
            effective_date=effective_date or date.today().isoformat(),
            trusted=True,
            pinned=pinned,
            expires_at="" if pinned else self._expires_at(),
            memory_id=memory_id,
        )
        self._write_snapshot(company_id)
        return item

    def record_turn(
        self,
        user_text: str,
        assistant_text: str = "",
        *,
        company_id: str = "default",
        source: str = "terminal",
    ) -> dict[str, Any] | None:
        del assistant_text  # Full turns are archived separately; only explicit user facts become curated memory.
        if not trusted_source(source) or contains_secret(user_text):
            return None
        if user_text.rstrip().endswith("?"):
            return None
        for kind, pattern in _AUTO_MEMORY:
            automatic = pattern.match(user_text)
            if automatic:
                return self.remember(
                    automatic.group(1),
                    company_id=company_id,
                    kind=kind,
                    provenance={
                        "source": source,
                        "type": "confirmed_user_statement",
                    },
                    trusted=True,
                )
        match = _REMEMBER.match(user_text)
        if not match:
            return None
        return self.remember(
            match.group(1),
            company_id=company_id,
            provenance={"source": source, "type": "explicit_user_memory"},
            trusted=True,
        )

    def search(
        self,
        query: str = "",
        *,
        company_id: str = "default",
        limit: int | None = None,
        include_global: bool = True,
    ) -> list[dict[str, Any]]:
        company_id = GLOBAL_MEMORY_SCOPE if company_id == GLOBAL_MEMORY_SCOPE else safe_company_id(company_id)
        return self.store.memory_items(
            company_id=company_id,
            query=query,
            limit=limit or self.max_facts,
            include_global=include_global,
        )

    def forget(self, memory_id: str, *, company_id: str = "default", reason: str = "user_request") -> bool:
        company_id = GLOBAL_MEMORY_SCOPE if company_id == GLOBAL_MEMORY_SCOPE else safe_company_id(company_id)
        forgotten = self.store.forget_memory(memory_id, company_id=company_id, reason=reason)
        if forgotten:
            self._write_snapshot(company_id, remove_stale_on_error=True)
        return forgotten

    def pin(self, memory_id: str, *, company_id: str = "default", pinned: bool = True) -> bool:
        company_id = GLOBAL_MEMORY_SCOPE if company_id == GLOBAL_MEMORY_SCOPE else safe_company_id(company_id)
        changed = self.store.pin_memory(
            memory_id,
            company_id=company_id,
            pinned=pinned,
            expires_at="" if pinned else self._expires_at(),
        )
        if changed:
            self._write_snapshot(company_id)
        return changed

    def purge_expired(self, *, now: str | None = None) -> dict[str, int]:
        result = self.store.purge_expired(now=now)
        if result["memory"]:
            self._write_all_snapshots()
        return result

    def _expires_at(self) -> str:
        return (datetime.now(timezone.utc) + timedelta(days=self.retention_days)).isoformat()

    def _snapshot_path(self, company_id: str) -> Path:
        if company_id == GLOBAL_MEMORY_SCOPE:
            return self.home / "MEMORY.md"
        return self.home / "companies" / safe_company_id(company_id) / "MEMORY.md"

    def _write_snapshot(self, company_id: str, *, remove_stale_on_error: bool = False) -> None:
        items = self.store.memory_items(
            company_id=company_id,
            limit=self.max_facts,
            include_global=False,
        )
        title = "Bộ nhớ đã tuyển chọn" if company_id == GLOBAL_MEMORY_SCOPE else f"Bộ nhớ doanh nghiệp: {company_id}"
        lines = [f"# {title}", "", "<!-- Generated from the memory database. -->", ""]
        for item in reversed(items):
            lines.append(
                f"- [{item['kind']}] {item['content']} "
                f"_(nguồn: {item['provenance']}; hiệu lực: {item['effective_date']}; "
                f"revision: {item['revision']})_"
            )
        if not items:
            lines.append("Chưa có mục bộ nhớ nào.")
        path = self._snapshot_path(company_id)
        temp = path.with_suffix(".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
            os.replace(temp, path)
        except OSError:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass
            if remove_stale_on_error:
                try:
                    path.unlink(missing_ok=True)
                except OSError as unlink_error:
                    raise RuntimeError("Memory was forgotten, but its stale Markdown snapshot could not be removed") from unlink_error
            # The database remains authoritative when an installation is read-only.

    def _write_all_snapshots(self) -> None:
        for company_id in self.store.memory_scopes() | {GLOBAL_MEMORY_SCOPE}:
            self._write_snapshot(company_id)


class SessionService:
    def __init__(self, store: JobStore):
        self.store = store

    def resume(self, session_id: str, *, company_id: str = "default") -> dict[str, Any]:
        company_id = safe_company_id(company_id)
        session = self.store.session(session_id)
        if not session:
            raise KeyError(session_id)
        if session["company_id"] != company_id:
            raise PermissionError("Session belongs to another company")
        return {**session, "messages": self.store.session_messages(session_id, limit=None)}

    def search(self, query: str, *, company_id: str = "default", limit: int = 20) -> list[dict[str, Any]]:
        return self.store.search_sessions(query, company_id=safe_company_id(company_id), limit=limit)

    def pin_message(
        self,
        message_id: str,
        *,
        company_id: str = "default",
        pinned: bool = True,
        retention_days: int = 90,
    ) -> bool:
        company_id = safe_company_id(company_id)
        expires_at = (
            ""
            if pinned
            else (datetime.now(timezone.utc) + timedelta(days=retention_days)).isoformat()
        )
        return self.store.pin_message(
            message_id,
            company_id=company_id,
            pinned=pinned,
            expires_at=expires_at,
        )
