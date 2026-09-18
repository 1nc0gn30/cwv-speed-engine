"""Tests for Performance Budget & Network Latency Simulator.

Validates:
1. HTML resource weight parsing for scripts, styles, images, fonts, and document.
2. Network transfer time calculations under 3G, 4G, and 5G profiles.
3. Mobile CPU parse/compile time estimation and INP risk scoring.
4. Passing vs failing budget threshold detection and overage math.
5. Standard Lighthouse budget.json configuration synthesis.
6. Terminal ASCII progress bar and report card rendering.
7. MCP tool integration (cwv_audit_performance_budget).
8. CLI subcommand execution with --json, --lighthouse, and --fail-on-error.
9. UI server REST endpoint (/api/budget).

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

from cwv_speed_engine.budget_simulator import (
    ResourceType,
    NetworkCondition,
    ResourceEntry,
    BudgetThreshold,
    NetworkSimulation,
    INPBudgetBreakdown,
    PerformanceBudgetReport,
    parse_html_resource_weights,
    simulate_network_transfer,
    audit_performance_budget,
    generate_lighthouse_budget_json_config,
    render_ascii_budget_report,
    NETWORK_PROFILES,
    DEFAULT_MOBILE_BUDGETS,
)
from cwv_speed_engine.mcp_server import MCPServer
from cwv_speed_engine.cli import build_cli_parser, main as cli_main
from cwv_speed_engine.ui_server import create_server


SAMPLE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Budget Test Page</title>
  <link rel="stylesheet" href="/styles/main.css">
  <link rel="preload" href="/fonts/inter.woff2" as="font" type="font/woff2">
  <script src="/scripts/vendor.js" defer></script>
  <style>body { margin: 0; background: #fff; }</style>
</head>
<body>
  <h1>Budget Auditor</h1>
  <img src="/images/hero.webp" alt="Hero Banner" loading="lazy">
  <script>console.log("Analytics initialized");</script>
</body>
</html>
"""


def test_parse_html_resource_weights():
    """Verify resource extraction and categorization from HTML."""
    resources = parse_html_resource_weights(SAMPLE_HTML, base_url="https://myapp.test")
    assert len(resources) >= 5

    res_types = [r.resource_type for r in resources]
    assert ResourceType.DOCUMENT in res_types
    assert ResourceType.STYLESHEET in res_types
    assert ResourceType.FONT in res_types
    assert ResourceType.SCRIPT in res_types
    assert ResourceType.IMAGE in res_types

    # Document check
    doc_res = [r for r in resources if r.resource_type == ResourceType.DOCUMENT][0]
    assert doc_res.is_critical is True
    assert doc_res.transfer_bytes > 0

    # Image check (lazy loaded should not be critical)
    img_res = [r for r in resources if r.resource_type == ResourceType.IMAGE][0]
    assert img_res.is_critical is False


def test_simulate_network_transfer():
    """Verify latency and bandwidth calculations under various network conditions."""
    prof_3g = NETWORK_PROFILES["slow_3g"]
    total_bytes = 200 * 1024  # 200 KB
    js_bytes = 100 * 1024     # 100 KB

    sim = simulate_network_transfer(total_bytes, js_bytes, prof_3g)
    assert sim.profile_name == "Slow 3G"
    assert sim.bandwidth_kbps == 400.0
    assert sim.rtt_ms == 400.0
    # 200KB * 8 / 400 kbps = 4 seconds = 4000ms + 400ms RTT = ~4400ms
    assert 4300 <= sim.download_time_ms <= 4600
    # 100KB * 1.1 = ~110ms CPU parse
    assert 100 <= sim.estimated_cpu_parse_ms <= 120
    assert sim.estimated_tti_ms > sim.download_time_ms


def test_audit_performance_budget_pass():
    """Verify passing budget report on lean markup."""
    report = audit_performance_budget(SAMPLE_HTML, target_name="Lean Site")
    assert report.is_passing is True
    assert report.total_transfer_kb < report.total_budget_kb
    assert report.inp_breakdown.risk_level in ("LOW", "MEDIUM")
    assert len(report.items) >= 5

    script_item = [i for i in report.items if i.resource_type == "script"][0]
    assert script_item.status == "PASS"
    assert script_item.overage_kb == 0.0


def test_audit_performance_budget_fail_and_overage():
    """Verify budget threshold failure and overage calculations with custom tight budgets."""
    custom_budgets = {
        "script": 20.0,   # Very tight budget: 20 KB
        "total": 50.0,    # Very tight total: 50 KB
    }
    report = audit_performance_budget(SAMPLE_HTML, custom_budgets=custom_budgets, target_name="Heavy Site")
    assert report.is_passing is False

    failing_items = [i for i in report.items if i.status == "FAIL"]
    assert len(failing_items) >= 1

    script_item = [i for i in report.items if i.resource_type == "script"][0]
    assert script_item.status == "FAIL"
    assert script_item.actual_kb > 20.0
    assert script_item.overage_kb > 0.0


