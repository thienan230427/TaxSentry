from __future__ import annotations

import os
from dataclasses import dataclass
from typing import MutableMapping, MutableSequence

from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine


@dataclass(slots=True)
class StartupContext:
    director_name: str
    director_email: str
    accountant_email: str
    email_user: str
    model_name: str
    llm_url: str


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default) or default


def format_model_status(model_name: str) -> str:
    if not model_name:
        return "[yellow]Not Configured[/yellow]"
    display = model_name.split("/")[-1] if "/" in model_name else model_name
    return f"[green]Connected ({display})[/green]"


def get_model_display_name() -> str:
    return format_model_status(_env("LM_MODEL_NAME"))


def get_llm_server_url() -> str:
    return _env("LM_STUDIO_URL", "http://localhost:1234/v1")


def get_director_name() -> str:
    return _env("DIRECTOR_NAME")


def get_director_email() -> str:
    return _env("DIRECTOR_EMAIL")


def get_accountant_email() -> str:
    return _env("ACCOUNTANT_EMAIL")


def get_email_user() -> str:
    return _env("EMAIL_USER")


def build_startup_context(
    log_messages: MutableSequence[str],
    system_status: MutableMapping[str, str],
) -> StartupContext:
    director_name = get_director_name()
    director_email = get_director_email()
    accountant_email = get_accountant_email()
    email_user = get_email_user()
    model_name = _env("LM_MODEL_NAME")
    llm_url = get_llm_server_url()

    if director_name:
        log_messages.append(f"Kính chào Giám đốc {director_name}. Hệ thống giám sát đã sẵn sàng làm việc.")
    else:
        log_messages.append("Kính chào Sếp. Hệ thống giám sát đã sẵn sàng làm việc.")

    log_messages.append(f"🤖 AI Server: {llm_url} | Model: {model_name or '[chưa cấu hình]'}")
    log_messages.append(f"📧 IMAP Login: {email_user or '[chưa cấu hình]'}")
    log_messages.append(f"👩‍💼 Đang giám sát thư từ Kế toán trưởng: {accountant_email or '[chưa cấu hình]'}")
    if director_email:
        log_messages.append(f"📬 Báo cáo PDF sẽ gửi tới: {director_email}")
    log_messages.append("📡 Telegram Bot đang khởi động...")

    try:
        engine = TaxSentryAnalysisEngine()
        if engine.connect():
            system_status["LM Studio"] = format_model_status(model_name)
            log_messages.append(f"✅ Kết nối AI Server thành công: {model_name}")
        else:
            system_status["LM Studio"] = "[red]Disconnected[/red]"
            log_messages.append(f"❌ Không thể kết nối AI Server tại {llm_url}")
    except Exception as exc:
        system_status["LM Studio"] = f"[red]Error: {exc}[/red]"
        log_messages.append(f"❌ Lỗi AI: {exc}")

    return StartupContext(
        director_name=director_name,
        director_email=director_email,
        accountant_email=accountant_email,
        email_user=email_user,
        model_name=model_name,
        llm_url=llm_url,
    )
