import os
from datetime import datetime
import pymysql
from dotenv import load_dotenv

# Nạp cấu hình từ .env
load_dotenv()


class TaxSentryDBManager:
    """Quản lý kết nối và lưu trữ lịch sử báo cáo tài chính vào MySQL."""

    def __init__(self):
        self.host = os.getenv("DB_HOST", "localhost")
        self.port = int(os.getenv("DB_PORT", 3306))
        self.user = os.getenv("DB_USER", "root")
        self.password = os.getenv("DB_PASS")
        self.database = os.getenv("DB_NAME", "tax_sentry")
        self.connection = None

    def connect(self):
        """Khởi tạo kết nối tới MySQL Database."""
        try:
            self.connection = pymysql.connect(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor
            )
            return True
        except Exception as e:
            print(f"❌ Kết nối MySQL thất bại rồi Sếp ơi: {e}")
            return False

    def close(self):
        """Đóng kết nối an toàn."""
        if self.connection:
            try:
                self.connection.close()
            except:
                pass

    def log_report(self, received_at: datetime, sender: str, file_name: str, 
                   revenue: float, gross_profit: float, total_opex: float, 
                   net_income: float, hospitality_no_invoice: float, 
                   tax_risk_status: str, status: str = "Processed") -> bool:
        """Ghi nhận thông tin chi tiết một báo cáo tài chính mới vào MySQL."""
        if not self.connection:
            if not self.connect():
                return False

        sql = """
            INSERT INTO reports_log (
                received_at, sender, file_name, revenue, gross_profit, 
                total_opex, net_income, hospitality_no_invoice, 
                tax_risk_status, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (
                    received_at, sender, file_name, revenue, gross_profit,
                    total_opex, net_income, hospitality_no_invoice,
                    tax_risk_status, status
                ))
            # Commit thay đổi
            self.connection.commit()
            return True
        except Exception as e:
            print(f"❌ Lỗi khi ghi báo cáo vào Database: {e}")
            if self.connection:
                self.connection.rollback()
            return False

    def get_recent_logs(self, limit: int = 5) -> list:
        """Lấy danh sách các báo cáo tài chính gần nhất từ Database."""
        if not self.connection:
            if not self.connect():
                return []

        sql = """
            SELECT id, received_at, sender, file_name, revenue, net_income, 
                   tax_risk_status, status, created_at 
            FROM reports_log 
            ORDER BY received_at DESC 
            LIMIT %s
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, (limit,))
                return cursor.fetchall()
        except Exception as e:
            print(f"❌ Lỗi khi đọc dữ liệu từ Database: {e}")
            return []


def main():
    print("=== CHẠY THỬ NGHIỆM MYSQL DATABASE CONNECTION ===")
    db = TaxSentryDBManager()
    
    if db.connect():
        print("✅ Kết nối thành công tới MySQL Database 'tax_sentry'!")
        
        # Test ghi một bản ghi giả lập
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
            status="Processed"
        )
        
        if success:
            print("🎉 Ghi dữ liệu mẫu vào MySQL thành công rực rỡ!")
            
            # Đọc lại dữ liệu để xác nhận
            logs = db.get_recent_logs(limit=3)
            print(f"\n🔎 Đã lấy ra {len(logs)} bản ghi gần nhất:")
            for log in logs:
                print(f"  • ID: {log['id']} | File: {log['file_name']} | Doanh thu: {log['revenue']:,.0f} VND | Trạng thái: {log['tax_risk_status']}")
        else:
            print("❌ Ghi dữ liệu thất bại.")
            
        db.close()
    else:
        print("❌ Kết nối MySQL thất bại. Sếp vui lòng kiểm tra xem MySQL Service đã chạy trên cổng 3306 chưa nha!")


if __name__ == "__main__":
    main()
