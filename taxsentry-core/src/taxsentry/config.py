from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

APP_NAME = "taxsentry"
APP_HOME = Path(os.getenv("TAXSENTRY_HOME", Path.home() / ".taxsentry"))
CONFIG_DIR = Path(os.getenv("TAXSENTRY_CONFIG_DIR", APP_HOME / "config"))
MEMORY_DIR = Path(os.getenv("TAXSENTRY_MEMORY_DIR", APP_HOME / "memory"))
RUNTIME_DIR = Path(os.getenv("TAXSENTRY_RUNTIME_DIR", APP_HOME / "run"))
LOGS_DIR = Path(os.getenv("TAXSENTRY_LOGS_DIR", APP_HOME / "logs"))
CORE_DIR = Path(os.getenv("TAXSENTRY_CORE_DIR", APP_HOME / "taxsentry-core"))
CONFIG_FILE = Path(os.getenv("TAXSENTRY_CONFIG_FILE", CONFIG_DIR / "config.json"))
ENV_FILE = Path(os.getenv("TAXSENTRY_ENV_FILE", CORE_DIR / ".env"))
MEMORY_DB = Path(os.getenv("TAXSENTRY_MEMORY_DB", MEMORY_DIR / "memory.db"))
SESSION_FILE = Path(os.getenv("TAXSENTRY_SESSION_FILE", MEMORY_DIR / "sessions.jsonl"))

DEFAULT_SETTINGS: dict[str, Any] = {
    "version": "1.1.6",
    "configured": False,
    "agent": {
        "name": "TaxSentry",
        "persona": "warm, precise, and practical",
        "language": "vi",
        "memory_enabled": True,
        "llm_planner_enabled": False,
        "welcome_message": "Chào Sếp, em là TaxSentry — trợ lý agent local-first.",
    },
    "provider": {
        "kind": "lmstudio",
        "base_url": "http://localhost:1234/v1",
        "model": "google/gemma-4-e4b",
        "api_key": "",
        "auth_mode": "lmstudio",
    },
    "memory": {
        "max_facts": 50,
        "max_turns": 12,
        "session_title": "TaxSentry session",
    },
    "jobs": {
        "tracking_enabled": True,
        "retry_limit": 2,
        "default_state": "pending",
        "needs_human_review_on_missing_data": True,
        "auto_send_email": True,
        "auto_send_telegram": True,
    },
    "integrations": {
        "telegram": {
            "enabled": False,
            "bot_token": "",
            "admin_chat_id": "",
        },
    },
    "ui": {
        "theme": "ocean",
        "show_banner": True,
    },
    "extra_env": {},
}

SECRET_FIELDS: dict[str, tuple[str, ...]] = {
    "provider.api_key": ("provider", "api_key"),
    "integrations.telegram.bot_token": ("integrations", "telegram", "bot_token"),
}

ENV_MAPPING: dict[str, str] = {
    "agent.name": "TAXSENTRY_AGENT_NAME",
    "agent.persona": "TAXSENTRY_AGENT_PERSONA",
    "agent.language": "TAXSENTRY_LANGUAGE",
    "agent.memory_enabled": "TAXSENTRY_MEMORY_ENABLED",
    "agent.llm_planner_enabled": "TAXSENTRY_LLM_PLANNER_ENABLED",
    "provider.kind": "TAXSENTRY_PROVIDER_KIND",
    "provider.base_url": "TAXSENTRY_PROVIDER_URL",
    "provider.model": "TAXSENTRY_PROVIDER_MODEL",
    "provider.api_key": "TAXSENTRY_PROVIDER_API_KEY",
    "provider.auth_mode": "TAXSENTRY_AI_AUTH_MODE",
    "memory.max_facts": "TAXSENTRY_MEMORY_MAX_FACTS",
    "memory.max_turns": "TAXSENTRY_MEMORY_MAX_TURNS",
    "memory.session_title": "TAXSENTRY_SESSION_TITLE",
    "jobs.tracking_enabled": "TAXSENTRY_JOB_TRACKING",
    "jobs.retry_limit": "TAXSENTRY_JOB_RETRY_LIMIT",
    "jobs.default_state": "TAXSENTRY_JOB_DEFAULT_STATE",
    "jobs.needs_human_review_on_missing_data": "TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA",
    "jobs.auto_send_email": "AUTO_SEND_EMAIL",
    "jobs.auto_send_telegram": "AUTO_SEND_TELEGRAM",
    "integrations.telegram.enabled": "TELEGRAM_ENABLED",
    "integrations.telegram.bot_token": "TELEGRAM_BOT_TOKEN",
    "integrations.telegram.admin_chat_id": "ADMIN_CHAT_ID",
    "ui.theme": "TAXSENTRY_THEME",
    "ui.show_banner": "TAXSENTRY_SHOW_BANNER",
    "TAXSENTRY_HOME": "TAXSENTRY_HOME",
    "TAXSENTRY_CONFIG_FILE": "TAXSENTRY_CONFIG_FILE",
    "TAXSENTRY_MEMORY_DB": "TAXSENTRY_MEMORY_DB",
}


