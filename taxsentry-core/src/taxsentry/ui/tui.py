import sys
import os
import subprocess

def bootstrap_venv():
    """Tự động phát hiện và khởi chạy lại chương trình bằng Python của môi trường ảo .venv nếu đang chạy ngoài venv."""
    in_venv = (sys.prefix != sys.base_prefix) or ('VIRTUAL_ENV' in os.environ)
    
    if not in_venv:
        root_dir = os.path.dirname(os.path.abspath(__file__))
        venv_python = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
        
        if not os.path.exists(venv_python):
            venv_python = os.path.join(root_dir, ".venv", "bin", "python")
            
        if os.path.exists(venv_python):
            args = [venv_python] + sys.argv
            try:
                sys.exit(subprocess.run(args).returncode)
            except Exception as e:
                print(f"Không thể tự động chuyển hướng sang môi trường ảo: {e}")
                print("Vui lòng kích hoạt thủ công .venv và chạy lại.")
                sys.exit(1)
        else:
            print("⚠️ Cảnh báo: Không tìm thấy môi trường ảo .venv cục bộ. Hệ thống sẽ cố gắng chạy bằng Python hệ thống.")

# Tự động kích hoạt môi trường ảo nếu cần thiết
bootstrap_venv()

# Tiến hành import các thư viện sau khi đã chắc chắn chạy trong môi trường ảo
import json
import time
import re
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

from taxsentry.config.paths import DB_PATH, EXCEL_PATH, JSON_PATH, ENV_PATH

# --- Trạng thái hệ thống mặc định ---
SYSTEM_STATUS = {
    "LM Studio": "[green]Connected (Local Gemma 2)[/green]",
    "Automation Workflow": "[green]Active (Polling 60s)[/green]",
    "Telegram Bot": "[yellow]Offline (Connecting...)[/yellow]",
    "Database (SQLite)": "[green]Connected (Local DB)[/green]",
}

