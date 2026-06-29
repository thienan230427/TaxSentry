from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from rich import box
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from taxsentry.config.paths import EVIDENCE_CONTEXT_PATH
from taxsentry.core.evidence_preview import build_evidence_preview_text, load_evidence_context
from taxsentry.database.db_manager import TaxSentryDBManager


@dataclass(slots=True)
class DashboardReportRow:
    file_name: str
    received_at: str
    sender: str
    status: str
    risk: str
    revenue: str
    net_income: str


@dataclass(slots=True)
class DashboardStatusCard:
    label: str
    value: str
    emphasis: str = "white"


@dataclass(slots=True)
class DashboardSnapshot:
    director_name: str
    model_name: str
    llm_url: str
    database_status: str
    telegram_status: str
    automation_status: str
    report_count: int
    recent_reports: list[DashboardReportRow]
    evidence_preview: str
    status_cards: list[DashboardStatusCard]
    action_hints: list[str]
    last_refresh: str


def _clean_text(value: Any, fallback: str = "n/a") -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _format_currency(value: Any, fallback: str = "n/a") -> str:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, (int, float)):
        return f"{value:,.0f} VND"
    return fallback


def _format_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d/%m %H:%M")
    if value is None:
        return "-"
    text = str(value).strip()
    return text or "-"


def _build_report_row(log: dict[str, Any]) -> DashboardReportRow:
    status = _clean_text(log.get("status"), "Chưa xác định")
    if status.lower() == "processed":
        status = "Đã xử lý"

    return DashboardReportRow(
        file_name=_clean_text(log.get("file_name")),
        received_at=_format_timestamp(log.get("received_at")),
        sender=_clean_text(log.get("sender")),
        status=status,
        risk=_clean_text(log.get("tax_risk_status")),
        revenue=_format_currency(log.get("revenue")),
        net_income=_format_currency(log.get("net_income")),
    )


def _build_status_cards(
    director_name: str,
    model_name: str,
    llm_url: str,
    report_count: int,
    telegram_status: str,
    automation_status: str,
) -> list[DashboardStatusCard]:
    pretty_model = model_name.split("/")[-1] if model_name and "/" in model_name else model_name
    model_label = pretty_model or "[chưa cấu hình]"
    director_label = director_name or "Sếp"
    return [
        DashboardStatusCard("Giám đốc", director_label, "bold white"),
        DashboardStatusCard("AI server", llm_url, "cyan"),
        DashboardStatusCard("Model", model_label, "green"),
        DashboardStatusCard("Telegram", telegram_status, "yellow"),
        DashboardStatusCard("Tự động hoá", automation_status, "magenta"),
        DashboardStatusCard("Bản ghi", f"{report_count} báo cáo gần nhất", "bold white"),
    ]


def _build_action_hints() -> list[str]:
    return [
        "Nhấn [c] để mở chế độ chat trực tiếp với Copilot.",
        "Nhấn [q] hoặc [Esc] để thoát dashboard nhanh.",
        "Nhấn Ctrl+C để thoát an toàn và dừng gateway nền.",
        "Dùng lệnh /analyze hoặc /reports từ Telegram khi cần đối chiếu nhanh.",
    ]


