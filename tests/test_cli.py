from __future__ import annotations

import json

from conftest import CONTRACT_CASES

from gitnext.cli import main


def test_cli_help_prints_usage_to_stdout(capsys: object) -> None:
    for option in ("--help", "-h"):
        assert main([option]) == 0
        captured = capsys.readouterr()  # type: ignore[attr-defined]
        assert captured.out.startswith("Usage: gitnext")
        assert captured.err == ""


def test_fixture_cli_prints_only_json_to_stdout(capsys: object) -> None:
    fixture = sorted(CONTRACT_CASES.glob("*.json"))[0]
    assert main(["--fixture", str(fixture)]) == 0
    captured = capsys.readouterr()  # type: ignore[attr-defined]
    payload = json.loads(captured.out)
    assert payload["facts"]["schemaVersion"] == "1.0.0"
    assert payload["decision"]["schemaVersion"] == "1.0.0"
    assert captured.err == ""


def test_cli_usage_and_input_errors_stay_on_stderr(capsys: object) -> None:
    assert main([]) == 2
    usage = capsys.readouterr()  # type: ignore[attr-defined]
    assert usage.out == ""
    assert "Usage:" in usage.err

    assert main(["https://evil.example/a/b/pull/1"]) == 2
    invalid = capsys.readouterr()  # type: ignore[attr-defined]
    assert invalid.out == ""
    error = json.loads(invalid.err)
    assert error["error"]["kind"] == "INPUT"
