from __future__ import annotations

import asyncio
import hmac
import json
import secrets
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Timer
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from . import __version__
from .chat_service import ChatService
from .config import load_config, save_config
from .gmail import GmailClient
from .onboarding_service import OnboardingService
from .providers import CodexAppServerProvider, from_settings, health_check
from .reporting import html_summary
from .secrets import get_secret, set_secret
from .service_control import service
from .store import JobStore
from .telegram import TelegramDirector

STATIC_DIR = Path(__file__).parent / "web" / "static"
COOKIE = "taxsentry_session"


class DashboardAuth:
    def __init__(self):
        self.token = get_secret("dashboard:token") or secrets.token_urlsafe(32)
        if not get_secret("dashboard:token"):
            set_secret("dashboard:token", self.token)
        self.codes: dict[str, float] = {}
        self.sessions: dict[str, str] = {}

    def issue_code(self) -> str:
        code = secrets.token_urlsafe(24)
        self.codes[code] = time.monotonic() + 60
        return code

    def login(self, credential: str) -> tuple[str, str] | None:
        valid_token = hmac.compare_digest(credential, self.token)
        expiry = self.codes.pop(credential, 0)
        if not valid_token and expiry < time.monotonic():
            return None
        session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(24)
        self.sessions[session_id] = csrf
        return session_id, csrf

    def csrf(self, request: Request) -> str:
        return self.sessions.get(request.cookies.get(COOKIE, ""), "")

    def logout(self, request: Request) -> None:
        self.sessions.pop(request.cookies.get(COOKIE, ""), None)

    def rotate(self) -> str:
        self.token = secrets.token_urlsafe(32)
        set_secret("dashboard:token", self.token)
        self.sessions.clear()
        self.codes.clear()
        return self.token


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _authenticated(request: Request) -> bool:
    return bool(request.app.state.auth.csrf(request))


def _guard(request: Request, *, mutate: bool = False) -> Response | None:
    csrf = request.app.state.auth.csrf(request)
    if not csrf:
        return _error("Authentication required", 401)
    if mutate and not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf):
        return _error("Invalid CSRF token", 403)
    return None


async def bootstrap(request: Request) -> Response:
    csrf = request.app.state.auth.csrf(request)
    settings = load_config()
    return JSONResponse({"authenticated": bool(csrf), "csrf": csrf, "configured": bool(settings.get("configured")), "version": __version__})


async def login(request: Request) -> Response:
    body = await request.json()
    result = request.app.state.auth.login(str(body.get("credential", "")))
    if not result:
        return _error("Token hoặc mã đăng nhập không hợp lệ / invalid credential", 401)
    session_id, csrf = result
    response = JSONResponse({"authenticated": True, "csrf": csrf})
    response.set_cookie(COOKIE, session_id, httponly=True, samesite="strict", secure=False, path="/")
    return response


async def logout(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    request.app.state.auth.logout(request)
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE, path="/")
    return response


def _overview() -> dict[str, Any]:
    settings, store = load_config(), JobStore()
    try:
        jobs = store.recent_jobs(8)
        latest = store.latest_report()
    finally:
        store.close()
    ok, detail = health_check(from_settings(settings))
    states: dict[str, int] = {}
    for item in jobs:
        states[item["state"]] = states.get(item["state"], 0) + 1
    return {
        "provider": {"kind": settings["provider"]["kind"], "model": settings["provider"].get("model") or "default", "healthy": ok, "detail": detail},
        "gmail": {"enabled": settings["gmail"].get("enabled", True), "account": settings["gmail"].get("account", "")},
        "telegram": {"enabled": settings["telegram"].get("enabled", False)},
        "configured": bool(settings.get("configured")),
        "jobs": jobs,
        "job_counts": states,
        "latest_report": latest,
    }


