from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from .config import load_config, save_config
from .events import EventType
from .gmail import GmailClient
from .providers import CodexAppServerProvider, from_settings, generate_chat, lmstudio_models
from .secrets import delete_secret, get_secret, set_secret

ALLOWED_SECTIONS = {"agent", "provider", "gmail", "director", "telegram", "worker", "report", "ocr", "ui"}


def _merge(base: dict[str, Any], patch: dict[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value


class OnboardingService:
    """In-memory setup draft. Nothing is persisted before every enabled service verifies."""

    def __init__(self, settings: dict[str, Any] | None = None):
        self.draft = deepcopy(settings or load_config())
        self.staged_secrets: dict[str, str] = {}
        self.verified: dict[str, str] = {}

    def update(self, patch: dict[str, Any]) -> dict[str, Any]:
        filtered = {key: value for key, value in patch.items() if key in ALLOWED_SECTIONS}
        _merge(self.draft, filtered)
        self.verified.clear()
        return self.public_config()

    def public_config(self) -> dict[str, Any]:
        payload = deepcopy(self.draft)
        payload.get("provider", {}).pop("api_key", None)
        return payload

    async def verify_provider(self) -> str:
        provider = self.draft["provider"]
        if provider["kind"] == "codex":
            client = CodexAppServerProvider(model=provider.get("model", ""))
            try:
                account = await client.account(refresh=True)
                if not account.get("account") and account.get("requiresOpenaiAuth", True):
                    raise RuntimeError("Codex chưa đăng nhập / Codex is not authenticated")
                models = await client.models()
                if not provider.get("model") and models:
                    provider["model"] = models[0][0]
                text = []
                async for event in client.stream_turn([{"role": "user", "content": "Reply with exactly OK"}]):
                    if event.type == EventType.TEXT_DELTA:
                        text.append(event.text)
                    elif event.type == EventType.ERROR:
                        raise RuntimeError(event.text)
                if not "".join(text).strip():
                    raise RuntimeError("Codex live check returned no text")
                detail = f"Codex ready · {provider.get('model') or 'default'}"
            finally:
                await client.close()
        else:
            models = await asyncio.to_thread(lmstudio_models, from_settings(self.draft))
            if not models:
                raise RuntimeError("LM Studio không trả về model nào / no models found")
            if not provider.get("model"):
                provider["model"] = models[0]
            reply = await asyncio.to_thread(
                generate_chat,
                from_settings(self.draft),
                [{"role": "user", "content": "Reply with exactly OK"}],
                0,
            )
            if not reply:
                raise RuntimeError("LM Studio live check returned no text")
            detail = f"LM Studio ready · {provider['model']}"
        self.verified["provider"] = detail
        return detail

    async def verify_gmail(self, password: str = "") -> str:
        account = str(self.draft["gmail"].get("account", ""))
        secret_name = f"gmail-app-password:{account}"
        normalized = "".join(password.split()) or get_secret(secret_name)
        client = GmailClient(self.draft)
        await asyncio.to_thread(client.authenticate, app_password=normalized, store=False)
        if client.imap:
            try:
                client.imap.logout()
            except Exception:
                pass
        if password:
            self.staged_secrets[secret_name] = normalized
        self.verified["gmail"] = account
        return account

    async def verify_telegram(self, token: str = "") -> str:
        from telegram import Bot

        value = token or get_secret("telegram:bot-token")
        if not value:
            raise RuntimeError("Telegram bot token is missing")
        async with Bot(value) as bot:
            identity = await bot.get_me()
        if token:
            self.staged_secrets["telegram:bot-token"] = value
        detail = f"@{identity.username}" if getattr(identity, "username", None) else str(identity.id)
        self.verified["telegram"] = detail
        return detail

    async def verify_all(self, *, gmail_password: str = "", telegram_token: str = "") -> dict[str, str]:
        await self.verify_provider()
        if self.draft["gmail"].get("enabled", True):
            await self.verify_gmail(gmail_password)
        if self.draft["telegram"].get("enabled", False):
            await self.verify_telegram(telegram_token)
        return dict(self.verified)

    def commit(self) -> dict[str, Any]:
        required = {"provider"}
        if self.draft["gmail"].get("enabled", True):
            required.add("gmail")
        if self.draft["telegram"].get("enabled", False):
            required.add("telegram")
        missing = required - self.verified.keys()
        if missing:
            raise RuntimeError(f"Verify before commit: {', '.join(sorted(missing))}")

        previous = {name: get_secret(name) for name in self.staged_secrets}
        try:
            for name, value in self.staged_secrets.items():
                set_secret(name, value)
            self.draft["configured"] = True
            save_config(self.draft)
        except Exception:
            for name, value in previous.items():
                set_secret(name, value) if value else delete_secret(name)
            raise
        return self.public_config()
