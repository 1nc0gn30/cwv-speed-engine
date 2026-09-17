"""Long Animation Frame (LoAF) API breakdown and INP script attribution engine.

Chrome 123+ introduced the Long Animation Frame API as the successor to Long Tasks,
enabling precise attribution of slow frames (>50ms) affecting Interaction to Next Paint (INP).
This module analyzes LoAF entries, decomposes render vs style vs script overhead,
and highlights culprit third-party and first-party scripts.

100% Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union


@dataclass
class LongAnimationFrameScript:
    """Script execution record contributing to a long animation frame."""

    invoker: str  # e.g. 'Promise.then', 'setTimeout', 'click'
    source_url: str
    source_function_name: str
    duration_ms: float
    pause_duration_ms: float = 0.0
    forced_style_and_layout_duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LongAnimationFrameEntry:
    """Parsed Long Animation Frame API record."""

    start_time_ms: float
    duration_ms: float
    render_duration_ms: float
    style_and_layout_duration_ms: float
    script_duration_ms: float
    blocking_duration_ms: float
    scripts: List[LongAnimationFrameScript] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time_ms": self.start_time_ms,
            "duration_ms": self.duration_ms,
            "render_duration_ms": self.render_duration_ms,
            "style_and_layout_duration_ms": self.style_and_layout_duration_ms,
            "script_duration_ms": self.script_duration_ms,
            "blocking_duration_ms": self.blocking_duration_ms,
            "scripts": [s.to_dict() for s in self.scripts],
        }


@dataclass
class LoAFAttributionReport:
    """Aggregated analysis and attribution of Long Animation Frames."""

    total_loaf_count: int
    total_blocking_time_ms: float
    max_frame_duration_ms: float
    avg_frame_duration_ms: float
    render_ratio: float
    style_layout_ratio: float
    script_ratio: float
    dominant_bottleneck: str  # 'script-execution', 'style-and-layout', 'render-presentation', 'balanced'
    culprit_scripts: List[Dict[str, Any]] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    inp_risk_level: str = "good"  # 'good' (<200ms), 'needs-improvement' (200-500ms), 'poor' (>500ms)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def analyze_loaf_entries(
    entries: Sequence[Union[Dict[str, Any], LongAnimationFrameEntry]],
) -> LoAFAttributionReport:
    """Analyze a collection of LoAF entries and pinpoint root causes.

    Args:
        entries: List of LoAF records (dicts or LongAnimationFrameEntry objects).

    Returns:
        LoAFAttributionReport with timing ratios, dominant bottleneck, culprit scripts,
        and actionable recommendations.
    """
    if not entries:
        return LoAFAttributionReport(
            total_loaf_count=0,
            total_blocking_time_ms=0.0,
            max_frame_duration_ms=0.0,
            avg_frame_duration_ms=0.0,
            render_ratio=0.0,
            style_layout_ratio=0.0,
            script_ratio=0.0,
            dominant_bottleneck="none",
            culprit_scripts=[],
            recommendations=["No long animation frames observed; frame execution meets 60fps budgets."],
            inp_risk_level="good",
        )

    parsed_entries: List[LongAnimationFrameEntry] = []
    for item in entries:
        if isinstance(item, LongAnimationFrameEntry):
            parsed_entries.append(item)
        elif isinstance(item, dict):
            # Parse dict
            dur = float(item.get("duration", item.get("duration_ms", 0.0)))
            start = float(item.get("startTime", item.get("start_time_ms", 0.0)))
            render = float(item.get("renderDuration", item.get("render_duration_ms", 0.0)))
            style = float(item.get("styleAndLayoutDuration", item.get("style_and_layout_duration_ms", 0.0)))
            script = float(item.get("scriptDuration", item.get("script_duration_ms", 0.0)))
            blocking = max(0.0, dur - 50.0)

            scripts_raw = item.get("scripts", [])
            script_objs: List[LongAnimationFrameScript] = []
            for s in scripts_raw:
                if isinstance(s, LongAnimationFrameScript):
                    script_objs.append(s)
                elif isinstance(s, dict):
                    script_objs.append(
                        LongAnimationFrameScript(
                            invoker=str(s.get("invoker", "")),
                            source_url=str(s.get("sourceURL", s.get("source_url", ""))),
                            source_function_name=str(s.get("sourceFunctionName", s.get("source_function_name", ""))),
                            duration_ms=float(s.get("duration", s.get("duration_ms", 0.0))),
                            pause_duration_ms=float(s.get("pauseDuration", s.get("pause_duration_ms", 0.0))),
                            forced_style_and_layout_duration_ms=float(
                                s.get("forcedStyleAndLayoutDuration", s.get("forced_style_and_layout_duration_ms", 0.0))
                            ),
                        )
                    )
            parsed_entries.append(
                LongAnimationFrameEntry(
                    start_time_ms=start,
                    duration_ms=dur,
                    render_duration_ms=render,
                    style_and_layout_duration_ms=style,
                    script_duration_ms=script,
                    blocking_duration_ms=blocking,
                    scripts=script_objs,
                )
            )

    total_count = len(parsed_entries)
    total_dur = sum(e.duration_ms for e in parsed_entries)
    total_blocking = sum(e.blocking_duration_ms for e in parsed_entries)
    max_dur = max(e.duration_ms for e in parsed_entries)
    avg_dur = round(total_dur / total_count, 2) if total_count > 0 else 0.0

    total_render = sum(e.render_duration_ms for e in parsed_entries)
    total_style = sum(e.style_and_layout_duration_ms for e in parsed_entries)
    total_script = sum(e.script_duration_ms for e in parsed_entries)
    total_work = total_render + total_style + total_script

    if total_work > 0:
        render_ratio = round(total_render / total_work, 3)
        style_layout_ratio = round(total_style / total_work, 3)
        script_ratio = round(total_script / total_work, 3)
    else:
        render_ratio = style_layout_ratio = script_ratio = 0.0

    # Determine dominant bottleneck
    if script_ratio >= 0.50:
        dominant_bottleneck = "script-execution"
    elif style_layout_ratio >= 0.35:
        dominant_bottleneck = "style-and-layout"
    elif render_ratio >= 0.35:
        dominant_bottleneck = "render-presentation"
    else:
        dominant_bottleneck = "balanced"

    # Aggregate scripts
    script_time_by_url: Dict[str, Dict[str, Any]] = {}
    for entry in parsed_entries:
        for s in entry.scripts:
            url = s.source_url or "(inline / anonymous)"
            if url not in script_time_by_url:
                script_time_by_url[url] = {
                    "source_url": url,
                    "total_duration_ms": 0.0,
                    "execution_count": 0,
                    "functions": set(),
                    "forced_reflow_ms": 0.0,
                }
            script_time_by_url[url]["total_duration_ms"] += s.duration_ms
            script_time_by_url[url]["execution_count"] += 1
            if s.source_function_name:
                script_time_by_url[url]["functions"].add(s.source_function_name)
            script_time_by_url[url]["forced_reflow_ms"] += s.forced_style_and_layout_duration_ms

    culprits: List[Dict[str, Any]] = []
    for data in sorted(script_time_by_url.values(), key=lambda x: x["total_duration_ms"], reverse=True):
        culprits.append({
            "source_url": data["source_url"],
            "total_duration_ms": round(data["total_duration_ms"], 2),
            "execution_count": data["execution_count"],
            "functions": sorted(list(data["functions"]))[:5],
            "forced_reflow_ms": round(data["forced_reflow_ms"], 2),
        })

    # Recommendations
    recs: List[str] = []
    if dominant_bottleneck == "script-execution":
        recs.append("Yield frequently to main thread using `scheduler.yield()` or `setTimeout(..., 0)`.")
        recs.append("Break synchronous chunk processing into microtasks to maintain INP under 200ms.")
    elif dominant_bottleneck == "style-and-layout":
        recs.append("Avoid forced synchronous reflows (reading offsetHeight/scrollTop immediately after DOM mutations).")
        recs.append("Batch DOM measurements before applying batch mutations (use requestAnimationFrame).")
    elif dominant_bottleneck == "render-presentation":
        recs.append("Reduce paint complexity: simplify CSS box-shadows, blurs, and large gradient overlays.")
        recs.append("Use `content-visibility: auto` to defer off-screen element rendering.")

    if total_blocking > 300:
        recs.append(f"High total blocking time ({round(total_blocking, 1)}ms) detected; INP is at severe risk.")

    # Risk level
    if max_dur > 500 or total_blocking > 500:
        inp_risk = "poor"
    elif max_dur > 200 or total_blocking > 150:
        inp_risk = "needs-improvement"
    else:
        inp_risk = "good"

    return LoAFAttributionReport(
        total_loaf_count=total_count,
        total_blocking_time_ms=round(total_blocking, 2),
        max_frame_duration_ms=round(max_dur, 2),
        avg_frame_duration_ms=avg_dur,
        render_ratio=render_ratio,
        style_layout_ratio=style_layout_ratio,
        script_ratio=script_ratio,
        dominant_bottleneck=dominant_bottleneck,
        culprit_scripts=culprits,
        recommendations=recs,
        inp_risk_level=inp_risk,
    )


def audit_html_for_loaf_risks(html_content: str) -> List[str]:
    """Scan HTML source code for patterns that provoke Long Animation Frames."""
    risks: List[str] = []
    # Synchronous blocking head scripts
    sync_scripts = re.findall(r"<script(?![^>]*(?:async|defer|type=[\"']module[\"']))[^>]*src=[\"']([^\"']+)[\"'][^>]*>", html_content, re.IGNORECASE)
    if sync_scripts:
        risks.append(f"Found {len(sync_scripts)} parser-blocking synchronous script(s) without async/defer: {', '.join(sync_scripts[:3])}")

    # Heavy third-party trackers
    trackers = ["googletagmanager.com", "facebook.net", "hotjar.com", "clarity.ms", "segment.io"]
    for tracker in trackers:
        if tracker in html_content.lower():
            risks.append(f"Presence of third-party analytics tag '{tracker}' increases INP LoAF risk; ensure sandboxing or deferred initialization.")

    return risks
