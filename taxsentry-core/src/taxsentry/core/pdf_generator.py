"""
📄 TaxSentry PDF Generator Module
Chuyển đổi báo cáo phân tích Markdown của AI thành tệp PDF chuyên nghiệp
sử dụng thư viện reportlab, hỗ trợ tiếng Việt không bị lỗi font (nạp font Arial từ hệ thống Windows).
"""

import os
import re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    HRFlowable
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

class TaxSentryPDFGenerator:
    """Bộ tạo PDF từ báo cáo Markdown chuyên nghiệp."""

    def __init__(self):
        self._register_vietnamese_font()
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _register_vietnamese_font(self):
        """Đăng ký font TrueType hỗ trợ tiếng Việt từ thư mục font của Windows."""
        # Các đường dẫn font phổ biến trên Windows
        font_dir = "C:/Windows/Fonts"
        normal_font_path = os.path.join(font_dir, "arial.ttf")
        bold_font_path = os.path.join(font_dir, "arialbd.ttf")
        italic_font_path = os.path.join(font_dir, "ariali.ttf")

        # Fallback nếu không chạy trên Windows hoặc không tìm thấy font Arial
        if not os.path.exists(normal_font_path):
            # Thử tìm trong thư mục hiện tại hoặc các đường dẫn khác
            normal_font_path = "arial.ttf"
            bold_font_path = "arialbd.ttf"
            italic_font_path = "ariali.ttf"

        try:
            # Đăng ký font thường
            if os.path.exists(normal_font_path):
                pdfmetrics.registerFont(TTFont('Arial', normal_font_path))
                print(f"✅ Đã đăng ký font Arial từ: {normal_font_path}")
            else:
                pdfmetrics.registerFont(TTFont('Arial', 'Helvetica'))
                print("⚠️ Không tìm thấy font Arial, sử dụng Helvetica (Không hỗ trợ tốt tiếng Việt)")

            # Đăng ký font đậm
            if os.path.exists(bold_font_path):
                pdfmetrics.registerFont(TTFont('Arial-Bold', bold_font_path))
            else:
                pdfmetrics.registerFont(TTFont('Arial-Bold', 'Helvetica-Bold'))

            # Đăng ký font nghiêng
            if os.path.exists(italic_font_path):
                pdfmetrics.registerFont(TTFont('Arial-Italic', italic_font_path))
            else:
                pdfmetrics.registerFont(TTFont('Arial-Italic', 'Helvetica-Oblique'))

        except Exception as e:
            print(f"❌ Lỗi khi đăng ký font tiếng Việt: {e}")

    def _setup_custom_styles(self):
        """Thiết lập các kiểu định dạng văn bản (Paragraph Styles) đẹp mắt, hiện đại."""
        # Lấy font đã đăng ký
        font_family = 'Arial'
        
        # Tiêu đề chính (Title)
        self.title_style = ParagraphStyle(
            'DocTitle',
            parent=self.styles['Normal'],
            fontName=f'{font_family}-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor('#1F4E79'),  # Xanh navy cổ điển
            alignment=TA_CENTER,
            spaceAfter=20
        )

        # Tiêu đề cấp 1 (H1)
        self.h1_style = ParagraphStyle(
            'DocH1',
            parent=self.styles['Normal'],
            fontName=f'{font_family}-Bold',
            fontSize=15,
            leading=18,
            textColor=colors.HexColor('#1F4E79'),
            spaceBefore=15,
            spaceAfter=8,
            keepWithNext=True
        )

        # Tiêu đề cấp 2 (H2)
        self.h2_style = ParagraphStyle(
            'DocH2',
            parent=self.styles['Normal'],
            fontName=f'{font_family}-Bold',
            fontSize=12,
            leading=15,
            textColor=colors.HexColor('#2E75B6'),  # Xanh nhạt hơn
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True
        )

        # Nội dung chính (Body Text)
        self.body_style = ParagraphStyle(
            'DocBody',
            parent=self.styles['Normal'],
            fontName=font_family,
            fontSize=10.5,
            leading=14,
            textColor=colors.HexColor('#333333'),  # Xám đậm dễ đọc
            alignment=TA_JUSTIFY,
            spaceBefore=4,
            spaceAfter=4
        )

        # Khối cảnh báo rủi ro (Alert / Callout Box)
        self.alert_style = ParagraphStyle(
            'DocAlert',
            parent=self.styles['Normal'],
            fontName=font_family,
            fontSize=10,
            leading=13,
            textColor=colors.HexColor('#9C0006'),  # Đỏ đậm
            spaceBefore=4,
            spaceAfter=4
        )

        # Ghi chú / Text nhỏ
        self.caption_style = ParagraphStyle(
            'DocCaption',
            parent=self.styles['Normal'],
            fontName=f'{font_family}-Italic',
            fontSize=9,
            leading=11,
            textColor=colors.HexColor('#666666'),
            spaceBefore=2,
            spaceAfter=2
        )

    def _parse_markdown_to_flowables(self, markdown_text: str) -> list:
        """Phân tích văn bản Markdown đơn giản và chuyển đổi thành danh sách Flowables của ReportLab."""
        flowables = []
        lines = markdown_text.split('\n')
        
        in_list = False
        list_items = []
        
        # Biến hỗ trợ đọc bảng biểu Markdown
        in_table = False
        table_rows = []

        for line in lines:
            stripped = line.strip()
            
            # 1. Bỏ qua dòng trống
            if not stripped:
                if in_list:
                    in_list = False
                    # Không cần làm gì thêm, danh sách đã được xử lý từng phần
                if in_table:
                    # Xuất bảng ra flowable
                    table_flowable = self._create_table_flowable(table_rows)
                    if table_flowable:
                        flowables.append(table_flowable)
                        flowables.append(Spacer(1, 10))
                    in_table = False
                    table_rows = []
                continue

            # 2. Xử lý bảng biểu Markdown (đường kẻ phân tách |---|---|...)
            if stripped.startswith('|'):
                if '---' in stripped:
                    # Dòng gạch ngang phân tách header, bỏ qua
                    continue
                in_table = True
                # Tách các cột
                cols = [c.strip() for c in stripped.split('|')[1:-1]]
                table_rows.append(cols)
                continue
            elif in_table:
                # Nếu đang trong bảng mà gặp dòng không bắt đầu bằng '|', kết thúc bảng
                table_flowable = self._create_table_flowable(table_rows)
                if table_flowable:
                    flowables.append(table_flowable)
                    flowables.append(Spacer(1, 10))
                in_table = False
                table_rows = []

            # 3. Xử lý tiêu đề chính (ví dụ: # Tiêu đề chính)
            if stripped.startswith('# '):
                title_text = stripped[2:]
                flowables.append(Paragraph(self._clean_inline_markdown(title_text), self.title_style))
                flowables.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor('#1F4E79'), spaceAfter=15))
                continue

            # 4. Xử lý tiêu đề cấp 1 (## H1) hoặc cấp 2 (### H2)
            if stripped.startswith('## '):
                h1_text = stripped[3:]
                flowables.append(Paragraph(self._clean_inline_markdown(h1_text), self.h1_style))
                continue
            if stripped.startswith('### '):
                h2_text = stripped[4:]
                flowables.append(Paragraph(self._clean_inline_markdown(h2_text), self.h2_style))
                continue

            # 5. Xử lý đường kẻ phân tách (---)
            if stripped == '---':
                flowables.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CCCCCC'), spaceBefore=8, spaceAfter=8))
                continue

            # 6. Xử lý danh sách (bắt đầu bằng * hoặc - hoặc 1.)
            list_match = re.match(r'^[\*\-\+]\s+(.*)', stripped)
            num_list_match = re.match(r'^\d+\.\s+(.*)', stripped)
            
            if list_match:
                bullet_content = list_match.group(1)
                clean_bullet = self._clean_inline_markdown(bullet_content)
                flowables.append(Paragraph(f"• &nbsp; {clean_bullet}", self.body_style))
                continue
            elif num_list_match:
                num_content = num_list_match.group(1)
                clean_num = self._clean_inline_markdown(num_content)
                # Lấy số thứ tự
                num_prefix = re.match(r'^(\d+\.)', stripped).group(1)
                flowables.append(Paragraph(f"{num_prefix} &nbsp; {clean_num}", self.body_style))
                continue

            # 7. Khối văn bản cảnh báo rủi ro nhạy cảm (🚨 hoặc ⚠️ ở đầu)
            if stripped.startswith('🚨') or stripped.startswith('⚠️') or stripped.startswith('🚨') or 'rủi ro' in stripped.lower() or 'vi phạm' in stripped.lower():
                clean_text = self._clean_inline_markdown(stripped)
                # Tạo một bảng nhỏ có viền đỏ nhạt để làm nổi bật cảnh báo
                alert_p = Paragraph(clean_text, self.alert_style)
                alert_table = Table([[alert_p]], colWidths=[460])
                alert_table.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#FFEBEE')),  # Đỏ nhạt cực sang
                    ('BOX', (0,0), (-1,-1), 1, colors.HexColor('#FFCDD2')),
                    ('PADDING', (0,0), (-1,-1), 8),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 8),
                ]))
                flowables.append(alert_table)
                flowables.append(Spacer(1, 8))
                continue

            # 8. Văn bản thường
            clean_text = self._clean_inline_markdown(stripped)
            flowables.append(Paragraph(clean_text, self.body_style))
            flowables.append(Spacer(1, 4))
            
        # Kiểm tra bảng cuối cùng nếu chưa xuất
        if in_table and table_rows:
            table_flowable = self._create_table_flowable(table_rows)
            if table_flowable:
                flowables.append(table_flowable)
                flowables.append(Spacer(1, 10))

        return flowables

    def _clean_inline_markdown(self, text: str) -> str:
        """Làm sạch các cú pháp markdown in-line như chữ đậm (**), chữ nghiêng (*), mã code (`)."""
        # Thay thế chữ đậm: **text** -> <b>text</b>
        text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', text)
        # Thay thế chữ nghiêng: *text* -> <i>text</i>
        text = re.sub(r'\*(.*?)\*', r'<i>\1</i>', text)
        # Thay thế ký tự đặc biệt HTML
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        # Phục hồi tag <b> và <i> đã escape
        text = text.replace('&lt;b&gt;', '<b>').replace('&lt;/b&gt;', '</b>')
        text = text.replace('&lt;i&gt;', '<i>').replace('&lt;/i&gt;', '</i>')
        return text

    def _create_table_flowable(self, rows: list) -> Table:
        """Tạo đối tượng Table ReportLab đẹp mắt từ danh sách các hàng dữ liệu bảng biểu."""
        if not rows:
            return None
            
        # Convert các cell thành Paragraph để tự xuống dòng
        paragraph_rows = []
        for r_idx, row in enumerate(rows):
            paragraph_row = []
            for cell in row:
                # Header thì in đậm
                if r_idx == 0:
                    style = ParagraphStyle(
                        'TableHeader',
                        parent=self.styles['Normal'],
                        fontName='Arial-Bold',
                        fontSize=9.5,
                        textColor=colors.white,
                        alignment=TA_LEFT
                    )
                else:
                    style = ParagraphStyle(
                        'TableCell',
                        parent=self.styles['Normal'],
                        fontName='Arial',
                        fontSize=9,
                        textColor=colors.HexColor('#333333'),
                        alignment=TA_LEFT
                    )
                paragraph_row.append(Paragraph(self._clean_inline_markdown(cell), style))
            paragraph_rows.append(paragraph_row)

        # Tính toán độ rộng cột tự động dựa trên số cột
        num_cols = len(rows[0])
        col_width = 460.0 / num_cols
        col_widths = [col_width] * num_cols

        t = Table(paragraph_rows, colWidths=col_widths)
        
        # Style cho bảng
        t_style = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1F4E79')),  # Header Navy
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('PADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#EEEEEE')),
        ]
        
        # Thêm dòng kẻ sọc ngựa vằn (zebra striping)
        for i in range(1, len(rows)):
            if i % 2 == 0:
                t_style.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#F9FBFD')))
                
        t.setStyle(TableStyle(t_style))
        return t

    def generate(self, markdown_content: str, output_pdf_path: str):
        """Tạo file PDF từ nội dung báo cáo Markdown và lưu ra đường dẫn đích."""
        output_path = Path(output_pdf_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Thiết lập template tài liệu
        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=letter,
            rightMargin=54,  # Lề 0.75 inch tương đối rộng rãi, chuyên nghiệp
            leftMargin=54,
            topMargin=54,
            bottomMargin=54
        )

        story = []
        
        # Tạo trang bìa hoặc đầu trang đẹp mắt
        story.append(Paragraph("TAXSENTRY AI CO-PILOT REPORT", self.caption_style))
        story.append(Spacer(1, 10))

        # Phân tích markdown thành flowables
        flowables = self._parse_markdown_to_flowables(markdown_content)
        story.extend(flowables)
        
        # Chữ ký chân trang
        story.append(Spacer(1, 25))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#CCCCCC'), spaceAfter=10))
        story.append(Paragraph("Báo cáo được thực hiện tự động và bảo mật hoàn toàn bởi hệ thống TaxSentry Co-Pilot.", self.caption_style))

        # Build PDF
        try:
            doc.build(story)
            print(f"🎉 Đã xuất bản báo cáo PDF thành công tại: {output_path}")
            return True
        except Exception as e:
            print(f"❌ Lỗi khi xây dựng file PDF: {e}")
            return False

