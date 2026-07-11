from taxsentry.tui import _parser, report, update


def test_new_commands_are_public(monkeypatch):
    parser = _parser()
    assert parser.parse_args(["start"]).command == "start"
    assert parser.parse_args(["gateway"]).command == "gateway"
    assert parser.parse_args(["doctor", "--fix"]).fix is True

    monkeypatch.setattr("taxsentry.tui.shutil.which", lambda name: "uv")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return type("Result", (), {"returncode": 0})()

    monkeypatch.setattr("taxsentry.tui.subprocess.run", run)
    assert update() == 0
    assert calls[0][:3] == ["uv", "tool", "install"]
    assert calls[0][-1].startswith("git+https://github.com/")


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
