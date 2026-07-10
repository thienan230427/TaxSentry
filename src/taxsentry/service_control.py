from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

from .config import APP_HOME, LOGS_DIR

NAME = "taxsentry-worker"


def artifact() -> tuple[Path, str]:
    python, system = Path(sys.executable), platform.system()
    if system == "Windows":
        path = APP_HOME / "service" / f"{NAME}.cmd"
        return path, f'@echo off\r\n"{python}" -m taxsentry worker run >> "{LOGS_DIR / "worker.log"}" 2>&1\r\n'
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / "ai.taxsentry.worker.plist"
        return path, f'''<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd"><plist version="1.0"><dict><key>Label</key><string>ai.taxsentry.worker</string><key>ProgramArguments</key><array><string>{python}</string><string>-m</string><string>taxsentry</string><string>worker</string><string>run</string></array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/></dict></plist>'''
    path = Path.home() / ".config" / "systemd" / "user" / f"{NAME}.service"
    return path, f"[Unit]\nDescription=TaxSentry Worker\n[Service]\nExecStart={python} -m taxsentry worker run\nRestart=on-failure\n[Install]\nWantedBy=default.target\n"


def service(action: str) -> str:
    path, content = artifact()
    system = platform.system()
    if action == "install":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if system == "Windows":
            subprocess.run(["schtasks", "/Create", "/F", "/SC", "ONLOGON", "/TN", NAME, "/TR", str(path)], check=True)
        elif system == "Darwin":
            subprocess.run(["launchctl", "load", str(path)], check=True)
        else:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "--user", "enable", "--now", NAME], check=True)
        return f"Installed: {path}"
    if action in {"start", "stop"}:
        command = ["schtasks", f"/{'Run' if action == 'start' else 'End'}", "/TN", NAME] if system == "Windows" else (["launchctl", action, "ai.taxsentry.worker"] if system == "Darwin" else ["systemctl", "--user", action, NAME])
        subprocess.run(command, check=True)
        return f"{action}: ok"
    if action == "remove":
        if system == "Windows": subprocess.run(["schtasks", "/Delete", "/F", "/TN", NAME], check=False)
        elif system == "Darwin": subprocess.run(["launchctl", "unload", str(path)], check=False)
        else: subprocess.run(["systemctl", "--user", "disable", "--now", NAME], check=False)
        path.unlink(missing_ok=True)
        return "removed"
    if action == "logs":
        log = LOGS_DIR / "worker.log"
        return log.read_text(encoding="utf-8")[-10000:] if log.exists() else "No logs."
    return f"artifact={'present' if path.exists() else 'missing'}: {path}"
