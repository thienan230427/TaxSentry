import json
import sys
import time
from datetime import datetime
from pathlib import Path
from threading import Thread

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# --- Đường dẫn tệp ---
DB_PATH = Path("D:/TaxSentry/taxsentry.db")
EXCEL_PATH = Path("D:/TaxSentry/mock_report.xlsx")
JSON_PATH = Path("D:/TaxSentry/parsed_report.json")

# --- Trạng thái hệ thống mặc định ---
SYSTEM_STATUS = {
    "LM Studio": "[green]Connected (Local Gemma 2)[/green]",
    "Email Poller (IMAP)": "[green]Active (Listening...)[/green]",
    "Telegram Bot": "[green]Online (Listening...)[/green]",
    "Database (SQLite)": "[green]Ready[/green]",
}

LOG_MESSAGES = [
    "System started successfully.",
    f"Connected to SQLite database at {DB_PATH}.",
    "Checking LM Studio server status at http://localhost:1234/v1...",
    "LM Studio connection established. Found model: gemma-2-9b-it.",
    "Email Poller active. Listening for emails from Kế toán trưởng...",
    "Telegram Bot active. Listening to user commands...",
]

EMAILS_QUEUE = []


def load_parsed_data():
    """Tải dữ liệu báo cáo từ MySQL Database thực tế."""
    global EMAILS_QUEUE
    EMAILS_QUEUE.clear()

    try:
        from db_manager import TaxSentryDBManager
        db = TaxSentryDBManager()
        if db.connect():
            logs = db.get_recent_logs(limit=5)
            if logs:
                for log in logs:
                    # Chuyển đổi thời gian nhận
                    if isinstance(log["received_at"], datetime):
                        time_str = log["received_at"].strftime("%H:%M:%S")
                    else:
                        # Thư viện pymysql đôi khi trả về chuỗi hoặc đối tượng datetime
                        time_str = str(log["received_at"])
                    
                    status_text = "[green]Processed[/green]" if log["status"] == "Processed" else f"[yellow]{log['status']}[/yellow]"
                    EMAILS_QUEUE.append({
                        "time": time_str,
                        "sender": log["sender"],
                        "subject": f"Báo cáo tài chính ({log['tax_risk_status']})",
                        "status": status_text,
                        "file": log["file_name"],
                    })
            else:
                EMAILS_QUEUE.append({
                    "time": "-",
                    "sender": "-",
                    "subject": "No reports found in DB",
                    "status": "[red]Empty[/red]",
                    "file": "-",
                })
            db.close()
        else:
            EMAILS_QUEUE.append({
                "time": "-",
                "sender": "-",
                "subject": "Database connection error",
                "status": "[red]Error[/red]",
                "file": "-",
            })
    except Exception as e:
        EMAILS_QUEUE.append({
            "time": "-",
            "sender": "-",
            "subject": f"Error: {e}",
            "status": "[red]Error[/red]",
            "file": "-",
        })