def main():
    print("--- CHẠY THỬ NGHIỆM PDF GENERATOR ---")
    markdown_test = """# Báo Cáo Phân Tích Tài Chính & Rủi Ro Thuế
## 📊 1. Đánh giá hiệu quả kinh doanh
Tháng này hoạt động kinh doanh của doanh nghiệp ghi nhận các kết quả khả quan:
*   Doanh thu bán hàng đạt **650,000,000 VND**, tăng trưởng mạnh mẽ.
*   Lợi nhuận gộp đạt **410,000,000 VND** nhờ việc tối ưu chi phí giá vốn.
*   Chi phí lương thưởng tăng do động viên phòng kinh doanh hoàn thành KPI.

---

## 🚨 2. Cảnh báo rủi ro thuế nghiêm trọng
🚨 Phát hiện **45,000,000 VND** chi phí Tiếp khách KHÔNG có hóa đơn đỏ (Sẽ bị loại khi tính thuế TNDN!).
⚠️ Tổng chi phí tiếp khách thực tế vượt quá hạn mức quy định của luật thuế Việt Nam.

## 📊 3. Bảng số liệu chi tiết
| Chỉ tiêu | Giá trị (VND) | Đánh giá |
|---|---|---|
| Doanh thu | 650,000,000 | Tốt |
| Lợi nhuận | 120,000,000 | Ổn định |
| Chi phí không hóa đơn | 45,000,000 | Nguy hiểm |
"""
    generator = TaxSentryPDFGenerator()
    generator.generate(markdown_test, "D:/TaxSentry/downloads/test_report.pdf")

if __name__ == "__main__":
    main()
