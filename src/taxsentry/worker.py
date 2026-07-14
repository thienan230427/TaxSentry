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


async def run_worker(*, once: bool = False, stop: asyncio.Event | None = None, notify: Callable[[str], None] | None = None) -> int:
    settings, stop = load_config(), stop or asyncio.Event()
    console = Console()
    if not settings.get("gmail", {}).get("enabled", True):
        console.print("[red]Gmail đang tắt / Gmail is disabled. Chạy `taxsentry setup` và chọn Full Agent hoặc Email Agent.[/]")
        return 2
    if settings["gmail"].get("process_after_uid") is None:
        settings["gmail"]["process_after_uid"] = GmailClient(settings).latest_uid()
        save_config(settings)
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    workflow = TaxSentryWorkflow(settings)
    try:
        with single_instance():
            while not stop.is_set():
                completed = await workflow.run_once()
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
        await workflow.close()
    return 0
