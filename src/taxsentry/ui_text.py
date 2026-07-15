from __future__ import annotations

from typing import Any

TEXT = {
    "vi": {
        "assistant": "TaxSentry",
        "boss": "Sếp",
        "cancel": "Hủy",
        "commands": "lệnh",
        "connected": "sẵn sàng",
        "error": "Lỗi",
        "exit": "thoát",
        "gmail_disabled": "Gmail đang tắt. Chạy `taxsentry setup` để bật.",
        "help": "trợ giúp",
        "new_content": "Có nội dung mới · End để xem",
        "narrow": "Mở rộng terminal lên ít nhất 60 cột để có bố cục tốt nhất",
        "no_report": "Chưa có báo cáo.",
        "processing": "đang phân tích",
        "ready": "Sẵn sàng",
        "session": "phiên",
        "setup_cancelled": "Đã hủy; cấu hình không thay đổi.",
        "setup_next": "Cấu hình hoàn tất. Chạy `taxsentry doctor`, sau đó chạy `taxsentry`.",
        "status": "trạng thái",
        "system": "Hệ thống",
        "tool": "Công cụ",
        "unknown_command": "Lệnh chưa hỗ trợ. Dùng /help.",
    },
    "en": {
        "assistant": "TaxSentry",
        "boss": "Boss",
        "cancel": "Cancel",
        "commands": "commands",
        "connected": "ready",
        "error": "Error",
        "exit": "exit",
        "gmail_disabled": "Gmail is disabled. Run `taxsentry setup` to enable it.",
        "help": "help",
        "new_content": "New content · press End to view",
        "narrow": "Widen the terminal to at least 60 columns for the best layout",
        "no_report": "No report yet.",
        "processing": "analyzing",
        "ready": "Ready",
        "session": "session",
        "setup_cancelled": "Cancelled; configuration was not changed.",
        "setup_next": "Setup complete. Run `taxsentry doctor`, then run `taxsentry`.",
        "status": "status",
        "system": "System",
        "tool": "Tool",
        "unknown_command": "Unsupported command. Use /help.",
    },
}


def language(settings: dict[str, Any] | None) -> str:
    value = (settings or {}).get("ui", {}).get("language") or (settings or {}).get("agent", {}).get("language")
    return value if value in TEXT else "vi"


def text(settings: dict[str, Any] | None, key: str) -> str:
    lang = language(settings)
    return TEXT[lang].get(key, TEXT["vi"].get(key, key))