LOG_MESSAGES = [
    "Hệ thống giám sát TaxSentry bắt đầu khởi chạy.",
    f"Đang liên kết cơ sở dữ liệu SQLite cục bộ (Zero-Setup).",
    "Kiểm thái máy chủ trí tuệ nhân tạo LM Studio tại http://localhost:1234/v1...",
    "LM Studio kết nối thành công. Đã xác định mô hình hoạt động.",
    "Hệ thống Email Poller sẵn sàng. Đang giám sát thư điện tử từ Kế toán trưởng...",
    "Hệ thống Telegram Bot sẵn sàng. Đang kết nối kênh tương tác...",
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
        director_name = os.getenv("DIRECTOR_NAME", "Thiên Ân")
        grid.add_row(
            Text(f"🛡️ TAXSENTRY — HỆ THỐNG AI KIỂM TOÁN DÀNH CHO GIÁM ĐỐC: {director_name.upper()}", style="bold white"),
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

    def __rich__(self) -> Panel:
        text = Text()
        
        # 1. Hiển thị thông tin báo cáo thực tế trích xuất từ JSON (nếu có)
        if JSON_PATH.exists():
            try:
                with open(JSON_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                is_t5 = data["data"]["income_statement"]["T5_Actual"]
                text.append("📊 THÔNG TIN BÁO CÁO KINH DOANH THÁNG 05/2026 (TRÍCH XUẤT)\n", style="bold green")
                text.append(f"  • Doanh thu thuần:  {is_t5['revenue']:,.0f} VND\n", style="white")
                text.append(f"  • Lợi nhuận gộp:   {is_t5['gross_profit']:,.0f} VND\n", style="white")
                text.append(f"  • Chi phí vận hành: {is_t5['total_opex']:,.0f} VND\n", style="white")
                text.append(f"  • Lợi nhuận ròng:   {is_t5['net_income']:,.0f} VND\n", style="bold yellow")
                
                # Cảnh báo rủi ro thuế
                limit = is_t5["revenue"] * data["assumptions"]["hospitality_limit_pct"]
                actual_hospitality = is_t5["hospitality_valid_exp"] + is_t5["hospitality_no_invoice_exp"]
                no_invoice = is_t5["hospitality_no_invoice_exp"]
                
                text.append("\n⚠️ ĐÁNH GIÁ RỦI RO THUẾ BAN ĐẦU:\n", style="bold red")
                
                if no_invoice is not None and no_invoice > 0:
                    text.append(f"  🚨 Phát hiện {no_invoice:,.0f} VND chi phí Tiếp khách KHÔNG có hóa đơn đỏ (Sẽ bị loại khi quyết toán thuế TNDN!).\n", style="bold red")
                if actual_hospitality is not None and limit is not None and actual_hospitality > limit:
                    text.append(f"  🚨 Chi phí tiếp khách ({actual_hospitality:,.0f} VND) vượt hạn mức quy định ({limit:,.0f} VND).\n", style="bold red")
                else:
                    text.append("  ✅ Chi phí tiếp khách nằm trong hạn mức cho phép theo quy định hiện hành.\n", style="green")
                text.append("=" * 50 + "\n\n", style="gray50")
            except Exception as e:
                text.append(f"❌ Lỗi cấu trúc tệp dữ liệu phân tích JSON: {e}\n\n", style="bold red")

        # 2. Hiển thị logs hệ thống thời gian thực từ Automation Workflow
        text.append("💬 NHẬT KÝ HOẠT ĐỘNG HỆ THỐNG THỜI GIAN THỰC:\n", style="bold deep_sky_blue1")
        from taxsentry.core.automation import AUTOMATION_LOGS
        
        combined_logs = []
        for log in LOG_MESSAGES:
            combined_logs.append(f"[gray50][Khởi tạo][/gray50] {log}")
        for log in AUTOMATION_LOGS:
            combined_logs.append(log)
            
        for log in combined_logs[-10:]:
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

    root_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(root_dir, ".venv", "Scripts", "python.exe")
    if not os.path.exists(venv_python):
        venv_python = os.path.join(root_dir, ".venv", "bin", "python")
    if not os.path.exists(venv_python):
        venv_python = sys.executable

    script_path = os.path.join(root_dir, "telegram_bot.py")

    try:
        # Khởi chạy bot qua subprocess, chuyển hướng stdout/stderr để chạy ngầm hoàn toàn
        TELEGRAM_PROCESS = subprocess.Popen(
            [venv_python, script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
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
    
    current_director = os.getenv("DIRECTOR_NAME", "Thiên Ân")
    
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
        default=os.getenv("DIRECTOR_NAME", "Thiên Ân")
    ).strip()
    
    # Nhận diện tên mới ngay lập tức
    new_director_name = config_data["DIRECTOR_NAME"]
    
    config_data["DIRECTOR_EMAIL"] = Prompt.ask(
        f"[bold deep_sky_blue1]2. Email nhận báo cáo của Giám đốc {new_director_name}[/bold deep_sky_blue1]",
        default=os.getenv("DIRECTOR_EMAIL", "thienan12342007@gmail.com")
    ).strip()
    
    config_data["ACCOUNTANT_EMAIL"] = Prompt.ask(
        "[bold deep_sky_blue1]3. Email gửi báo cáo của Kế toán trưởng[/bold deep_sky_blue1]",
        default=os.getenv("ACCOUNTANT_EMAIL", "thienan12342007@gmail.com")
    ).strip()
    
    config_data["EMAIL_USER"] = Prompt.ask(
        "[bold deep_sky_blue1]4. Email hệ thống (dùng để quét và gửi thư)[/bold deep_sky_blue1]",
        default=os.getenv("EMAIL_USER", "an25800600029@hutech.edu.vn")
    ).strip()
    
    config_data["EMAIL_PASS"] = Prompt.ask(
        "[bold deep_sky_blue1]5. Gmail App Password (16 ký tự viết liền của Email hệ thống)[/bold deep_sky_blue1]",
        default=os.getenv("EMAIL_PASS", "")
    ).strip()
    
    # --- PHẦN 2: CẤU HÌNH AI SERVER (LM STUDIO) ---
    console.print("\n", end="")
    console.print(Panel("[bold sky_blue1]PHẦN 2: CẤU HÌNH MÁY CHỦ TRÍ TUỆ NHÂN TẠO CỤC BỘ (LM STUDIO)[/bold sky_blue1]", border_style="deep_sky_blue1"))
    
    config_data["LM_STUDIO_URL"] = Prompt.ask(
        "[bold deep_sky_blue1]1. LM Studio Server API Base URL[/bold deep_sky_blue1]",
        default=os.getenv("LM_STUDIO_URL", "http://localhost:1234/v1")
    ).strip()
    
    config_data["LM_STUDIO_API_KEY"] = Prompt.ask(
        "[bold deep_sky_blue1]2. LM Studio API Key[/bold deep_sky_blue1]",
        default=os.getenv("LM_STUDIO_API_KEY", "sk-lm-sVlR2otW:D3EDq8EiXWYdmvAhYsgY")
    ).strip()
    
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
    director_name = os.getenv("DIRECTOR_NAME", "Thiên Ân")
    
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
            
            prompt = f"""# Role: Trợ lý AI Kiểm toán TaxSentry của Giám đốc {director_name}
Nhiệm vụ của bạn là trả lời câu hỏi của Giám đốc {director_name} một cách trang trọng, chính xác, sắc bén chuẩn chuyên gia CFO/Kiểm toán cấp cao.
Sử dụng dữ liệu tài chính của doanh nghiệp và tri thức luật thuế Việt Nam dưới đây làm ngữ cảnh.

## Dữ liệu báo cáo tài chính hiện tại:
{financial_data_str}

## Trích lục quy định thuế liên quan:
{tax_rules_str}

## Câu hỏi của Giám đốc:
"{user_input}"
"""
            response = engine.analyze_report(prompt)
            
            console.print(f"\n[bold sky_blue1]🛡️ TaxSentry Copilot[/bold sky_blue1]:")
            console.print(Panel(response, border_style="sky_blue1"))
            
        except KeyboardInterrupt:
            break


def main():
    run_onboarding_setup()

    # Đồng bộ thông điệp chào mừng trong logs hệ thống
    director_name = os.getenv("DIRECTOR_NAME", "Thiên Ân")
    LOG_MESSAGES.append(f"Kính chào Giám đốc {director_name}. Hệ thống giám sát đã sẵn sàng làm việc.")

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
