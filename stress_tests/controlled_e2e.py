import asyncio
import json
from pathlib import Path

from taxsentry.bot import telegram_bot
from taxsentry.config.paths import AUDIT_REPORT_PATH, DOWNLOAD_DIR, JSON_PATH
from taxsentry.core.automation import AUTOMATION_LOGS, TaxSentryAutomationWorkflow


def main():
    base = Path(r'D:\TaxSentry\stress_tests')
    target_files = [
        str(base / 'stress_financial_multisheet.xlsx'),
        str(base / 'stress_payroll_formula_heavy.xlsx'),
        str(base / 'stress_raw_single_sheet.xlsx'),
    ]

    workflow = TaxSentryAutomationWorkflow()

    workflow.poller.connect = lambda: True
    workflow.poller.disconnect = lambda: None
    workflow.poller.check_and_download = lambda: target_files
    workflow.poller.mark_as_processed = lambda: None
    workflow.sender.send_report = lambda pdf_path, summary: True

    async def fake_send_active_report_to_director(pdf_path, summary_text):
        return True

    telegram_bot.send_active_report_to_director = fake_send_active_report_to_director

    before_pdfs = {p.name for p in DOWNLOAD_DIR.glob('BaoCao_KiemToan_*.pdf')}
    AUTOMATION_LOGS.clear()
    processed = workflow.run_once()
    after_pdfs = {p.name for p in DOWNLOAD_DIR.glob('BaoCao_KiemToan_*.pdf')}
    new_pdfs = sorted(after_pdfs - before_pdfs)

    result = {
        'processed_count': processed,
        'target_files': target_files,
        'new_pdfs': new_pdfs,
        'json_exists': JSON_PATH.exists(),
        'json_path': str(JSON_PATH),
        'audit_report_exists': AUDIT_REPORT_PATH.exists(),
        'audit_report_path': str(AUDIT_REPORT_PATH),
        'last_logs': AUTOMATION_LOGS[-25:],
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
