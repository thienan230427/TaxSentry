from __future__ import annotations

import json

from scripts import benchmark_documents


def test_acceptance_profile_locks_required_large_fixture_sizes():
    profile = benchmark_documents.PROFILES["acceptance"]
    assert profile.xlsx_sheets >= 100
    assert profile.xlsx_sheets * profile.xlsx_rows_per_sheet >= 1_000_000
    assert profile.pdf_pages >= 1_000 and profile.pdf_scan_every > 0
    assert profile.pptx_slides >= 500
    assert 490 <= profile.target_case_mb < 500


def test_quick_profile_has_complete_coverage_and_no_silent_unit_loss(tmp_path):
    result = benchmark_documents.run_benchmark("quick", tmp_path / "benchmark")

    assert result["passed"]
    assert {item["name"] for item in result["documents"]} == {
        "xlsx",
        "pdf",
        "pptx",
        "docx",
    }
    for document in result["documents"]:
        coverage = document["coverage"]
        assert coverage["total"] == coverage["processed"]
        assert coverage["failed"] == coverage["skipped"] == 0
        assert document["no_silent_unit_loss"]
        assert document["missing_units"] == {}
    case = result["case"]["coverage"]
    assert case["complete"]
    assert case["total"] == case["processed"]


def test_benchmark_cli_writes_json_result(monkeypatch, tmp_path):
    monkeypatch.setattr(
        benchmark_documents,
        "run_benchmark",
        lambda profile: {"profile": profile, "passed": True},
    )
    output = tmp_path / "benchmark.json"
    assert (
        benchmark_documents.main(
            ["--profile", "quick", "--output", str(output)]
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8")) == {
        "profile": "quick",
        "passed": True,
    }
