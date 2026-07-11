# TaxSentry 2.0

TaxSentry là AI agent Python-first cho Giám đốc và bộ phận tài chính: nhận báo cáo từ Gmail, kiểm tra nguồn gửi, đọc XLSX/PDF/ảnh scan, phân tích hiệu quả kinh doanh và rủi ro thuế, xuất PDF rồi phân phối qua Gmail và Telegram.

TaxSentry chỉ đưa ra phân tích, căn cứ và khuyến nghị. Quyết định tài chính, khai thuế và điều hành luôn thuộc về người có thẩm quyền.

## Tính năng

- Nhận email có tệp đính kèm từ Gmail API.
- Chỉ xử lý sender nằm trong `gmail.trusted_senders`.
- Hỗ trợ XLSX, PDF, PNG, JPG/JPEG.
- Kiểm tra phần mở rộng, MIME type, magic bytes, kích thước và SHA-256.
- Trích xuất dữ liệu bảng tính bằng parser tài chính dùng chung; OCR ảnh/PDF scan qua Tesseract.
- Phân tích bằng LM Studio hoặc Codex App Server.
- Chuẩn hóa kết quả về schema báo cáo JSON cố định.
- Chuyển báo cáo confidence thấp sang `needs_review`.
- Theo dõi trạng thái job, retry có giới hạn và phục hồi job dở dang sau khi worker khởi động lại.
- Chống xử lý trùng theo Gmail message ID và chống gửi email trùng bằng `Message-ID` ổn định.
- Xuất PDF, gửi Gmail và gửi Telegram tới chat ID đã cấu hình.
- Terminal cockpit, Telegram gateway và native service cho Windows/macOS/Linux.
- Secrets được lưu trong OS keyring; config không chứa refresh token hoặc bot token.

## Luồng xử lý

```text
Gmail
  → trusted sender + attachment validation
  → queued
  → fetching
  → extracting
  → analyzing
  → needs_review hoặc rendering
  → delivering
  → completed / failed
```

Job lỗi được retry theo exponential backoff trong giới hạn cấu hình. Job cần duyệt phải được `/approve` từ Telegram trước khi xử lý tiếp.

## Yêu cầu

- Python 3.11, 3.12 hoặc 3.13.
- [uv](https://docs.astral.sh/uv/).
- Tesseract OCR và language packs `vie`, `eng` nếu cần đọc ảnh/PDF scan.
- Gmail OAuth Desktop App nếu dùng Gmail.
- LM Studio đang chạy tại `http://127.0.0.1:1234/v1`, hoặc Codex CLI đã đăng nhập nếu dùng Codex.
- Telegram bot token nếu muốn gửi hoặc điều khiển qua Telegram.

## Cài đặt

Cài trực tiếp từ repository:

```powershell
uv tool install git+https://github.com/thienan230427/TaxSentry.git
taxsentry setup
taxsentry doctor
```

Trong lúc phát triển local:

```powershell
uv sync --extra dev
uv run taxsentry setup
```

`taxsentry setup` tạo profile tại `~/.taxsentry`. Nếu phát hiện profile v1, TaxSentry đổi tên profile cũ thành thư mục backup có timestamp và không xóa dữ liệu.

## Xác thực và cấu hình

```powershell
taxsentry auth gmail
taxsentry auth telegram
taxsentry auth codex
taxsentry auth status
taxsentry doctor
```

- Gmail dùng OAuth scope `gmail.modify`; refresh token nằm trong OS keyring.
- Telegram bot token nằm trong OS keyring, không ghi vào `config.json`.
- Codex được kết nối qua official `codex app-server`; TaxSentry không tự quản lý OAuth token Codex.
- LM Studio dùng OpenAI-compatible endpoint. Chọn provider và model trong `taxsentry setup`.
- `taxsentry doctor --fix` có thể tạo thư mục runtime và thử cài Tesseract bằng package manager native của hệ điều hành.

Các giá trị nghiệp vụ quan trọng gồm:

```text
gmail.account                 Gmail nhận báo cáo
gmail.oauth_client_file       credentials.json của Gmail OAuth
gmail.trusted_senders         allowlist email Kế toán trưởng
director.email                email nhận PDF
director.telegram_chat_ids    danh sách chat ID được phép
provider.kind                 lmstudio hoặc codex
provider.model                model phân tích
worker.poll_seconds           chu kỳ quét Gmail
worker.max_retries            số lần retry tối đa
ocr.minimum_confidence        ngưỡng OCR, mặc định 70%
report.minimum_confidence     ngưỡng report, mặc định 70%
```

## Sử dụng

```powershell
taxsentry                       # terminal cockpit
taxsentry start                 # cockpit
taxsentry gateway               # Telegram gateway foreground
taxsentry status                # tóm tắt cấu hình
taxsentry doctor --fix          # kiểm tra và sửa phần cài đặt có thể tự động sửa
taxsentry worker run            # worker liên tục
taxsentry worker run --once     # chạy một chu kỳ rồi thoát
taxsentry worker run --gateway  # worker kèm Telegram gateway
taxsentry jobs                  # danh sách job gần đây
taxsentry report                # xem report mới nhất
taxsentry report --send         # xác nhận rồi gửi lại report mới nhất
taxsentry update                # cập nhật từ source trong config
```

Trong cockpit có các lệnh `/help`, `/status`, `/jobs`, `/latest`, `/report`, `/provider`, `/auth`, `/retry`, `/clear` và `/exit`.

Native service:

```powershell
taxsentry service install
taxsentry service start
taxsentry service status
taxsentry service logs
taxsentry service stop
taxsentry service remove
```

## Dữ liệu cục bộ

Mặc định tại `~/.taxsentry`:

```text
config.json       cấu hình không chứa secrets nhạy cảm
taxsentry.db      SQLite jobs, reports, deliveries và events
logs/             log runtime
run/              worker lock và runtime files
downloads/        tệp đính kèm và PDF đã tạo
```

Có thể đổi thư mục bằng biến môi trường `TAXSENTRY_HOME`; có thể đổi riêng config hoặc database bằng `TAXSENTRY_CONFIG_FILE` và `TAXSENTRY_MEMORY_DB`.

## Phát triển

```powershell
uv sync --extra dev
uv lock --check
uv run ruff check src tests
uv run pytest -q
uv build
```

Pytest có một test OCR ảnh thật sẽ tự skip nếu máy chưa cài Tesseract. Trên Windows sandbox, nếu thư mục temp mặc định bị hạn chế quyền, dùng:

```powershell
uv run pytest -q --basetemp=D:\TaxSentry\tmp-pytest
```

CI tại `.github/workflows/cross-platform.yml` kiểm tra Windows, macOS và Ubuntu với Python 3.11–3.13.

## Bảo mật và giới hạn

- Không commit `.env`, database, attachments, tokens hoặc credentials.
- Allowlist sender là trust boundary bắt buộc; email ngoài allowlist bị bỏ qua và ghi event.
- Tệp đính kèm không hợp lệ bị từ chối trước khi parse.
- TaxSentry là ứng dụng nội bộ cho một Google Workspace, không phải public API và không phải hệ thống multi-tenant.
- Kết quả AI cần được con người kiểm tra trước khi dùng cho quyết định tài chính hoặc hồ sơ thuế.
- Nghiệm thu production vẫn cần kiểm tra OAuth Gmail, provider AI, Telegram và Tesseract trên máy triển khai thật.

## Giấy phép

Phát hành theo [MIT License](LICENSE).
