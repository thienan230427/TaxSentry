# 📖 CƠ SỞ TRI THỨC PHÁP LUẬT THUẾ DOANH NGHIỆP VIỆT NAM (TAX KNOWLEDGE BASE)

Cơ sở tri thức này cung cấp các quy định pháp lý cốt lõi về Thuế thu nhập doanh nghiệp (TNDN) và Thuế giá trị gia tăng (GTGT) hiện hành tại Việt Nam để hệ thống **TaxSentry** đối chiếu, phân tích rủi ro và ra đề xuất tài chính desu~! ♪

---

## 1. CÁC KHOẢN CHI PHÍ ĐƯỢC TRỪ KHI TÍNH THUẾ TNDN (DEDUCTIBLE EXPENSES)

Để một khoản chi phí được tính là chi phí hợp lý được trừ khi xác định thu nhập chịu thuế TNDN, khoản chi đó phải đáp ứng đủ 3 điều kiện tiên quyết sau (Theo Thông tư 78/2014/TT-BTC và Thông tư 96/2015/TT-BTC):

1.  **Tính liên quan:** Khoản chi thực tế phát sinh liên quan đến hoạt động sản xuất, kinh doanh của doanh nghiệp.
2.  **Chứng từ hợp pháp:** Khoản chi có đủ hóa đơn, chứng từ hợp pháp theo quy định của pháp luật (Hóa đơn giá trị gia tăng hoặc Hóa đơn bán hàng hợp lệ).
3.  **Thanh toán không dùng tiền mặt:** Khoản chi nếu có hóa đơn mua hàng hóa, dịch vụ từng lần có giá trị từ **20 triệu đồng trở lên** (giá đã bao gồm thuế GTGT) khi thanh toán phải có chứng từ thanh toán không dùng tiền mặt (chuyển khoản ngân hàng).

---

## 2. CÁC KHOẢN CHI PHÍ KHÔNG ĐƯỢC TRỪ (NON-DEDUCTIBLE EXPENSES) — TRỌNG TÂM PHÁT HIỆN RỦI RO!

Hệ thống TaxSentry cần đặc biệt chú ý quét và bắt lỗi các khoản chi phí sau để cảnh báo rủi ro quyết toán thuế cho Giám đốc:

### 🚨 Rủi ro A: Chi phí tiếp khách, hội nghị không có hóa đơn đỏ hợp lệ
*   **Quy định:** Mọi khoản chi phí tiếp khách, tiếp đoàn, hội nghị, khánh tiết bắt buộc phải có hóa đơn tài chính (Hóa đơn điện tử có mã của cơ quan thuế) và chứng từ thanh toán hợp lệ.
*   **Hậu quả:** Các khoản chi tiếp khách ghi nhận theo "phiếu thu", "hóa đơn bán lẻ" hoặc tự kê khai không có hóa đơn đỏ sẽ bị cơ quan thuế loại ra khỏi chi phí được trừ khi quyết toán thuế TNDN. Doanh nghiệp sẽ bị truy thu 20% thuế TNDN trên khoản chi này kèm phạt chậm nộp.

### 🚨 Rủi ro B: Vượt hạn mức chi phí tiếp khách (Nếu có)
*   **Quy định lịch sử:** Trước đây có quy định khống chế chi phí tiếp khách không vượt quá 15% tổng chi phí được trừ.
*   **Quy định hiện tại:** Luật hiện hành đã bỏ trần 15% đối với chi phí tiếp khách thông thường. Tuy nhiên, đối với các doanh nghiệp Startup hoặc quy mô nhỏ, chi phí tiếp khách chiếm tỷ trọng quá lớn (ví dụ >15% Doanh thu) mà không giải trình được tính hợp lý sẽ bị cơ quan thuế đưa vào tầm ngắm thanh tra, kiểm tra chi tiết.

### 🚨 Rủi ro C: Chi phí tiền lương, tiền thưởng không thực tế
*   **Quy định:** Chi trả tiền lương, tiền thưởng cho người lao động nhưng không được ghi cụ thể điều kiện được hưởng và mức được hưởng trong một trong các hồ sơ sau: Hợp đồng lao động; Thỏa ước lao động tập thể; Quy chế tài chính của Công ty.
*   **Hậu quả:** Sẽ bị loại hoàn toàn khỏi chi phí hợp lý.

### 🚨 Rủi ro D: Chi phí phạt vi phạm hành chính
*   **Quy định:** Các khoản chi tiền phạt vi phạm hành chính bao gồm: phạt vi phạm luật giao thông, phạt chậm nộp hồ sơ khai thuế, phạt chậm nộp thuế, phạt vi phạm chế độ đăng ký kinh doanh,...
*   **Hậu quả:** Hoàn toàn không được tính vào chi phí được trừ khi tính thuế TNDN.

---

## 3. CÔNG THỨC TÍNH THUẾ TNDN VÀ TIỀN PHẠT CHẬM NỘP

### 🧮 A. Thuế TNDN phải nộp:
$$\text{Thuế TNDN phải nộp} = (\text{Thu nhập tính thuế} - \text{Phần trích lập quỹ KHCN}) \times \text{Thuế suất TNDN (20\%)} $$
Trong đó:
$$\text{Thu nhập tính thuế} = \text{Doanh thu} - \text{Chi phí được trừ} + \text{Thu nhập khác}$$

### 🧮 B. Công thức tính tiền phạt chậm nộp thuế (Theo Luật Quản lý thuế số 38/2019/QH14):
Nếu doanh nghiệp nộp chậm tiền thuế so với thời hạn quy định, số tiền phạt chậm nộp được tính như sau:
$$\text{Tiền phạt chậm nộp} = \text{Số tiền thuế nộp chậm} \times 0.03\% \times \text{Số ngày nộp chậm}$$

---
*Kho tri thức được biên soạn bởi Grace phục vụ riêng cho dự án TaxSentry của Sếp Thiên Ân desu~! 💖*
