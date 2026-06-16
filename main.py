import sys
import time
from datetime import datetime
from threading import Thread

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

# --- Shared Global State for Dashboard ---
SYSTEM_STATUS = {
    "LM Studio": "[green]Connected (Local Gemma 2)[/green]",
    "Email Poller (IMAP)": "[green]Active (Listening...)[/green]",
    "Telegram Bot": "[green]Online (Listening...)[/green]",
    "Database (SQLite)": "[green]Ready[/green]",
}

LOG_MESSAGES = [
    "System started successfully.",
    "Connected to SQLite database at D:/TaxSentry/taxsentry.db.",
    "Checking LM Studio server status at http://localhost:1234/v1...",
    "LM Studio connection established. Found model: gemma-2-9b-it.",
    "Connecting to IMAP email server...",
    "Email Poller started in background thread.",
    "Telegram Bot active. Listening to user commands...",
]

EMAILS_QUEUE = [
    {
        "time": "14:20:15",
        "sender": "ke-toan-truong@company.com",
        "subject": "Bao cao tai chinh thang 05/2026",
        "status": "[green]Completed[/green]",
        "file": "BC_KinhDoanh_T5.xlsx",
    }
]


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
        Layout(name="right", ratio=1),  # Thay đổi từ 1.2 (float) thành 1 (integer) để tương thích 100% với Python 3.14 desu~!
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
    """Hiển thị logs hệ thống đang chạy thời gian thực."""

    def __rich__(self) -> Panel:
        text = Text()
        # Chỉ lấy 10 logs gần nhất để không bị tràn khung
        for log in LOG_MESSAGES[-10:]:
            time_str = datetime.now().strftime("%H:%M:%S")
            text.append(f"[{time_str}] ", style="gray50")
            text.append(f"{log}\n", style="white")

        return Panel(text, title="[bold cyan]Logs Hoạt Động (Real-time Logs)[/bold cyan]", border_style="cyan")


def background_worker():
    """Hàm chạy giả lập các tác vụ ngầm trong khi Dashboard hoạt động."""
    time.sleep(5)
    LOG_MESSAGES.append("Quét hòm thư email mới... Không có email mới.")
    time.sleep(5)
    LOG_MESSAGES.append("Đang kiểm tra kết nối với Telegram API...")
    time.sleep(3)
    LOG_MESSAGES.append("Đã đồng bộ hóa dữ liệu SQLite thành công.")


def main():
    # Chạy worker trong luồng phụ để cập nhật logs động
    worker_thread = Thread(target=background_worker, daemon=True)
    worker_thread.start()

    layout = make_layout()

    # Áp các Panels vào từng phân vùng tương ứng trong layout
    layout["header"].update(Header())
    layout["left"].split_column(
        Layout(SystemStatusPanel(), ratio=5),
        Layout(RecentActivityPanel(), ratio=6),  # Thay đổi từ 1.2 thành 6 (và 1 thành 5) để giữ nguyên tỷ lệ nhưng hoàn toàn dùng số nguyên (integers), tránh lỗi Python 3.14 desu~!
    )
    layout["right"].update(LogsPanel())
    layout["footer"].update(Footer())

    console.clear()
    console.print("[bold green]Đang khởi động giao diện TaxSentry TUI...[/bold green]\n")
    time.sleep(1)

    # Chạy Live render giao diện thời gian thực trong 15 giây để Sếp kiểm tra (hoặc chạy vô hạn cho đến khi Ctrl+C)
    # Ở đây chúng ta cho chạy Live để Sếp chiêm ngưỡng giao diện desu~!
    try:
        with Live(layout, refresh_per_second=4, screen=True) as live:
            # Cho chạy loop cập nhật đồng hồ và logs
            start_time = time.time()
            while time.time() - start_time < 15:  # Chạy thử 15 giây để Sếp xem demo
                time.sleep(0.5)
                # Cập nhật thời gian thực ở Header
                layout["header"].update(Header())
                # Render lại
                live.refresh()
    except KeyboardInterrupt:
        pass

    console.clear()
    console.print("\n[bold yellow]Giao diện TUI đã được đóng an toàn. Cảm ơn Sếp Thiên Ân! (◕‿◕✿)[/bold yellow]\n")


if __name__ == "__main__":
    main()
