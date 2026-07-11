from __future__ import annotations

from pathlib import Path
from typing import Any

from .secrets import get_secret


class TelegramDirector:
    def __init__(self, settings: dict[str, Any], bot=None):
        self.settings = settings
        self.bot = bot

    async def _client(self):
        if self.bot is None:
            from telegram import Bot

            token = get_secret("telegram:bot-token")
            if not token:
                raise RuntimeError("Telegram is not authenticated")
            self.bot = Bot(token)
        return self.bot

    async def notify(self, text: str, pdf: Path | None = None) -> list[str]:
        if not self.settings.get("telegram", {}).get("enabled"):
            return []
        bot, sent = await self._client(), []
        for chat_id in self.settings["director"].get("telegram_chat_ids", []):
            message = await bot.send_message(chat_id=chat_id, text=text[:4096])
            sent.append(str(getattr(message, "message_id", "")))
            if pdf:
                with pdf.open("rb") as file:
                    document = await bot.send_document(chat_id=chat_id, document=file, filename=pdf.name)
                    sent.append(str(getattr(document, "message_id", "")))
        return sent
