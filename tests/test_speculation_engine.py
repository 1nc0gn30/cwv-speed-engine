"""Tests for Speculation Rules & 103 Early Hints Instant Navigation Engine.

Validates:
1. W3C Speculation Rules schema generation for prerender and prefetch.
2. Link graph extraction and safe exclusion guardrails (cart, auth, logout).
3. RFC 8297 103 Early Hints synthesis across edge platforms (Netlify, Cloudflare, Nginx, Vercel).
4. Idempotent HTML injection into <head>.
5. Predictive TTFB & LCP Core Web Vitals telemetry.
6. MCP tool integration, CLI subcommand, and UI REST endpoint.

100% Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest

from cwv_speed_engine.speculation_engine import (
    EarlyHintItem,
    SpeculationAction,
    SpeculationEagerness,
    SpeculationPlanReport,
    build_server_configs,
    extract_links_from_html,
    generate_speculation_plan,
    generate_speculation_rules,
    inject_speculation_rules_into_html,
    is_safe_for_speculation,
    synthesize_early_hints,
)
from cwv_speed_engine.mcp_server import MCPServer
from cwv_speed_engine.cli import build_cli_parser, main as cli_main
from cwv_speed_engine.ui_server import create_server


SAMPLE_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Speedy SaaS App</title>
  <link rel="stylesheet" href="/assets/main.css">
  <link rel="stylesheet" href="/assets/theme.css">
  <link rel="preload" href="/fonts/inter.woff2" as="font" type="font/woff2" crossorigin>
</head>
<body>
  <header>
    <a href="/features">Features</a>
    <a href="/pricing">Pricing</a>
    <a href="/blog/case-study-speed">Case Studies</a>
    <a href="/cart">Cart (Side-effect)</a>
    <a href="/logout">Logout (Sensitive)</a>
    <a href="https://external-partner.com/docs">External Docs</a>
  </header>
  <main>
    <img src="/hero-banner.webp" fetchpriority="high" alt="Hero">
    <h1>Sub-second Web Experience</h1>
    <a href="/docs/getting-started">Get Started</a>
  </main>
</body>
</html>
"""


def test_is_safe_for_speculation():
    """Verify sensitive, side-effect, and heavy download URLs are properly excluded."""
    # Safe navigational pages
    assert is_safe_for_speculation("/about") is True
    assert is_safe_for_speculation("/features") is True
    assert is_safe_for_speculation("/blog/post-1") is True
    assert is_safe_for_speculation("/docs/intro") is True

    # Sensitive or side-effect paths
    assert is_safe_for_speculation("/logout") is False
    assert is_safe_for_speculation("/signout") is False
    assert is_safe_for_speculation("/auth/login") is False
    assert is_safe_for_speculation("/api/v1/user") is False
    assert is_safe_for_speculation("/cart") is False
    assert is_safe_for_speculation("/checkout") is False
    assert is_safe_for_speculation("/admin/settings") is False
    assert is_safe_for_speculation("/downloads/app.zip") is False
    assert is_safe_for_speculation("/whitepaper.pdf") is False


def test_extract_links_from_html():
    """Verify internal link extraction and separation of safe vs excluded targets."""
    safe, excluded = extract_links_from_html(SAMPLE_PAGE_HTML, base_url="https://example.com")

    # Internal safe links
    assert "/features" in safe
    assert "/pricing" in safe
    assert "/blog/case-study-speed" in safe
    assert "/docs/getting-started" in safe

    # Sensitive paths
    assert "/cart" in excluded
    assert "/logout" in excluded

    # External links should not be in safe internal targets
    assert not any("external-partner.com" in u for u in safe)


def test_synthesize_early_hints():
    """Verify 103 Early Hints generation for critical stylesheets, fonts, and hero images."""
    hints = synthesize_early_hints(SAMPLE_PAGE_HTML)
    assert len(hints) >= 3

    urls = [h.url for h in hints]
    as_types = [h.as_type for h in hints]

    assert "/assets/main.css" in urls
    assert "style" in as_types
    assert any(h.as_type == "font" and "inter.woff2" in h.url for h in hints)
    assert any(h.as_type == "image" and "hero-banner.webp" in h.url for h in hints)

    # Check header formatting
    for h in hints:
        header_val = h.to_header_value()
        assert f"<{h.url}>" in header_val
        assert f"as={h.as_type}" in header_val


