import sys
import os
import subprocess
from pathlib import Path

if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from taxsentry.utils.runtime import bootstrap_into_venv, get_project_root, get_venv_python

# Tự động kích hoạt môi trường ảo nếu cần thiết
bootstrap_into_venv(["-m", "taxsentry", *sys.argv[1:]])

# Tiến hành import các thư viện sau khi đã chắc chắn chạy trong môi trường ảo
import json
import time
import re
from datetime import datetime
from threading import Thread

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.prompt import Confirm, Prompt

console = Console()

from taxsentry.config.paths import DB_PATH, EXCEL_PATH, JSON_PATH, ENV_PATH

# --- Dynamic config readers (đọc từ env, không hardcode) ---
def get_model_display_name() -> str:
    """Lấy tên model từ config, format đẹp để hiển thị."""
    model = os.getenv("LM_MODEL_NAME", "")
    if not model:
        return "[yellow]Not Configured[/yellow]"
    # Lấy phần cuối của model name (sau /) và capitalize
    display = model.split("/")[-1] if "/" in model else model
    return f"[green]Connected ({display})[/green]"

def get_llm_server_url() -> str:
    """Lấy URL server AI từ config."""
    return os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")

def get_director_name() -> str:
    """Lấy tên Giám đốc từ config."""
    return os.getenv("DIRECTOR_NAME", "") or ""

def get_director_email() -> str:
    """Lấy email Giám đốc từ config."""
    return os.getenv("DIRECTOR_EMAIL", "") or ""

def get_accountant_email() -> str:
    """Lấy email Kế toán trưởng từ config."""
    return os.getenv("ACCOUNTANT_EMAIL", "") or ""

def get_email_user() -> str:
    """Lấy email hệ thống (IMAP login) từ config."""
    return os.getenv("EMAIL_USER", "") or ""

# --- Trạng thái hệ thống (dynamic, cập nhật từ config) ---
SYSTEM_STATUS = {
    "LM Studio": "[yellow]Checking...[/yellow]",
    "Automation Workflow": "[green]Active (Polling 60s)[/green]",
    "Telegram Bot": "[yellow]Offline (Connecting...)[/yellow]",
    "Database (SQLite)": "[green]Connected (Local DB)[/green]",
}

LOG_MESSAGES = [
    "Hệ thống giám sát TaxSentry bắt đầu khởi chạy.",
    f"Đang liên kết cơ sở dữ liệu SQLite cục bộ (Zero-Setup).",
]

EMAILS_QUEUE = []


