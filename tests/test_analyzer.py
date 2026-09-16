"""Comprehensive test suite for analyzer.py Core Web Vitals Auditor."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from cwv_speed_engine.analyzer import PerformanceAuditor, audit_core_web_vitals


OPTIMAL_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Fast Web Page</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;700&display=swap">
  <link rel="preload" as="style" href="/styles.css" onload="this.onload=null;this.rel='stylesheet'">
  <script src="/app.js" defer></script>
</head>
<body>
  <header>
    <h1>CWV Optimized</h1>
    <img src="/hero.webp" alt="Hero" width="1200" height="675" fetchpriority="high" decoding="async">
  </header>
  <main>
    <p>Fast and stable content.</p>
    <img src="/photo1.webp" alt="Photo 1" width="800" height="600" loading="lazy" decoding="async">
    <img src="/photo2.webp" alt="Photo 2" width="800" height="600" loading="lazy" decoding="async">
  </main>
</body>
</html>"""

POOR_HTML = """<!DOCTYPE html>
<html>
<head>
  <title>Slow and Janky Page</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto">
  <link rel="stylesheet" href="/blocking.css">
  <script src="https://www.googletagmanager.com/gtm.js?id=GTM-XXXX"></script>
  <script src="/blocking-app.js"></script>
  <style>
    @font-face {
      font-family: 'CustomFont';
      src: url('/font.woff2') format('woff2');
    }
  </style>
</head>
<body>
  <div>
    <!-- Lazy loaded hero image without dimensions -->
    <img src="/hero.jpg" loading="lazy">
    <img src="/thumb1.jpg">
    <img src="/thumb2.jpg">
  </div>
</body>
</html>"""


def test_audit_optimal_page():
    """Test auditor against a fully optimized HTML page."""
    report = audit_core_web_vitals(
        OPTIMAL_HTML,
        headers={"content-encoding": "gzip", "cache-control": "public, max-age=0, must-revalidate"},
    )
    assert report["score"] >= 90
    assert report["rating"] == "Good"
    assert report["metrics"]["lcp"]["rating"] in ("Good", "Needs Improvement")
    assert report["metrics"]["cls"]["rating"] == "Good"
    assert report["metrics"]["inp"]["rating"] == "Good"
    assert report["heuristics"]["viewport"]["status"] == "PASS"
    assert report["heuristics"]["image_dimensions"]["status"] == "PASS"


def test_audit_poor_page():
    """Test auditor against a slow/unoptimized page with layout shift and blocking assets."""
    report = audit_core_web_vitals(POOR_HTML)
    assert report["score"] < 70
    assert report["rating"] in ("Needs Improvement", "Poor")

    finding_ids = [f["id"] for f in report["findings"]]
    # Should catch missing viewport, lazy hero, missing dimensions, blocking CSS/JS, fonts, etc.
    assert "CWV-VIEWPORT-MISSING" in finding_ids
    assert "CWV-HERO-LAZY" in finding_ids
    assert "CWV-IMG-NO-DIM" in finding_ids
    assert "CWV-RENDER-BLOCKING-CSS" in finding_ids
    assert "CWV-RENDER-BLOCKING-JS" in finding_ids
    assert "CWV-FONT-NO-PRECONNECT" in finding_ids
    assert "CWV-FONT-NO-SWAP" in finding_ids
    assert "CWV-FONT-DISPLAY-MISSING" in finding_ids
    assert "CWV-THIRDPARTY-BLOCKING-SCRIPT" in finding_ids


def test_viewport_heuristics():
    """Test viewport variations (missing, no initial-scale, disabled zoom)."""
    # Viewport disabling zoom
    html = """<html><head><meta name="viewport" content="width=device-width, user-scalable=no, maximum-scale=1"></head><body></body></html>"""
    report = audit_core_web_vitals(html)
    finding_ids = [f["id"] for f in report["findings"]]
    assert "CWV-VIEWPORT-SCALABLE-DISABLED" in finding_ids

    # Viewport missing width=device-width
    html2 = """<html><head><meta name="viewport" content="initial-scale=1.0"></head><body></body></html>"""
    report2 = audit_core_web_vitals(html2)
    finding_ids2 = [f["id"] for f in report2["findings"]]
    assert "CWV-VIEWPORT-NO-DEVICE-WIDTH" in finding_ids2


