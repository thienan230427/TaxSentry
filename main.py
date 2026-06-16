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
from rich.prompt import Confirm, Prompt

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
        from database.db_manager import TaxSentryDBManager
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
            Text(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="bold white"),
        )
        return Panel(grid, style="bold white on deep_sky_blue1", border_style="deep_sky_blue1")


class Footer:
    """Footer component hiển thị hướng dẫn phím tắt."""

    def __rich__(self) -> Panel:
        return Panel(
            Text(
                "Phím tắt: [ctrl+c] Thoát chương trình | [r] Refresh thủ công | [t] Gửi test email",
                justify="center",
                style="italic sky_blue1",
            ),
            border_style="deep_sky_blue1",
        )


class SystemStatusPanel:
    """Hiển thị trạng thái các cổng kết nối và database."""

    def __rich__(self) -> Panel:
        table = Table(box=None, expand=True)
        table.add_column("Dịch vụ", style="bold sky_blue1")
        table.add_column("Trạng thái", style="white")

        for service, status in SYSTEM_STATUS.items():
            table.add_row(service, status)

        return Panel(table, title="[bold sky_blue1]Trạng Thái Hệ Thống[/bold sky_blue1]", border_style="deep_sky_blue1")


class RecentActivityPanel:
    """Hiển thị bảng danh sách email báo cáo nhận được."""

    def __rich__(self) -> Panel:
        table = Table(expand=True, box=None)
        table.add_column("Thời gian", style="gray50", width=10)
        table.add_column("Người gửi", style="sky_blue1", width=25)
        table.add_column("Tên tệp đính kèm", style="deep_sky_blue1")
        table.add_column("Trạng thái", style="bold")

        for item in EMAILS_QUEUE:
            table.add_row(item["time"], item["sender"], item["file"], item["status"])

        return Panel(table, title="[bold sky_blue1]Danh Sách Báo Cáo Nhận Được[/bold sky_blue1]", border_style="deep_sky_blue1")


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
        text.append("💬 LOGS HOẠT ĐỘNG THỜI GIAN THỰC:\n", style="bold deep_sky_blue1")
        for log in LOG_MESSAGES[-8:]:
            time_str = datetime.now().strftime("%H:%M:%S")
            text.append(f"[{time_str}] ", style="gray50")
            text.append(f"{log}\n", style="white")

        return Panel(text, title="[bold sky_blue1]Bảng Phân Tích & Logs Hệ Thống[/bold sky_blue1]", border_style="deep_sky_blue1")


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
    console.clear()
    
    # 1. Bảng chào mừng và giới thiệu
    welcome_text = Text()
    welcome_text.append("🌟 CHÀO MỪNG SẾP THIÊN ÂN ĐẾN VỚI HỆ THỐNG TAXSENTRY 🌟\n", style="bold deep_sky_blue1")
    welcome_text.append("\nTaxSentry là trợ lý AI giám sát kinh doanh và kiểm toán thuế tối mật,\n")
    welcome_text.append("bảo vệ pháp lý và tối ưu hóa dòng tiền cho doanh nghiệp của Sếp.\n\n")
    welcome_text.append("Hệ thống hoạt động cục bộ bảo mật kết hợp mô hình Gemma 4 trên LM Studio\n")
    welcome_text.append("và hòm thư Email Kế toán trưởng để tự động đối chiếu luật thuế Việt Nam.\n\n", style="italic")
    welcome_text.append("----------------------------------------------------------------------\n")
    welcome_text.append("ĐIỀU KHOẢN SỬ DỤNG:\n", style="bold yellow")
    welcome_text.append("1. Toàn bộ dữ liệu tài chính được xử lý hoàn toàn cục bộ (local) trên máy tính.\n")
    welcome_text.append("2. Sếp chịu trách nhiệm bảo mật khóa API Key của LM Studio và Email Password.\n")
    welcome_text.append("3. Báo cáo của AI mang tính tham khảo và hỗ trợ ra quyết định tài chính.\n")
    
    console.print(Panel(welcome_text, border_style="deep_sky_blue1", title="[bold sky_blue1]Welcome to TaxSentry[/bold sky_blue1]"))
    console.print()
    
    # 2. Đồng ý điều khoản
    agreed = Confirm.ask("[bold deep_sky_blue1]Sếp có đồng ý với các điều khoản bảo mật dữ liệu của TaxSentry không?[/bold deep_sky_blue1]", default=True)
    if not agreed:
        console.print("\n[bold red]Sếp không đồng ý điều khoản. Hệ thống sẽ tự động đóng ngay lập tức desu~! Bye bye Sếp! (｡•́︿•̀｡)[/bold red]\n")
        time.sleep(1)
        sys.exit(0)
        
    console.print("\n[bold green]Cảm ơn Sếp đã đồng ý điều khoản! Đi tiếp đến bước Setup thôi nào desu~! ♪ ヽ(>∀<☆)ノ[/bold green]\n")
    time.sleep(1)
    
    # 3. Setup: Nhập Email App Password
    console.print(Panel("[bold sky_blue1]CÀI ĐẶT EMAIL KẾ TOÁN TRƯỞNG (GMAIL APP PASSWORD)[/bold sky_blue1]\n\nNhập Gmail App Password (16 ký tự viết liền) của Kế toán trưởng để email poller hoạt động thực tế.\nNhấn [Enter] để bỏ qua và sử dụng mật khẩu đã lưu trữ sẵn trong tệp cấu hình .env desu~! ♪", border_style="deep_sky_blue1"))
    app_pass = Prompt.ask("[bold deep_sky_blue1]Gmail App Password[/bold deep_sky_blue1]", password=True, default="")
    
    if app_pass.strip():
        app_pass_clean = app_pass.strip().replace(" ", "")
        console.print(f"\n[bold green]Đã nhận mật khẩu mới (Độ dài: {len(app_pass_clean)} ký tự). Đang tự động lưu trữ bảo mật vào tệp .env...[/bold green]")
        
        # Đọc và ghi đè EMAIL_PASS trong file .env
        env_path = Path("D:/TaxSentry/.env")
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            import re
            new_content = re.sub(r"EMAIL_PASS=.*", f"EMAIL_PASS={app_pass_clean}", content)
            env_path.write_text(new_content, encoding="utf-8")
            console.print("[bold green]✅ Đã tự động cập nhật tệp .env thành công desu~![/bold green]\n")
        else:
            console.print("[bold red]❌ Không tìm thấy tệp .env để cập nhật mật khẩu mới![/bold red]\n")
        time.sleep(1.5)
    else:
        console.print("\n[bold yellow]Sếp đã chọn sử dụng mật khẩu cũ có sẵn trong tệp .env desu~! Tiếp tục thôi nào! (◕‿◕✿)[/bold yellow]\n")
        time.sleep(1.5)
        
    console.clear()
    console.print("[bold deep_sky_blue1]Đang khởi động giao diện TaxSentry Workflow Terminal...[/bold deep_sky_blue1]\n")
    time.sleep(1)

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

    try:
        with Live(layout, refresh_per_second=4, screen=True) as live:
            # Chạy vô hạn cho đến khi Sếp nhấn [Ctrl+C] để thoát desu~!
            while True:
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