def collect_dashboard_snapshot(limit: int = 5) -> DashboardSnapshot:
    director_name = _clean_text(os.getenv("DIRECTOR_NAME", ""), "Sếp")
    model_name = _clean_text(os.getenv("LM_MODEL_NAME", ""), "")
    llm_url = _clean_text(os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1"), "http://localhost:1234/v1")
    telegram_status = "[green]Sẵn sàng[/green]" if os.getenv("TELEGRAM_BOT_TOKEN") else "[yellow]Chưa cấu hình[/yellow]"
    automation_status = "[green]Tự động hoá bật[/green]" if os.getenv("TAXSENTRY_AUTOMATION_DISABLED") != "1" else "[red]Tự động hoá tắt[/red]"

    db = TaxSentryDBManager()
    logs: list[dict[str, Any]] = []
    database_status = "[red]Chưa kết nối[/red]"
    try:
        if db.connect():
            logs = db.get_recent_logs(limit=limit)
            database_status = "[green]Đang hoạt động[/green]"
        else:
            database_status = "[red]Không thể kết nối[/red]"
    except Exception as exc:  # pragma: no cover - defensive UI layer
        database_status = f"[red]Lỗi: {exc}[/red]"
    finally:
        try:
            db.close()
        except Exception:
            pass

    recent_reports = [_build_report_row(log) for log in logs[:limit]]
    if not recent_reports:
        recent_reports = [
            DashboardReportRow(
                file_name="Chưa có báo cáo mới",
                received_at="-",
                sender="-",
                status="Chờ dữ liệu",
                risk="Sẵn sàng nhận file",
                revenue="-",
                net_income="-",
            )
        ]

    evidence_context = load_evidence_context(EVIDENCE_CONTEXT_PATH)
    evidence_preview = build_evidence_preview_text(evidence_context, director_name=director_name) if evidence_context else ""
    if not evidence_preview:
        evidence_preview = (
            "Sếp chưa có evidence context mới trong lần refresh này.\n"
            "Khi một file Excel/PDF được parse xong, phần preview sẽ hiện ở đây để Sếp đối chiếu trước khi vào phân tích sâu."
        )

    return DashboardSnapshot(
        director_name=director_name,
        model_name=model_name,
        llm_url=llm_url,
        database_status=database_status,
        telegram_status=telegram_status,
        automation_status=automation_status,
        report_count=len(logs),
        recent_reports=recent_reports,
        evidence_preview=evidence_preview,
        status_cards=_build_status_cards(director_name, model_name, llm_url, len(logs), telegram_status, automation_status),
        action_hints=_build_action_hints(),
        last_refresh=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def _build_metric_card(card: DashboardStatusCard) -> Panel:
    body = Text()
    body.append(f"{card.label}\n", style="dim")
    body.append(Text.from_markup(card.value))
    border_style = card.emphasis if card.emphasis != "white" else "deep_sky_blue1"
    return Panel(body, border_style=border_style)


def _build_summary_panel(snapshot: DashboardSnapshot) -> Panel:
    grid = Table.grid(expand=True)
    for _ in range(3):
        grid.add_column(ratio=1)

    cards = snapshot.status_cards
    grid.add_row(
        _build_metric_card(cards[0]),
        _build_metric_card(cards[1]),
        _build_metric_card(cards[2]),
    )
    grid.add_row(
        _build_metric_card(cards[3]),
        _build_metric_card(cards[4]),
        _build_metric_card(cards[5]),
    )
    return Panel(grid, title="[bold deep_sky_blue1]Bảng Điều Khiển Nhanh[/bold deep_sky_blue1]", border_style="deep_sky_blue1")


def _build_recent_reports_panel(snapshot: DashboardSnapshot) -> Panel:
    table = Table(expand=True, box=box.SIMPLE_HEAVY)
    table.add_column("Thời gian", style="gray50", width=11)
    table.add_column("Tệp", style="bold white")
    table.add_column("Người gửi", style="cyan", width=24)
    table.add_column("Doanh thu", style="green", justify="right", width=14)
    table.add_column("LN ròng", style="yellow", justify="right", width=14)
    table.add_column("Rủi ro", style="magenta")
    table.add_column("Trạng thái", style="bold")

    for row in snapshot.recent_reports[:5]:
        table.add_row(
            row.received_at,
            row.file_name,
            row.sender,
            row.revenue,
            row.net_income,
            row.risk,
            row.status,
        )

    return Panel(table, title="[bold deep_sky_blue1]Báo Cáo Gần Nhất[/bold deep_sky_blue1]", border_style="deep_sky_blue1")


def _build_evidence_panel(snapshot: DashboardSnapshot) -> Panel:
    return Panel(
        Text(snapshot.evidence_preview, style="white"),
        title="[bold deep_sky_blue1]Chứng Cứ & Preview Đầu Vào[/bold deep_sky_blue1]",
        border_style="deep_sky_blue1",
        expand=True,
    )


def _build_actions_panel(snapshot: DashboardSnapshot) -> Panel:
    body = Text()
    for hint in snapshot.action_hints:
        body.append(f"• {hint}\n", style="white")
    body.append(f"\nLần refresh cuối: {snapshot.last_refresh}", style="dim")
    return Panel(body, title="[bold deep_sky_blue1]Điểm Chạm Nhanh[/bold deep_sky_blue1]", border_style="deep_sky_blue1")


def _build_header_panel(snapshot: DashboardSnapshot) -> Panel:
    header_text = Text()
    header_text.append("🛡️ TAXSENTRY 0.2.1\n", style="bold white")
    header_text.append(f"Chủ hệ thống: {snapshot.director_name} • AI: {snapshot.model_name or '[chưa cấu hình]'}\n", style="white")
    header_text.append(f"LLM: {snapshot.llm_url} • Database: {snapshot.database_status} • Telegram: {snapshot.telegram_status}", style="dim white")
    return Panel(header_text, border_style="deep_sky_blue1", style="bold white on deep_sky_blue1")


def _build_footer_panel() -> Panel:
    footer_text = Text("Phím tắt: [c] chat • [Ctrl+C] thoát an toàn • dashboard tự làm mới theo chu kỳ", justify="center", style="bold sky_blue1")
    return Panel(footer_text, border_style="deep_sky_blue1")


def build_dashboard_layout(snapshot: DashboardSnapshot | None = None) -> Layout:
    snapshot = snapshot or collect_dashboard_snapshot()
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=7),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=4),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    layout["left"].split_column(
        Layout(name="summary", ratio=4),
        Layout(name="reports", ratio=6),
    )
    layout["right"].split_column(
        Layout(name="evidence", ratio=7),
        Layout(name="actions", ratio=3),
    )

    layout["header"].update(_build_header_panel(snapshot))
    layout["left"]["summary"].update(_build_summary_panel(snapshot))
    layout["left"]["reports"].update(_build_recent_reports_panel(snapshot))
    layout["right"]["evidence"].update(_build_evidence_panel(snapshot))
    layout["right"]["actions"].update(_build_actions_panel(snapshot))
    layout["footer"].update(_build_footer_panel())
    return layout