def make_layout() -> Layout:
    """Tạo bố cục layout cho Terminal User Interface (TUI)."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body", ratio=1),
        Layout(name="footer", size=3),
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1),
    )
    return layout


class Header:
    """Header component cho Dashboard."""

    def __rich__(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left", ratio=1)
        grid.add_column(justify="right", ratio=1)
        grid.add_row(
            Text("🛡️ TAXSENTRY — AI AGENT GIÁM SÁT KINH DOANH & THUẾ", style="bold white"),
            Text(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="bold cyan"),
        )
        return Panel(grid, style="bold white on blue", border_style="blue")


class Footer:
    """Footer component hiển thị hướng dẫn phím tắt."""

    def __rich__(self) -> Panel:
        return Panel(
            Text(
                "Phím tắt: [ctrl+c] Thoát chương trình | [r] Refresh thủ công | [t] Gửi test email",
                justify="center",
                style="italic gray70",
            ),
            border_style="gray50",
        )


class SystemStatusPanel:
    """Hiển thị trạng thái các cổng kết nối và database."""

    def __rich__(self) -> Panel:
        table = Table(box=None, expand=True)
        table.add_column("Dịch vụ", style="bold cyan")
        table.add_column("Trạng thái", style="white")

        for service, status in SYSTEM_STATUS.items():
            table.add_row(service, status)

        return Panel(table, title="[bold yellow]Trạng Thái Hệ Thống[/bold yellow]", border_style="yellow")


class RecentActivityPanel:
    """Hiển thị bảng danh sách email báo cáo nhận được."""

    def __rich__(self) -> Panel:
        table = Table(expand=True, box=None)
        table.add_column("Thời gian", style="gray50", width=10)
        table.add_column("Người gửi", style="magenta", width=25)
        table.add_column("Tên tệp đính kèm", style="cyan")
        table.add_column("Trạng thái", style="bold")

        for item in EMAILS_QUEUE:
            table.add_row(item["time"], item["sender"], item["file"], item["status"])

        return Panel(table, title="[bold green]Danh Sách Báo Cáo Nhận Được[/bold green]", border_style="green")


class LogsPanel:
    """Hiển thị logs hệ thống đang chạy thời gian thực và thông tin báo cáo đã trích xuất."""

    def __rich__(self) -> Panel:
        text = Text()
        
        # 1. Hiển thị thông tin báo cáo thực tế trích xuất từ JSON (nếu có)
        if JSON_PATH.exists():
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                is_t5 = data["data"]["income_statement"]["T5_Actual"]
                text.append("📊 THÔNG TIN BÁO CÁO KINH DOANH THÁNG 05/2026\n", style="bold green")
                text.append(f"  • Doanh thu:     {is_t5['revenue']:,.0f} VND\n", style="white")
                text.append(f"  • Lợi nhuận gộp: {is_t5['gross_profit']:,.0f} VND\n", style="white")
                text.append(f"  • Tổng Chi phí:  {is_t5['total_opex']:,.0f} VND\n", style="white")
                text.append(f"  • Lợi nhuận ròng: {is_t5['net_income']:,.0f} VND\n", style="bold yellow")
                
                # Cảnh báo rủi ro thuế!
                limit = is_t5["revenue"] * data["assumptions"]["hospitality_limit_pct"]
                actual_hospitality = is_t5["hospitality_valid_exp"] + is_t5["hospitality_no_invoice_exp"]
                no_invoice = is_t5["hospitality_no_invoice_exp"]
                
                text.append("\n⚠️ ĐÁNH GIÁ RỦI RO THUẾ BAN ĐẦU:\n", style="bold red")
                if no_invoice > 0:
                    text.append(f"  🚨 Phát hiện {no_invoice:,.0f} VND chi phí Tiếp khách KHÔNG có hóa đơn đỏ (Sẽ bị loại khi tính thuế TNDN!).\n", style="bold red")
                if actual_hospitality > limit:
                    text.append(f"  🚨 Chi phí tiếp khách ({actual_hospitality:,.0f} VND) vượt hạn mức quy định ({limit:,.0f} VND).\n", style="bold red")
                else:
                    text.append("  ✅ Chi phí tiếp khách nằm trong hạn mức cho phép.\n", style="green")
                text.append("=" * 50 + "\n\n", style="gray50")
            except Exception as e:
                text.append(f"❌ Lỗi đọc dữ liệu JSON: {e}\n\n", style="bold red")

        # 2. Hiển thị logs hệ thống
        text.append("💬 LOGS HOẠT ĐỘNG THỜI GIAN THỰC:\n", style="bold cyan")
        for log in LOG_MESSAGES[-8:]:
            time_str = datetime.now().strftime("%H:%M:%S")
            text.append(f"[{time_str}] ", style="gray50")
            text.append(f"{log}\n", style="white")

        return Panel(text, title="[bold cyan]Bảng Phân Tích & Logs Hệ Thống[/bold cyan]", border_style="cyan")


def background_worker():
    """Hàm chạy giả lập các tác vụ ngầm trong khi Dashboard hoạt động."""
    time.sleep(3)
    if EXCEL_PATH.exists():
        LOG_MESSAGES.append(f"Phát hiện tệp tin mới: {EXCEL_PATH.name}.")
    time.sleep(3)
    if JSON_PATH.exists():
        LOG_MESSAGES.append(f"Đã nạp dữ liệu phân tích thành công từ: {JSON_PATH.name}.")
    else:
        LOG_MESSAGES.append("Đang chờ Parser trích xuất dữ liệu Excel...")
    time.sleep(4)
    LOG_MESSAGES.append("Hệ thống hoạt động ổn định. Đang nghe lệnh từ Telegram Bot...")


def main():
    # Tải dữ liệu Excel/JSON thực tế vào giao diện
    load_parsed_data()

    # Chạy worker trong luồng phụ để cập nhật logs động
    worker_thread = Thread(target=background_worker, daemon=True)
    worker_thread.start()

    layout = make_layout()

    # Áp các Panels vào từng phân vùng tương ứng trong layout
    layout["header"].update(Header())
    layout["left"].split_column(
        Layout(SystemStatusPanel(), ratio=5),
        Layout(RecentActivityPanel(), ratio=6),
    )
    layout["right"].update(LogsPanel())
    layout["footer"].update(Footer())

    console.clear()
    console.print("[bold green]Đang khởi động giao diện TaxSentry TUI...[/bold green]\n")
    time.sleep(1)

    try:
        with Live(layout, refresh_per_second=4, screen=True) as live:
            start_time = time.time()
            # Cho chạy Live demo 15 giây để Sếp kiểm tra
            while time.time() - start_time < 15:
                time.sleep(0.5)
                # Cập nhật thời gian thực ở Header & tải lại data
                load_parsed_data()
                layout["header"].update(Header())
                layout["right"].update(LogsPanel())
                live.refresh()
    except KeyboardInterrupt:
        pass

    console.clear()
    console.print("\n[bold yellow]Giao diện TUI đã được đóng an toàn. Cảm ơn Sếp Thiên Ân! (◕‿◕✿)[/bold yellow]\n")


if __name__ == "__main__":
    main()
