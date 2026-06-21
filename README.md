# TaxSentry

TaxSentry là một AI audit agent chạy local, dành cho founder, giám đốc, đội tài chính - kế toán, và các doanh nghiệp muốn theo dõi rủi ro tài chính - thuế mà không phải mang dữ liệu nhạy cảm đẩy lên một SaaS bên ngoài.

Nói cho dễ hình dung: TaxSentry nhận báo cáo, đọc file, phân tích dấu hiệu rủi ro, rồi gửi phần tóm tắt dễ hành động qua Telegram. Doanh nghiệp vẫn giữ quyền kiểm soát dữ liệu, runtime, và cách vận hành hằng ngày.

## TaxSentry giải quyết bài toán gì?

Ở nhiều doanh nghiệp nhỏ và vừa, quy trình kiểm tra tài chính - thuế thường bị đứt đoạn:
- file Excel hoặc PDF được gửi qua email
- người quản lý chỉ xem khi có ai đó nhắc
- việc rà rủi ro thường đến muộn
- dữ liệu nằm rải rác, khó theo dõi liên tục

TaxSentry gom các bước đó lại thành một flow rõ ràng hơn:
- nhận báo cáo từ email
- đọc file Excel và PDF
- chuẩn hóa dữ liệu để xử lý tiếp
- phân tích bằng AI chạy local
- gửi cảnh báo và tóm tắt qua Telegram
- cho phép vận hành bằng CLI hoặc service runtime

## Vì sao TaxSentry đáng dùng?

Điểm hay của TaxSentry không chỉ là “có AI”, mà là cách nó được đóng gói để dùng thật:
- dữ liệu nhạy cảm được giữ local thay vì mặc định đẩy lên cloud
- có CLI rõ ràng, dễ kiểm soát và dễ tự động hóa
- có thể chạy như bot nền thay vì mở tay từng lần
- cấu hình linh hoạt, không khóa người dùng vào một schema cứng
- phù hợp với người muốn tự chủ vận hành thay vì phụ thuộc hoàn toàn vào dashboard web

## Phù hợp với ai?

TaxSentry hợp với:
- giám đốc muốn nhận cảnh báo tài chính - thuế qua Telegram
- founder hoặc COO muốn dựng một lớp giám sát gọn hơn
- đội tài chính nội bộ muốn có thêm một công cụ rà soát và nhắc việc
- doanh nghiệp ưu tiên local-first, privacy, và quyền kiểm soát dữ liệu

Nếu Sếp đang tìm một công cụ kiểu “đăng ký xong dùng như SaaS full-managed”, TaxSentry chưa đi theo hướng đó. Nó thiên về kiểm soát, tự chủ, và triển khai on-premise hơn.

## Những gì TaxSentry đã làm được

Ở bản hiện tại, TaxSentry đã có các phần quan trọng sau:
- nhận đầu vào báo cáo tài chính qua email IMAP
- đọc và xử lý file Excel hoặc PDF
- phân tích bằng local LLM hoặc endpoint tương thích OpenAI, ví dụ LM Studio
- dùng Telegram bot để gửi cảnh báo, tóm tắt và hỗ trợ tương tác hai chiều
- có các lệnh runtime như `setup`, `status`, `up`, `bot`, `stop`
- có service workflow để apply bot vào OS, gồm cả Task Scheduler trên Windows
- có hệ config linh hoạt: thêm, đổi tên, xóa field mà không cần sửa source code cho từng thay đổi nhỏ

## Yêu cầu trước khi cài

TaxSentry hiện cần:
- Node.js >= 24
- Python >= 3.10
- MySQL
- Telegram bot token từ @BotFather
- local AI endpoint nếu muốn phân tích bằng LLM local, ví dụ LM Studio

## Cài đặt trên Windows

### 1. Cài các thành phần cần thiết

Node.js 24+
```powershell
winget install OpenJS.NodeJS
```

Python 3.10+
```powershell
winget install Python.Python.3.12
```

MySQL
- Cài bằng MySQL Installer hoặc gói phù hợp với môi trường hiện tại của Sếp.
- Sau khi cài xong, kiểm tra chắc là MySQL đang chạy được.

### 2. Cài TaxSentry từ npm

```powershell
npm install -g taxsentry
```

Hoặc nếu muốn chạy ngay mà chưa cài global:

```powershell
npx taxsentry setup
```

### 3. Nếu muốn chạy từ source code

