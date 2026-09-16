"""
Unit tests for CI/CD Quality Gate (ci_gate.py).
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from cwv_speed_engine.ci_gate import (
    run_cwv_check,
    format_github_annotation,
    write_github_step_summary,
    main as ci_gate_main,
)


class TestCIGate:
    """Test suite for CI Quality Gate and enforcement."""

    def test_format_github_annotation(self):
        anno = format_github_annotation(
            level="error",
            message="LCP exceeds 2500ms",
            title="LCP Violation",
            file="src/index.html",
            line=12,
        )
        assert anno.startswith("::error file=src/index.html,line=12,title=LCP Violation::")
        assert "LCP exceeds 2500ms" in anno

    def test_run_cwv_check_pass(self):
        audit = {
            "url": "https://speed.example.com",
            "score": 94.0,
            "metrics": {
                "lcp": 1900.0,
                "cls": 0.03,
                "inp": 110.0,
                "fcp": 1200.0,
                "ttfb": 280.0,
            }
        }

        passed, details, output = run_cwv_check(audit, min_score=85)

        assert passed is True
        assert details["score"] == 94.0
        assert len(details["failures"]) == 0
        assert "CORE WEB VITALS QUALITY GATE: PASSED" in output

    def test_run_cwv_check_score_failure(self):
        audit = {
            "url": "https://slow.example.com",
            "score": 72.0,
            "metrics": {
                "lcp": 2200.0,
                "cls": 0.05,
                "inp": 150.0,
            }
        }

        passed, details, output = run_cwv_check(audit, min_score=85)

        assert passed is False
        assert details["score"] == 72.0
        assert len(details["failures"]) == 1
        assert "below minimum required threshold 85" in details["failures"][0]
        assert "CORE WEB VITALS QUALITY GATE: FAILED" in output

    def test_run_cwv_check_critical_metric_failure(self):
        audit = {
            "url": "https://shift.example.com",
            "score": 88.0,  # Score passes threshold
            "metrics": {
                "lcp": 2100.0,
                "cls": 0.38,  # Poor CLS (> 0.25)
                "inp": 140.0,
            }
        }

        # With fail_on_critical=True, poor CLS should fail the gate
        passed, details, output = run_cwv_check(audit, min_score=85, fail_on_critical=True)
        assert passed is False
        assert any("rated POOR" in f for f in details["failures"])

        # With fail_on_critical=False, overall score passes
        passed_no_crit, _, _ = run_cwv_check(audit, min_score=85, fail_on_critical=False)
        assert passed_no_crit is True

    def test_run_cwv_check_custom_thresholds(self):
        audit = {
            "score": 90.0,
            "metrics": {
                "lcp": 2200.0,
                "cls": 0.04,
                "inp": 180.0,
            }
        }

        # Max allowed LCP is strictly 2000ms
        passed, details, _ = run_cwv_check(audit, min_score=80, max_lcp_ms=2000.0)
        assert passed is False
        assert any("exceeds custom threshold 2000.0" in f for f in details["failures"])

    def test_run_cwv_check_output_formats(self):
        audit = {
            "score": 91.0,
            "metrics": {
                "lcp": 1750.0,
                "cls": 0.02,
                "inp": 90.0,
            }
        }

        # 1. JSON
        _, _, json_out = run_cwv_check(audit, output_format="json")
        parsed = json.loads(json_out)
        assert parsed["score"] == 91.0
        assert parsed["passed"] is True

        # 2. Markdown
        _, _, md_out = run_cwv_check(audit, output_format="markdown")
        assert "# 🛡️ CWV Quality Gate Report" in md_out
        assert "✅ **PASSED**" in md_out
        assert "| **Largest Contentful Paint (LCP)**" in md_out

        # 3. GitHub Annotations
        _, _, gh_out = run_cwv_check(audit, output_format="github")
        assert "::notice" in gh_out
        assert "CWV Gate Passed" in gh_out

    def test_run_cwv_check_file_and_baseline_diff(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_file = Path(tmpdir) / "baseline.json"
            cand_file = Path(tmpdir) / "candidate.json"

            base_file.write_text(json.dumps({
                "score": 90.0,
                "metrics": {"lcp": 2000.0, "cls": 0.04, "inp": 120.0}
            }), encoding="utf-8")

            cand_file.write_text(json.dumps({
                "score": 60.0,
                "metrics": {"lcp": 4500.0, "cls": 0.35, "inp": 550.0}
            }), encoding="utf-8")

            passed, details, output = run_cwv_check(
                target_url_or_file=str(cand_file),
                baseline_file=str(base_file),
                min_score=85,
            )

            assert passed is False
            assert details["diff"] is not None
            assert any("Regression detected" in f for f in details["failures"])

    def test_github_step_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            summary_file = Path(tmpdir) / "summary.md"
            os.environ["GITHUB_STEP_SUMMARY"] = str(summary_file)

            try:
                audit = {"score": 89.0, "metrics": {"lcp": 2100.0, "cls": 0.03}}
                run_cwv_check(audit, min_score=85)

                assert summary_file.exists()
                content = summary_file.read_text(encoding="utf-8")
                assert "# ⚡ CWV Quality Gate Summary — ✅ PASSED" in content
            finally:
                os.environ.pop("GITHUB_STEP_SUMMARY", None)

    def test_cli_main(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            audit_path = Path(tmpdir) / "audit.json"
            audit_path.write_text(json.dumps({
                "score": 92.0,
                "metrics": {"lcp": 1800.0, "cls": 0.02, "inp": 100.0}
            }), encoding="utf-8")

            report_export = Path(tmpdir) / "exported_report.json"

            # Pass scenario
            exit_code = ci_gate_main([
                str(audit_path),
                "--min-score", "85",
                "-f", "markdown",
                "--export-report", str(report_export),
            ])
            assert exit_code == 0
            assert report_export.exists()

            # Fail scenario (min-score 95)
            exit_code_fail = ci_gate_main([
                str(audit_path),
                "--min-score", "95",
            ])
            assert exit_code_fail == 1

    def test_raw_json_string_input(self):
        raw_json = json.dumps({
            "score": 90.0,
            "metrics": {
                "lcp": 1800.0,
                "cls": 0.05,
                "inp": 120.0,
                "fcp": 1100.0,
                "ttfb": 250.0,
            }
        })
        passed, details, _ = run_cwv_check(raw_json, min_score=85)
        assert passed is True
        assert details["score"] == 90.0

    def test_broken_json_string_error(self):
        with pytest.raises(ValueError, match="Invalid JSON string"):
            run_cwv_check("{invalid_json: true}", min_score=85)

    def test_additional_metric_limits(self):
        audit = {
            "score": 90.0,
            "metrics": {
                "lcp": 2000.0,
                "cls": 0.02,
                "inp": 100.0,
                "fcp": 2500.0,  # exceeds max_fcp_ms 1500
                "ttfb": 900.0,  # exceeds max_ttfb_ms 500
            }
        }
        passed, details, _ = run_cwv_check(
            audit,
            min_score=80,
            max_fcp_ms=1500.0,
            max_ttfb_ms=500.0,
        )
        assert passed is False
        assert len(details["failures"]) == 2
