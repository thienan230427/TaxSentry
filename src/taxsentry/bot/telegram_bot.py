from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Callable
from pathlib import Path

from taxsentry.artifacts import ArtifactService, detect_artifact_kind
from taxsentry.chat_service import ChatService
from taxsentry.config import load_config, save_config
from taxsentry.events import EventType
from taxsentry.gmail import GmailMessage, natural_gmail_query
from taxsentry.knowledge import KnowledgeBase
from taxsentry.secrets import get_secret
from taxsentry.store import JobStore
from taxsentry.workflow import TaxSentryWorkflow

COMMANDS = ("status", "jobs", "report", "retry", "approve", "gmail", "create", "cancel", "profile", "knowledge")


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
            await update.message.reply_text("Chưa có tài liệu.")
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
            if action == "approve" and workflow:
                await workflow.approve(job["id"])
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
        detected = detect_artifact_kind(kind)
        request = " ".join(context.args[1:] if detected else context.args).strip()
        if not request:
            await update.message.reply_text("Dùng: /create [docx|xlsx|pptx|pdf] <yêu cầu>")
            return
        request_id = uuid.uuid4().hex[:8]
        await update.message.reply_text(f"Đã nhận · request {request_id}")
        messages = pending.get(str(update.effective_chat.id), []) if re.search(r"\bgmail\b|hòm thư", request, re.IGNORECASE) else []
        _start(tasks, _create_artifact(artifacts, detected, request, messages, update, request_id))

    async def profile(update, context):
        if not _allowed(update, settings):
            return
        company = settings.setdefault("advisor", {}).setdefault("company", {})
        if not context.args or context.args[0].casefold() == "show":
            await update.message.reply_text(
                "\n".join(f"{key}: {value if value not in ('', []) else 'chưa cấu hình'}" for key, value in company.items())
            )
            return
        if len(context.args) < 3 or context.args[0].casefold() != "set":
            await update.message.reply_text("Dùng: /profile set <field> <value>")
            return
        field, raw = context.args[1], " ".join(context.args[2:]).strip()
        if field not in {"name", "industry", "business_model", "fiscal_year_start", "reporting_cycle", "currency", "materiality_ratio", "objectives"}:
            await update.message.reply_text("Trường hồ sơ không hợp lệ.")
            return
        if field == "materiality_ratio":
            try:
                value = float(raw.replace(",", "."))
            except ValueError:
                await update.message.reply_text("materiality_ratio phải là số.")
                return
            if not 0 < value <= 1:
                await update.message.reply_text("materiality_ratio phải nằm trong (0, 1].")
                return
        elif field == "objectives":
            value = [item.strip() for item in raw.split(",") if item.strip()]
        else:
            value = raw
        company[field] = value
        save_config(settings)
        await update.message.reply_text(f"Đã cập nhật {field}.")

    async def knowledge(update, context):
        if not _allowed(update, settings):
            return
        service = KnowledgeBase(settings)
        action = context.args[0].casefold() if context.args else "status"
        result = await asyncio.to_thread(service.refresh) if action == "refresh" else service.status()
        await update.message.reply_text(
            f"Tri thức: {'cũ/chưa xác minh' if result['stale'] else 'đã xác minh'}\n"
            f"Nguồn: {result['verified_sources']}/{result['total_sources']}\n"
            f"Kiểm tra gần nhất: {result['verified_at'] or 'chưa có'}"
        )

    async def chat_message(update, context):
        if not _allowed(update, settings):
            return
        chat_id, text = str(update.effective_chat.id), update.message.text
        if notify:
            notify(f"◇ TELEGRAM · {chat_id} › {text}")
        kind = detect_artifact_kind(text)
        wants_artifact = bool(kind) or bool(
            re.search(
                r"\b(tạo|viết|xuất|làm|create|make|export)\b.*\b(báo cáo|tài liệu|report|document|file)\b",
                text,
                re.IGNORECASE,
            )
        )
        if wants_artifact:
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

    for name, handler in zip(COMMANDS, (status, status, report, retry, approve, gmail, create, cancel, profile, knowledge), strict=True):
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
        source = await artifacts.source(messages=messages) if messages else None
        bundle = await artifacts.create_bundle(request, kind=kind, source=source)
        names = ", ".join(path.name for path in bundle.files)
        review = " · cần kiểm tra" if bundle.needs_review else ""
        await update.message.reply_text(f"Request {request_id} hoàn tất · {names}{review}")
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
