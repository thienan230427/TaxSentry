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


async def run_worker(*, once: bool = False, gateway: bool = False) -> int:
    settings, stop = load_config(), asyncio.Event()
    console = Console()
    if not settings.get("gmail", {}).get("enabled", True):
        console.print("[red]Gmail đang tắt / Gmail is disabled. Chạy `taxsentry setup` và chọn Full Agent hoặc Email Agent.[/]")
        return 2
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, RuntimeError):
            pass
    workflow, gateway_task = TaxSentryWorkflow(settings), None
    if gateway and settings.get("telegram", {}).get("enabled") and not once:
        from .bot.telegram_bot import serve

        gateway_task = asyncio.create_task(serve(stop))
    try:
        with single_instance():
            while not stop.is_set():
                if gateway_task and gateway_task.done():
                    gateway_task.result()
                completed = await workflow.run_once()
                console.print(f"[cyan]TaxSentry worker:[/] hoàn tất {completed} báo cáo")
                if once:
                    return 0
                try:
                    await asyncio.wait_for(stop.wait(), timeout=max(10, int(settings["worker"]["poll_seconds"])))
                except asyncio.TimeoutError:
                    pass
    finally:
        stop.set()
        if gateway_task:
            await gateway_task
    return 0
