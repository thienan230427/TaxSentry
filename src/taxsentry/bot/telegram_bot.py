from __future__ import annotations

import json
from pathlib import Path

from taxsentry.config import load_config
from taxsentry.events import EventType
from taxsentry.providers import create_provider
from taxsentry.secrets import get_secret
from taxsentry.store import JobStore


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
        if action == "cancel":
            store.transition(job["id"], "failed", error="Cancelled by Director")
        else:
            store.requeue(job["id"], approved=action == "approve")
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
        async for event in create_provider(settings).stream_turn([{"role": "user", "content": prompt}]):
            if event.type == EventType.TEXT_DELTA: chunks.append(event.text)
        text = "".join(chunks) or "Em chưa thể trả lời vì provider không có phản hồi."
        for start in range(0, len(text), 4096): await update.message.reply_text(text[start:start + 4096])

    for name, handler in (("status", status), ("jobs", status), ("latest", latest), ("report", report), ("retry", retry), ("approve", approve), ("cancel", cancel)):
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat))
    return app


def main() -> None:
    build_application().run_polling()


if __name__ == "__main__": main()