def test_image_dimensions_and_cls():
    """Test CLS heuristic when images have missing width/height vs CSS aspect-ratio."""
    html_missing = """<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
    <body>
      <img src="1.jpg">
      <img src="2.jpg">
    </body></html>"""
    report = audit_core_web_vitals(html_missing)
    assert report["heuristics"]["image_dimensions"]["missing_dimensions_count"] == 2
    assert report["metrics"]["cls"]["estimated_value"] > 0.10

    # With CSS aspect-ratio
    html_style = """<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head>
    <body>
      <img src="1.jpg" style="aspect-ratio: 16/9;">
    </body></html>"""
    report_style = audit_core_web_vitals(html_style)
    assert report_style["heuristics"]["image_dimensions"]["missing_dimensions_count"] == 0


def test_dom_size_and_depth():
    """Test DOM size and excessive nesting depth heuristics."""
    # Build deep DOM tree > 35 levels
    deep_html = "<div>" * 36 + "Deep Leaf" + "</div>" * 36
    doc = f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>{deep_html}</body></html>"""
    report = audit_core_web_vitals(doc)
    finding_ids = [f["id"] for f in report["findings"]]
    assert "CWV-DOM-DEPTH-EXCESSIVE" in finding_ids

    # Build large DOM tree > 850 elements
    many_nodes = "".join(f"<p>Item {i}</p>" for i in range(850))
    doc_large = f"""<html><head><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>{many_nodes}</body></html>"""
    report_large = audit_core_web_vitals(doc_large)
    finding_ids_large = [f["id"] for f in report_large["findings"]]
    assert "CWV-DOM-SIZE-WARNING" in finding_ids_large


def test_headers_caching_and_compression():
    """Test HTTP response headers evaluation."""
    # Missing compression and cache-control
    report = audit_core_web_vitals(OPTIMAL_HTML, headers={})
    finding_ids = [f["id"] for f in report["findings"]]
    assert "CWV-HEADER-NO-COMPRESSION" in finding_ids
    assert "CWV-HEADER-NO-CACHE-CONTROL" in finding_ids

    # Proper Brotli and Cache-Control
    report_good = audit_core_web_vitals(
        OPTIMAL_HTML,
        headers={"content-encoding": "br", "cache-control": "public, max-age=31536000, immutable"},
    )
    assert report_good["heuristics"]["caching_compression"]["status"] == "PASS"


def test_audit_url_fetching():
    """Test auditing via mocked HTTP request."""
    mock_headers = MagicMock()
    mock_headers.items.return_value = [
        ("content-type", "text/html; charset=utf-8"),
        ("content-encoding", "gzip"),
        ("cache-control", "public, max-age=3600"),
    ]
    mock_headers.get_content_charset.return_value = "utf-8"

    mock_response = MagicMock()
    mock_response.read.return_value = OPTIMAL_HTML.encode("utf-8")
    mock_response.headers = mock_headers
    mock_response.__enter__.return_value = mock_response

    with patch("urllib.request.urlopen", return_value=mock_response):
        report = audit_core_web_vitals("https://example.com/speed-test")
        assert report["url"] == "https://example.com/speed-test"
        assert report["score"] > 80


def test_audit_network_fetch_failure():
    """Test auditor behavior when network request raises an exception."""
    with patch("urllib.request.urlopen", side_effect=Exception("Connection refused")):
        report = audit_core_web_vitals("https://down-site.example.com")
        assert report["summary"]["critical"] >= 1
        finding_ids = [f["id"] for f in report["findings"]]
        assert "CWV-FETCH-FAILED" in finding_ids


def test_audit_excessive_dom_and_heavy_third_party():
    """Test massive DOM > 1400 nodes and heavy 3rd party scripts."""
    many_nodes = "".join(f"<span>Node {i}</span>" for i in range(1450))
    third_parties = """
      <script src="https://www.google-analytics.com/analytics.js" async></script>
      <script src="https://connect.facebook.net/en_US/fbevents.js" async></script>
      <script src="https://static.hotjar.com/c/hotjar.js" async></script>
      <script src="https://www.clarity.ms/tag/clarity.js" async></script>
      <script src="https://widget.intercom.io/widget/123" async></script>
      <script src="https://analytics.tiktok.com/i18n/pixel/sdk.js" async></script>
    """
    html = f"""<!DOCTYPE html><html><head><meta name="viewport" content="width=device-width, initial-scale=1">{third_parties}</head><body>{many_nodes}</body></html>"""
    report = audit_core_web_vitals(html)
    finding_ids = [f["id"] for f in report["findings"]]
    assert "CWV-DOM-SIZE-EXCESSIVE" in finding_ids
    assert "CWV-THIRDPARTY-HEAVY-TAGS" in finding_ids
