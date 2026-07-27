from __future__ import annotations

import hashlib
import uuid
from datetime import date, datetime, timezone

import pytest

from taxsentry.data_plane import HybridStore, PostgresAgentStore
from taxsentry.data_plane.queue import PostgresJobQueue
from taxsentry.store import JobStore, runtime_store


class _Step:
    def __init__(self, contains: str, rows=(), *, rowcount: int = 0):
        self.contains = contains
        self.rows = rows
        self.rowcount = rowcount


class _Script:
    def __init__(self, *steps: _Step):
        self.steps = list(steps)
        self.executed = []

    def connect(self):
        return _Connection(self)


class _Connection:
    def __init__(self, script: _Script):
        self.script = script

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return _Cursor(self.script)


class _Cursor:
    def __init__(self, script: _Script):
        self.script = script
        self.rows = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        if not self.script.steps:
            raise AssertionError(f"Unexpected SQL: {normalized}")
        step = self.script.steps.pop(0)
        assert step.contains in normalized
        self.script.executed.append((normalized, params))
        self.rows = list(step.rows(sql, params) if callable(step.rows) else step.rows)
        self.rowcount = step.rowcount
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)


def _store(script: _Script, company_id: str = "company-a") -> PostgresAgentStore:
    return PostgresAgentStore(
        PostgresJobQueue(connect=script.connect),
        company_id=company_id,
    )


def test_company_session_message_and_pin_are_strictly_scoped():
    session_uuid = uuid.uuid4()
    created = datetime(2026, 7, 27, tzinfo=timezone.utc)
    script = _Script(
        _Step("INSERT INTO taxsentry.companies"),
        _Step("INSERT INTO taxsentry.sessions"),
        _Step(
            "FROM taxsentry.sessions LEFT JOIN taxsentry.session_summaries",
            [
                {
                    "id": session_uuid,
                    "company_id": "company-a",
                    "provider": "codex",
                    "platform": "shared",
                    "summary": "",
                    "created_at": created,
                }
            ],
        ),
        _Step("SELECT id FROM taxsentry.sessions", [{"id": session_uuid}]),
        _Step("INSERT INTO taxsentry.messages"),
        _Step("UPDATE taxsentry.sessions SET updated_at"),
        _Step(
            "FROM taxsentry.messages JOIN taxsentry.sessions",
            [
                {
                    "id": uuid.uuid4(),
                    "role": "user",
                    "content": "hello",
                    "source": "terminal",
                    "trusted": True,
                    "pinned": False,
                    "expires_at": None,
                    "created_at": created,
                }
            ],
        ),
        _Step("UPDATE taxsentry.messages SET pinned", rowcount=1),
    )
    store = _store(script)

    session_id = store.create_session(
        "codex",
        platform="shared",
        company_id="company-a",
        system_prompt_hash="a" * 64,
    )
    assert uuid.UUID(session_id)
    assert store.session(str(session_uuid))["id"] == str(session_uuid)
    message_id = store.add_message(
        str(session_uuid),
        "user",
        "hello",
        company_id="company-a",
    )
    assert uuid.UUID(message_id)
    assert store.session_messages(str(session_uuid), limit=None)[0]["expires_at"] == ""
    assert store.pin_message(message_id, company_id="company-a")
    with pytest.raises(PermissionError):
        store.add_message(str(session_uuid), "user", "leak", company_id="company-b")
    assert not script.steps

    insert_message = next(
        params for sql, params in script.executed if "INSERT INTO taxsentry.messages" in sql
    )
    assert insert_message[2] == "company-a"
    assert insert_message[8] is not None


def test_session_updates_and_search_use_summary_table_and_company_filter():
    session_id = str(uuid.uuid4())
    script = _Script(
        _Step("INSERT INTO taxsentry.session_summaries"),
        _Step("UPDATE taxsentry.sessions SET updated_at"),
        _Step("SET system_prompt="),
        _Step("SET provider_thread_id="),
        _Step(
            "COALESCE(session_summaries.summary, '') AS summary",
            [
                {
                    "id": uuid.UUID(session_id),
                    "company_id": "company-a",
                    "summary": "Tax decision",
                    "message_count": 3,
                }
            ],
        ),
    )
    store = _store(script)

    store.update_session_summary(session_id, "Tax decision")
    store.update_session_prompt(session_id, "prompt", "b" * 64)
    store.set_session_provider_thread(session_id, "thread-1")
    rows = store.search_sessions("decision", company_id="company-a")

    assert rows[0]["id"] == session_id and rows[0]["message_count"] == 3
    with pytest.raises(PermissionError):
        store.search_sessions("decision", company_id="company-b")
    assert not script.steps
    assert all(
        "company_id=%s" in sql
        for sql, _ in script.executed
        if "UPDATE taxsentry.sessions" in sql
    )


