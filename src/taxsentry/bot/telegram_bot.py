from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from pathlib import Path

from taxsentry.artifacts import ArtifactService, detect_artifact_kind
from taxsentry.chat_service import ChatService
from taxsentry.config import load_config
from taxsentry.events import EventType
from taxsentry.gmail import GmailMessage, natural_gmail_query
from taxsentry.secrets import get_secret
from taxsentry.store import JobStore
from taxsentry.workflow import TaxSentryWorkflow

COMMANDS = ("status", "jobs", "report", "retry", "approve", "gmail", "create", "cancel")


def _allowed(update, settings) -> bool:
    return str(update.effective_chat.id) in {str(item) for item in settings["director"].get("telegram_chat_ids", [])}


def build_application(
    chat: ChatService,
    notify: Callable[[str], None] | None = None,
    *,
    workflow: TaxSentryWorkflow | None = None,
    artifacts: ArtifactService | None = None,
):
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    settings = load_config()
    store = workflow.store if workflow else JobStore()
    token = get_secret("telegram:bot-token")
    if not token:
        raise RuntimeError("Run `taxsentry auth telegram` first")
    app = Application.builder().token(token).build()
    pending: dict[str, list[GmailMessage]] = {}
    tasks: set[asyncio.Task] = set()
    if not hasattr(app, "bot_data"):
        app.bot_data = {}
    app.bot_data["taxsentry_tasks"] = tasks

    async def status(update, context):
        if _allowed(update, settings):
            jobs = store.recent_jobs(5)
            await update.message.reply_text("\n".join(f"{j['id'][:8]} · {j['state']} · {j['subject']}" for j in jobs) or "Chưa có job.")

    async def report(update, context):
        if not _allowed(update, settings):
            return
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

    async def cancel(update, context):
        if not _allowed(update, settings) or not workflow:
            return
        job = store.resolve(context.args[0] if context.args else "")
        if not job:
            await update.message.reply_text("Không tìm thấy job.")
            return
        try:
            workflow.cancel(job["id"])
            await update.message.reply_text(f"Đã yêu cầu hủy job {job['id'][:8]}.")
        except ValueError as exc:
            await update.message.reply_text(str(exc))

    async def gmail(update, context):
        if not _allowed(update, settings) or not workflow:
            return
        chat_id = str(update.effective_chat.id)
        action = context.args[0].casefold() if context.args else "search"
        if action == "process":
            selected = _select_messages(pending.get(chat_id, []), context.args[1:])
            if not selected:
                await update.message.reply_text("Không có thư phù hợp. Hãy dùng /gmail search trước.")
                return
            job_ids = workflow.queue_messages(selected)
            await update.message.reply_text("Đã nhận · " + ", ".join(job[:8] for job in job_ids))
            _start(tasks, _background(workflow.process_messages(selected), update, "Xử lý Gmail"))
            return
        query = " ".join(context.args[1:]) if action == "search" else " ".join(context.args)
        await update.message.reply_text("Đã nhận · đang tìm Gmail…")
        messages = await asyncio.wait_for(asyncio.to_thread(workflow.gmail.search, query or "in:anywhere newer_than:30d", 20), timeout=30)
        pending[chat_id] = messages
        await update.message.reply_text(_gmail_table(messages) + "\n\nXác nhận: /gmail process <UID hoặc all>")

    async def create(update, context):
        if not _allowed(update, settings) or not artifacts:
            return
        kind = context.args[0] if context.args else ""
        request = " ".join(context.args[1:]).strip()
        if not detect_artifact_kind(kind) or not request:
            await update.message.reply_text("Dùng: /create <docx|xlsx|pptx|pdf> <yêu cầu>")
            return
        request_id = uuid.uuid4().hex[:8]
        await update.message.reply_text(f"Đã nhận · request {request_id}")
        messages = pending.get(str(update.effective_chat.id), []) if re.search(r"\bgmail\b|hòm thư", request, re.IGNORECASE) else []
        _start(tasks, _create_artifact(artifacts, kind, request, messages, update, request_id))

    async def chat_message(update, context):
        if not _allowed(update, settings):
            return
        chat_id, text = str(update.effective_chat.id), update.message.text
        if notify:
            notify(f"◇ TELEGRAM · {chat_id} › {text}")
        kind = detect_artifact_kind(text)
        if kind and re.search(r"\b(tạo|viết|xuất|làm|create|make|export)\b", text, re.IGNORECASE):
            if re.search(r"\bgmail\b|hòm thư", text, re.IGNORECASE):
                await update.message.reply_text("Đã nhận · đang tìm nguồn Gmail để Sếp xác nhận…")
                messages = await asyncio.wait_for(asyncio.to_thread(workflow.gmail.search, natural_gmail_query(text), 20), timeout=30) if workflow else []
                pending[chat_id] = messages
                await update.message.reply_text(_gmail_table(messages) + f"\n\nSau khi kiểm tra, dùng /create {kind} <yêu cầu có chữ Gmail>.")
                return
            await update.message.reply_text(f"Đã nhận · request {uuid.uuid4().hex[:8]}")
            _start(tasks, _create_artifact(artifacts, kind, text, [], update, "artifact"))
            return
        if workflow and re.search(r"\b(?:gmail|email)\b|hòm thư", text, re.IGNORECASE):
            await update.message.reply_text("Đã nhận · đang tìm Gmail…")
            messages = await asyncio.wait_for(asyncio.to_thread(workflow.gmail.search, natural_gmail_query(text), 20), timeout=30)
            pending[chat_id] = messages
            await update.message.reply_text(_gmail_table(messages) + "\n\nXác nhận xử lý: /gmail process <UID hoặc all>")
            return
        chunks = []
        async for event in chat.stream(text, source=f"telegram:{chat_id}"):
            if event.type == EventType.TEXT_DELTA:
                chunks.append(event.text)
            elif event.type == EventType.ERROR:
                chunks.append(f"Lỗi: {event.text}")
        answer = "".join(chunks) or "Em chưa thể trả lời vì provider không có phản hồi."
        for start in range(0, len(answer), 4096):
            await update.message.reply_text(answer[start:start + 4096])

    for name, handler in zip(COMMANDS, (status, status, report, retry, approve, gmail, create, cancel), strict=True):
        app.add_handler(CommandHandler(name, handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, chat_message))
    return app