def load_parsed_data():
    """Tải dữ liệu báo cáo từ MySQL Database thực tế."""
    global EMAILS_QUEUE
    EMAILS_QUEUE.clear()

    try:
        from taxsentry.database.db_manager import TaxSentryDBManager
        db = TaxSentryDBManager()
        if db.connect():
            logs = db.get_recent_logs(limit=5)
            if logs:
                for log in logs:
                    if isinstance(log["received_at"], datetime):
                        time_str = log["received_at"].strftime("%H:%M:%S")
                    else:
                        time_str = str(log["received_at"])
                    
                    status_text = "[green]Đã xử lý[/green]" if log["status"] == "Processed" else f"[yellow]{log['status']}[/yellow]"
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
                    "subject": "Không tìm thấy dữ liệu trong Database",
                    "status": "[red]Trống[/red]",
                    "file": "-",
                })
            db.close()
        else:
            EMAILS_QUEUE.append({
                "time": "-",
                "sender": "-",
                "subject": "Lỗi kết nối cơ sở dữ liệu",
                "status": "[red]Lỗi[/red]",
                "file": "-",
            })
    except Exception as e:
        EMAILS_QUEUE.append({
            "time": "-",
            "sender": "-",
            "subject": f"Lỗi hệ thống: {e}",
            "status": "[red]Lỗi[/red]",
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
        director_name = os.getenv("DIRECTOR_NAME", "")
        title_text = f"🛡️ TAXSENTRY — HỆ THỐNG AI KIỂM TOÁN DÀNH CHO GIÁM ĐỐC: {director_name.upper()}" if director_name else "🛡️ TAXSENTRY — HỆ THỐNG AI KIỂM TOÁN"
        grid.add_row(
            Text(title_text, style="bold white"),
            Text(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", style="bold white"),
        )
        return Panel(grid, style="bold white on deep_sky_blue1", border_style="deep_sky_blue1")


class Footer:
    """Footer component hiển thị hướng dẫn phím tắt."""

    def __rich__(self) -> Panel:
        return Panel(
            Text(
                "Phím tắt: [c] Chat với Trợ lý AI | [ctrl+c] Thoát hệ thống | Nhật ký cập nhật tự động",
                justify="center",
                style="bold italic sky_blue1",
            ),
            border_style="deep_sky_blue1",
        )


class SystemStatusPanel:
    """Hiển thị trạng thái các cổng kết nối và database."""

    def __rich__(self) -> Panel:
        table = Table(box=None, expand=True)
        table.add_column("Dịch vụ hệ thống", style="bold sky_blue1")
        table.add_column("Trạng thái", style="white")

        for service, status in SYSTEM_STATUS.items():
            table.add_row(service, status)

        return Panel(table, title="[bold sky_blue1]Trạng Thái Kết Nối Hệ Thống[/bold sky_blue1]", border_style="deep_sky_blue1")


class RecentActivityPanel:
    """Hiển thị bảng danh sách email báo cáo nhận được."""

    def __rich__(self) -> Panel:
        table = Table(expand=True, box=None)
        table.add_column("Thời gian", style="gray50", width=10)
        table.add_column("Kế toán trưởng", style="sky_blue1", width=25)
        table.add_column("Tên tài liệu", style="deep_sky_blue1")
        table.add_column("Trạng thái", style="bold")

        for item in EMAILS_QUEUE:
            table.add_row(item["time"], item["sender"], item["file"], item["status"])

        return Panel(table, title="[bold sky_blue1]Nhật Ký Nhận Báo Cáo Tài Chính[/bold sky_blue1]", border_style="deep_sky_blue1")


class LogsPanel:
    """Hiển thị logs hệ thống đang chạy thời gian thực và thông tin báo cáo đã trích xuất."""

    @staticmethod
    def _fmt_currency(value) -> str:
        if isinstance(value, (int, float)):
            return f"{value:,.0f} VND"
        return "n/a"

    def _append_report_summary(self, text: Text, data: dict) -> None:
        metadata = data.get("metadata", {})
        parsed_at = metadata.get("parsed_at", "")
        period_display = f"({parsed_at})" if parsed_at else f"(Cập nhật: {datetime.now().strftime('%m/%Y')})"

        income_statement = data.get("data", {}).get("income_statement", {})
        is_t5 = income_statement.get("T5_Actual", {}) or {}
        assumptions = data.get("assumptions", {}) or {}
        canonical = data.get("data", {}).get("canonical_metrics", {}) or {}
        document_types = metadata.get("document_types", []) or data.get("data", {}).get("workbook_overview", {}).get("document_types", []) or []

        if all(key in is_t5 for key in ("revenue", "gross_profit", "total_opex", "net_income")):
            text.append(f"📊 THÔNG TIN BÁO CÁO KINH DOANH {period_display}\n", style="bold green")
            text.append(f"  • Doanh thu thuần:  {self._fmt_currency(is_t5.get('revenue'))}\n", style="white")
            text.append(f"  • Lợi nhuận gộp:   {self._fmt_currency(is_t5.get('gross_profit'))}\n", style="white")
            text.append(f"  • Chi phí vận hành: {self._fmt_currency(is_t5.get('total_opex'))}\n", style="white")
            text.append(f"  • Lợi nhuận ròng:   {self._fmt_currency(is_t5.get('net_income'))}\n", style="bold yellow")

            revenue = is_t5.get("revenue")
            hospitality_limit_pct = assumptions.get("hospitality_limit_pct")
            hospitality_valid = is_t5.get("hospitality_valid_exp") or 0
            hospitality_no_invoice = is_t5.get("hospitality_no_invoice_exp") or 0
            limit = revenue * hospitality_limit_pct if revenue is not None and hospitality_limit_pct is not None else None
            actual_hospitality = hospitality_valid + hospitality_no_invoice

            text.append("\n⚠️ ĐÁNH GIÁ RỦI RO THUẾ BAN ĐẦU:\n", style="bold red")
            if hospitality_no_invoice > 0:
                text.append(
                    f"  🚨 Phát hiện {hospitality_no_invoice:,.0f} VND chi phí tiếp khách không có hóa đơn đỏ (có thể bị loại khi quyết toán thuế TNDN).\n",
                    style="bold red",
                )
            if limit is not None and actual_hospitality > limit:
                text.append(
                    f"  🚨 Chi phí tiếp khách ({actual_hospitality:,.0f} VND) vượt hạn mức quy định ({limit:,.0f} VND).\n",
                    style="bold red",
                )
            else:
                text.append("  ✅ Chưa thấy cảnh báo hạn mức tiếp khách từ dữ liệu hiện tại.\n", style="green")
            text.append("=" * 50 + "\n\n", style="gray50")
            return

        if "payroll" in document_types or any(key in canonical for key in ("total_income", "personal_income_tax", "social_insurance", "net_pay")):
            text.append(f"📋 THÔNG TIN BẢNG LƯƠNG / CHI TRẢ NHÂN SỰ {period_display}\n", style="bold green")
            text.append(
                f"  • Tổng thu nhập chi trả: {self._fmt_currency(canonical.get('total_income', {}).get('value'))}\n",
                style="white",
            )
            text.append(
                f"  • Bảo hiểm bắt buộc:    {self._fmt_currency(canonical.get('social_insurance', {}).get('value'))}\n",
                style="white",
            )
            text.append(
                f"  • Thuế TNCN tạm khấu trừ: {self._fmt_currency(canonical.get('personal_income_tax', {}).get('value'))}\n",
                style="white",
            )
            text.append(
                f"  • Thực lĩnh:            {self._fmt_currency(canonical.get('net_pay', {}).get('value'))}\n",
                style="bold yellow",
            )
            text.append("\nℹ️ Đây là file payroll, nên bảng bên này hiển thị số chi trả nhân sự thay vì chỉ tiêu doanh thu/lợi nhuận.\n", style="cyan")
            text.append("=" * 50 + "\n\n", style="gray50")
            return

        text.append(f"📄 ĐÃ NHẬN DỮ LIỆU MỚI {period_display}\n", style="bold green")
        if document_types:
            text.append(f"  • Loại dữ liệu nhận diện: {', '.join(document_types)}\n", style="white")
        if canonical:
            for key, label in [
                ("revenue", "Doanh thu"),
                ("gross_profit", "Lợi nhuận gộp"),
                ("total_opex", "Tổng chi phí vận hành"),
                ("net_income", "Lợi nhuận ròng"),
                ("total_income", "Tổng thu nhập chi trả"),
            ]:
                metric = canonical.get(key)
                if metric:
                    text.append(f"  • {label}: {self._fmt_currency(metric.get('value'))}\n", style="white")
        text.append("=" * 50 + "\n\n", style="gray50")

    def __rich__(self) -> Panel:
        text = Text()

        if JSON_PATH.exists():
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._append_report_summary(text, data)
            except Exception as e:
                text.append(f"❌ Không thể đọc tệp dữ liệu phân tích JSON: {e}\n\n", style="bold red")

        text.append("💬 NHẬT KÝ HOẠT ĐỘNG HỆ THỐNG THỜI GIAN THỰC:\n", style="bold deep_sky_blue1")
        from taxsentry.core.automation import AUTOMATION_LOGS

        for log in LOG_MESSAGES[-10:]:
            line = Text()
            line.append("[Khởi tạo] ", style="gray50")
            line.append(str(log), style="white")
            text.append_text(line)
            text.append("\n")

        for log in AUTOMATION_LOGS[-10:]:
            text.append(f"{log}\n", style="white")

        return Panel(text, title="[bold sky_blue1]Nhật Ký Hoạt Động & Đánh Giá Ban Đầu[/bold sky_blue1]", border_style="deep_sky_blue1")


TELEGRAM_PROCESS = None

def start_telegram_gateway():
    """Khởi chạy Telegram Bot chạy ngầm dưới dạng tiến trình con."""
    global TELEGRAM_PROCESS
    LOG_MESSAGES.append("Đang kích hoạt kết nối Telegram Bot Gateway...")

    # Kiểm tra Token và Chat ID trong .env trước khi start
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("ADMIN_CHAT_ID")
    if not token or token == "YOUR_BOT_TOKEN_HERE" or not chat_id:
        LOG_MESSAGES.append("⚠️ Telegram Bot Gateway: Chưa cấu hình token/chat id trong .env. Bỏ qua khởi động.")
        return False

    # Tìm Python executable
    root_dir = get_project_root(Path(__file__).resolve())
    venv_python = get_venv_python(root_dir) or Path(sys.executable)

    try:
        # Chạy bot qua module path (dùng cấu trúc src layout mới)
        # python -m taxsentry.bot.telegram_bot --admin-chat-id <id>
        TELEGRAM_PROCESS = subprocess.Popen(
            [str(venv_python), '-m', 'taxsentry.bot.telegram_bot', '--admin-chat-id', chat_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=str(root_dir),
        )
        LOG_MESSAGES.append("✅ Telegram Bot Gateway: Khởi chạy kết nối thành công!")
        return True
    except Exception as e:
        LOG_MESSAGES.append(f"❌ Telegram Bot Gateway: Lỗi khởi chạy: {e}")
        return False


def background_worker():
    """Khởi chạy Automation Workflow chạy nền định kỳ thực tế."""
    LOG_MESSAGES.append("Đang khởi tạo luồng tự động hóa chạy ngầm...")
    try:
        from taxsentry.core.automation import TaxSentryAutomationWorkflow
        workflow = TaxSentryAutomationWorkflow()
        LOG_MESSAGES.append("Hệ thống tự động hóa khởi chạy thành công!")
        workflow.start_loop(60)
    except Exception as e:
        LOG_MESSAGES.append(f"❌ Lỗi khởi tạo luồng tự động hóa: {e}")


def write_env_file(config: dict):
    """Ghi đè/cập nhật tệp tin cấu hình .env một cách an toàn."""
    try:
        content = ""
        if ENV_PATH.exists():
            content = ENV_PATH.read_text(encoding="utf-8")
        
        for key, value in config.items():
            os.environ[key] = str(value)

            # Bo qua ghi neu gia tri rong va key da ton tai trong .env (giu nguyen gia tri cu)
            if not value and f"{key}=" in content:
                continue

            if f"{key}=" in content:
                content = re.sub(rf"{key}=.*", f"{key}={value}", content)
            else:
                if content and not content.endswith("\n"):
                    content += "\n"
                content += f"{key}={value}\n"
                
        ENV_PATH.write_text(content, encoding="utf-8")
        return True
    except Exception as e:
        console.print(f"[bold red]Lỗi lưu tệp cấu hình .env: {e}[/bold red]")
        return False


def run_onboarding_setup():
    """Luồng thiết lập cấu hình Onboarding toàn diện (OpenClaw-style)."""
    # Đọc cấu hình hiện tại trong .env để làm giá trị mặc định (default)
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=ENV_PATH)
    
    current_director = get_director_name() or ""
    
    console.clear()
    
    # Tiêu đề chào mừng
    welcome_text = Text()
    welcome_text.append("🛡️ BỘ CÀI ĐẶT CẤU HÌNH HỆ THỐNG TAXSENTRY (AI CO-PILOT) 🛡️\n", style="bold deep_sky_blue1")
    welcome_text.append(f"\nChào mừng Giám đốc {current_director} đến với trình thiết lập cấu hình Onboarding.\n")
    welcome_text.append("Hệ thống sẽ lưu trữ bảo mật các tham số môi trường và tự động ghi nhận vào tệp cấu hình cục bộ.\n\n", style="italic")
    welcome_text.append("--------------------------------------------------------------------------------\n")
    welcome_text.append("CHÍNH SÁCH BẢO MẬT & ĐIỀU KHOẢN SỬ DỤNG:\n", style="bold yellow")
    welcome_text.append("1. Toàn bộ dữ liệu tài chính, tài khoản email và khóa API được lưu trữ cục bộ (local).\n")
    welcome_text.append("2. Hệ thống xử lý ngôn ngữ tự nhiên thông qua mô hình cục bộ hoặc dịch vụ chỉ định.\n")
    welcome_text.append("3. Giám đốc chịu trách nhiệm quản lý quyền truy cập tệp tin cấu hình .env.\n")
    
    console.print(Panel(welcome_text, border_style="deep_sky_blue1", title="[bold sky_blue1]TaxSentry Setup Guide[/bold sky_blue1]"))
    console.print()
    
    agreed = Confirm.ask(f"[bold deep_sky_blue1]Giám đốc {current_director} có đồng ý với các điều khoản bảo mật dữ liệu trên không?[/bold deep_sky_blue1]", default=True)
    if not agreed:
        console.print("\n[bold red]Điều khoản bảo mật bị từ chối. Hệ thống sẽ tự động đóng.[/bold red]\n")
        time.sleep(1.5)
        sys.exit(0)
        
    console.print("\n[bold green]Điều khoản bảo mật được chấp thuận. Bắt đầu cấu hình hệ thống...[/bold green]\n")
    time.sleep(1)
    
    config_data = {}
    
    # --- PHẦN 1: CẤU HÌNH EMAIL ---
    console.print(Panel("[bold sky_blue1]PHẦN 1: CẤU HÌNH THƯ ĐIỆN TỬ (GMAIL STACK)[/bold sky_blue1]", border_style="deep_sky_blue1"))
    
    config_data["DIRECTOR_NAME"] = Prompt.ask(
        "[bold deep_sky_blue1]1. Họ và tên của Giám đốc[/bold deep_sky_blue1]",
        default=os.getenv("DIRECTOR_NAME", "")
    ).strip()
    
    # Nhận diện tên mới ngay lập tức
    new_director_name = config_data["DIRECTOR_NAME"]
    
    config_data["DIRECTOR_EMAIL"] = Prompt.ask(
        f"[bold deep_sky_blue1]2. Email nhận báo cáo của Giám đốc {new_director_name}[/bold deep_sky_blue1]",
        default=os.getenv("DIRECTOR_EMAIL", "")
    ).strip()
    
    config_data["ACCOUNTANT_EMAIL"] = Prompt.ask(
        "[bold deep_sky_blue1]3. Email gửi báo cáo của Kế toán trưởng[/bold deep_sky_blue1]",
        default=os.getenv("ACCOUNTANT_EMAIL", "")
    ).strip()
    
    config_data["EMAIL_USER"] = Prompt.ask(
        "[bold deep_sky_blue1]4. Email hệ thống (IMAP login - thường là email Giám đốc)[/bold deep_sky_blue1]",
        default=os.getenv("EMAIL_USER", "")
    ).strip()
    
    email_pass = Prompt.ask(
        "[bold deep_sky_blue1]5. Gmail App Password (16 ky tu) (bo trong de giu nguyen)[/bold deep_sky_blue1]",
        default=""
    ).strip()
    if email_pass:
        config_data["EMAIL_PASS"] = email_pass
    
    # --- PHẦN 2: CẤU HÌNH AI SERVER (LM STUDIO) ---
    console.print("\n", end="")
    console.print(Panel("[bold sky_blue1]PHẦN 2: CẤU HÌNH MÁY CHỦ TRÍ TUỆ NHÂN TẠO CỤC BỘ (LM STUDIO)[/bold sky_blue1]", border_style="deep_sky_blue1"))
    
    config_data["LM_STUDIO_URL"] = Prompt.ask(
        "[bold deep_sky_blue1]1. LM Studio Server API Base URL[/bold deep_sky_blue1]",
        default=os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
    ).strip()
    
    lm_api_key = Prompt.ask(
        "[bold deep_sky_blue1]2. LM Studio API Key (bo trong de giu nguyen)[/bold deep_sky_blue1]",
        default=""
    ).strip()
    if lm_api_key:
        config_data["LM_STUDIO_API_KEY"] = lm_api_key
    
    config_data["LM_MODEL_NAME"] = Prompt.ask(
        "[bold deep_sky_blue1]3. Tên mô hình AI kích hoạt (Model Name)[/bold deep_sky_blue1]",
        default=os.getenv("LM_MODEL_NAME", "google/gemma-4-e4b")
    ).strip()

    # --- PHẦN 3: CẤU HÌNH TELEGRAM BOT ---
    console.print("\n", end="")
    console.print(Panel("[bold sky_blue1]PHẦN 3: CẤU HÌNH KÊNH TƯƠNG TÁC TELEGRAM BOT[/bold sky_blue1]", border_style="deep_sky_blue1"))
    
    config_data["TELEGRAM_BOT_TOKEN"] = Prompt.ask(
        "[bold deep_sky_blue1]1. Telegram Bot Token[/bold deep_sky_blue1]",
        default=os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    ).strip()
    
    config_data["ADMIN_CHAT_ID"] = Prompt.ask(
        f"[bold deep_sky_blue1]2. Chat ID Telegram của Giám đốc {new_director_name}[/bold deep_sky_blue1]",
        default=os.getenv("ADMIN_CHAT_ID", "YOUR_ADMIN_CHAT_ID")
    ).strip()

    # Ghi nhận cấu hình
    console.print("\n[bold deep_sky_blue1]Đang đồng bộ dữ liệu cấu hình vào tệp tin môi trường cục bộ...[/bold deep_sky_blue1]")
    write_success = write_env_file(config_data)
    
    if write_success:
        console.print("[bold green]✅ Cấu hình môi trường đã được lưu và cập nhật thành công![/bold green]")
    else:
        console.print("[bold red]❌ Ghi cấu hình môi trường thất bại.[/bold red]")
    
    # Kiểm tra thử kết nối
    console.print("[bold deep_sky_blue1]Đang tiến hành kiểm tra kết nối dịch vụ thử nghiệm...[/bold deep_sky_blue1]")
    time.sleep(1)
    
    from taxsentry.database.db_manager import TaxSentryDBManager
    db = TaxSentryDBManager()
    if db.connect():
        console.print("[bold green]  • Kết nối Database SQLite cục bộ: THÀNH CÔNG[/bold green]")
        db.close()
    else:
        console.print("[bold red]  • Kết nối Database SQLite cục bộ: THẤT BẠI (Vui lòng kiểm tra quyền ghi ổ đĩa)[/bold red]")
        
    from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
    engine = TaxSentryAnalysisEngine()
    if engine.connect():
        console.print("[bold green]  • Kết nối AI Server (LM Studio): THÀNH CÔNG[/bold green]")
    else:
        console.print("[bold red]  • Kết nối AI Server (LM Studio): THẤT BẠI (Vui lòng kiểm tra LM Studio đang chạy)[/bold red]")
        
    console.print(f"\n[bold green]Hoàn tất quá trình Onboarding. Chào mừng Giám đốc {new_director_name} đến với hệ thống![/bold green]\n")
    time.sleep(2.5)


def run_chat_mode():
    """Chế độ trò chuyện CLI trực tiếp với Trợ lý AI TaxSentry."""
    console.clear()
    director_name = get_director_name() or "Sếp"
    
    welcome_text = Text()
    welcome_text.append(f"💬 PHÒNG TRÒ CHUYỆN AI COPILOT — GIÁM ĐỐC: {director_name.upper()}\n", style="bold green")
    welcome_text.append("Trợ lý AI TaxSentry đã sẵn sàng lắng nghe và giải đáp.\n", style="italic")
    welcome_text.append("• Hỏi về: Số liệu doanh thu, lợi nhuận, chi phí rủi ro, quy định thuế Việt Nam.\n", style="gray50")
    welcome_text.append("• Gõ 'quay lai' hoặc 'exit' để quay trở lại màn hình Dashboard.\n", style="bold yellow")
    
    console.print(Panel(welcome_text, border_style="green"))
    
    from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
    engine = TaxSentryAnalysisEngine()
    if not engine.connect():
        console.print("[bold red]❌ Lỗi kết nối AI Engine (LM Studio Server chưa hoạt động).[/bold red]")
        console.print("[yellow]Nhấn phím bất kỳ để quay lại Dashboard...[/yellow]")
        import msvcrt
        msvcrt.getch()
        return

    # Nạp context tri thức luật thuế và dữ liệu báo cáo
    financial_data_str = ""
    if JSON_PATH.exists():
        try:
            with open(JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            financial_data_str = json.dumps(data, indent=2, ensure_ascii=False)
        except:
            pass

    tax_rules_str = ""
    from taxsentry.config.paths import KNOWLEDGE_PATH
    if KNOWLEDGE_PATH.exists():
        try:
            tax_rules_str = KNOWLEDGE_PATH.read_text(encoding="utf-8")[:3000]
        except:
            pass

    while True:
        try:
            console.print(f"\n[bold green]🤵 {director_name}[/bold green] > ", end="")
            user_input = input().strip()
            
            if not user_input:
                continue
                
            if user_input.lower() in ["exit", "quay lai", "quay lại", "quit"]:
                console.print("\n[yellow]Đang kết thúc trò chuyện và quay lại Dashboard TUI...[/yellow]")
                time.sleep(1)
                break

            console.print("[italic gray50]🤖 TaxSentry đang suy nghĩ...[/italic gray50]")
            
            prompt = f"""# Vai trò: TaxSentry Copilot đồng hành cùng Sếp {director_name}
Bạn là trợ lý tài chính-thuế của Sếp {director_name}. Hãy trả lời bằng tiếng Việt thật tự nhiên như một người trợ lý đang nói chuyện trực tiếp với Sếp.

YÊU CẦU GIỌNG VĂN:
- Xưng 'em', gọi người dùng là 'Sếp'.
- Ưu tiên nói tự nhiên, rõ ràng, ngắn gọn, không giáo điều, không mở đầu kiểu công văn.
- Không trình bày thành một khối báo cáo máy móc trừ khi Sếp thực sự yêu cầu báo cáo formal.
- Nếu dữ liệu chưa đủ để kết luận, nói thẳng phần nào đã thấy, phần nào chưa đủ.

## Dữ liệu báo cáo tài chính hiện tại:
{financial_data_str}

## Trích lục quy định thuế liên quan:
{tax_rules_str}

## Câu hỏi của Sếp:
\"{user_input}\"

Hãy trả lời như một người trợ lý hiểu việc, ưu tiên:
1. Xác nhận nhanh mình đang nhìn vào dữ liệu nào.
2. Trả lời đúng trọng tâm câu hỏi.
3. Nếu cần phân tích, nêu các số chính trước rồi mới nhận xét.
4. Tránh văn phong khuôn mẫu kiểu 'dưới đây là báo cáo gồm 3 phần'.
"""
            response = engine.analyze_report(prompt)
            
            console.print(f"\n[bold sky_blue1]🛡️ TaxSentry Copilot[/bold sky_blue1]:")

            console.print(Panel(response, border_style="sky_blue1"))
            
        except KeyboardInterrupt:
            break


def main():
    run_onboarding_setup()

    # Đồng bộ thông điệp chào mừng trong logs hệ thống — tất cả ĐỌC TỪ CONFIG
    director_name = get_director_name()
    director_email = get_director_email()
    accountant_email = get_accountant_email()
    email_user = get_email_user()
    model_name = os.getenv("LM_MODEL_NAME", "")
    llm_url = get_llm_server_url()

    if director_name:
        LOG_MESSAGES.append(f"Kính chào Giám đốc {director_name}. Hệ thống giám sát đã sẵn sàng làm việc.")
    else:
        LOG_MESSAGES.append("Kính chào Sếp. Hệ thống giám sát đã sẵn sàng làm việc.")

    # Hiển thị cấu hình thực tế (dynamic, không hardcode)
    LOG_MESSAGES.append(f"🤖 AI Server: {llm_url} | Model: {model_name or '[chưa cấu hình]'}")
    LOG_MESSAGES.append(f"📧 IMAP Login: {email_user or '[chưa cấu hình]'}")
    LOG_MESSAGES.append(f"👩‍💼 Đang giám sát thư từ Kế toán trưởng: {accountant_email or '[chưa cấu hình]'}")
    if director_email:
        LOG_MESSAGES.append(f"📬 Báo cáo PDF sẽ gửi tới: {director_email}")
    LOG_MESSAGES.append(f"📡 Telegram Bot đang khởi động...")

    # Kiểm tra kết nối AI thực tế → cập nhật status động
    try:
        from taxsentry.core.analysis_engine import TaxSentryAnalysisEngine
        engine = TaxSentryAnalysisEngine()
        if engine.connect():
            SYSTEM_STATUS["LM Studio"] = get_model_display_name()
            LOG_MESSAGES.append(f"✅ Kết nối AI Server thành công: {model_name}")
        else:
            SYSTEM_STATUS["LM Studio"] = f"[red]Disconnected[/red]"
            LOG_MESSAGES.append(f"❌ Không thể kết nối AI Server tại {llm_url}")
    except Exception as e:
        SYSTEM_STATUS["LM Studio"] = f"[red]Error: {e}[/red]"
        LOG_MESSAGES.append(f"❌ Lỗi AI: {e}")

    # Khởi động Telegram Bot Gateway
    start_telegram_gateway()

    load_parsed_data()

    worker_thread = Thread(target=background_worker, daemon=True)
    worker_thread.start()

    layout = make_layout()

    layout["header"].update(Header())
    layout["left"].split_column(
        Layout(SystemStatusPanel(), ratio=5),
        Layout(RecentActivityPanel(), ratio=6),
    )
    layout["right"].update(LogsPanel())
    layout["footer"].update(Footer())

    try:
        import msvcrt
        with Live(layout, refresh_per_second=4, screen=True) as live:
            while True:
                time.sleep(0.1)
                
                # Cập nhật trạng thái Telegram Bot Gateway thời gian thực
                global TELEGRAM_PROCESS
                if TELEGRAM_PROCESS:
                    if TELEGRAM_PROCESS.poll() is None:
                        SYSTEM_STATUS["Telegram Bot"] = "[green]Online (Listening...)[/green]"
                    else:
                        SYSTEM_STATUS["Telegram Bot"] = "[red]Offline (Stopped)[/red]"
                else:
                    SYSTEM_STATUS["Telegram Bot"] = "[yellow]Offline (Not Started)[/yellow]"

                # Kiểm tra phím nhấn (không chặn luồng) trên Windows
                if msvcrt.kbhit():
                    key = msvcrt.getch()
                    if key.lower() == b'c':
                        # Tạm dừng Live TUI và vào Chat CLI
                        live.stop()
                        run_chat_mode()
                        # Khôi phục màn hình Dashboard
                        console.clear()
                        live.start()
                
                load_parsed_data()
                layout["header"].update(Header())
                layout["right"].update(LogsPanel())
                live.refresh()
    except KeyboardInterrupt:
        pass
    finally:
        # Giải phóng tiến trình Telegram Bot Gateway khi thoát hệ thống
        if TELEGRAM_PROCESS:
            try:
                TELEGRAM_PROCESS.terminate()
                TELEGRAM_PROCESS.wait(timeout=2)
            except:
                try:
                    TELEGRAM_PROCESS.kill()
                except:
                    pass

    console.clear()
    console.print(f"\n[bold yellow]Hệ thống TaxSentry đã được đóng an toàn. Kính chúc Giám đốc {director_name} một ngày làm việc hiệu quả![/bold yellow]\n")


if __name__ == "__main__":
    main()
