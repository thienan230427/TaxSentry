from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

APP_HOME = Path(os.getenv("TAXSENTRY_HOME", Path.home() / ".taxsentry"))
CONFIG_FILE = Path(os.getenv("TAXSENTRY_CONFIG_FILE", APP_HOME / "config.json"))
MEMORY_DB = Path(os.getenv("TAXSENTRY_MEMORY_DB", APP_HOME / "taxsentry.db"))
SESSION_FILE = APP_HOME / "sessions.jsonl"
LOGS_DIR, RUNTIME_DIR, DOWNLOAD_DIR = APP_HOME / "logs", APP_HOME / "run", APP_HOME / "downloads"

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": "2.0.0", "configured": False,
    "agent": {"name": "TaxSentry", "persona": "precise and practical", "language": "vi", "memory_enabled": True},
    "provider": {"kind": "lmstudio", "model": "", "lmstudio_base_url": "http://127.0.0.1:1234/v1", "base_url": "http://127.0.0.1:1234/v1", "api_key": "", "auth_mode": "lmstudio"},
    "gmail": {"account": "", "oauth_client_file": "", "trusted_senders": []},
    "director": {"email": "", "telegram_chat_ids": []},
    "telegram": {"enabled": False},
    "worker": {"poll_seconds": 60, "max_retries": 3, "max_attachment_mb": 25, "gateway": True},
    "update": {"source": "git+https://github.com/thienan230427/TaxSentry.git"},
    "report": {"language": "vi", "minimum_confidence": 0.70},
    "ocr": {"languages": ["vie", "eng"], "minimum_confidence": 70.0},
    "memory": {"max_facts": 50, "max_turns": 12, "session_title": "TaxSentry session"},
    "jobs": {"tracking_enabled": True, "retry_limit": 3, "default_state": "queued", "needs_human_review_on_missing_data": True, "auto_send_email": True, "auto_send_telegram": True},
    "integrations": {"telegram": {"enabled": False, "bot_token": "", "admin_chat_id": ""}},
    "ui": {"theme": "ocean", "show_banner": True}, "extra_env": {},
}


def ensure_directories() -> None:
    for path in (APP_HOME, LOGS_DIR, RUNTIME_DIR, DOWNLOAD_DIR):
        path.mkdir(parents=True, exist_ok=True)


def backup_v1_profile() -> Path | None:
    if not CONFIG_FILE.exists():
        return None
    try:
        current = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        current = {}
    if str(current.get("version", "")).startswith("2."):
        return None
    backup = APP_HOME.with_name(f"{APP_HOME.name}-v1-backup-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}")
    shutil.move(str(APP_HOME), str(backup))
    ensure_directories()
    return backup


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        result[key] = _merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else value
    return result


def get_empty_config() -> dict[str, Any]:
    config = deepcopy(DEFAULT_SETTINGS)
    config["paths"] = {"home": str(APP_HOME), "config": str(CONFIG_FILE), "memory_db": str(MEMORY_DB), "session_file": str(SESSION_FILE)}
    return config


def load_config() -> dict[str, Any]:
    ensure_directories()
    if not CONFIG_FILE.exists():
        return get_empty_config()
    try:
        loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        return _merge(get_empty_config(), loaded if isinstance(loaded, dict) else {})
    except (OSError, json.JSONDecodeError):
        return get_empty_config()


def save_config(config: dict[str, Any]) -> None:
    ensure_directories()
    payload = deepcopy(config)
    payload["version"] = "2.0.0"
    payload.get("provider", {}).pop("api_key", None)
    payload.get("integrations", {}).get("telegram", {}).pop("bot_token", None)
    temp = CONFIG_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, CONFIG_FILE)


def get_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    value: Any = config
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return default
        value = value[part]
    return value


def set_value(config: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    cursor, parts = config, path.split(".")
    for part in parts[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[parts[-1]] = value
    return config


def write_env_file(config: dict[str, Any]) -> Path:
    path = APP_HOME / ".env"
    path.write_text(f'TAXSENTRY_HOME="{APP_HOME}"\n', encoding="utf-8")
    return path


def describe_config(config: dict[str, Any]) -> str:
    provider = config["provider"]
    return "\n".join((f"TaxSentry {config.get('version', '2.0.0')}", f"Provider: {provider['kind']} / {provider.get('model') or 'default'}", f"Gmail: {config['gmail'].get('account') or 'not connected'}", f"Telegram: {'enabled' if config['telegram'].get('enabled') else 'disabled'}", f"Trusted senders: {len(config['gmail'].get('trusted_senders', []))}", f"Config: {CONFIG_FILE}"))


def build_env_lines(config: dict[str, Any]) -> list[str]:
    return [f'TAXSENTRY_HOME="{APP_HOME}"']


def load_env_snapshot() -> dict[str, str]:
    return {}