```powershell
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Cài đặt trên macOS

### 1. Cài các thành phần cần thiết

Nếu chưa có Homebrew, cài Homebrew trước từ trang chủ brew.sh.

Node.js 24+
```bash
brew install node
```

Python 3.10+
```bash
brew install python
```

MySQL
```bash
brew install mysql
brew services start mysql
```

### 2. Cài TaxSentry từ npm

```bash
npm install -g taxsentry
```

Hoặc chạy ngay:

```bash
npx taxsentry setup
```

### 3. Nếu muốn chạy từ source code

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Cài đặt trên Linux

TaxSentry hỗ trợ Linux, nhưng cách cài package nền sẽ tùy distro. Ví dụ dưới đây dùng Ubuntu/Debian.

### 1. Cài các thành phần cần thiết

```bash
sudo apt update
sudo apt install -y nodejs npm python3 python3-venv python3-pip mysql-server git
```

Nếu distro của Sếp dùng package Node quá cũ, nên cài Node 24+ bằng nvm hoặc NodeSource thay vì dùng bản repo mặc định.

Ví dụ cài bằng nvm:

```bash
curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 24
nvm use 24
```

### 2. Cài TaxSentry từ npm

```bash
npm install -g taxsentry
```

Hoặc chạy ngay:

```bash
npx taxsentry setup
```

### 3. Nếu muốn chạy từ source code

```bash
git clone https://github.com/thienan230427/TaxSentry.git
cd TaxSentry
npm install
node bin/taxsentry.js setup
```

## Bắt đầu nhanh sau khi cài

### 1. Chạy setup

```bash
taxsentry setup
```

Lệnh này sẽ:
- kiểm tra Python
- tạo virtual environment trong `~/.taxsentry/.venv`
- copy Python core vào runtime home của TaxSentry
- cài dependencies Python
- mở wizard cấu hình ban đầu

### 2. Kiểm tra trạng thái hệ thống

```bash
taxsentry status
```

Lệnh này hữu ích để xem nhanh:
- Python đã được nhận chưa
- config đã có chưa
- bot Telegram đang ở trạng thái nào
- service/runtime đang ra sao

### 3. Chạy hệ thống

Nếu muốn chạy gateway đầy đủ:

```bash
taxsentry up
```

Flow này sẽ:
- mở TUI dashboard ở foreground
- chạy Telegram bot song song theo runtime đi kèm

Nếu chỉ muốn mở dashboard:

```bash
taxsentry start
```

Nếu chỉ muốn bật bot nền:

```bash
taxsentry bot
```

### 4. Dừng bot hoặc runtime nền

```bash
taxsentry stop
```

## Service mode

Nếu muốn bot hoạt động kiểu ổn định hơn ở tầng hệ điều hành, TaxSentry có service workflow riêng.

Xem trạng thái service definition hiện tại:

```bash
taxsentry service status
```

Tạo artifact service:

```bash
taxsentry service install
```

Apply service vào OS:

```bash
taxsentry service apply
```

Trên Windows, bước này sẽ đăng ký bot vào Task Scheduler.

Điều khiển service đã apply:

```bash
taxsentry service start
taxsentry service stop
taxsentry service restart
taxsentry service logs
```

Gỡ service hoặc artifact:

```bash
taxsentry service remove
taxsentry service uninstall
```

## Cấu hình linh hoạt

Một điểm rất đáng tiền của TaxSentry là phần config không bị đóng cứng.

Các lệnh chính:

```bash
taxsentry config
taxsentry config set <fieldPath> <value>
taxsentry config add-field <group> <key> <label>
taxsentry config rename-field <group> <oldKey> <newKey>
taxsentry config remove-field <group> <key>
taxsentry config add-group <id> <label>
taxsentry config env-map <fieldPath> <ENV_VAR>
taxsentry config generate-env
```

Điều này giúp mỗi doanh nghiệp có thể tùy biến field cấu hình mà không phải lao vào chỉnh code cho từng thay đổi nhỏ.

## Một flow vận hành điển hình

Nếu triển khai thực tế, flow thường sẽ là:
1. chạy `taxsentry setup`
2. kiểm tra lại bằng `taxsentry status`
3. chạy `taxsentry up` hoặc `taxsentry bot`
4. theo dõi runtime bằng `taxsentry service status` và `taxsentry service logs`
5. nếu muốn giao bot cho OS quản lý, dùng `taxsentry service install` rồi `taxsentry service apply`

## Troubleshooting

### Setup báo thiếu Python

Cài Python 3.10+ trước, rồi chạy lại:

```bash
taxsentry setup
```

### npm báo chưa đăng nhập

Nếu gặp lỗi kiểu auth khi publish:

```bash
npm adduser
```

### `service apply` trên Windows báo access is denied

Mở terminal với quyền phù hợp rồi chạy lại:

```bash
taxsentry service apply
```

### Bot Telegram có vẻ không khỏe

Kiểm tra status và logs:

```bash
taxsentry status
taxsentry service logs
```

Nếu cần, restart sạch:

```bash
taxsentry stop
taxsentry bot
```

### Muốn reset runtime cho sạch

```bash
taxsentry stop
taxsentry status
taxsentry bot
```

## TaxSentry lưu dữ liệu ở đâu?

Runtime data chủ yếu nằm trong:
- `~/.taxsentry/`
- `~/.taxsentry/.venv/`
- `~/.taxsentry/taxsentry-core/`
- `~/.taxsentry/logs/`
- `~/.taxsentry/services/`
- `~/.taxsentry/run/`

## Trạng thái sản phẩm hiện tại

TaxSentry đã qua mức prototype cho vui. Ở thời điểm README này được viết lại, sản phẩm đã có:
- npm package public: `taxsentry@0.1.1`
- public `npx taxsentry --version` hoạt động đúng
- runtime local đã được làm sạch và ổn định hơn trước
- Windows Task Scheduler flow đã được verify thực tế
- tarball npm đã được làm sạch, không còn nhét secrets hoặc runtime artifacts vào package publish

Vẫn còn phần có thể polish tiếp cho launch rộng rãi hơn, như screenshot, GIF demo, tài liệu tiếng Anh, và launch assets. Nhưng lõi kỹ thuật và đường publish hiện đã khá vững.

## Ghi chú về bảo mật

TaxSentry được xây theo tinh thần local-first, nhưng local-first không có nghĩa là tự động an toàn tuyệt đối.

Sếp vẫn nên coi các thứ sau là dữ liệu nhạy cảm:
- file `.env`
- database nội bộ
- file báo cáo tải về
- log runtime
- các file đầu ra có chứa dữ liệu tài chính

## Dành cho maintainers

Trước khi publish bản mới, nên kiểm tra tối thiểu:

```bash
npm pack --json
npm publish --dry-run
npm view taxsentry version dist-tags.latest
npx --yes taxsentry --version
```

## License

MIT
