from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from taxsentry.chat_service import ChatService
from taxsentry.config import load_config
from taxsentry.events import EventType
from taxsentry.secrets import get_secret
from taxsentry.store import JobStore

COMMANDS = ("status", "jobs", "report", "retry", "approve")


def _allowed(update, settings) -> bool:
    return str(update.effective_chat.id) in {str(item) for item in settings["director"].get("telegram_chat_ids", [])}


def build_application(chat: ChatService, notify: Callable[[str], None] | None = None):
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    settings, store = load_config(), JobStore()
    token = get_secret("telegram:bot-token")
    if not token:
        raise RuntimeError("Run `taxsentry auth telegram` first")
    app = Application.builder().token(token).build()

    async def status(update, context):
        if _allowed(update, settings):
            jobs = store.recent_jobs(5)
            await update.message.reply_text("\n".join(f"{j['id'][:8]} · {j['state']} · {j['subject']}" for j in jobs) or "Chưa có job.")

    async def report(update, context):
        if not _allowed(update, settings): return
        item = store.latest_report()
        if not item or not item.get("pdf_path") or not Path(item["pdf_path"]).exists():
            await update.message.reply_text("Chưa có PDF.")
            return
        with Path(item["pdf_path"]).open("rb") as file:
            await update.message.reply_document(file, filename=Path(item["pdf_path"]).name)

    async def change_job(update, context, action):
        if not _allowed(update, settings):
            return
        job = store.resolve(context.args[0] if context.args else "")
        if not job:
            await update.message.reply_text("Không tìm thấy job.")
            return
        try:
            store.requeue(job["id"], approved=action == "approve")
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"Đã {action} job {job['id'][:8]}.")

    async def retry(update, context):
        await change_job(update, context, "retry")

    async def approve(update, context):
        await change_job(update, context, "approve")

    async def chat_message(update, context):
        if not _allowed(update, settings): return
        chat_id = str(update.effective_chat.id)
        if notify:
            notify(f"◇ TELEGRAM · {chat_id} › {update.message.text}")
        chunks = []
        async for event in chat.stream(update.message.text, source=f"telegram:{chat_id}"):
            if event.type == EventType.TEXT_DELTA:
                chunks.append(event.text)
            elif event.type == EventType.ERROR:
                chunks.append(f"Lỗi: {event.text}")
        text = "".join(chunks) or "Em chưa thể trả lời vì provider không có phản hồi."
        for start in range(0, len(text), 4096): await update.message.reply_text(text[start:start + 4096])

    for name, handler in zip(COMMANDS, (status, status, report, retry, approve), strict=True):
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))
    return app


async def serve(stop, chat: ChatService, notify: Callable[[str], None] | None = None) -> None:
    app = build_application(chat, notify)
    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await stop.wait()
        finally:
            await app.updater.stop()
            await app.stop()
