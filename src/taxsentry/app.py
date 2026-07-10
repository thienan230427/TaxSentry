from __future__ import annotations

import asyncio

from .cockpit import Cockpit


def run_tui() -> int:
    return asyncio.run(Cockpit().run())


def run_status() -> int:
    from .tui import main

    return main(["status"])


def run_doctor() -> int:
    from .tui import doctor

    return doctor()


def run_jobs(limit: int = 10) -> int:
    del limit
    from .tui import jobs

    return jobs()


def run_replay(session_id=None) -> int:
    del session_id
    return 0


def run_memory_list() -> int:
    return 0


def run_memory_add(text: str) -> int:
    return int(not bool(text))


def run_dashboard() -> int:
    return run_status()
