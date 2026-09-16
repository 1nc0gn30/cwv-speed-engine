"""
Unit tests for Performance Diff Engine & CWV Comparator (diff_engine.py).
"""

import json
import pytest

from cwv_speed_engine.diff_engine import (
    PerformanceDiffEngine,
    compare_cwv_audits,
    rate_metric,
    format_metric_value,
    format_rating_badge,
)


class TestPerformanceDiffEngine:
    """Test suite for PerformanceDiffEngine and compare_cwv_audits."""

    def test_rate_metric_and_formatting(self):
        # LCP thresholds: <= 2500 Good, <= 4000 Needs Improvement, > 4000 Poor
        assert rate_metric("lcp", 1800) == "good"
        assert rate_metric("lcp", 3200) == "needs_improvement"
        assert rate_metric("lcp", 4800) == "poor"

        # CLS thresholds: <= 0.1 Good, <= 0.25 Needs Improvement, > 0.25 Poor
        assert rate_metric("cls", 0.04) == "good"
        assert rate_metric("cls", 0.18) == "needs_improvement"
        assert rate_metric("cls", 0.35) == "poor"

        # INP thresholds: <= 200 Good, <= 500 Needs Improvement, > 500 Poor
        assert rate_metric("inp", 150) == "good"
        assert rate_metric("inp", 350) == "needs_improvement"
        assert rate_metric("inp", 600) == "poor"

        # Formatting
        assert format_metric_value("lcp", 2450.0) == "2,450ms"
        assert format_metric_value("cls", 0.085) == "0.085"
        assert format_rating_badge("good") == "🟢 Good"

    def test_compare_improvement_scenario(self):
        baseline = {
            "score": 65.0,
            "metrics": {
                "lcp": 4200.0,  # Poor
                "cls": 0.28,    # Poor
                "inp": 450.0,   # Needs Improvement
                "fcp": 2800.0,
                "ttfb": 950.0,
            },
            "bottlenecks": [
                "Unoptimized hero image format (PNG 3.2MB)",
                "Render-blocking stylesheet: theme.css",
                "Unused JavaScript execution (620ms)",
            ]
        }

        candidate = {
            "score": 92.0,
            "metrics": {
                "lcp": 1800.0,  # Good (Improved!)
                "cls": 0.02,    # Good (Improved!)
                "inp": 120.0,   # Good (Improved!)
                "fcp": 1100.0,  # Good (Improved!)
                "ttfb": 320.0,  # Good (Improved!)
            },
            "bottlenecks": [
                "Unused JavaScript execution (620ms)",  # Persistent
            ]
        }

        diff = compare_cwv_audits(baseline, candidate)

        assert diff["overall_status"] == "improved"
        assert diff["baseline_score"] == 65.0
        assert diff["candidate_score"] == 92.0
        assert diff["score_delta"] == 27.0
        assert diff["score_pct_change"] > 40.0
        assert diff["improved_count"] >= 5
        assert diff["regressed_count"] == 0
        assert len(diff["critical_regressions"]) == 0

        # Check metric transitions
        lcp_diff = diff["metrics"]["lcp"]
        assert lcp_diff["baseline_rating"] == "poor"
        assert lcp_diff["candidate_rating"] == "good"
        assert lcp_diff["rating_transition"] == "poor -> good"
        assert lcp_diff["delta"] == -2400.0
        assert lcp_diff["status"] == "improved"

        cls_diff = diff["metrics"]["cls"]
        assert cls_diff["rating_transition"] == "poor -> good"
        assert cls_diff["status"] == "improved"

        # Check Bottleneck Differencing
        assert len(diff["resolved_bottlenecks"]) == 2
        assert "Unoptimized hero image format (PNG 3.2MB)" in diff["resolved_bottlenecks"]
        assert "Render-blocking stylesheet: theme.css" in diff["resolved_bottlenecks"]
        assert "Unused JavaScript execution (620ms)" in diff["persistent_bottlenecks"]
        assert len(diff["new_regressions"]) == 0

    def test_compare_regression_scenario(self):
        baseline = {
            "score": 90.0,
            "lcp": 2000.0,
            "cls": 0.05,
            "inp": 150.0,
            "bottlenecks": [],
        }

        candidate = {
            "score": 68.0,
            "lcp": 4500.0,  # Poor (Severe regression!)
            "cls": 0.32,    # Poor (Severe regression!)
            "inp": 180.0,
            "bottlenecks": ["Heavy synchronous third-party tag inserted into <head>"],
        }

        diff = compare_cwv_audits(baseline, candidate)

        assert diff["overall_status"] == "regressed"
        assert diff["score_delta"] == -22.0
        assert len(diff["critical_regressions"]) >= 2

        crit_metrics = [r["metric"] for r in diff["critical_regressions"]]
        assert "lcp" in crit_metrics
        assert "cls" in crit_metrics

        assert len(diff["new_regressions"]) == 1
        assert "Heavy synchronous third-party tag inserted into <head>" in diff["new_regressions"]

    def test_render_markdown_and_ascii(self):
        baseline = {"score": 75, "lcp": 3100, "cls": 0.12, "inp": 220}
        candidate = {"score": 88, "lcp": 2100, "cls": 0.04, "inp": 160}

        diff = compare_cwv_audits(baseline, candidate)

        md = PerformanceDiffEngine.render_markdown(diff)
        assert "## ⚡ Performance Audit Diff" in md
        assert "| **Performance Score** | `75.0` | `88.0` | `+13.0` |" in md
        assert "### 🎯 Core Web Vitals" in md
        assert "LCP" in md

        ascii_rep = PerformanceDiffEngine.render_ascii(diff)
        assert "PERFORMANCE AUDIT COMPARISON REPORT" in ascii_rep
        assert "Overall Score: Baseline 75.0 -> Candidate 88.0 (+13.0 pts)" in ascii_rep

        json_str = PerformanceDiffEngine.render_json(diff)
        parsed = json.loads(json_str)
        assert parsed["score_delta"] == 13.0

    def test_lighthouse_format_compatibility(self):
        lh_baseline = {
            "categories": {
                "performance": {"score": 0.70}
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 3500.0},
                "cumulative-layout-shift": {"numericValue": 0.15},
                "total-blocking-time": {"numericValue": 450.0},
            }
        }

        lh_candidate = {
            "categories": {
                "performance": {"score": 0.95}
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 1900.0},
                "cumulative-layout-shift": {"numericValue": 0.03},
                "total-blocking-time": {"numericValue": 80.0},
            }
        }

        diff = compare_cwv_audits(lh_baseline, lh_candidate)
        assert diff["baseline_score"] == 70.0
        assert diff["candidate_score"] == 95.0
        assert diff["score_delta"] == 25.0
        assert diff["metrics"]["lcp"]["candidate_value"] == 1900.0
        assert diff["metrics"]["tbt"]["candidate_value"] == 80.0

    def test_missing_or_partial_metrics(self):
        baseline = {"score": 80.0, "metrics": {"lcp": 2200.0}}
        candidate = {"score": 80.0, "metrics": {"cls": 0.05}}

        diff = compare_cwv_audits(baseline, candidate)
        assert diff["score_delta"] == 0.0
        assert diff["metrics"]["lcp"]["baseline_value"] == 2200.0
        assert diff["metrics"]["lcp"]["candidate_value"] is None
        assert diff["metrics"]["cls"]["baseline_value"] is None
        assert diff["metrics"]["cls"]["candidate_value"] == 0.05

    def test_zero_baseline_score_edge_case(self):
        baseline = {"score": 0.0, "lcp": 6000.0}
        candidate = {"score": 85.0, "lcp": 2000.0}

        diff = compare_cwv_audits(baseline, candidate)
        assert diff["score_delta"] == 85.0
        assert diff["score_pct_change"] == 0.0  # Safe handling of division by zero
        assert diff["overall_status"] == "improved"