def test_memory_lifecycle_removes_payload_and_keeps_hash_only_tombstone():
    memory_id = str(uuid.uuid4())
    deleted_hash = hashlib.sha256("remember this".encode()).hexdigest()

    def inserted(_sql, params):
        return [
            {
                "id": uuid.UUID(memory_id),
                "company_id": "company-a",
                "kind": "preference",
                "content": "remember this",
                "provenance": {"source": "terminal"},
                "sensitivity": "internal",
                "effective_date": date(2026, 7, 27),
                "revision": 1,
                "trusted": True,
                "pinned": False,
                "expires_at": params[9],
                "created_at": params[10],
                "updated_at": params[11],
            }
        ]

    memory_row = inserted(
        "",
        (None,) * 9 + ("2026-10-25T00:00:00+00:00", "", ""),
    )
    script = _Script(
        _Step("INSERT INTO taxsentry.companies"),
        _Step("SELECT pg_advisory_xact_lock"),
        _Step("SELECT * FROM taxsentry.memory_items", []),
        _Step("INSERT INTO taxsentry.memory_items", inserted),
        _Step("SELECT * FROM taxsentry.memory_items", memory_row),
        _Step("UPDATE taxsentry.memory_items SET pinned", rowcount=1),
        _Step("SELECT content FROM taxsentry.memory_items", [{"content": "remember this"}]),
        _Step("INSERT INTO taxsentry.memory_tombstones"),
        _Step("DELETE FROM taxsentry.memory_items"),
        _Step(
            "SELECT * FROM taxsentry.memory_tombstones",
            [
                {
                    "id": uuid.uuid4(),
                    "memory_id": uuid.UUID(memory_id),
                    "company_id": "company-a",
                    "content_hash": deleted_hash,
                    "reason": "user_request",
                    "deleted_at": datetime(2026, 7, 27, tzinfo=timezone.utc),
                }
            ],
        ),
        _Step(
            "SELECT company_id FROM taxsentry.memory_items",
            [
                {"company_id": "company-a"},
                {"company_id": "__global__"},
                {"company_id": "company-b"},
            ],
        ),
    )
    store = _store(script)

    saved = store.save_memory(
        "remember this",
        company_id="company-a",
        kind="preference",
        provenance='{"source":"terminal"}',
        sensitivity="internal",
        effective_date="2026-07-27",
    )
    assert saved["id"] == memory_id
    assert saved["provenance"] == '{"source": "terminal"}'
    assert store.memory_items(company_id="company-a", query="remember")[0]["id"] == memory_id
    assert store.pin_memory(memory_id, company_id="company-a")
    assert store.forget_memory(memory_id, company_id="company-a")
    assert store.memory_tombstone(memory_id)["content_hash"] == deleted_hash
    assert store.memory_scopes() == {"company-a", "__global__"}
    with pytest.raises(PermissionError):
        store.memory_items(company_id="company-b")
    assert not script.steps

    tombstone_params = next(
        params
        for sql, params in script.executed
        if "INSERT INTO taxsentry.memory_tombstones" in sql
    )
    assert tombstone_params[3] == deleted_hash
    assert "remember this" not in tombstone_params
    assert script.executed[1][1] == (
        '["company-a","preference","remember this"]',
    )


def test_memory_update_increments_revision_and_clears_stale_embedding():
    memory_id = str(uuid.uuid4())
    script = _Script(
        _Step("INSERT INTO taxsentry.companies"),
        _Step(
            "SELECT * FROM taxsentry.memory_items",
            [{"id": memory_id, "revision": 1, "pinned": False}],
        ),
        _Step(
            "UPDATE taxsentry.memory_items",
            [
                {
                    "id": uuid.UUID(memory_id),
                    "company_id": "company-a",
                    "kind": "decision",
                    "content": "updated",
                    "provenance": "user",
                    "sensitivity": "internal",
                    "effective_date": None,
                    "revision": 2,
                    "trusted": True,
                    "pinned": False,
                    "expires_at": None,
                }
            ],
        ),
    )
    store = _store(script)

    updated = store.save_memory(
        "updated",
        company_id="company-a",
        kind="decision",
        provenance="user",
        sensitivity="internal",
        memory_id=memory_id,
    )

    update_sql, update_params = script.executed[-1]
    assert "embedding=NULL" in update_sql
    assert update_params[5] == 2
    assert updated["revision"] == 2