def ensure_directories() -> None:
    for directory in (APP_HOME, CONFIG_DIR, MEMORY_DIR, RUNTIME_DIR, LOGS_DIR, CORE_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def _deep_update(base: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_update(result[key], value)
        else:
            result[key] = value
    return result


def get_empty_config() -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_SETTINGS)
    cfg["paths"] = {
        "home": str(APP_HOME),
        "config": str(CONFIG_FILE),
        "memory_db": str(MEMORY_DB),
        "session_file": str(SESSION_FILE),
    }
    return cfg


def load_env_snapshot() -> dict[str, str]:
    ensure_directories()
    load_dotenv(ENV_FILE)
    snapshot: dict[str, str] = {}
    for _, env_var in ENV_MAPPING.items():
        if env_var in os.environ:
            snapshot[env_var] = os.environ.get(env_var, "")
    return snapshot


def _set_path(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = data
    for part in path[:-1]:
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    cursor[path[-1]] = value


def _get_path(data: dict[str, Any], path: tuple[str, ...]) -> Any:
    cursor: Any = data
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def load_config() -> dict[str, Any]:
    ensure_directories()
    config = get_empty_config()
    if CONFIG_FILE.exists():
        try:
            loaded = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config = _deep_update(config, loaded)
        except Exception:
            pass

    env = load_env_snapshot()
    for cfg_path, env_var in ENV_MAPPING.items():
        if env_var not in env:
            continue
        value = env[env_var]
        if value == "":
            continue
        if cfg_path.startswith("TAXSENTRY_"):
            config.setdefault("extra_env", {})[cfg_path] = value
            continue
        _set_path(config, tuple(cfg_path.split(".")), _coerce_value(cfg_path, value))

    return config


def _coerce_value(cfg_path: str, value: str) -> Any:
    if cfg_path in {
        "agent.memory_enabled",
        "agent.llm_planner_enabled",
        "integrations.telegram.enabled",
        "ui.show_banner",
        "jobs.tracking_enabled",
        "jobs.needs_human_review_on_missing_data",
        "jobs.auto_send_email",
        "jobs.auto_send_telegram",
    }:
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if cfg_path in {"memory.max_facts", "memory.max_turns", "jobs.retry_limit"}:
        try:
            return int(value)
        except ValueError:
            return _get_default(cfg_path)
    return value


def _get_default(cfg_path: str) -> Any:
    return _get_path(DEFAULT_SETTINGS, tuple(cfg_path.split(".")))


def _sanitize_for_disk(config: dict[str, Any]) -> dict[str, Any]:
    persisted = deepcopy(config)
    for cfg_path, path in SECRET_FIELDS.items():
        _set_path(persisted, path, "")
    return persisted


def save_config(config: dict[str, Any]) -> None:
    ensure_directories()
    payload = _sanitize_for_disk(config)
    CONFIG_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_env_lines(config: dict[str, Any]) -> list[str]:
    lines = [
        f'TAXSENTRY_HOME="{APP_HOME}"',
        f'TAXSENTRY_CONFIG_FILE="{CONFIG_FILE}"',
        f'TAXSENTRY_MEMORY_DB="{MEMORY_DB}"',
        f'TAXSENTRY_SESSION_FILE="{SESSION_FILE}"',
        f'TAXSENTRY_AGENT_NAME="{config["agent"]["name"]}"',
        f'TAXSENTRY_AGENT_PERSONA="{config["agent"]["persona"]}"',
        f'TAXSENTRY_LANGUAGE="{config["agent"]["language"]}"',
        f'TAXSENTRY_MEMORY_ENABLED="{str(bool(config["agent"]["memory_enabled"])).lower()}"',
        f'TAXSENTRY_LLM_PLANNER_ENABLED="{str(bool(config["agent"].get("llm_planner_enabled", False))).lower()}"',
        f'TAXSENTRY_PROVIDER_KIND="{config["provider"]["kind"]}"',
        f'TAXSENTRY_PROVIDER_URL="{config["provider"]["base_url"]}"',
        f'TAXSENTRY_PROVIDER_MODEL="{config["provider"]["model"]}"',
        f'TAXSENTRY_AI_AUTH_MODE="{config["provider"]["auth_mode"]}"',
        f'TAXSENTRY_MEMORY_MAX_FACTS="{int(config["memory"]["max_facts"])}"',
        f'TAXSENTRY_MEMORY_MAX_TURNS="{int(config["memory"]["max_turns"])}"',
        f'TAXSENTRY_SESSION_TITLE="{config["memory"]["session_title"]}"',
        f'TAXSENTRY_JOB_TRACKING="{str(bool(config["jobs"]["tracking_enabled"])).lower()}"',
        f'TAXSENTRY_JOB_RETRY_LIMIT="{int(config["jobs"]["retry_limit"])}"',
        f'TAXSENTRY_JOB_DEFAULT_STATE="{config["jobs"]["default_state"]}"',
        f'TAXSENTRY_JOB_NEEDS_HUMAN_REVIEW_ON_MISSING_DATA="{str(bool(config["jobs"]["needs_human_review_on_missing_data"])).lower()}"',
        f'AUTO_SEND_EMAIL="{str(bool(config["jobs"]["auto_send_email"])).lower()}"',
        f'AUTO_SEND_TELEGRAM="{str(bool(config["jobs"]["auto_send_telegram"])).lower()}"',
        f'TELEGRAM_ENABLED="{str(bool(config["integrations"]["telegram"]["enabled"])).lower()}"',
        f'TELEGRAM_BOT_TOKEN="{config["integrations"]["telegram"]["bot_token"]}"',
        f'ADMIN_CHAT_ID="{config["integrations"]["telegram"]["admin_chat_id"]}"',
    ]
    if config["provider"].get("api_key"):
        lines.append(f'TAXSENTRY_PROVIDER_API_KEY="{config["provider"]["api_key"]}"')
    for key, value in config.get("extra_env", {}).items():
        lines.append(f'{key}="{value}"')
    return lines


def write_env_file(config: dict[str, Any]) -> Path:
    ensure_directories()
    content = "\n".join(build_env_lines(config)) + "\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    return ENV_FILE


def get_value(config: dict[str, Any], path: str, default: Any = None) -> Any:
    value = _get_path(config, tuple(path.split(".")))
    if value is None:
        return default
    return value


def set_value(config: dict[str, Any], path: str, value: Any) -> dict[str, Any]:
    _set_path(config, tuple(path.split(".")), value)
    return config


def describe_config(config: dict[str, Any]) -> str:
    provider = config["provider"]
    telegram = config["integrations"]["telegram"]
    memory = config["memory"]
    agent = config["agent"]
    lines = [
        f'Agent: {agent["name"]} ({agent["persona"]}, {agent["language"]})',
        f'Provider: {provider["kind"]} / {provider["model"]}',
        f'Endpoint: {provider["base_url"]}',
        f'Memory: {"on" if agent["memory_enabled"] else "off"} · facts={memory["max_facts"]} · turns={memory["max_turns"]}',
        f'LLM planner: {"on" if agent.get("llm_planner_enabled", False) else "off"}',
        f'Jobs: {"tracking on" if config["jobs"]["tracking_enabled"] else "tracking off"} · retry={config["jobs"]["retry_limit"]} · default={config["jobs"]["default_state"]} · review={"on" if config["jobs"]["needs_human_review_on_missing_data"] else "off"} · email={"on" if config["jobs"]["auto_send_email"] else "off"} · telegram={"on" if config["jobs"]["auto_send_telegram"] else "off"}',
        f'Telegram: {"enabled" if telegram["enabled"] else "disabled"}',
        f'Config file: {CONFIG_FILE}',
        f'Memory DB: {MEMORY_DB}',
    ]
    return "\n".join(lines)
