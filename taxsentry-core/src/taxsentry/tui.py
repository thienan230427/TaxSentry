from __future__ import annotations

import argparse

from .app import run_dashboard, run_doctor, run_jobs, run_memory_add, run_memory_list, run_replay, run_status, run_tui


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="taxsentry")
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("tui", help="Launch the interactive agent cockpit")
    subparsers.add_parser("dashboard", help="Open the operational dashboard")
    subparsers.add_parser("status", help="Show current configuration and provider health")
    subparsers.add_parser("doctor", help="Check runtime health")
    subparsers.add_parser("jobs", help="Show recent jobs and their states")
    replay_parser = subparsers.add_parser("replay", help="Replay a session trace")
    replay_parser.add_argument("session_id", nargs="?", help="Replay a specific session id")
    memory_parser = subparsers.add_parser("memory", help="Inspect or add memory facts")
    memory_sub = memory_parser.add_subparsers(dest="memory_command")
    memory_sub.add_parser("list", help="List recent memory facts")
    add_parser = memory_sub.add_parser("add", help="Add a memory fact")
    add_parser.add_argument("text", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)

    if args.command in {None, "tui"}:
        return run_tui()
    if args.command == "dashboard":
        return run_dashboard()
    if args.command == "status":
        return run_status()
    if args.command == "doctor":
        return run_doctor()
    if args.command == "jobs":
        return run_jobs()
    if args.command == "replay":
        return run_replay(args.session_id)
    if args.command == "memory":
        if args.memory_command == "list":
            return run_memory_list()
        if args.memory_command == "add":
            return run_memory_add(" ".join(args.text).strip())
        parser.error("memory requires list or add")
    parser.error("Unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
