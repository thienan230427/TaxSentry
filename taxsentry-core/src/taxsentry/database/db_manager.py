import json
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4

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
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            self.init_db()
            return True
        except Exception as e:
            print(f"❌ Kết nối SQLite thất bại rồi Sếp ơi: {e}")
            return False

    @staticmethod
    def _to_db_timestamp(value: datetime | str | None) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat(sep=" ")
        return value

    def _ensure_column(self, table_name: str, column_name: str, sql_type: str):
        cursor = self.connection.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        existing_columns = {row[1] for row in cursor.fetchall()}
        if column_name not in existing_columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}")

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
            job_id TEXT,
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
                ("job_id", "TEXT"),
                ("session_id", "TEXT"),
                ("event_id", "TEXT"),
                ("trace_id", "TEXT"),
                ("source_path", "TEXT"),
                ("source_file", "TEXT"),
                ("trace_generated_at", "TEXT"),
            ]:
                self._ensure_column("reports_log", column_name, sql_type)

            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS job_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT UNIQUE,
                    session_id TEXT,
                    job_type TEXT,
                    state TEXT,
                    source_file TEXT,
                    source_path TEXT,
                    email_id TEXT,
                    event_id TEXT,
                    trace_id TEXT,
                    retry_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    metadata_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP
                )
                """
            )
            for column_name, sql_type in [
                ("session_id", "TEXT"),
                ("job_type", "TEXT"),
                ("state", "TEXT"),
                ("source_file", "TEXT"),
                ("source_path", "TEXT"),
                ("email_id", "TEXT"),
                ("event_id", "TEXT"),
                ("trace_id", "TEXT"),
                ("retry_count", "INTEGER DEFAULT 0"),
                ("error_message", "TEXT"),
                ("metadata_json", "TEXT"),
                ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                ("completed_at", "TIMESTAMP"),
            ]:
                self._ensure_column("job_log", column_name, sql_type)
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
        job_id: str | None = None,
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
                tax_risk_status, status, job_id,
                session_id, event_id, trace_id, source_path, source_file, trace_generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                sql,
                (
                    self._to_db_timestamp(received_at),
                    sender,
                    file_name,
                    revenue,
                    gross_profit,
                    total_opex,
                    net_income,
                    hospitality_no_invoice,
                    tax_risk_status,
                    status,
                    job_id,
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

    def log_job(
        self,
        job_type: str,
        *,
        state: str = "pending",
        session_id: str | None = None,
        source_file: str | None = None,
        source_path: str | None = None,
        email_id: str | None = None,
        event_id: str | None = None,
        trace_id: str | None = None,
        retry_count: int = 0,
        error_message: str | None = None,
        metadata: dict | None = None,
        job_id: str | None = None,
    ) -> str | None:
        if not self.connection:
            if not self.connect():
                return None

        job_id = job_id or uuid4().hex
        payload = json.dumps(metadata or {}, ensure_ascii=False)
        sql = """
            INSERT INTO job_log (
                job_id, session_id, job_type, state, source_file, source_path,
                email_id, event_id, trace_id, retry_count, error_message, metadata_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                sql,
                (
                    job_id,
                    session_id,
                    job_type,
                    state,
                    source_file,
                    source_path,
                    email_id,
                    event_id,
                    trace_id,
                    retry_count,
                    error_message,
                    payload,
                ),
            )
            self.connection.commit()
            return job_id
        except Exception as e:
            print(f"❌ Lỗi khi ghi job vào Database: {e}")
            if self.connection:
                self.connection.rollback()
            return None

    def _hydrate_job_rows(self, rows):
        result = []
        for row in rows:
            row_dict = dict(row)
            metadata_json = row_dict.get("metadata_json")
            if metadata_json:
                try:
                    row_dict["metadata"] = json.loads(metadata_json)
                except Exception:
                    row_dict["metadata"] = {}
            else:
                row_dict["metadata"] = {}
            result.append(row_dict)
        return result

    def get_job(self, job_id: str) -> dict | None:
        if not self.connection:
            if not self.connect():
                return None

        sql = """
            SELECT id, job_id, session_id, job_type, state, source_file, source_path,
                   email_id, event_id, trace_id, retry_count, error_message, metadata_json,
                   created_at, updated_at, completed_at
            FROM job_log
            WHERE job_id = ?
            LIMIT 1
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (job_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._hydrate_job_rows([row])[0]
        except Exception as e:
            print(f"❌ Lỗi khi đọc job từ Database: {e}")
            return None

    def update_job_state(
        self,
        job_id: str,
        state: str,
        *,
        retry_count: int | None = None,
        error_message: str | None = None,
        metadata: dict | None = None,
        source_file: str | None = None,
        source_path: str | None = None,
        email_id: str | None = None,
        event_id: str | None = None,
        trace_id: str | None = None,
    ) -> bool:
        if not self.connection:
            if not self.connect():
                return False

        assignments = ["state = ?", "updated_at = CURRENT_TIMESTAMP"]
        params: list = [state]

        if retry_count is not None:
            assignments.append("retry_count = ?")
            params.append(retry_count)
        if error_message is not None:
            assignments.append("error_message = ?")
            params.append(error_message)
        if metadata is not None:
            assignments.append("metadata_json = ?")
            params.append(json.dumps(metadata, ensure_ascii=False))
        if source_file is not None:
            assignments.append("source_file = ?")
            params.append(source_file)
        if source_path is not None:
            assignments.append("source_path = ?")
            params.append(source_path)
        if email_id is not None:
            assignments.append("email_id = ?")
            params.append(email_id)
        if event_id is not None:
            assignments.append("event_id = ?")
            params.append(event_id)
        if trace_id is not None:
            assignments.append("trace_id = ?")
            params.append(trace_id)
        if state.lower() in {"completed", "failed", "needs_review", "cancelled"}:
            assignments.append("completed_at = CURRENT_TIMESTAMP")

        params.append(job_id)
        sql = f"UPDATE job_log SET {', '.join(assignments)} WHERE job_id = ?"
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, tuple(params))
            self.connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"❌ Lỗi khi cập nhật job trong Database: {e}")
            if self.connection:
                self.connection.rollback()
            return False

    def get_jobs_for_session(self, session_id: str) -> list[dict]:
        if not self.connection:
            if not self.connect():
                return []

        sql = """
            SELECT id, job_id, session_id, job_type, state, source_file, source_path,
                   email_id, event_id, trace_id, retry_count, error_message, metadata_json,
                   created_at, updated_at, completed_at
            FROM job_log
            WHERE session_id = ?
            ORDER BY created_at DESC, id DESC
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (session_id,))
            return self._hydrate_job_rows(cursor.fetchall())
        except Exception as e:
            print(f"❌ Lỗi khi đọc job theo session từ Database: {e}")
            return []

    def get_recent_jobs(self, limit: int = 5) -> list[dict]:
        if not self.connection:
            if not self.connect():
                return []

        sql = """
            SELECT id, job_id, session_id, job_type, state, source_file, source_path,
                   email_id, event_id, trace_id, retry_count, error_message, metadata_json,
                   created_at, updated_at, completed_at
            FROM job_log
            ORDER BY created_at DESC, id DESC
            LIMIT ?
        """
        try:
            cursor = self.connection.cursor()
            cursor.execute(sql, (limit,))
            return self._hydrate_job_rows(cursor.fetchall())
        except Exception as e:
            print(f"❌ Lỗi khi đọc danh sách job từ Database: {e}")
            return []

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
                   tax_risk_status, status, job_id,
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
                   tax_risk_status, status, job_id,
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
