from __future__ import annotations

import json
from pathlib import Path

from taxsentry.config import load_config
from taxsentry.events import EventType
from taxsentry.gmail import GmailClient
from taxsentry.providers import create_provider
from taxsentry.secrets import get_secret
from taxsentry.store import JobStore

COMMANDS = ("status", "jobs", "latest", "report", "retry", "approve", "cancel")


def _allowed(update, settings) -> bool:
    return str(update.effective_chat.id) in {str(item) for item in settings["director"].get("telegram_chat_ids", [])}


def build_application():
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

    async def latest(update, context):
        if _allowed(update, settings):
            report = store.latest_report()
            await update.message.reply_text(report["payload"]["executive_summary"] if report else "Chưa có báo cáo.")

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
            if action == "cancel":
                store.transition(job["id"], "failed", error="Cancelled by Director")
                GmailClient(settings).label(job["gmail_message_id"], "TaxSentry/Failed")
            else:
                store.requeue(job["id"], approved=action == "approve")
        except ValueError as exc:
            await update.message.reply_text(str(exc))
            return
        await update.message.reply_text(f"Đã {action} job {job['id'][:8]}.")

    async def retry(update, context):
        await change_job(update, context, "retry")

    async def approve(update, context):
        await change_job(update, context, "approve")

    async def cancel(update, context):
        await change_job(update, context, "cancel")

    async def chat(update, context):
        if not _allowed(update, settings): return
        latest_report = store.latest_report()
        grounding = json.dumps(latest_report["payload"], ensure_ascii=False) if latest_report else "Không có báo cáo"
        prompt = f"Dữ liệu báo cáo gần nhất: {grounding[:30000]}\n\nCâu hỏi Giám đốc: {update.message.text}\nLuôn nêu độ tin cậy."
        chunks = []
        provider = create_provider(settings)
        try:
            async for event in provider.stream_turn([{"role": "user", "content": prompt}]):
                if event.type == EventType.TEXT_DELTA: chunks.append(event.text)
        finally:
            await provider.close()
        text = "".join(chunks) or "Em chưa thể trả lời vì provider không có phản hồi."
        for start in range(0, len(text), 4096): await update.message.reply_text(text[start:start + 4096])

    for name, handler in zip(COMMANDS, (status, status, latest, report, retry, approve, cancel), strict=True):
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return app


def main() -> None:
    build_application().run_polling()


async def serve(stop) -> None:
    app = build_application()
    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await stop.wait()
        finally:
            await app.updater.stop()
            await app.stop()


if __name__ == "__main__": main()
