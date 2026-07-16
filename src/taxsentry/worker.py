from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console

from .config import RUNTIME_DIR, load_config, save_config
from .gmail import GmailClient
from .workflow import TaxSentryWorkflow


@contextmanager
def single_instance(path: Path = RUNTIME_DIR / "worker.lock"):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = path.open("a+")
    try:
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("TaxSentry worker is already running") from exc
        else:
            import fcntl
            try:
                fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("TaxSentry worker is already running") from exc
        yield
    finally:
        file.close()


async def run_worker(
    *,
    once: bool = False,
    stop: asyncio.Event | None = None,
    notify: Callable[[str], None] | None = None,
    workflow: TaxSentryWorkflow | None = None,
    settings: dict | None = None,
) -> int:
    settings, stop = settings or load_config(), stop or asyncio.Event()
    console = Console()
    if not settings.get("gmail", {}).get("enabled", True):
        console.print("[red]Gmail đang tắt / Gmail is disabled. Chạy `taxsentry setup` và chọn Full Agent hoặc Email Agent.[/]")
        return 2
    gmail = workflow.gmail if workflow else GmailClient(settings)
    if not settings["gmail"].get("process_after_uids"):
        latest = gmail.latest_uids if hasattr(gmail, "latest_uids") else lambda: {"INBOX": gmail.latest_uid()}
        settings["gmail"]["process_after_uids"] = await asyncio.wait_for(
            asyncio.to_thread(latest),
            timeout=float(settings["worker"].get("imap_timeout_seconds", 30)),
        )
        settings["gmail"]["process_after_uid"] = None
        save_config(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    owns_workflow = workflow is None
    workflow = workflow or TaxSentryWorkflow(settings, gmail=gmail)
    try:
        with single_instance():
            while not stop.is_set():
                completed = await workflow.run_once()
                save_config(settings)
                if completed:
                    message = f"Worker hoàn tất {completed} báo cáo"
                    notify(message) if notify else console.print(f"[cyan]TaxSentry:[/] {message}")
                if once:
                    return 0
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(10, int(settings["worker"]["poll_seconds"])))
                except asyncio.TimeoutError:
                    pass
    finally:
        stop.set()
        if owns_workflow:
            await workflow.close()
    return 0
