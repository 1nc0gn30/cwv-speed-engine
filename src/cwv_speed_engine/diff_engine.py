"""
Performance Diff Engine & Core Web Vitals Comparator for cwv-speed-engine.

Compares baseline vs candidate performance audits, computes score deltas,
evaluates CWV rating transitions (Poor -> Good, Needs Improvement -> Good, etc.),
isolates resolved bottlenecks and new regressions, and renders GitHub-flavored Markdown
and terminal ASCII comparison reports.

Zero external dependencies (pure Python standard library).
"""

import json
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Union


# =============================================================================
# CWV Metric Thresholds & Configurations
# =============================================================================

# Standard Web Vitals thresholds (Google Core Web Vitals standard)
METRIC_THRESHOLDS = {
    "lcp": {
        "name": "Largest Contentful Paint",
        "unit": "ms",
        "good": 2500.0,
        "needs_improvement": 4000.0,
        "lower_is_better": True,
        "is_core": True,
    },
    "cls": {
        "name": "Cumulative Layout Shift",
        "unit": "",
        "good": 0.1,
        "needs_improvement": 0.25,
        "lower_is_better": True,
        "is_core": True,
    },
    "inp": {
        "name": "Interaction to Next Paint",
        "unit": "ms",
        "good": 200.0,
        "needs_improvement": 500.0,
        "lower_is_better": True,
        "is_core": True,
    },
    "fcp": {
        "name": "First Contentful Paint",
        "unit": "ms",
        "good": 1800.0,
        "needs_improvement": 3000.0,
        "lower_is_better": True,
        "is_core": False,
    },
    "ttfb": {
        "name": "Time to First Byte",
        "unit": "ms",
        "good": 800.0,
        "needs_improvement": 1800.0,
        "lower_is_better": True,
        "is_core": False,
    },
    "tbt": {
        "name": "Total Blocking Time",
        "unit": "ms",
        "good": 200.0,
        "needs_improvement": 600.0,
        "lower_is_better": True,
        "is_core": False,
    },
    "si": {
        "name": "Speed Index",
        "unit": "ms",
        "good": 3400.0,
        "needs_improvement": 5800.0,
        "lower_is_better": True,
        "is_core": False,
    },
}

# Alias map for normalized key resolution
METRIC_ALIASES = {
    "largest_contentful_paint": "lcp",
    "largest-contentful-paint": "lcp",
    "lcp_ms": "lcp",
    "cumulative_layout_shift": "cls",
    "cumulative-layout-shift": "cls",
    "interaction_to_next_paint": "inp",
    "interaction-to-next-paint": "inp",
    "inp_ms": "inp",
    "first_contentful_paint": "fcp",
    "first-contentful-paint": "fcp",
    "fcp_ms": "fcp",
    "time_to_first_byte": "ttfb",
    "time-to-first-byte": "ttfb",
    "ttfb_ms": "ttfb",
    "total_blocking_time": "tbt",
    "total-blocking-time": "tbt",
    "tbt_ms": "tbt",
    "speed_index": "si",
    "speed-index": "si",
    "speedindex": "si",
}


# =============================================================================
# Helper Utilities
# =============================================================================

def rate_metric(metric_key: str, value: float) -> str:
    """Rate a metric value as 'good', 'needs_improvement', or 'poor'."""
    key = METRIC_ALIASES.get(metric_key.lower(), metric_key.lower())
    spec = METRIC_THRESHOLDS.get(key)
    if not spec:
        return "unknown"

    if value <= spec["good"]:
        return "good"
    elif value <= spec["needs_improvement"]:
        return "needs_improvement"
    else:
        return "poor"


def format_metric_value(metric_key: str, value: Optional[float]) -> str:
    """Format a metric numeric value with appropriate units and decimals."""
    if value is None:
        return "N/A"
    key = METRIC_ALIASES.get(metric_key.lower(), metric_key.lower())
    if key == "cls":
        return f"{value:.3f}"
    return f"{value:,.0f}ms" if METRIC_THRESHOLDS.get(key, {}).get("unit") == "ms" else f"{value:.2f}"


