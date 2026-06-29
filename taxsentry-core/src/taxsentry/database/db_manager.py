import sys
from datetime import datetime
from pathlib import Path

import sqlite3
from dotenv import load_dotenv

from taxsentry.config.paths import DB_PATH

sys.path.insert(0, str(Path(__file__).parent.parent.absolute()))

# Nạp cấu hình từ .env
load_dotenv()


class TaxSentryDBManager:
    """Quản lý kết nối và lưu trữ lịch sử báo cáo tài chính vào SQLite cục bộ (Zero-Setup)."""

    def __init__(self, db_path: str | None = None):
        self.db_path = str(db_path or DB_PATH)
        self.connection = None

    def connect(self):
        """Khởi tạo kết nối tới SQLite Database và tự động tạo bảng nếu chưa có."""
        try:
            self.connection = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            self.connection.row_factory = sqlite3.Row
            self.init_db()
            return True
        except Exception as e:
            print(f"❌ Kết nối SQLite thất bại rồi Sếp ơi: {e}")
            return False

    def _ensure_column(self, column_name: str, sql_type: str):
        cursor = self.connection.cursor()
        cursor.execute("PRAGMA table_info(reports_log)")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE reports_log ADD COLUMN {column_name} {sql_type}")

    def init_db(self):
        """Khởi tạo cấu trúc bảng reports_log."""
        sql = """
        CREATE TABLE IF NOT EXISTS reports_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            received_at TIMESTAMP,
            sender TEXT,
            file_name TEXT,
            revenue REAL,
            gross_profit REAL,
            total_opex REAL,
            net_income REAL,
            hospitality_no_invoice REAL,
            tax_risk_status TEXT,
            status TEXT,
            session_id TEXT,
            event_id TEXT,
            trace_id TEXT,
            source_path TEXT,
            source_file TEXT,
            trace_generated_at TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql)
            for column_name, sql_type in [
                ("session_id", "TEXT"),
                ("event_id", "TEXT"),
                ("trace_id", "TEXT"),
                ("source_path", "TEXT"),
                ("source_file", "TEXT"),
                ("trace_generated_at", "TEXT"),
            ]:
                self._ensure_column(column_name, sql_type)
            self.connection.commit()
        except Exception as e:
            print(f"❌ Lỗi khi khởi tạo cấu trúc bảng SQLite: {e}")

    def close(self):
        """Đóng kết nối an toàn."""
        if self.connection:
            try:
                self.connection.close()
            except Exception:
                pass

    def log_report(
        self,
        received_at: datetime,
        sender: str,
        file_name: str,
        revenue: float,
        gross_profit: float,
        total_opex: float,
        net_income: float,
        hospitality_no_invoice: float,
        tax_risk_status: str,
        status: str = "Processed",
        session_id: str | None = None,
        event_id: str | None = None,
        trace_id: str | None = None,
        source_path: str | None = None,
        source_file: str | None = None,
        trace_generated_at: str | None = None,
    ) -> bool:
        """Ghi nhận thông tin chi tiết một báo cáo tài chính mới vào SQLite."""
        if not self.connection:
            if not self.connect():
                return False

        sql = """
            INSERT INTO reports_log (
                received_at, sender, file_name, revenue, gross_profit,
                total_opex, net_income, hospitality_no_invoice,
                tax_risk_status, status,
                session_id, event_id, trace_id, source_path, source_file, trace_generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                sql,
                (
                    received_at,
                    sender,
                    file_name,
                    revenue,
                    gross_profit,
                    total_opex,
                    net_income,
                    hospitality_no_invoice,
                    tax_risk_status,
                    status,
                    session_id,
                    event_id,
                    trace_id,
                    source_path,
                    source_file,
                    trace_generated_at,
                ),
            )
            self.connection.commit()
            return True
        except Exception as e:
            print(f"❌ Lỗi khi ghi báo cáo vào Database: {e}")
            if self.connection:
                self.connection.rollback()
            return False

    def _hydrate_report_rows(self, rows):
        result = []
        for row in rows:
            row_dict = dict(row)
            if isinstance(row_dict.get("received_at"), str):
                try:
                    row_dict["received_at"] = datetime.fromisoformat(row_dict["received_at"])
                except Exception:
                    pass
            result.append(row_dict)
        return result

    def get_reports_for_session(self, session_id: str) -> list[dict]:
        if not self.connection:
            if not self.connect():
                return []

        sql = """
            SELECT id, received_at, sender, file_name, revenue, gross_profit,
                   total_opex, net_income, hospitality_no_invoice,
                   tax_risk_status, status,
                   session_id, event_id, trace_id, source_path, source_file, trace_generated_at,
                   created_at
            FROM reports_log
            WHERE session_id = ?
            ORDER BY received_at DESC, created_at DESC
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (session_id,))
            return self._hydrate_report_rows(cursor.fetchall())
        except Exception as e:
            print(f"❌ Lỗi khi đọc dữ liệu theo session từ Database: {e}")
            return []

    def get_recent_logs(self, limit: int = 5) -> list:
        """Lấy danh sách các báo cáo tài chính gần nhất từ Database."""
        if not self.connection:
            if not self.connect():
                return []

        sql = """
            SELECT id, received_at, sender, file_name, revenue, gross_profit,
                   total_opex, net_income, hospitality_no_invoice,
                   tax_risk_status, status,
                   session_id, event_id, trace_id, source_path, source_file, trace_generated_at,
                   created_at
            FROM reports_log
            ORDER BY received_at DESC
            LIMIT ?
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (limit,))
            return self._hydrate_report_rows(cursor.fetchall())
        except Exception as e:
            print(f"❌ Lỗi khi đọc dữ liệu từ Database: {e}")
            return []


def main():
    print("=== CHẠY THỬ NGHIỆM SQLITE DATABASE CONNECTION (ZERO-SETUP) ===")
    db = TaxSentryDBManager()

    if db.connect():
        print(f"✅ Kết nối thành công tới SQLite Database tại: {db.db_path}!")

        print("\nĐang thử ghi nhận một bản ghi mẫu vào Database...")
        now = datetime.now()
        success = db.log_report(
            received_at=now,
            sender="ke-toan-truong@company.com",
            file_name="BC_KinhDoanh_T5.xlsx",
            revenue=650000000.00,
            gross_profit=410000000.00,
            total_opex=260000000.00,
            net_income=120000000.00,
            hospitality_no_invoice=45000000.00,
            tax_risk_status="🚨 Rủi ro (Chi phí không hóa đơn)",
            status="Processed",
        )

        if success:
            print("🎉 Ghi dữ liệu mẫu vào SQLite thành công rực rỡ!")

            logs = db.get_recent_logs(limit=3)
            print(f"\n🔎 Đã lấy ra {len(logs)} bản ghi gần nhất:")
            for log in logs:
                print(f"  • ID: {log['id']} | File: {log['file_name']} | Doanh thu: {log['revenue']:,.0f} VND | Trạng thái: {log['tax_risk_status']}")
        else:
            print("❌ Ghi dữ liệu thất bại.")

        db.close()
    else:
        print("❌ Kết nối SQLite thất bại.")


if __name__ == "__main__":
    main()
