<div align="center">

# TaxSentry

**Trợ lý AI trên terminal dành cho xử lý tài liệu tài chính, Gmail và báo cáo.**

[![npm](https://img.shields.io/npm/v/taxsentry?logo=npm&label=npm)](https://www.npmjs.com/package/taxsentry)
[![CI](https://img.shields.io/github/actions/workflow/status/thienan230427/TaxSentry/cross-platform.yml?branch=main&logo=githubactions&label=build)](https://github.com/thienan230427/TaxSentry/actions/workflows/cross-platform.yml)
[![License](https://img.shields.io/github/license/thienan230427/TaxSentry)](LICENSE)

</div>

> TaxSentry hỗ trợ phân tích và tổng hợp thông tin. Mọi kết luận quan trọng về thuế, tài chính hoặc pháp lý vẫn cần người có chuyên môn kiểm tra.

## Chức năng

- Chat AI trực tiếp trong giao diện terminal.
- Tìm kiếm và đọc toàn bộ Gmail bằng tiếng Việt hoặc lệnh `/gmail`.
- Tự xử lý file đính kèm mới từ mọi người gửi sau thời điểm bật Gmail.
- Đọc DOCX, XLSX, PPTX, PDF, PNG, JPG và JPEG.
- Tạo DOCX, XLSX, PPTX hoặc PDF từ prompt, Gmail hay file cục bộ và tự gửi Telegram.
- Chuyển đổi DOC, XLS và PPT bằng LibreOffice nếu đã cài.
- Kiểm tra loại file, dung lượng, nội dung và chống xử lý job trùng.
- Tạo báo cáo PDF, lưu lịch sử trong SQLite và hỗ trợ bước duyệt thủ công.
- Gửi báo cáo về Gmail đã kết nối và các Telegram chat đã cấu hình.
- Giao diện TUI có slash-command palette, trạng thái Gmail, Telegram, model và session.
- Hỗ trợ Codex / ChatGPT App Server hoặc LM Studio.

## Yêu cầu

- Node.js 22 trở lên.
- [uv](https://docs.astral.sh/uv/getting-started/installation/) và Python 3.11–3.13 để tạo runtime Python riêng.
- Windows, macOS hoặc Linux.
- Gmail App Password nếu dùng Gmail. Tài khoản Google cần bật xác minh 2 bước.
- Codex CLI hoặc LM Studio để chạy model AI.
- Tesseract OCR là tùy chọn cho ảnh và PDF scan.
- LibreOffice là tùy chọn, chỉ cần cho file Office cũ `.doc`, `.xls`, `.ppt`.

## Cài đặt

```bash
npm install -g taxsentry
```

Kiểm tra cài đặt:

```bash
taxsentry --version
taxsentry --help
```

## Setup lần đầu

Chạy trình cấu hình:

```bash
taxsentry setup
```

Chọn một hồ sơ:

- **Full Agent:** AI + Gmail + Telegram.
- **Email Agent:** AI + Gmail.
- **Chat Only:** chỉ dùng chat terminal.

Trình setup sẽ hướng dẫn chọn provider, model và kết nối các dịch vụ cần thiết.

### Gmail

1. Bật xác minh 2 bước cho tài khoản Google.
2. Tạo App Password 16 ký tự tại [Google App Passwords](https://myaccount.google.com/apppasswords).
3. Nhập Gmail và App Password khi setup.

TaxSentry dùng chính Gmail đã kết nối để đọc hộp thư và nhận báo cáo. Không cần nhập email kế toán trưởng, danh sách người gửi tin cậy hoặc email giám đốc lần nữa. App Password được lưu trong keyring của hệ điều hành, không lưu trong file cấu hình.

Worker quét All Mail, Spam và Trash mỗi 30 giây sau khi vòng trước hoàn tất; Sent và Drafts được loại trừ để tránh tự lặp. Chỉ thư mới sau mốc UID theo từng mailbox được xử lý tự động. `/gmail search` vẫn tìm lịch sử và luôn yêu cầu xác nhận trước khi xử lý.

### Telegram

Với hồ sơ Full Agent, nhập Bot Token và một hoặc nhiều Chat ID. Báo cáo hoàn tất sẽ được gửi đến tất cả Chat ID đã cấu hình.

## Sử dụng

Mở TaxSentry:

```bash
taxsentry
```

Các lệnh CLI:

```bash
taxsentry setup
taxsentry status
taxsentry doctor
taxsentry doctor --fix
```

Trong giao diện chat, gõ `/` để mở danh sách lệnh, dùng `↑/↓` để chọn, `Tab` để hoàn tất và `Esc` để đóng.

| Lệnh | Công dụng |
| --- | --- |
| `/help` | Hiển thị danh sách lệnh và phím tắt |
| `/status` | Trạng thái provider, Gmail, Telegram và LibreOffice |
| `/gmail` | Hiển thị thư gần đây |
| `/gmail search <query>` | Tìm bằng Gmail search syntax |
| `/gmail read <uid>` | Đọc đầy đủ một thư |
| `/gmail process <uid\|all>` | Xác nhận xử lý kết quả Gmail vừa tìm |
| `/create <docx\|xlsx\|pptx\|pdf> <yêu cầu>` | Tạo tài liệu; thêm `--template <path>` để dùng mẫu riêng |
| `/cancel <job>` | Hủy job đang chạy |
| `/jobs` | Xem các job Gmail gần đây |
| `/report` | Xem tóm tắt báo cáo mới nhất |
| `/retry <job>` | Chạy lại job lỗi |
| `/approve <job>` | Duyệt job đang chờ kiểm tra |
| `/new` | Bắt đầu phiên chat mới |
| `/exit` | Thoát TaxSentry |

Ví dụ:

```text
Hôm nay Gmail có thư nào chưa đọc?
/gmail search from:invoice@example.com has:attachment
/gmail read 1842
/gmail process 1842
/create pdf Tổng hợp báo cáo tháng 6 từ Gmail
```

## Định dạng hỗ trợ

| Định dạng | Cách xử lý |
| --- | --- |
| DOCX, XLSX, PPTX | Đọc và tạo trực tiếp |
| PDF | Trích xuất text, OCR khi cần và tạo báo cáo |
| PNG, JPG, JPEG | Tesseract OCR |
| DOC, XLS, PPT | Chuyển đổi bằng LibreOffice headless |

File macro `.docm`, `.xlsm` và `.pptm` chưa được hỗ trợ. Nội dung email và tài liệu luôn được xem là dữ liệu không tin cậy; TaxSentry không thực thi macro, script, liên kết hay hướng dẫn nằm trong file.

## Phát triển

```bash
uv sync --extra dev
uv run pytest --basetemp=tmp-pytest
uv run ruff check src tests

cd npm
npm install
npm run typecheck
npm test
npm run smoke
```

Đóng gói npm:

```bash
cd npm
npm pack --dry-run --json
npm publish
```

## Dữ liệu cục bộ

TaxSentry lưu cấu hình, database và file tải về trong `~/.taxsentry`; tài liệu tạo từ terminal nằm ở `~/.taxsentry/outputs`. Không commit App Password, Telegram Bot Token, database, file tải về hoặc báo cáo lên Git.

## License

[MIT](LICENSE)