def format_rating_badge(rating: str) -> str:
    """Format human-readable rating badge with emoji."""
    if rating == "good":
        return "🟢 Good"
    elif rating == "needs_improvement":
        return "🟡 Needs Improvement"
    elif rating == "poor":
        return "🔴 Poor"
    return "⚪ Unknown"


def _extract_score(audit: Dict[str, Any]) -> float:
    """Extract performance score (0-100) from diverse audit payload structures."""
    if "score" in audit:
        s = audit["score"]
        # Convert decimal 0.0-1.0 to 0-100 if necessary
        return float(s * 100) if 0.0 <= s <= 1.0 and not isinstance(s, int) else float(s)
    if "performance_score" in audit:
        s = audit["performance_score"]
        return float(s * 100) if 0.0 <= s <= 1.0 and not isinstance(s, int) else float(s)
    if "categories" in audit and "performance" in audit["categories"]:
        cat = audit["categories"]["performance"]
        s = cat.get("score", 0)
        return float(s * 100) if 0.0 <= s <= 1.0 else float(s)
    return 0.0


def _extract_metrics(audit: Dict[str, Any]) -> Dict[str, float]:
    """Extract normalized metrics dictionary {lcp: float, cls: float, ...} from audit."""
    metrics: Dict[str, float] = {}

    # Source 1: explicit 'metrics' dictionary
    if "metrics" in audit and isinstance(audit["metrics"], dict):
        for k, v in audit["metrics"].items():
            norm_k = METRIC_ALIASES.get(k.lower(), k.lower())
            if isinstance(v, (int, float)):
                metrics[norm_k] = float(v)
            elif isinstance(v, dict) and "value" in v and isinstance(v["value"], (int, float)):
                metrics[norm_k] = float(v["value"])
            elif isinstance(v, dict) and "numericValue" in v and isinstance(v["numericValue"], (int, float)):
                metrics[norm_k] = float(v["numericValue"])

    # Source 2: top-level metric fields (e.g. {'lcp': 2100, 'cls': 0.05})
    for k, v in audit.items():
        norm_k = METRIC_ALIASES.get(k.lower(), k.lower())
        if norm_k in METRIC_THRESHOLDS and isinstance(v, (int, float)) and norm_k not in metrics:
            metrics[norm_k] = float(v)

    # Source 3: Lighthouse audits dict (e.g. audits['largest-contentful-paint']['numericValue'])
    if "audits" in audit and isinstance(audit["audits"], dict):
        for k, v in audit["audits"].items():
            norm_k = METRIC_ALIASES.get(k.lower(), k.lower())
            if norm_k in METRIC_THRESHOLDS and norm_k not in metrics and isinstance(v, dict):
                num = v.get("numericValue") or v.get("value")
                if isinstance(num, (int, float)):
                    metrics[norm_k] = float(num)

    return metrics


def _extract_bottlenecks(audit: Dict[str, Any]) -> List[str]:
    """Extract list of bottleneck descriptions or IDs from audit payload."""
    for key in ("bottlenecks", "issues", "opportunities", "recommendations"):
        if key in audit and isinstance(audit[key], list):
            items = []
            for item in audit[key]:
                if isinstance(item, str):
                    items.append(item.strip())
                elif isinstance(item, dict):
                    # extract title or id or description
                    val = item.get("title") or item.get("id") or item.get("description") or item.get("message")
                    if val and isinstance(val, str):
                        items.append(val.strip())
            return items
    return []


# =============================================================================
# PerformanceDiffEngine Class
# =============================================================================

