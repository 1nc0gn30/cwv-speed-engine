"""Comprehensive test suite for cache_rules.py Cache Generator & Exporters."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from cwv_speed_engine.cache_rules import (
    HEADER_HTML_REVALIDATE,
    HEADER_IMMUTABLE_STATIC,
    export_cache_config,
    generate_apache_htaccess,
    generate_cache_headers,
    generate_cloudflare_headers,
    generate_netlify_headers,
    generate_netlify_toml,
    generate_nextjs_config,
    generate_nginx_conf,
    generate_vercel_json,
)


def test_netlify_headers_generation():
    """Test Netlify _headers syntax and rules."""
    content = generate_netlify_headers()
    assert "/_next/static/*" in content
    assert "/assets/*" in content
    assert HEADER_IMMUTABLE_STATIC in content
    assert HEADER_HTML_REVALIDATE in content
    assert "/*" in content

    # Test with custom rules
    custom = [{"path": "/api/*", "headers": {"Cache-Control": "no-store", "X-Custom": "1"}}]
    custom_content = generate_netlify_headers(custom_rules=custom)
    assert "/api/*" in custom_content
    assert "X-Custom: 1" in custom_content


def test_netlify_toml_generation():
    """Test netlify.toml headers configuration."""
    content = generate_netlify_toml()
    assert "[[headers]]" in content
    assert 'for = "/_next/static/*"' in content
    assert HEADER_IMMUTABLE_STATIC in content


def test_vercel_json_generation():
    """Test Vercel JSON schema and valid formatting."""
    json_str = generate_vercel_json()
    parsed = json.loads(json_str)

    assert "headers" in parsed
    assert isinstance(parsed["headers"], list)

    sources = [h["source"] for h in parsed["headers"]]
    assert any("assets" in s or "static" in s for s in sources)
    assert any("(.*)" in s for s in sources)


def test_nginx_conf_generation():
    """Test Nginx configuration with Gzip and Brotli directives."""
    conf = generate_nginx_conf(enable_gzip=True, enable_brotli=True)

    assert "gzip on;" in conf
    assert "brotli on;" in conf
    assert "expires 1y;" in conf
    assert HEADER_IMMUTABLE_STATIC in conf
    assert HEADER_HTML_REVALIDATE in conf


def test_cloudflare_and_nextjs_and_apache():
    """Test Cloudflare, Next.js, and Apache exporters."""
    # Cloudflare
    cf = generate_cloudflare_headers()
    assert HEADER_IMMUTABLE_STATIC in cf

    # Next.js
    next_conf = generate_nextjs_config()
    assert "async headers()" in next_conf
    assert "/_next/static/:path*" in next_conf

    # Apache
    htaccess = generate_apache_htaccess()
    assert "<IfModule mod_deflate.c>" in htaccess
    assert "<IfModule mod_expires.c>" in htaccess
    assert "<IfModule mod_headers.c>" in htaccess
    assert HEADER_IMMUTABLE_STATIC in htaccess


def test_generate_cache_headers_facade():
    """Test high-level generate_cache_headers helper."""
    res_netlify = generate_cache_headers("netlify")
    assert res_netlify["framework"] == "netlify"
    assert res_netlify["default_filename"] == "_headers"

    res_vercel = generate_cache_headers("vercel")
    assert res_vercel["framework"] == "vercel"
    assert res_vercel["default_filename"] == "vercel.json"

    res_nginx = generate_cache_headers("nginx")
    assert res_nginx["framework"] == "nginx"
    assert res_nginx["default_filename"] == "nginx.conf"


def test_export_cache_config_file_writing(tmp_path: Path):
    """Test atomic file export to disk."""
    out_file = tmp_path / "_headers"
    res = export_cache_config(target="netlify", output_path=out_file)

    assert res["written"] is True
    assert out_file.exists()
    assert HEADER_IMMUTABLE_STATIC in out_file.read_text(encoding="utf-8")


def test_custom_rules_across_exporters():
    """Test custom rules propagation in Vercel and Nginx."""
    custom = [{"path": "/custom/*", "headers": {"X-Test": "Passed"}}]

    # Vercel
    v_json = generate_vercel_json(custom_rules=custom)
    assert "/custom/*" in v_json
    assert "Passed" in v_json

    # Unknown framework fallback
    fallback = generate_cache_headers("unknown_custom_server")
    assert fallback["default_filename"] == "_headers"
    assert HEADER_IMMUTABLE_STATIC in fallback["content"]
