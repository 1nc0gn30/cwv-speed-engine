"""
Tests for production reference examples, CI/CD workflows, and documentation integrity.
Validates JSON syntax, schema compliance, speed configurations, and file completeness.
"""

import json
import pathlib
import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent


# ==============================================================================
# 1. File Existence & Integrity Tests
# ==============================================================================

def test_examples_directory_structure():
    required_paths = [
        "examples/README.md",
        "examples/nextjs-optimized/next.config.js",
        "examples/nextjs-optimized/middleware.ts",
        "examples/nextjs-optimized/README.md",
        "examples/astro-speed/astro.config.mjs",
        "examples/astro-speed/src/components/SpeedHead.astro",
        "examples/astro-speed/README.md",
        "examples/pwa-manifest/site.webmanifest",
        "examples/pwa-manifest/sw.js",
        "examples/pwa-manifest/offline.html",
        "examples/pwa-manifest/README.md",
        "examples/nginx-caching/nginx.conf",
        "examples/nginx-caching/README.md",
        "examples/mcp-clients/claude_desktop_config.json",
        "examples/mcp-clients/cursor_mcp.json",
        "examples/mcp-clients/cline_mcp.json",
        "examples/mcp-clients/zed_settings.json",
        "examples/mcp-clients/README.md",
    ]

    for rel_path in required_paths:
        full_path = REPO_ROOT / rel_path
        assert full_path.exists(), f"Missing required example file: {rel_path}"
        assert full_path.stat().st_size > 20, f"File appears too short/empty: {rel_path}"


def test_github_workflows_structure():
    required_workflows = [
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        ".github/workflows/cwv-gate.yml",
    ]

    for rel_path in required_workflows:
        full_path = REPO_ROOT / rel_path
        assert full_path.exists(), f"Missing required workflow: {rel_path}"
        content = full_path.read_text(encoding="utf-8")
        assert len(content) > 100


def test_docs_structure():
    required_docs = [
        "docs/CORE_WEB_VITALS_GUIDE.md",
        "docs/MCP_GUIDE.md",
        "docs/CACHING_STRATEGIES.md",
        "README.md",
    ]

    for rel_path in required_docs:
        full_path = REPO_ROOT / rel_path
        assert full_path.exists(), f"Missing required doc file: {rel_path}"
        content = full_path.read_text(encoding="utf-8")
        assert len(content) > 200


# ==============================================================================
# 2. JSON Validity & Schema Tests
# ==============================================================================

def test_pwa_webmanifest_valid_json():
    manifest_path = REPO_ROOT / "examples/pwa-manifest/site.webmanifest"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "name" in data
    assert "short_name" in data
    assert "start_url" in data
    assert "display" in data
    assert data["display"] == "standalone"
    assert "icons" in data
    assert len(data["icons"]) >= 2
    assert any(i.get("sizes") == "192x192" for i in data["icons"])
    assert any(i.get("sizes") == "512x512" for i in data["icons"])


@pytest.mark.parametrize("mcp_file", [
    "examples/mcp-clients/claude_desktop_config.json",
    "examples/mcp-clients/cursor_mcp.json",
    "examples/mcp-clients/cline_mcp.json",
    "examples/mcp-clients/zed_settings.json",
])
def test_mcp_client_configs_valid_json(mcp_file):
    config_path = REPO_ROOT / mcp_file
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    text_content = json.dumps(data)
    assert "cwv_speed_engine.mcp_server" in text_content or "cwv-speed-engine" in text_content


# ==============================================================================
# 3. Next.js Config & Middleware Tests
# ==============================================================================

def test_nextjs_config_speed_directives():
    config_path = REPO_ROOT / "examples/nextjs-optimized/next.config.js"
    content = config_path.read_text(encoding="utf-8")

    assert "minimumCacheTTL" in content
    assert "avif" in content
    assert "webp" in content
    assert "31536000" in content
    assert "immutable" in content


def test_nextjs_middleware_headers():
    middleware_path = REPO_ROOT / "examples/nextjs-optimized/middleware.ts"
    content = middleware_path.read_text(encoding="utf-8")

    assert "Link" in content
    assert "rel=preload" in content
    assert "Server-Timing" in content


# ==============================================================================
# 4. Astro Config & Component Tests
# ==============================================================================

def test_astro_config_directives():
    config_path = REPO_ROOT / "examples/astro-speed/astro.config.mjs"
    content = config_path.read_text(encoding="utf-8")

    assert "inlineStylesheets" in content
    assert "prefetch" in content


def test_astro_speed_head_component():
    comp_path = REPO_ROOT / "examples/astro-speed/src/components/SpeedHead.astro"
    content = comp_path.read_text(encoding="utf-8")

    assert "rel=\"preconnect\"" in content
    assert "fetchpriority=\"high\"" in content
    assert "og:title" in content
    assert "twitter:card" in content


# ==============================================================================
# 5. Service Worker & Nginx Directives Tests
# ==============================================================================

def test_service_worker_caching_logic():
    sw_path = REPO_ROOT / "examples/pwa-manifest/sw.js"
    content = sw_path.read_text(encoding="utf-8")

    assert "addEventListener('install'" in content or 'addEventListener("install"' in content
    assert "addEventListener('activate'" in content or 'addEventListener("activate"' in content
    assert "addEventListener('fetch'" in content or 'addEventListener("fetch"' in content
    assert "caches.open" in content
    assert "offline.html" in content


def test_nginx_caching_directives():
    nginx_path = REPO_ROOT / "examples/nginx-caching/nginx.conf"
    content = nginx_path.read_text(encoding="utf-8")

    assert "open_file_cache" in content
    assert "gzip on;" in content
    assert "31536000" in content
    assert "immutable" in content
    assert "stale-while-revalidate" in content


# ==============================================================================
# 6. CI Matrix Multi-OS Matrix Verification
# ==============================================================================

def test_ci_matrix_completeness():
    ci_path = REPO_ROOT / ".github/workflows/ci.yml"
    content = ci_path.read_text(encoding="utf-8")

    assert "ubuntu-latest" in content
    assert "macos-latest" in content
    assert "windows-latest" in content
    for py in ["3.9", "3.10", "3.11", "3.12", "3.13"]:
        assert py in content
