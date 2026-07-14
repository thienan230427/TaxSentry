import pytest

from taxsentry.tui import _parser, main, report


@pytest.mark.parametrize(
    ("arguments", "command"),
    [
        (["chat"], "chat"),
        (["start"], "start"),
        (["gateway"], "gateway"),
        (["update"], "update"),
        (["update", "--main"], "update"),
        (["setup"], "setup"),
        (["status"], "status"),
        (["doctor", "--fix"], "doctor"),
        (["jobs"], "jobs"),
        (["report", "--send"], "report"),
        (["worker", "run", "--once"], "worker"),
        (["auth", "codex", "--device-code"], "auth"),
        (["service", "status"], "service"),
    ],
)
def test_all_commands_are_public(arguments, command):
    parser = _parser()
    assert parser.parse_args(arguments).command == command


def test_update_flag_is_dispatched(monkeypatch):
    calls = []
    monkeypatch.setattr("taxsentry.tui.perform_update", lambda **kwargs: calls.append(kwargs) or (0, "ok"))

    assert main(["update", "--main"]) == 0
    assert calls == [{"main": True}]


def test_manual_report_send_requires_confirmation_and_audits(monkeypatch, tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.7")
    deliveries = []

    class Store:
        def latest_report(self):
            return {"job_id": "job-1", "subject": "Tháng 5", "pdf_path": str(pdf), "payload": {"executive_summary": "Ổn định", "performance": [], "tax_risks": [], "missing_data": [], "recommendations": [], "confidence": 0.9}}

        def delivery(self, *args):
            deliveries.append(args)

    class Gmail:
        def send_report(self, *args, **kwargs):
            return "gmail-1"

    class Telegram:
        async def notify(self, *args):
            return ["telegram-1"]

    monkeypatch.setattr("taxsentry.tui.JobStore", Store)
    monkeypatch.setattr("taxsentry.tui.Confirm.ask", lambda *args: True)
    monkeypatch.setattr("taxsentry.tui.load_config", lambda: {"director": {"email": "director@example.com"}})
    monkeypatch.setattr("taxsentry.tui.GmailClient", lambda settings: Gmail())
    monkeypatch.setattr("taxsentry.tui.TelegramDirector", lambda settings: Telegram())
    assert report(send=True) == 0
    assert [item[1] for item in deliveries] == ["gmail", "telegram"]
