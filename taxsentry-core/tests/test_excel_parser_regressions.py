import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / 'src'
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from taxsentry.core.excel_parser import TaxSentryParser
from taxsentry.core.automation import AUTOMATION_LOGS, TaxSentryAutomationWorkflow
from taxsentry.core.evidence_preview import build_evidence_context, build_evidence_preview_text, build_trace_replay_text, load_evidence_context, save_evidence_context

FIXTURES_DIR = PROJECT_ROOT.parent / 'stress_tests'


class ExcelParserRegressionTests(unittest.TestCase):
    def test_stress_raw_single_sheet_ignores_numeric_code_column(self):
        parser = TaxSentryParser(str(FIXTURES_DIR / 'stress_raw_single_sheet.xlsx'))
        parser.load()
        parser.parse_workbook()

        self.assertEqual(parser.document_types, ['income_statement'])
        self.assertEqual(parser.is_data['T4']['revenue'], 980000000.0)
        self.assertEqual(parser.is_data['T4']['cogs'], 360000000.0)
        self.assertEqual(parser.is_data['T4']['ebt'], 190000000.0)
        self.assertEqual(parser.is_data['T5']['revenue'], 1260000000.0)
        self.assertEqual(parser.canonical_metrics['revenue']['periods'], ['Kỳ trước', 'Kỳ này'])

    def test_stress_financial_multisheet_extracts_multiple_document_types(self):
        parser = TaxSentryParser(str(FIXTURES_DIR / 'stress_financial_multisheet.xlsx'))
        parser.load()
        parser.parse_workbook()

        self.assertEqual(
            parser.document_types,
            ['assumptions', 'income_statement', 'balance_sheet', 'cash_flow'],
        )
        self.assertIn('gross_profit', parser.canonical_metrics)
        self.assertIn('net_income', parser.is_data['T5'])
        self.assertAlmostEqual(parser.assumptions['tax_rate'], 0.2)

    def test_stress_payroll_formula_heavy_extracts_payroll_metrics(self):
        parser = TaxSentryParser(str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx'))
        parser.load()
        parser.parse_workbook()

        self.assertEqual(parser.document_types, ['payroll'])
        self.assertEqual(sorted(parser.canonical_metrics.keys()), [
            'net_pay',
            'personal_income_tax',
            'social_insurance',
            'total_income',
        ])
        self.assertTrue(parser.has_meaningful_data())

    def test_payroll_evidence_preview_includes_attachments_and_sheet_details(self):
        parser = TaxSentryParser(str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx'))
        parser.load()
        parser.parse_workbook()

        evidence = build_evidence_context(
            parser,
            {
                'email_subject': 'Bảng lương tháng 06/2026',
                'attachments': [
                    {'file_name': 'stress_payroll_formula_heavy.xlsx', 'kind': 'excel', 'suffix': '.xlsx', 'path': str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx')},
                    {'file_name': 'bang-luong-preview-1.png', 'kind': 'image', 'suffix': '.png', 'path': 'D:/fake/bang-luong-preview-1.png'},
                ],
            },
        )
        preview_text = build_evidence_preview_text(evidence, director_name='Sếp')

        self.assertIn('Bảng lương tháng 06/2026', preview_text)
        self.assertIn('bang-luong-preview-1.png', preview_text)
        self.assertIn('Workbook có', preview_text)
        self.assertIn('Tổng thu nhập chi trả', preview_text)
        self.assertTrue(evidence['image_attachments'])

    def test_evidence_context_roundtrip_preserves_preview_inputs(self):
        parser = TaxSentryParser(str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx'))
        parser.load()
        parser.parse_workbook()

        evidence = build_evidence_context(
            parser,
            {
                'email_subject': 'Bảng lương tháng 06/2026',
                'attachments': [
                    {'file_name': 'stress_payroll_formula_heavy.xlsx', 'kind': 'excel', 'suffix': '.xlsx', 'path': str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx')},
                ],
            },
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / 'evidence.json'
            saved_path = save_evidence_context(evidence, target)

            self.assertEqual(saved_path, target)
            loaded = load_evidence_context(target)
            self.assertEqual(loaded['source_file'], evidence['source_file'])
            self.assertEqual(loaded['email_subject'], 'Bảng lương tháng 06/2026')
            self.assertEqual(loaded['attachments'][0]['file_name'], 'stress_payroll_formula_heavy.xlsx')
            self.assertTrue(loaded.get('session_id'))
            self.assertTrue(loaded.get('event_id'))
            self.assertTrue(loaded.get('trace_id'))
            self.assertEqual(loaded['session_id'], evidence['session_id'])
            self.assertEqual(loaded['event_id'], evidence['event_id'])
            self.assertEqual(loaded['trace_id'], evidence['trace_id'])
            self.assertIn(f"session={loaded['session_id']}", build_evidence_preview_text(loaded, director_name='Sếp'))
            replay_text = build_trace_replay_text(loaded, AUTOMATION_LOGS)
            self.assertIn('Trace replay for', replay_text)
            self.assertIn(loaded['session_id'], replay_text)
            self.assertIn(loaded['event_id'], replay_text)
            self.assertEqual(
                build_evidence_preview_text(loaded, director_name='Sếp'),
                build_evidence_preview_text(evidence, director_name='Sếp'),
            )


class ControlledWorkflowRegressionTests(unittest.TestCase):
    def test_run_once_processes_three_stubbed_excel_reports(self):
        target_files = [
            str(FIXTURES_DIR / 'stress_financial_multisheet.xlsx'),
            str(FIXTURES_DIR / 'stress_payroll_formula_heavy.xlsx'),
            str(FIXTURES_DIR / 'stress_raw_single_sheet.xlsx'),
        ]

        workflow = TaxSentryAutomationWorkflow()
        workflow.poller.connect = lambda: True
        workflow.poller.disconnect = lambda: None
        workflow.poller.check_and_download = lambda: target_files
        workflow.poller.get_file_context = lambda file_path: (
            {'email_id': 'email-a'} if 'multisheet' in file_path else
            {'email_id': 'email-b'} if 'formula_heavy' in file_path else
            {'email_id': 'email-c'}
        )
        workflow.poller.mark_email_ids_as_processed = mock.Mock(return_value=3)
        workflow.sender.send_report = mock.Mock(return_value=True)

        generated_pdfs = []

        def fake_generate(markdown, output_path, trace_context=None, artifact_store=None):
            Path(output_path).write_text(markdown, encoding='utf-8')
            generated_pdfs.append(output_path)
            return True

        workflow.generator.generate = fake_generate
        workflow.engine.run_audit = mock.Mock(return_value='# report\n\nTóm tắt rủi ro thuế')

        temp_json = Path(tempfile.gettempdir()) / 'taxsentry_regression_parsed_report.json'

        AUTOMATION_LOGS.clear()
        telegram_mock = mock.AsyncMock(return_value=True)
        with mock.patch('taxsentry.core.automation.JSON_PATH', temp_json), \
             mock.patch('taxsentry.core.automation.EVIDENCE_CONTEXT_PATH', Path(tempfile.gettempdir()) / 'taxsentry_regression_evidence.json'), \
             mock.patch('taxsentry.bot.telegram_bot.send_active_report_to_director', new=telegram_mock):
            processed = workflow.run_once()

        self.assertEqual(processed, 3)
        self.assertEqual(workflow.engine.run_audit.call_count, 3)
        self.assertEqual(workflow.sender.send_report.call_count, 3)
        workflow.poller.mark_email_ids_as_processed.assert_called_once_with(['email-a', 'email-b', 'email-c'])
        self.assertEqual(len(generated_pdfs), 3)
        self.assertTrue(temp_json.exists())
        telegram_mock.assert_awaited()
        self.assertIn('evidence_context_path', telegram_mock.await_args.kwargs)

        data = json.loads(temp_json.read_text(encoding='utf-8'))
        evidence_data = json.loads((Path(tempfile.gettempdir()) / 'taxsentry_regression_evidence.json').read_text(encoding='utf-8'))
        self.assertEqual(data['metadata']['file_name'], 'stress_raw_single_sheet.xlsx')
        self.assertEqual(data['data']['income_statement']['T5_Actual']['revenue'], 1260000000.0)
        self.assertTrue(evidence_data.get('session_id'))
        self.assertTrue(evidence_data.get('event_id'))
        self.assertTrue(evidence_data.get('trace_id'))
        self.assertTrue(any('Hoàn thành xử lý tự động hoàn toàn' in line for line in AUTOMATION_LOGS))


if __name__ == '__main__':
    unittest.main()
