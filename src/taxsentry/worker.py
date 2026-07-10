from __future__ import annotations

import asyncio
import os
import signal
from contextlib import contextmanager
from pathlib import Path

from rich.console import Console

from .config import RUNTIME_DIR, load_config
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


async def run_worker(*, once: bool = False) -> int:
    settings, stop = load_config(), asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    workflow, console = TaxSentryWorkflow(settings), Console()
    with single_instance():
        while not stop.is_set():
            completed = await workflow.run_once()
            console.print(f"[cyan]TaxSentry worker:[/] hoàn tất {completed} báo cáo")
            if once:
                return 0
            try:
                await asyncio.wait_for(stop.wait(), timeout=max(10, int(settings["worker"]["poll_seconds"])))
            except asyncio.TimeoutError:
                pass
    return 0