def _select_messages(messages: list[GmailMessage], values: list[str]) -> list[GmailMessage]:
    wanted = {value.casefold() for value in values}
    if not wanted or "all" in wanted:
        return messages
    return [message for message in messages if message.id.casefold() in wanted]


def _gmail_table(messages: list[GmailMessage]) -> str:
    if not messages:
        return "Không tìm thấy thư phù hợp."
    return "\n".join(f"{message.id} · {message.date[:10]} · {message.sender[:28]} · {message.subject} · {len(message.attachments)} file" for message in messages)


def _start(tasks: set[asyncio.Task], coroutine) -> None:
    task = asyncio.create_task(coroutine)
    tasks.add(task)
    task.add_done_callback(tasks.discard)


async def _background(coroutine, update, label: str) -> None:
    try:
        completed = await coroutine
        await update.message.reply_text(f"{label} hoàn tất · {completed} báo cáo.")
    except Exception as exc:
        await update.message.reply_text(f"{label} lỗi: {exc}")


async def _create_artifact(artifacts: ArtifactService | None, kind: str, request: str, messages: list[GmailMessage], update, request_id: str) -> None:
    if not artifacts:
        return
    try:
        source = await artifacts.source_text(messages=messages) if messages else ""
        path = await artifacts.create(kind, request, source_text=source)
        await update.message.reply_text(f"Request {request_id} hoàn tất · {path.name}")
    except Exception as exc:
        await update.message.reply_text(f"Request {request_id} lỗi: {exc}")


async def serve(
    stop,
    chat: ChatService,
    notify: Callable[[str], None] | None = None,
    *,
    workflow: TaxSentryWorkflow | None = None,
    artifacts: ArtifactService | None = None,
) -> None:
    app = build_application(chat, notify, workflow=workflow, artifacts=artifacts)
    async with app:
        await app.start()
        await app.updater.start_polling()
        try:
            await stop.wait()
        finally:
            await app.updater.stop()
            tasks = app.bot_data.get("taxsentry_tasks", set())
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await app.stop()
