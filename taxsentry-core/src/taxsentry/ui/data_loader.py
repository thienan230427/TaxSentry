from __future__ import annotations

from datetime import datetime

EMAILS_QUEUE: list[dict[str, str]] = []


def load_parsed_data() -> None:
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
