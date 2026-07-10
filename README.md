# TaxSentry 2.0

AI Agent Python-first cho Giám đốc: nhận báo cáo từ Gmail Kế toán trưởng, xác minh nguồn, đọc XLSX/PDF/ảnh scan, phân tích hiệu quả kinh doanh và rủi ro thuế, tạo PDF rồi gửi qua Gmail và Telegram.

Agent chỉ phân tích và khuyến nghị có căn cứ. Quyết định tài chính, khai thuế và điều hành luôn thuộc về Giám đốc.

## Cài đặt

Yêu cầu Python 3.11–3.13, [uv](https://docs.astral.sh/uv/) và Tesseract với gói ngôn ngữ `vie`, `eng`.

```powershell
uv tool install .
taxsentry setup
taxsentry doctor
```

`setup` tạo profile sạch tại `~/.taxsentry`. Nếu phát hiện profile v1, TaxSentry đổi tên nó thành thư mục backup có timestamp, không xóa dữ liệu cũ.

## Xác thực

```powershell
taxsentry auth gmail
taxsentry auth telegram
taxsentry auth codex
taxsentry auth status
```

- Gmail dùng OAuth Desktop App nội bộ Google Workspace với scope `gmail.modify`.
- Codex đăng nhập qua `codex app-server`; TaxSentry không đọc hoặc ghi token Codex.
- Telegram bot token và Gmail refresh token nằm trong OS keyring, không nằm trong config.
- LM Studio mặc định tại `http://127.0.0.1:1234/v1`; chọn provider/model trong `taxsentry setup`.

## Sử dụng

```powershell
taxsentry                 # terminal cockpit
taxsentry start           # khởi động terminal cockpit
taxsentry gateway         # kết nối Telegram foreground
taxsentry doctor --fix    # phát hiện và sửa lỗi cài đặt có thể tự động sửa
taxsentry update          # cập nhật bản uv tool đã cài
taxsentry worker run      # quét Gmail mỗi 60 giây
taxsentry worker run --once
taxsentry jobs
taxsentry report
taxsentry service install
taxsentry service start
taxsentry service status
```

Cockpit giữ transcript cuộn và hỗ trợ `/help`, `/status`, `/jobs`, `/latest`, `/report`, `/provider`, `/auth`, `/retry`, `/clear`, `/exit`.

Worker chỉ nhận sender trong `gmail.trusted_senders`, kiểm tra MIME/đuôi file/kích thước/SHA-256, chống trùng bằng Gmail message ID và điều khiển pipeline cố định:

`queued → fetching → extracting → analyzing → needs_review|rendering → delivering → completed|failed`

Báo cáo OCR confidence thấp hoặc thiếu chỉ số cốt lõi được chuyển sang `needs_review` và không tự gửi. Retry tối đa ba lần với exponential backoff.

## Phát triển

```powershell
uv sync --extra dev
uv lock --check
uv run ruff check src tests
uv run pytest -q
uv build
```

CI chạy Python 3.12 trên Windows/macOS/Ubuntu và Python 3.11, 3.13 trên Ubuntu.

## Dữ liệu cục bộ

- Config: `~/.taxsentry/config.json`
- SQLite: `~/.taxsentry/taxsentry.db`
- Log: `~/.taxsentry/logs`
- Attachment: `~/.taxsentry/downloads`

TaxSentry v2 là ứng dụng nội bộ một Google Workspace, không cung cấp API public hoặc multi-tenant.
