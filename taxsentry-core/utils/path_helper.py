import os
from pathlib import Path

# Nếu có ổ đĩa D, mặc định lưu dữ liệu ở D:/TaxSentry.
# Nếu không, tự động lưu ở thư mục gốc của dự án.
if os.path.exists("D:/"):
    BASE_DIR = Path("D:/TaxSentry")
else:
    BASE_DIR = Path(__file__).parent.parent.absolute()

# Đảm bảo thư mục gốc tồn tại
BASE_DIR.mkdir(parents=True, exist_ok=True)

# Tạo và định nghĩa các thư mục con
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

KNOWLEDGE_DIR = BASE_DIR / "knowledge_base"
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)

# Định nghĩa các đường dẫn file cụ thể
DB_PATH = BASE_DIR / "taxsentry.db"
EXCEL_PATH = BASE_DIR / "mock_report.xlsx"
JSON_PATH = BASE_DIR / "parsed_report.json"
ENV_PATH = BASE_DIR / ".env"
KNOWLEDGE_PATH = KNOWLEDGE_DIR / "tax_rules_vietnam.md"
AUDIT_REPORT_PATH = BASE_DIR / "audit_report.md"
