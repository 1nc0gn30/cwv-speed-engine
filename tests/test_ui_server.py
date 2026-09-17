"""
Comprehensive test suite for CWV Speed Studio UI Server and REST APIs.
Tests auditing algorithms, HTML transformation, PWA generation, diff comparator,
caching exporter, MCP configs, zip bundling, and live HTTP request handling.
"""

import io
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import zipfile
import pytest

from cwv_speed_engine.ui_server import (
    audit_html_content,
    audit_url,
    transform_html,
    generate_pwa,
    generate_og,
    compare_diff,
    export_cache_headers,
    get_mcp_config,
    create_zip_bundle,
    create_server,
    start_ui_server,
)


def get_free_port() -> int:
    """Find an available local TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ==============================================================================
# 1. Audit Engine Tests
# ==============================================================================

def test_audit_html_content_unoptimized():
    raw_html = """<!DOCTYPE html>
    <html>
    <head>
      <title>Slow Site</title>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Open+Sans">
      <script src="https://cdn.example.com/heavy.js"></script>
    </head>
    <body>
      <h1>Slow Site</h1>
      <img src="/hero.jpg" alt="Hero">
      <img src="/photo1.jpg" alt="Photo 1">
      <img src="/photo2.jpg" alt="Photo 2">
    </body>
    </html>"""

    result = audit_html_content(raw_html, device="mobile")
    assert "score" in result
    assert "metrics" in result
    assert "diagnostics" in result
    assert result["score"] < 90
    assert result["metrics"]["lcp"]["value"] > 1.5
    assert result["metrics"]["cls"]["value"] > 0.05
    assert result["summary"]["critical"] > 0 or result["summary"]["warning"] > 0


def test_audit_html_content_optimized():
    optimized_html = """<!DOCTYPE html>
    <html>
    <head>
      <title>Fast Site</title>
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Open+Sans&display=swap">
      <link rel="preload" as="image" href="/hero.jpg" fetchpriority="high">
      <link rel="manifest" href="/site.webmanifest">
      <meta property="og:title" content="Fast Site">
      <meta property="og:image" content="/og.jpg">
      <script defer src="https://cdn.example.com/heavy.js"></script>
    </head>
    <body>
      <h1>Fast Site</h1>
      <img src="/hero.jpg" width="800" height="500" fetchpriority="high" loading="eager" alt="Hero">
      <img src="/photo1.jpg" width="400" height="300" loading="lazy" decoding="async" alt="Photo 1">
      <img src="/photo2.jpg" width="400" height="300" loading="lazy" decoding="async" alt="Photo 2">
    </body>
    </html>"""

    result = audit_html_content(optimized_html, device="mobile")
    assert result["score"] >= 90
    assert result["rating"] == "GOOD"
    assert result["metrics"]["cls"]["value"] <= 0.10
    assert result["metrics"]["lcp"]["value"] <= 2.5


def test_audit_html_empty_input():
    result = audit_html_content("")
    assert result["score"] == 0
    assert result["rating"] == "POOR"


def test_audit_desktop_vs_mobile():
    html = "<html><head><title>Test</title></head><body><h1>Hello</h1></body></html>"
    mobile = audit_html_content(html, device="mobile")
    desktop = audit_html_content(html, device="desktop")
    assert desktop["metrics"]["ttfb"]["value"] <= mobile["metrics"]["ttfb"]["value"]


# ==============================================================================
# 2. HTML Transformer Tests
# ==============================================================================

def test_transform_html_dimensions_and_lazy():
    raw_html = """<!DOCTYPE html>
    <html>
    <head><title>Test</title></head>
    <body>
      <img src="/banner.jpg" alt="Banner">
      <img src="/gallery1.jpg" alt="Gallery 1">
    </body>
    </html>"""

    transformed = transform_html(raw_html)
    opt_html = transformed["optimized_html"]

    assert 'width="800"' in opt_html or 'width=' in opt_html
    assert 'height="500"' in opt_html or 'height=' in opt_html
    assert 'loading="lazy"' in opt_html
    assert 'decoding="async"' in opt_html
    assert 'fetchpriority="high"' in opt_html
    assert len(transformed["changes"]) > 0


def test_transform_html_font_and_scripts():
    raw_html = """<!DOCTYPE html>
    <html>
    <head>
      <title>Fonts & Scripts</title>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700">
      <script src="/app.js"></script>
    </head>
    <body>
      <h1>App</h1>
    </body>
    </html>"""

    transformed = transform_html(raw_html)
    opt_html = transformed["optimized_html"]

    assert "display=swap" in opt_html
    assert 'rel="preconnect"' in opt_html
    assert '<script defer' in opt_html


def test_transform_html_empty():
    transformed = transform_html("")
    assert transformed["optimized_html"] == ""
    assert transformed["changes"] == []


# ==============================================================================
# 3. PWA Generation Tests
# ==============================================================================

def test_generate_pwa_artifacts():
    pwa = generate_pwa({
        "name": "Super Fast Store",
        "short_name": "FastStore",
        "theme_color": "#1a73e8",
        "strategy": "stale-while-revalidate",
    })

    assert "manifest" in pwa
    assert pwa["manifest"]["name"] == "Super Fast Store"
    assert pwa["manifest"]["theme_color"] == "#1a73e8"
    assert "sw.js" in pwa["service_worker"] or "CACHE_NAME" in pwa["service_worker"]
    assert "offline" in pwa["offline_html"].lower()
    assert "<link rel=\"manifest\"" in pwa["html_snippet"]


# ==============================================================================
# 4. OpenGraph & Social Preview Tests
# ==============================================================================

def test_generate_og_tags():
    og = generate_og({
        "title": "Speed Studio Engine",
        "description": "High performance optimization.",
        "url": "https://speed.example.com",
        "image": "https://speed.example.com/og.png",
    })

    assert '<title>Speed Studio Engine</title>' in og["html_snippet"]
    assert '<meta property="og:title" content="Speed Studio Engine">' in og["html_snippet"]
    assert '<meta name="twitter:card" content="summary_large_image">' in og["html_snippet"]


# ==============================================================================
# 5. Performance Diff Comparator Tests
# ==============================================================================

def test_compare_diff_calculation():
    baseline_html = """<html><head><script src="/slow.js"></script></head><body><img src="/hero.jpg"></body></html>"""
    candidate_html = """<html><head><script defer src="/slow.js"></script><link rel="preload" as="image" href="/hero.jpg" fetchpriority="high"></head><body><img src="/hero.jpg" width="800" height="500" fetchpriority="high"></body></html>"""

    diff = compare_diff(baseline_html, candidate_html)
    assert diff["candidate_score"] >= diff["baseline_score"]
    assert diff["score_delta"] >= 0
    assert "lcp" in diff["metric_deltas"]
    assert "cls" in diff["metric_deltas"]


# ==============================================================================
# 6. Cache Headers Exporter Tests
# ==============================================================================

@pytest.mark.parametrize("platform,expected_file", [
    ("netlify", "_headers"),
    ("vercel", "vercel.json"),
    ("nginx", "nginx.conf"),
    ("cloudflare", "_headers"),
    ("nextjs", "next.config.js"),
    ("apache", ".htaccess"),
])
def test_export_cache_headers_platforms(platform, expected_file):
    res = export_cache_headers(platform)
    assert res["filename"] == expected_file
    assert "31536000" in res["content"] or "max-age" in res["content"]


# ==============================================================================
# 7. MCP Configuration Tests
# ==============================================================================

@pytest.mark.parametrize("client", ["claude", "cursor", "cline", "zed"])
def test_get_mcp_config_clients(client):
    res = get_mcp_config(client)
    assert res["client"] == client
    assert "cwv-speed-engine" in res["json_str"]
    assert len(res["available_tools"]) >= 5


# ==============================================================================
# 8. Zip Bundle Generator Tests
# ==============================================================================

def test_create_zip_bundle_pwa():
    zip_bytes = create_zip_bundle("pwa", {"name": "Test PWA"})
    assert len(zip_bytes) > 0

    with zipfile.ZipFile(io.BytesIO(zip_bytes), "r") as zf:
        names = zf.namelist()
        assert "site.webmanifest" in names
        assert "sw.js" in names
        assert "offline.html" in names


# ==============================================================================
# 9. Live HTTP Server REST API Tests
# ==============================================================================

class TestLiveHttpServer:
    @classmethod
    def setup_class(cls):
        cls.port = get_free_port()
        cls.server, cls.thread = start_ui_server(
            host="127.0.0.1",
            port=cls.port,
            open_browser=False,
            blocking=False,
        )
        time.sleep(0.3)
        cls.base_url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def teardown_class(cls):
        try:
            cls.server.shutdown()
            cls.server.server_close()
        except Exception:
            pass

    def _get(self, path: str):
        req = urllib.request.Request(f"{self.base_url}{path}")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.headers, response.read()

    def _post(self, path: str, data: dict):
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, response.headers, response.read()

    def test_root_index_html(self):
        status, headers, body = self._get("/")
        assert status == 200
        assert "text/html" in headers.get("Content-Type", "")
        html_str = body.decode("utf-8")
        assert "CWV Speed Studio" in html_str

    def test_api_health(self):
        status, headers, body = self._get("/api/health")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data

    def test_api_audit_post(self):
        payload = {"html": "<html><body><h1>Test</h1><img src='/pic.jpg'></body></html>", "device": "mobile"}
        status, headers, body = self._post("/api/audit", payload)
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert "score" in data
        assert "metrics" in data

    def test_api_optimize_post(self):
        payload = {"html": "<html><body><img src='/pic.jpg'></body></html>", "options": {"dimensions": True}}
        status, headers, body = self._post("/api/optimize", payload)
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert "optimized_html" in data
        assert "changes" in data

    def test_api_pwa_generate_post(self):
        payload = {"name": "Live PWA", "short_name": "PWA"}
        status, headers, body = self._post("/api/pwa/generate", payload)
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert "manifest" in data
        assert "service_worker" in data

    def test_api_og_generate_post(self):
        payload = {"title": "Live Title", "url": "https://test.com"}
        status, headers, body = self._post("/api/og/generate", payload)
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert "html_snippet" in data

    def test_api_diff_post(self):
        payload = {
            "baseline": "<html><body><h1>Baseline</h1></body></html>",
            "candidate": "<html><body><h1>Candidate</h1></body></html>",
        }
        status, headers, body = self._post("/api/diff", payload)
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert "score_delta" in data

    def test_api_cache_export_get(self):
        status, headers, body = self._get("/api/cache/export?platform=netlify")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["filename"] == "_headers"

    def test_api_mcp_config_get(self):
        status, headers, body = self._get("/api/mcp/config?client=cursor")
        assert status == 200
        data = json.loads(body.decode("utf-8"))
        assert data["client"] == "cursor"

    def test_api_export_zip_post(self):
        payload = {"bundle_type": "pwa", "data": {"name": "Test PWA"}}
        status, headers, body = self._post("/api/export-zip", payload)
        assert status == 200
        assert headers.get("Content-Type") == "application/zip"
        assert len(body) > 0
        with zipfile.ZipFile(io.BytesIO(body), "r") as zf:
            assert "site.webmanifest" in zf.namelist()

    def test_options_cors_preflight(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/audit",
            headers={"Origin": "https://example.com"},
            method="OPTIONS",
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            assert response.status == 204
            assert response.headers.get("Access-Control-Allow-Origin") == "*"
