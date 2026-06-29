from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI

from .config import get_value


@dataclass
class ProviderConfig:
    kind: str
    base_url: str
    model: str
    api_key: str
    auth_mode: str


class ProviderError(RuntimeError):
    pass


def load_codex_token() -> str:
    auth_path = Path.home() / ".codex" / "auth.json"
    if not auth_path.exists():
        raise ProviderError(f"Không tìm thấy Codex OAuth profile tại {auth_path}")
    try:
        payload = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ProviderError(f"Không thể đọc Codex OAuth profile: {exc}") from exc
    token = payload.get("tokens", {}).get("access_token") or payload.get("OPENAI_API_KEY", "")
    if not token:
        raise ProviderError("Codex OAuth profile không có access token khả dụng.")
    return str(token)


def from_settings(settings: dict[str, Any]) -> ProviderConfig:
    provider = get_value(settings, "provider", {}) or {}
    return ProviderConfig(
        kind=str(provider.get("kind", "lmstudio")),
        base_url=str(provider.get("base_url", "http://localhost:1234/v1")),
        model=str(provider.get("model", "google/gemma-4-e4b")),
        api_key=str(provider.get("api_key", "")),
        auth_mode=str(provider.get("auth_mode", provider.get("kind", "lmstudio"))),
    )


def build_client(spec: ProviderConfig) -> OpenAI:
    if spec.auth_mode == "codex_oauth":
        return OpenAI(api_key=load_codex_token(), base_url="https://api.openai.com/v1")

    api_key = spec.api_key or "lmstudio"
    base_url = spec.base_url or "http://localhost:1234/v1"
    if spec.kind == "custom" and not base_url:
        raise ProviderError("Custom provider requires a base URL.")
    return OpenAI(api_key=api_key, base_url=base_url)


def provider_label(spec: ProviderConfig) -> str:
    if spec.auth_mode == "codex_oauth":
        return "OpenAI Codex OAuth"
    if spec.kind == "lmstudio":
        return "LM Studio"
    if spec.kind == "custom":
        return "Custom OpenAI-compatible"
    return spec.kind


def health_check(spec: ProviderConfig) -> tuple[bool, str]:
    try:
        client = build_client(spec)
        client.models.list()
        return True, "Provider reachable"
    except Exception as exc:
        return False, str(exc)


def generate_chat(spec: ProviderConfig, messages: list[dict[str, str]], temperature: float = 0.3) -> str:
    client = build_client(spec)
    response = client.chat.completions.create(
        model=spec.model,
        messages=messages,
        temperature=temperature,
    )
    try:
        content = response.choices[0].message.content
    except Exception as exc:
        raise ProviderError(f"Model returned no content: {exc}") from exc

    if isinstance(content, list):
        content = "".join(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
    text = str(content or "").strip()
    if not text:
        raise ProviderError("Model returned an empty response.")
    return text