class PerformanceDiffEngine:
    """
    Core Web Vitals and Performance Audit Difference Comparator.
    """

    @classmethod
    def compare(
        cls,
        baseline_audit: Dict[str, Any],
        candidate_audit: Dict[str, Any],
        score_regression_threshold: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Compare baseline and candidate performance audits and produce a structured diff.
        """
        base_score = _extract_score(baseline_audit)
        cand_score = _extract_score(candidate_audit)
        score_delta = round(cand_score - base_score, 2)
        score_pct_change = round(((cand_score - base_score) / base_score) * 100, 2) if base_score > 0 else 0.0

        base_metrics = _extract_metrics(baseline_audit)
        cand_metrics = _extract_metrics(candidate_audit)

        all_metric_keys = list(METRIC_THRESHOLDS.keys())

        metric_diffs: Dict[str, Any] = {}
        improved_count = 0
        regressed_count = 0
        critical_regressions: List[Dict[str, Any]] = []

        for key in all_metric_keys:
            spec = METRIC_THRESHOLDS[key]
            b_val = base_metrics.get(key)
            c_val = cand_metrics.get(key)

            if b_val is None and c_val is None:
                continue

            b_rating = rate_metric(key, b_val) if b_val is not None else "unknown"
            c_rating = rate_metric(key, c_val) if c_val is not None else "unknown"

            if b_val is not None and c_val is not None:
                delta = round(c_val - b_val, 3 if key == "cls" else 2)
                pct_change = round(((c_val - b_val) / b_val) * 100, 2) if b_val > 0 else 0.0

                # Determine if improved / regressed
                # For CWV metrics lower is better
                if spec["lower_is_better"]:
                    if delta < 0:
                        status = "improved"
                        improved_count += 1
                    elif delta > 0:
                        status = "regressed"
                        regressed_count += 1
                    else:
                        status = "unchanged"
                else:
                    if delta > 0:
                        status = "improved"
                        improved_count += 1
                    elif delta < 0:
                        status = "regressed"
                        regressed_count += 1
                    else:
                        status = "unchanged"
            else:
                delta = None
                pct_change = None
                status = "unknown"

            transition = f"{b_rating} -> {c_rating}"

            # Check if this is a critical regression
            # (e.g. a Core metric moving to 'poor' or degrading from 'good' to 'needs_improvement'/'poor')
            is_critical_regression = False
            if spec["is_core"]:
                if b_rating in ("good", "needs_improvement") and c_rating == "poor":
                    is_critical_regression = True
                elif b_rating == "good" and c_rating in ("needs_improvement", "poor"):
                    is_critical_regression = True

            if is_critical_regression:
                critical_regressions.append({
                    "metric": key,
                    "name": spec["name"],
                    "baseline_value": b_val,
                    "candidate_value": c_val,
                    "baseline_rating": b_rating,
                    "candidate_rating": c_rating,
                    "delta": delta,
                })

            metric_diffs[key] = {
                "name": spec["name"],
                "unit": spec["unit"],
                "is_core": spec["is_core"],
                "baseline_value": b_val,
                "candidate_value": c_val,
                "baseline_rating": b_rating,
                "candidate_rating": c_rating,
                "rating_transition": transition,
                "delta": delta,
                "pct_change": pct_change,
                "status": status,
                "is_critical_regression": is_critical_regression,
            }

        # Bottlenecks differencing
        base_bottlenecks = set(_extract_bottlenecks(baseline_audit))
        cand_bottlenecks = set(_extract_bottlenecks(candidate_audit))

        resolved_bottlenecks = sorted(list(base_bottlenecks - cand_bottlenecks))
        new_regressions = sorted(list(cand_bottlenecks - base_bottlenecks))
        persistent_bottlenecks = sorted(list(base_bottlenecks & cand_bottlenecks))

        # Overall Status
        if critical_regressions or score_delta < -score_regression_threshold:
            overall_status = "regressed"
        elif score_delta > 0 or (improved_count > 0 and regressed_count == 0):
            overall_status = "improved"
        else:
            overall_status = "neutral"

        # Summary line
        score_sign = "+" if score_delta > 0 else ""
        summary_sentence = (
            f"Performance score: {cand_score:.1f} ({score_sign}{score_delta:.1f} pts vs baseline {base_score:.1f}). "
            f"{len(resolved_bottlenecks)} resolved bottleneck(s), {len(new_regressions)} new regression(s)."
        )

        return {
            "overall_status": overall_status,
            "summary": summary_sentence,
            "baseline_score": base_score,
            "candidate_score": cand_score,
            "score_delta": score_delta,
            "score_pct_change": score_pct_change,
            "metrics": metric_diffs,
            "critical_regressions": critical_regressions,
            "resolved_bottlenecks": resolved_bottlenecks,
            "new_regressions": new_regressions,
            "persistent_bottlenecks": persistent_bottlenecks,
            "improved_count": improved_count,
            "regressed_count": regressed_count,
        }

    @classmethod
    def render_markdown(cls, diff: Dict[str, Any]) -> str:
        """Render GitHub-flavored markdown comparison diff table and alerts."""
        status_emojis = {
            "improved": "🚀 Improved",
            "regressed": "⚠️ Regressed",
            "neutral": "➖ Unchanged",
        }
        overall = diff.get("overall_status", "neutral")
        status_label = status_emojis.get(overall, overall)

        lines: List[str] = [
            f"## ⚡ Performance Audit Diff — {status_label}",
            "",
            f"> **Summary:** {diff.get('summary', '')}",
            "",
            "### 📊 Overall Score Comparison",
            "",
            "| Metric | Baseline | Candidate | Delta | Status |",
            "| :--- | :---: | :---: | :---: | :---: |",
        ]

        b_sc = diff.get("baseline_score", 0.0)
        c_sc = diff.get("candidate_score", 0.0)
        sc_d = diff.get("score_delta", 0.0)
        sc_sign = "+" if sc_d > 0 else ""
        sc_status = "🟢 Improved" if sc_d > 0 else "🔴 Regressed" if sc_d < 0 else "⚪ Unchanged"
        lines.append(f"| **Performance Score** | `{b_sc:.1f}` | `{c_sc:.1f}` | `{sc_sign}{sc_d:.1f}` | {sc_status} |")
        lines.append("")

        # Core Web Vitals Table
        lines.extend([
            "### 🎯 Core Web Vitals",
            "",
            "| Metric | Baseline | Candidate | Delta | Transition | Status |",
            "| :--- | :---: | :---: | :---: | :--- | :---: |",
        ])

        metrics = diff.get("metrics", {})
        for key, m in metrics.items():
            if not m.get("is_core"):
                continue
            b_val = format_metric_value(key, m.get("baseline_value"))
            c_val = format_metric_value(key, m.get("candidate_value"))
            d = m.get("delta")
            if d is not None:
                d_sign = "+" if d > 0 else ""
                d_str = f"{d_sign}{d:.3f}" if key == "cls" else f"{d_sign}{d:,.0f}ms"
            else:
                d_str = "N/A"

            b_badge = format_rating_badge(m.get("baseline_rating", "unknown"))
            c_badge = format_rating_badge(m.get("candidate_rating", "unknown"))
            trans = f"{b_badge} → {c_badge}"

            st = m.get("status")
            st_icon = "🟢 Improved" if st == "improved" else "🔴 Regressed" if st == "regressed" else "⚪ Unchanged"

            lines.append(f"| **{m.get('name')} ({key.upper()})** | `{b_val}` | `{c_val}` | `{d_str}` | {trans} | {st_icon} |")

        # Diagnostic Metrics Table
        diag_metrics = [m for k, m in metrics.items() if not m.get("is_core")]
        if diag_metrics:
            lines.extend([
                "",
                "### ⏱️ Diagnostic Load & Runtime Metrics",
                "",
                "| Metric | Baseline | Candidate | Delta | Transition | Status |",
                "| :--- | :---: | :---: | :---: | :--- | :---: |",
            ])
            for key, m in metrics.items():
                if m.get("is_core"):
                    continue
                b_val = format_metric_value(key, m.get("baseline_value"))
                c_val = format_metric_value(key, m.get("candidate_value"))
                d = m.get("delta")
                if d is not None:
                    d_sign = "+" if d > 0 else ""
                    d_str = f"{d_sign}{d:,.0f}ms"
                else:
                    d_str = "N/A"

                b_badge = format_rating_badge(m.get("baseline_rating", "unknown"))
                c_badge = format_rating_badge(m.get("candidate_rating", "unknown"))
                trans = f"{b_badge} → {c_badge}"

                st = m.get("status")
                st_icon = "🟢 Improved" if st == "improved" else "🔴 Regressed" if st == "regressed" else "⚪ Unchanged"
                lines.append(f"| **{m.get('name')} ({key.upper()})** | `{b_val}` | `{c_val}` | `{d_str}` | {trans} | {st_icon} |")

        # Resolved Bottlenecks
        resolved = diff.get("resolved_bottlenecks", [])
        if resolved:
            lines.extend([
                "",
                "### ✅ Resolved Bottlenecks",
                "",
            ])
            for item in resolved:
                lines.append(f"- [x] {item}")

        # New Regressions
        new_regs = diff.get("new_regressions", [])
        if new_regs:
            lines.extend([
                "",
                "### ⚠️ Newly Introduced Bottlenecks / Regressions",
                "",
            ])
            for item in new_regs:
                lines.append(f"- [ ] ❗ {item}")

        return "\n".join(lines)

    @classmethod
    def render_ascii(cls, diff: Dict[str, Any], use_color: bool = False) -> str:
        """Render clean terminal ASCII report table."""
        b_sc = diff.get("baseline_score", 0.0)
        c_sc = diff.get("candidate_score", 0.0)
        sc_d = diff.get("score_delta", 0.0)
        sc_sign = "+" if sc_d > 0 else ""

        w = 78
        sep = "=" * w
        sub_sep = "-" * w

        lines: List[str] = [
            sep,
            f" PERFORMANCE AUDIT COMPARISON REPORT ({diff.get('overall_status', 'neutral').upper()})".center(w),
            sep,
            f" Overall Score: Baseline {b_sc:.1f} -> Candidate {c_sc:.1f} ({sc_sign}{sc_d:.1f} pts)",
            sub_sep,
            f" {'METRIC':<26} | {'BASELINE':<12} | {'CANDIDATE':<12} | {'DELTA':<10} | {'STATUS':<9}",
            sub_sep,
        ]

        metrics = diff.get("metrics", {})
        for key, m in metrics.items():
            name = f"{m.get('name')} ({key.upper()})"[:26]
            b_val = format_metric_value(key, m.get("baseline_value"))
            c_val = format_metric_value(key, m.get("candidate_value"))
            d = m.get("delta")
            if d is not None:
                d_sign = "+" if d > 0 else ""
                d_str = f"{d_sign}{d:.3f}" if key == "cls" else f"{d_sign}{d:,.0f}ms"
            else:
                d_str = "N/A"

            st = m.get("status", "unknown").upper()
            lines.append(f" {name:<26} | {b_val:<12} | {c_val:<12} | {d_str:<10} | {st:<9}")

        lines.append(sub_sep)

        resolved = diff.get("resolved_bottlenecks", [])
        if resolved:
            lines.append(" RESOLVED BOTTLENECKS:")
            for r in resolved:
                lines.append(f"  [+] {r}")
            lines.append(sub_sep)

        new_regs = diff.get("new_regressions", [])
        if new_regs:
            lines.append(" NEW REGRESSIONS:")
            for nr in new_regs:
                lines.append(f"  [-] {nr}")
            lines.append(sub_sep)

        lines.append(sep)
        return "\n".join(lines)

    @classmethod
    def render_json(cls, diff: Dict[str, Any], indent: int = 2) -> str:
        """Render JSON serialization of comparison diff."""
        return json.dumps(diff, indent=indent, ensure_ascii=False)


# =============================================================================
# Functional API
# =============================================================================

def compare_cwv_audits(
    baseline_audit: Dict[str, Any],
    candidate_audit: Dict[str, Any],
    score_regression_threshold: float = 0.0,
) -> Dict[str, Any]:
    """
    Compare two performance audits (baseline vs candidate) and compute metric deltas.

    Returns:
        Dict with 'overall_status', 'summary', 'score_delta', 'metrics',
        'critical_regressions', 'resolved_bottlenecks', 'new_regressions'.
    """
    return PerformanceDiffEngine.compare(
        baseline_audit=baseline_audit,
        candidate_audit=candidate_audit,
        score_regression_threshold=score_regression_threshold,
    )
