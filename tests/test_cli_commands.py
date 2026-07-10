from taxsentry.tui import _parser, update


def test_new_commands_are_public(monkeypatch):
    parser = _parser()
    assert parser.parse_args(["start"]).command == "start"
    assert parser.parse_args(["gateway"]).command == "gateway"
    assert parser.parse_args(["doctor", "--fix"]).fix is True

    monkeypatch.setattr("taxsentry.tui.shutil.which", lambda name: "uv")
    monkeypatch.setattr("taxsentry.tui.subprocess.run", lambda *args, **kwargs: type("Result", (), {"returncode": 0})())
    assert update() == 0