async def overview(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    return JSONResponse(_overview())


async def settings(request: Request) -> Response:
    if guard := _guard(request, mutate=request.method == "PATCH"):
        return guard
    current = load_config()
    if request.method == "GET":
        return JSONResponse({key: current[key] for key in ("agent", "provider", "gmail", "director", "telegram", "worker", "report", "ocr", "ui")})
    patch = await request.json()
    for section in ("agent", "worker", "report", "ocr", "ui"):
        if isinstance(patch.get(section), dict):
            current[section].update(patch[section])
    save_config(current)
    return JSONResponse({"ok": True})


async def chat(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    body = await request.json()
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        return _error("Prompt is required")

    async def events():
        async for event in request.app.state.chat.stream(prompt):
            payload = {"type": event.type.value, "text": event.text, "name": event.name, "data": event.data}
            yield json.dumps(payload, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson")


async def chat_session(request: Request) -> Response:
    if guard := _guard(request, mutate=request.method == "POST"):
        return guard
    chat_service: ChatService = request.app.state.chat
    if request.method == "POST":
        action = str((await request.json()).get("action", "new"))
        session_id = chat_service.new_session() if action == "new" else chat_service.session_id
        if action == "clear":
            chat_service.clear()
        return JSONResponse({"session_id": session_id, "messages": []})
    return JSONResponse({"session_id": chat_service.session_id, "messages": chat_service.store.session_messages(chat_service.session_id)})


async def jobs(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    store = JobStore()
    try:
        return JSONResponse({"jobs": store.recent_jobs(100)})
    finally:
        store.close()


async def job_detail(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    store = JobStore()
    try:
        job = store.get(request.path_params["job_id"])
        return JSONResponse({"job": job, "events": store.job_events(job["id"]) if job else []}, status_code=200 if job else 404)
    finally:
        store.close()


async def job_action(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    job_id, action = request.path_params["job_id"], request.path_params["action"]
    if action not in {"retry", "approve"}:
        return _error("Unknown action", 404)
    store = JobStore()
    try:
        store.requeue(job_id, approved=action == "approve")
    except ValueError as exc:
        return _error(str(exc), 409)
    finally:
        store.close()
    return JSONResponse({"ok": True})


async def reports(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    store = JobStore()
    try:
        report = store.latest_report()
        return JSONResponse({"report": report})
    finally:
        store.close()


async def report_download(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    store = JobStore()
    try:
        report = store.report_for_job(request.path_params["job_id"])
    finally:
        store.close()
    path = Path(report["pdf_path"]) if report else Path()
    if not report or not path.is_file():
        return _error("Report file not found", 404)
    return FileResponse(path, filename=path.name, media_type="application/pdf")


async def report_send(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    store, settings = JobStore(), load_config()
    try:
        report = store.report_for_job(request.path_params["job_id"])
        if not report:
            return _error("Report not found", 404)
        pdf, director = Path(report["pdf_path"]), settings["director"].get("email", "")
        if not director or not pdf.is_file():
            return _error("Director email or PDF is missing", 409)
        outgoing = GmailClient(settings).send_report(director, f"TaxSentry gửi lại: {report['subject']}", html_summary(report["payload"]), pdf, idempotency_key=f"{report['job_id']}-ui-{uuid.uuid4()}")
        store.delivery(report["job_id"], "gmail", "sent", outgoing)
        for external_id in await TelegramDirector(settings).notify(f"📄 Gửi lại: {report['payload']['executive_summary']}", pdf):
            store.delivery(report["job_id"], "telegram", "sent", external_id)
        return JSONResponse({"ok": True})
    finally:
        store.close()


async def connections(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    current = load_config()
    ok, detail = health_check(from_settings(current))
    account = current["gmail"].get("account", "")
    return JSONResponse({
        "provider": {"ok": ok, "detail": detail, "kind": current["provider"]["kind"]},
        "gmail": {"enabled": current["gmail"].get("enabled", True), "connected": bool(account and get_secret(f"gmail-app-password:{account}")), "account": account},
        "telegram": {"enabled": current["telegram"].get("enabled", False), "connected": bool(get_secret("telegram:bot-token"))},
    })


def _draft(request: Request) -> OnboardingService | None:
    return request.app.state.drafts.get(request.cookies.get(COOKIE, ""))


async def onboarding(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    session_id = request.cookies.get(COOKIE, "")
    action = request.path_params["action"]
    if action == "start":
        request.app.state.drafts[session_id] = OnboardingService()
        return JSONResponse({"config": request.app.state.drafts[session_id].public_config()})
    draft = _draft(request)
    if not draft:
        return _error("Start onboarding first", 409)
    body = await request.json() if request.headers.get("content-length", "0") != "0" else {}
    try:
        if action == "step":
            return JSONResponse({"config": draft.update(body.get("patch", {}))})
        if action == "verify":
            result = await draft.verify_all(gmail_password=str(body.get("gmail_password", "")), telegram_token=str(body.get("telegram_token", "")))
            return JSONResponse({"verified": result, "config": draft.public_config()})
        if action == "commit":
            config = draft.commit()
            request.app.state.drafts.pop(session_id, None)
            return JSONResponse({"ok": True, "config": config})
        if action == "cancel":
            request.app.state.drafts.pop(session_id, None)
            return JSONResponse({"ok": True})
    except Exception as exc:
        return _error(str(exc), 422)
    return _error("Unknown onboarding action", 404)


async def codex_oauth_start(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    body = await request.json()
    client = CodexAppServerProvider()
    try:
        challenge = await client.start_login(device_code=bool(body.get("device_code")))
        login_id = str(challenge.get("loginId", ""))
        task = asyncio.create_task(client.wait_login(login_id))
        request.app.state.oauth[login_id] = (request.cookies.get(COOKIE, ""), client, task)
        return JSONResponse(challenge)
    except Exception:
        await client.close()
        raise


async def codex_oauth_status(request: Request) -> Response:
    if guard := _guard(request):
        return guard
    login_id = request.path_params["login_id"]
    entry = request.app.state.oauth.get(login_id)
    if not entry or entry[0] != request.cookies.get(COOKIE, ""):
        return _error("Login not found", 404)
    _, client, task = entry
    if not task.done():
        return JSONResponse({"status": "pending"})
    try:
        task.result()
        account, models = await client.account(refresh=True), await client.models()
        return JSONResponse({"status": "complete", "account": account, "models": models})
    except Exception as exc:
        return _error(str(exc), 422)
    finally:
        await client.close()
        request.app.state.oauth.pop(login_id, None)


async def codex_oauth_cancel(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    login_id = request.path_params["login_id"]
    entry = request.app.state.oauth.pop(login_id, None)
    if entry:
        _, client, task = entry
        task.cancel()
        await client.cancel_login(login_id)
        await client.close()
    return JSONResponse({"ok": True})


async def service_action(request: Request) -> Response:
    if guard := _guard(request, mutate=True):
        return guard
    action = request.path_params["action"]
    if action not in {"install", "start", "stop", "status", "remove", "logs"}:
        return _error("Unknown service action", 404)
    try:
        return JSONResponse({"detail": await asyncio.to_thread(service, action)})
    except Exception as exc:
        return _error(str(exc), 422)


async def static(request: Request) -> Response:
    relative = request.path_params.get("path", "") or "index.html"
    candidate = (STATIC_DIR / relative).resolve()
    if STATIC_DIR.resolve() in candidate.parents and candidate.is_file():
        return FileResponse(candidate)
    index = STATIC_DIR / "index.html"
    if index.is_file():
        return FileResponse(index)
    return HTMLResponse("<h1>TaxSentry UI chưa được build</h1><p>Run <code>npm run ui:build</code>.</p>", status_code=503)


def create_app(auth: DashboardAuth | None = None) -> Starlette:
    @asynccontextmanager
    async def lifespan(app: Starlette):
        yield
        await app.state.chat.close()
        app.state.chat.store.close()
        for _, client, task in app.state.oauth.values():
            task.cancel()
            await client.close()

    app = Starlette(lifespan=lifespan, routes=[
        Route("/api/bootstrap", bootstrap),
        Route("/api/session", login, methods=["POST"]),
        Route("/api/session", logout, methods=["DELETE"]),
        Route("/api/overview", overview),
        Route("/api/settings", settings, methods=["GET", "PATCH"]),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/chat/session", chat_session, methods=["GET", "POST"]),
        Route("/api/jobs", jobs),
        Route("/api/jobs/{job_id}", job_detail),
        Route("/api/jobs/{job_id}/{action}", job_action, methods=["POST"]),
        Route("/api/reports/latest", reports),
        Route("/api/reports/{job_id}/download", report_download),
        Route("/api/reports/{job_id}/send", report_send, methods=["POST"]),
        Route("/api/connections", connections),
        Route("/api/onboarding/{action}", onboarding, methods=["POST"]),
        Route("/api/oauth/codex/start", codex_oauth_start, methods=["POST"]),
        Route("/api/oauth/codex/{login_id}", codex_oauth_status),
        Route("/api/oauth/codex/{login_id}", codex_oauth_cancel, methods=["DELETE"]),
        Route("/api/service/{action}", service_action, methods=["POST"]),
        Route("/{path:path}", static),
    ])
    app.state.auth = auth or DashboardAuth()
    app.state.chat = ChatService(load_config())
    app.state.drafts = {}
    app.state.oauth = {}
    return app


def run_dashboard(*, port: int = 8765, open_browser: bool = True) -> int:
    auth = DashboardAuth()
    code = auth.issue_code()
    url = f"http://127.0.0.1:{port}/?code={code}"
    print(f"TaxSentry Control Center: http://127.0.0.1:{port}")
    if open_browser:
        Timer(0.8, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(auth), host="127.0.0.1", port=port, log_level="warning")
    return 0