def test_generate_lighthouse_budget_json():
    """Verify standard Lighthouse budget.json schema generation."""
    report = audit_performance_budget(SAMPLE_HTML)
    lh = report.lighthouse_budget_json
    assert "budgets" in lh
    assert len(lh["budgets"]) == 1
    assert "resourceSizes" in lh["budgets"][0]
    assert "resourceCounts" in lh["budgets"][0]

    sizes = {entry["resourceType"]: entry["budget"] for entry in lh["budgets"][0]["resourceSizes"]}
    assert "script" in sizes
    assert "total" in sizes
    assert sizes["script"] == int(DEFAULT_MOBILE_BUDGETS["script"])


def test_render_ascii_budget_report():
    """Verify terminal card rendering with progress bars."""
    report = audit_performance_budget(SAMPLE_HTML, target_name="Demo Test")
    card = render_ascii_budget_report(report)
    assert "CORE WEB VITALS PERFORMANCE BUDGET" in card
    assert "Demo Test" in card
    assert "Slow 3G" in card
    assert "Fast 5G" in card
    assert "INP Latency Safety Rating" in card
    assert "╔" in card and "╝" in card


def test_mcp_tool_cwv_audit_performance_budget():
    """Verify MCPServer tool execution for cwv_audit_performance_budget."""
    server = MCPServer()

    # Verify tool is registered
    list_res = server.handle_request({"jsonrpc": "2.0", "id": 100, "method": "tools/list", "params": {}})
    tools = list_res["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "cwv_audit_performance_budget" in tool_names

    # Call tool
    call_res = server.handle_request({
        "jsonrpc": "2.0",
        "id": 101,
        "method": "tools/call",
        "params": {
            "name": "cwv_audit_performance_budget",
            "arguments": {
                "html_or_path": SAMPLE_HTML,
                "target_name": "MCP Test",
            },
        },
    })
    assert not call_res.get("error")
    assert not call_res["result"]["isError"]
    res = json.loads(call_res["result"]["content"][0]["text"])
    assert "total_transfer_kb" in res
    assert "is_passing" in res
    assert "items" in res
    assert "network_simulations" in res


def test_cli_budget_subcommand(capsys):
    """Verify CLI budget subcommand with --json and standard output."""
    parser = build_cli_parser()
    args = parser.parse_args(["budget", SAMPLE_HTML, "--json"])
    exit_code = cli_main(["budget", SAMPLE_HTML, "--json"])
    assert exit_code == 0

    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert data["is_passing"] is True
    assert "total_transfer_kb" in data


def test_cli_budget_fail_on_error():
    """Verify CLI budget subcommand returns exit code 1 when --fail-on-error is set and budget is exceeded."""
    exit_code = cli_main(["budget", SAMPLE_HTML, "--script-budget", "1", "--fail-on-error"])
    assert exit_code == 1


def test_cli_budget_lighthouse_flag(capsys):
    """Verify CLI budget subcommand outputs valid Lighthouse budget.json."""
    exit_code = cli_main(["budget", SAMPLE_HTML, "--lighthouse"])
    assert exit_code == 0
    captured = capsys.readouterr().out
    data = json.loads(captured)
    assert "budgets" in data


def test_ui_api_budget_endpoint():
    """Verify UI server REST /api/budget GET and POST endpoints."""
    server = create_server(host="127.0.0.1", port=0)
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever)
    t.daemon = True
    t.start()

    try:
        # Test GET /api/budget
        req_get = urllib.request.Request(f"http://127.0.0.1:{port}/api/budget?name=GETTest")
        with urllib.request.urlopen(req_get, timeout=3.0) as resp:
            assert resp.status == 200
            data_get = json.loads(resp.read().decode("utf-8"))
            assert data_get["target_name"] == "GETTest"
            assert "items" in data_get

        # Test POST /api/budget
        post_payload = json.dumps({"html": SAMPLE_HTML, "target_name": "POSTTest"}).encode("utf-8")
        req_post = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/budget",
            data=post_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_post, timeout=3.0) as resp:
            assert resp.status == 200
            data_post = json.loads(resp.read().decode("utf-8"))
            assert data_post["target_name"] == "POSTTest"
            assert data_post["is_passing"] is True
    finally:
        server.shutdown()
        server.server_close()
