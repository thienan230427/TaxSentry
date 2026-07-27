from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import signal
import socket
import threading
import uuid
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote, urlencode

from .queue import LostLeaseError, PostgresJobQueue


@dataclass(slots=True)
class JobContext:
    queue: PostgresJobQueue
    job: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.job["id"])

    @property
    def lease_token(self) -> str:
        return str(self.job["lease_token"])

    def checkpoint(
        self,
        step: str,
        value: Mapping[str, Any],
        *,
        processed: int = 0,
        total: int | None = None,
        state: str = "running",
    ) -> dict[str, Any]:
        return self.queue.checkpoint(
            self.id,
            self.lease_token,
            step,
            value,
            processed=processed,
            total=total,
            state=state,
        )

    def cancelled(self) -> bool:
        return self.queue.cancel_requested(self.id)

    def steps(self) -> list[dict[str, Any]]:
        return self.queue.steps(self.id)

    def persist_document(
        self,
        manifest: Mapping[str, Any],
        units: Iterable[Mapping[str, Any]],
        *,
        raw_object_key: str,
        units_object_key: str,
        mime_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        return self.queue.persist_document(
            manifest,
            units,
            raw_object_key=raw_object_key,
            units_object_key=units_object_key,
            mime_type=mime_type,
        )


class LeaseWorker:
    def __init__(
        self,
        queue: PostgresJobQueue,
        handler: Callable[[JobContext], Mapping[str, Any] | None],
        *,
        worker_id: str | None = None,
        lease_seconds: int = 60,
        poll_seconds: float = 2.0,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        if lease_seconds < 5:
            raise ValueError("lease_seconds must be at least 5")
        if poll_seconds < 0:
            raise ValueError("poll_seconds cannot be negative")
        self.queue = queue
        self.handler = handler
        self.worker_id = worker_id or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.on_error = on_error

    def run_once(self) -> bool:
        job = self.queue.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return False
        context = JobContext(self.queue, job)
        heartbeat = _Heartbeat(
            self.queue,
            context.id,
            context.lease_token,
            self.lease_seconds,
        )
        try:
            with heartbeat:
                result = self.handler(context)
                if inspect.isawaitable(result):
                    result = asyncio.run(result)
            heartbeat.raise_if_failed()
            if context.cancelled():
                return True
            if result is not None and not isinstance(result, Mapping):
                raise TypeError("Job handler must return a mapping or None")
            self.queue.complete(context.id, context.lease_token, result or {})
        except LostLeaseError:
            return True
        except Exception as exc:
            try:
                # Store the exception type only: handler messages can contain customer data or secrets.
                self.queue.fail(
                    context.id,
                    context.lease_token,
                    f"HandlerError:{type(exc).__name__}",
                    retryable=True,
                )
            except LostLeaseError:
                pass
            if self.on_error:
                self.on_error(exc)
        return True

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            worked = self.run_once()
            if not worked:
                stop.wait(self.poll_seconds)


class _Heartbeat:
    def __init__(
        self,
        queue: PostgresJobQueue,
        job_id: str,
        lease_token: str,
        lease_seconds: int,
    ) -> None:
        self.queue = queue
        self.job_id = job_id
        self.lease_token = lease_token
        self.lease_seconds = lease_seconds
        self.stop = threading.Event()
        self.error: Exception | None = None
        self.thread = threading.Thread(target=self._run, name=f"lease-{job_id[:8]}", daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=min(5, self.lease_seconds))

    def _run(self) -> None:
        interval = max(1.0, self.lease_seconds / 3)
        while not self.stop.wait(interval):
            try:
                if not self.queue.heartbeat(
                    self.job_id,
                    self.lease_token,
                    lease_seconds=self.lease_seconds,
                ):
                    raise LostLeaseError(f"Lease lost for job {self.job_id}")
            except Exception as exc:
                self.error = exc
                self.stop.set()

    def raise_if_failed(self) -> None:
        if self.error:
            raise self.error


def load_handler(path: str) -> Callable[[JobContext], Mapping[str, Any] | None]:
    try:
        module_name, attribute = path.rsplit(":", 1)
    except ValueError as exc:
        raise ValueError("TAXSENTRY_JOB_HANDLER must use module:function syntax") from exc
    if not module_name or not attribute:
        raise ValueError("TAXSENTRY_JOB_HANDLER must use module:function syntax")
    handler = getattr(importlib.import_module(module_name), attribute)
    if not callable(handler):
        raise TypeError(f"Configured job handler is not callable: {path}")
    return handler


def main() -> int:
    dsn = os.environ.get("TAXSENTRY_POSTGRES_DSN", "").strip() or _postgres_dsn_from_env()
    handler_path = os.environ.get("TAXSENTRY_JOB_HANDLER", "").strip()
    if not dsn:
        raise SystemExit("TAXSENTRY_POSTGRES_DSN is required")
    if not handler_path:
        raise SystemExit("TAXSENTRY_JOB_HANDLER is required; worker will not consume jobs without a handler")
    queue = PostgresJobQueue(dsn)
    queue.ensure_schema()
    worker = LeaseWorker(
        queue,
        load_handler(handler_path),
        worker_id=os.environ.get("TAXSENTRY_WORKER_ID") or None,
        lease_seconds=int(os.environ.get("TAXSENTRY_LEASE_SECONDS", "60")),
        poll_seconds=float(os.environ.get("TAXSENTRY_POLL_SECONDS", "2")),
        on_error=lambda exc: print(f"job handler failed: {type(exc).__name__}", flush=True),
    )
    stop = threading.Event()
    for signal_name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signal_name, lambda *_: stop.set())
    worker.run_forever(stop)
    return 0


def _postgres_dsn_from_env() -> str:
    password = os.environ.get("TAXSENTRY_POSTGRES_PASSWORD", "")
    if not password:
        return ""
    user = os.environ.get("TAXSENTRY_POSTGRES_USER", "taxsentry")
    host = os.environ.get("TAXSENTRY_POSTGRES_HOST", "localhost")
    port = os.environ.get("TAXSENTRY_POSTGRES_PORT", "5432")
    database = os.environ.get("TAXSENTRY_POSTGRES_DB", "taxsentry")
    query = urlencode({"sslmode": os.environ.get("TAXSENTRY_POSTGRES_SSLMODE", "require")})
    return (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}"
        f"@{host}:{port}/{quote(database, safe='')}?{query}"
    )


if __name__ == "__main__":
    raise SystemExit(main())