def test_build_server_configs():
    """Verify multi-cloud server configuration generation (Netlify, Cloudflare, Nginx, Vercel)."""
    hints = [
        EarlyHintItem(url="/main.css", rel="preload", as_type="style"),
        EarlyHintItem(url="/font.woff2", rel="preload", as_type="font", crossorigin=True),
    ]
    script_tag = '<script type="speculationrules">{}</script>'

    configs = build_server_configs(hints, script_tag)

    # Netlify
    assert "Link: </main.css>; rel=preload; as=style" in configs["netlify_headers"]
    assert "crossorigin" in configs["netlify_headers"]

    # Nginx
    assert 'add_header Link "</main.css>; rel=preload; as=style";' in configs["nginx_conf"]

    # Vercel JSON
    v_data = json.loads(configs["vercel_json"])
    assert "headers" in v_data


def test_generate_speculation_rules():
    """Verify W3C speculation rules JSON structure."""
    prerender = ["/features", "/pricing"]
    prefetch = ["/blog/1", "/blog/2"]

    rules = generate_speculation_rules(
        prerender_urls=prerender,
        prefetch_urls=prefetch,
        prerender_eagerness="moderate",
        prefetch_eagerness="conservative",
    )

    assert "prerender" in rules
    assert "prefetch" in rules
    assert rules["prerender"][0]["urls"] == prerender
    assert rules["prerender"][0]["eagerness"] == "moderate"
    assert rules["prefetch"][0]["urls"] == prefetch
    assert rules["prefetch"][0]["eagerness"] == "conservative"


def test_inject_speculation_rules_into_html():
    """Verify idempotent insertion into <head>."""
    tag = '<script type="speculationrules">{"prerender": []}</script>'
    injected = inject_speculation_rules_into_html(SAMPLE_PAGE_HTML, tag)
    assert '<script type="speculationrules">' in injected
    assert '</head>' in injected

    # Idempotent re-injection should not duplicate
    re_injected = inject_speculation_rules_into_html(injected, tag)
    assert re_injected.count('<script type="speculationrules">') == 1


def test_generate_speculation_plan_facade():
    """Verify the high-level facade with balanced aggressiveness."""
    plan = generate_speculation_plan(
        SAMPLE_PAGE_HTML,
        base_url="https://example.com",
        aggressiveness="balanced",
        baseline_ttfb_ms=700.0,
        baseline_lcp_ms=2500.0,
    )

    assert isinstance(plan, SpeculationPlanReport)
    assert len(plan.prerender_urls) > 0
    assert len(plan.prefetch_urls) >= 0
    assert len(plan.excluded_urls) >= 2

    # Core Web Vitals telemetry
    assert plan.estimated_ttfb_saving_ms > 0
    assert plan.estimated_lcp_saving_ms > 0
    assert plan.projected_new_ttfb_ms < 700.0
    assert plan.projected_new_lcp_ms < 2500.0

    p_dict = plan.to_dict()
    assert "speculation_rules" in p_dict
    assert "server_configs" in p_dict


def test_mcp_tool_cwv_generate_speculation_rules():
    """Verify MCP protocol handling for cwv_generate_speculation_rules."""
    server = MCPServer()

    # Verify tool listed
    list_res = server.handle_request({"jsonrpc": "2.0", "id": 100, "method": "tools/list", "params": {}})
    tools = list_res["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "cwv_generate_speculation_rules" in tool_names

    # Invoke tool
    call_res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 101,
        "method": "tools/call",
        "params": {
            "name": "cwv_generate_speculation_rules",
            "arguments": {
                "html_or_urls": SAMPLE_PAGE_HTML,
                "base_url": "https://example.com",
                "aggressiveness": "balanced",
            },
        },
    })
    assert not call_res.get("error")
    assert not call_res["result"]["isError"]
    content_text = call_res["result"]["content"][0]["text"]
    data = json.loads(content_text)
    assert "speculation_rules" in data
    assert "estimated_lcp_saving_ms" in data


def test_cli_speculation_subcommand(capsys):
    """Verify CLI execution of `cwv speculation`."""
    parser = build_cli_parser()
    args = parser.parse_args(["speculation", SAMPLE_PAGE_HTML, "--format", "json"])
    assert args.subcommand == "speculation"
    assert args.format == "json"

    ret = cli_main(["speculation", SAMPLE_PAGE_HTML, "--format", "json"])
    assert ret == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "speculation_rules" in payload
    assert "prerender_urls" in payload


def test_ui_api_speculation_endpoint():
    """Verify HTTP POST /api/speculation on test server."""
    server = create_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    url = f"http://127.0.0.1:{port}/api/speculation"

    th = threading.Thread(target=server.serve_forever, daemon=True)
    th.start()
    time.sleep(0.05)

    try:
        body = json.dumps({
            "html": SAMPLE_PAGE_HTML,
            "base_url": "https://example.com",
            "aggressiveness": "aggressive",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert "speculation_rules" in data
            assert len(data["prerender_urls"]) > 0
    finally:
        server.shutdown()
        server.server_close()
        th.join(timeout=1.0)
