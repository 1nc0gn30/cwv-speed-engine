"""Tests for Long Animation Frame (LoAF) API analyzer and INP attribution."""

from cwv_speed_engine.loaf_analyzer import (
    LoAFAttributionReport,
    LongAnimationFrameEntry,
    LongAnimationFrameScript,
    analyze_loaf_entries,
    audit_html_for_loaf_risks,
)


def test_empty_loaf_entries():
    report = analyze_loaf_entries([])
    assert isinstance(report, LoAFAttributionReport)
    assert report.total_loaf_count == 0
    assert report.total_blocking_time_ms == 0.0
    assert report.dominant_bottleneck == "none"
    assert report.inp_risk_level == "good"


def test_analyze_script_heavy_loaf():
    entries = [
        {
            "startTime": 1200.5,
            "duration": 180.0,
            "renderDuration": 15.0,
            "styleAndLayoutDuration": 10.0,
            "scriptDuration": 150.0,
            "scripts": [
                {
                    "invoker": "click",
                    "sourceURL": "https://example.com/bundle.js",
                    "sourceFunctionName": "handleLargeDataSort",
                    "duration": 120.0,
                    "forcedStyleAndLayoutDuration": 5.0,
                },
                {
                    "invoker": "setTimeout",
                    "sourceURL": "https://example.com/analytics.js",
                    "sourceFunctionName": "trackEvent",
                    "duration": 30.0,
                },
            ],
        },
        {
            "startTime": 2100.0,
            "duration": 90.0,
            "renderDuration": 10.0,
            "styleAndLayoutDuration": 5.0,
            "scriptDuration": 70.0,
            "scripts": [
                {
                    "invoker": "Promise.then",
                    "sourceURL": "https://example.com/bundle.js",
                    "sourceFunctionName": "renderResults",
                    "duration": 65.0,
                }
            ],
        },
    ]
    report = analyze_loaf_entries(entries)
    assert report.total_loaf_count == 2
    # Blocking time: (180 - 50) + (90 - 50) = 130 + 40 = 170
    assert report.total_blocking_time_ms == 170.0
    assert report.max_frame_duration_ms == 180.0
    assert report.dominant_bottleneck == "script-execution"
    assert report.script_ratio > 0.70
    assert len(report.culprit_scripts) == 2
    assert report.culprit_scripts[0]["source_url"] == "https://example.com/bundle.js"
    assert report.culprit_scripts[0]["total_duration_ms"] == 185.0
    assert "handleLargeDataSort" in report.culprit_scripts[0]["functions"]
    assert any("yield" in r.lower() for r in report.recommendations)


def test_style_and_layout_bottleneck():
    entry = LongAnimationFrameEntry(
        start_time_ms=500.0,
        duration_ms=250.0,
        render_duration_ms=20.0,
        style_and_layout_duration_ms=180.0,
        script_duration_ms=40.0,
        blocking_duration_ms=200.0,
        scripts=[],
    )
    report = analyze_loaf_entries([entry])
    assert report.dominant_bottleneck == "style-and-layout"
    assert report.style_layout_ratio > 0.5
    assert report.inp_risk_level in ("needs-improvement", "poor")
    assert any("reflow" in r.lower() for r in report.recommendations)


def test_audit_html_loaf_risks():
    html_with_risks = """
    <html>
    <head>
        <script src="/legacy/heavy-sync-lib.js"></script>
        <script async src="https://www.googletagmanager.com/gtm.js"></script>
    </head>
    <body>
        <h1>App</h1>
    </body>
    </html>
    """
    risks = audit_html_for_loaf_risks(html_with_risks)
    assert len(risks) >= 2
    assert any("parser-blocking" in r.lower() for r in risks)
    assert any("googletagmanager" in r.lower() for r in risks)