def test_retention_purges_only_scoped_unpinned_rows():
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    cutoff = "2026-07-27T00:00:00+00:00"
    script = _Script(
        _Step(
            "FROM taxsentry.memory_items",
            [
                {"id": first, "company_id": "company-a", "content": "alpha"},
                {"id": second, "company_id": "__global__", "content": "global"},
            ],
        ),
        _Step("INSERT INTO taxsentry.memory_tombstones"),
        _Step("DELETE FROM taxsentry.memory_items"),
        _Step("INSERT INTO taxsentry.memory_tombstones"),
        _Step("DELETE FROM taxsentry.memory_items"),
        _Step("DELETE FROM taxsentry.messages", rowcount=3),
    )
    store = _store(script)

    assert store.purge_expired(now=cutoff) == {"memory": 2, "messages": 3}
    assert not script.steps
    select_sql, select_params = script.executed[0]
    assert "NOT pinned" in select_sql
    assert select_params == ("company-a", "__global__", cutoff)
    assert all(
        raw not in params
        for raw in ("alpha", "global")
        for sql, params in script.executed
        if "INSERT INTO taxsentry.memory_tombstones" in sql
    )


def test_company_upsert_normalizes_postgres_values_and_rejects_cross_company():
    script = _Script(
        _Step(
            "INSERT INTO taxsentry.companies",
            [
                {
                    "id": "company-a",
                    "name": "Company A",
                    "country_code": "VN",
                    "currency": "VND",
                    "profile": {"industry": "software"},
                    "created_at": datetime(2026, 7, 27, tzinfo=timezone.utc),
                }
            ],
        )
    )
    store = _store(script)

    company = store.upsert_company(
        name="Company A",
        profile={"industry": "software"},
    )
    assert company["id"] == "company-a"
    assert company["created_at"].startswith("2026-07-27")
    with pytest.raises(PermissionError):
        store.upsert_company("company-b")


def test_hybrid_store_routes_agent_state_and_keeps_legacy_workflow_local():
    calls = []

    class Local:
        def event(self, *args):
            calls.append(("local", args))

        def close(self):
            calls.append(("local-close",))

    class Agent:
        def session(self, session_id):
            calls.append(("agent", session_id))
            return {"id": session_id}

        def close(self):
            calls.append(("agent-close",))

    store = HybridStore(Local(), Agent())

    assert store.session("session-1") == {"id": "session-1"}
    store.event(None, "chat_source", {})
    store.close()
    assert calls == [
        ("agent", "session-1"),
        ("local", (None, "chat_source", {})),
        ("agent-close",),
        ("local-close",),
    ]


def test_runtime_store_selects_postgres_agent_state_when_enabled(
    monkeypatch,
    tmp_path,
):
    calls = []

    class Queue:
        def ensure_schema(self):
            calls.append("schema")

    class Agent:
        def __init__(self, queue, *, company_id, retention_days):
            calls.append(("agent", queue, company_id, retention_days))

        def upsert_company(self, **profile):
            calls.append(("company", profile))

        def close(self):
            calls.append("agent-close")

    queue = Queue()
    monkeypatch.delenv("TAXSENTRY_POSTGRES_DSN", raising=False)
    monkeypatch.setattr(
        "taxsentry.data_plane.job_queue_from_settings",
        lambda settings: queue,
    )
    monkeypatch.setattr("taxsentry.data_plane.PostgresAgentStore", Agent)
    settings = {
        "agent": {"company_id": "company-a"},
        "advisor": {
            "company": {
                "id": "company-a",
                "name": "Company A",
                "country_code": "VN",
                "currency": "VND",
            }
        },
        "data_plane": {"enabled": True},
        "memory": {"retention_days": 45},
    }

    store = runtime_store(settings, path=tmp_path / "local.db")

    assert isinstance(store, HybridStore)
    assert isinstance(store.local_store, JobStore)
    assert calls[0] == "schema"
    assert calls[1][2:] == ("company-a", 45)
    assert calls[2][1]["name"] == "Company A"
    store.close()
