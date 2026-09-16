"""
Unit test suite for Model Context Protocol (MCP) Server in cwv-speed-engine.
"""

import json
import os
import tempfile
import unittest
from typing import Any, Dict

from cwv_speed_engine.mcp_server import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    MCPServer,
    audit_html_content,
    audit_target,
    diff_performance,
    generate_cache_config,
    generate_mcp_client_config,
    generate_og_card,
    generate_pwa,
    get_platform_diagnostics,
    optimize_html,
)


class TestMCPServer(unittest.TestCase):
    """Test suite for MCPServer JSON-RPC 2.0 handling and tool execution."""

    def setUp(self) -> None:
        self.server = MCPServer()
        self.sample_html = """<!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <title>Test Speed Page</title>
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <link rel="preconnect" href="https://fonts.googleapis.com">
          <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
          <script src="https://example.com/analytics.js" defer></script>
        </head>
        <body>
          <h1>High Speed Page</h1>
          <img src="/hero.webp" width="1200" height="600" fetchpriority="high" alt="Hero Banner">
          <img src="/thumb.webp" width="400" height="300" loading="lazy" decoding="async" alt="Thumbnail">
        </body>
        </html>"""

    def test_mcp_initialize(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        self.assertEqual(resp["jsonrpc"], "2.0")
        self.assertEqual(resp["id"], 1)
        result = resp["result"]
        self.assertEqual(result["protocolVersion"], MCP_PROTOCOL_VERSION)
        self.assertEqual(result["serverInfo"]["name"], SERVER_NAME)
        self.assertEqual(result["serverInfo"]["version"], SERVER_VERSION)
        self.assertIn("tools", result["capabilities"])

    def test_mcp_notifications_and_ping(self) -> None:
        # Initialized notification should return None
        notif = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {}
        }
        self.assertIsNone(self.server.handle_request(notif))

        # Ping
        ping_req = {
            "jsonrpc": "2.0",
            "id": "ping-123",
            "method": "ping"
        }
        resp = self.server.handle_request(ping_req)
        self.assertEqual(resp["id"], "ping-123")
        self.assertEqual(resp["result"], {})

    def test_mcp_tools_list(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {}
        }
        resp = self.server.handle_request(req)
        self.assertIsNotNone(resp)
        tools = resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]

        expected_tools = [
            "cwv_audit_site",
            "cwv_optimize_html",
            "cwv_generate_cache_config",
            "cwv_generate_pwa",
            "cwv_generate_og_card",
            "cwv_diff_performance",
        ]
        for t_name in expected_tools:
            self.assertIn(t_name, tool_names)

        # Check inputSchema validity
        for t in tools:
            self.assertEqual(t["inputSchema"]["type"], "object")
            self.assertIn("properties", t["inputSchema"])

    def test_tool_cwv_audit_site_local_file(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
            f.write(self.sample_html)
            tmp_path = f.name

        try:
            req = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "cwv_audit_site",
                    "arguments": {
                        "target": tmp_path,
                        "min_score": 80,
                        "device": "mobile"
                    }
                }
            }
            resp = self.server.handle_request(req)
            self.assertFalse(resp["result"]["isError"])
            content_text = resp["result"]["content"][0]["text"]
            audit_data = json.loads(content_text)

            self.assertIn("score", audit_data)
            self.assertGreaterEqual(audit_data["score"], 80)
            self.assertTrue(audit_data["passed"])
            self.assertIn("vitals", audit_data)
            self.assertIn("lcp", audit_data["vitals"])
            self.assertIn("cls", audit_data["vitals"])
            self.assertIn("inp", audit_data["vitals"])
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def test_tool_cwv_audit_site_missing_target(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "cwv_audit_site",
                "arguments": {}
            }
        }
        resp = self.server.handle_request(req)
        # Should report error gracefully
        self.assertTrue(resp["result"]["isError"])

    def test_tool_cwv_optimize_html(self) -> None:
        unoptimized_html = """<!DOCTYPE html>
        <html>
        <head>
          <link rel="stylesheet" href="https://fonts.googleapis.com/css?family=Roboto">
          <script src="https://example.com/app.js"></script>
        </head>
        <body>
          <img src="/photo1.jpg">
          <img src="/photo2.jpg">
        </body>
        </html>"""

        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "cwv_optimize_html",
                "arguments": {
                    "html": unoptimized_html,
                    "lazy_load_images": True,
                    "defer_scripts": True
                }
            }
        }
        resp = self.server.handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        opt_data = json.loads(resp["result"]["content"][0]["text"])

        self.assertIn("optimized_html", opt_data)
        self.assertIn("loading=\"lazy\"", opt_data["optimized_html"])
        self.assertIn("defer", opt_data["optimized_html"])
        self.assertIn("fonts.gstatic.com", opt_data["optimized_html"])
        self.assertGreater(opt_data["actions_count"], 0)

    def test_tool_cwv_generate_cache_config_all_frameworks(self) -> None:
        frameworks = ["netlify", "vercel", "nginx", "nextjs", "cloudflare", "apache"]
        for fw in frameworks:
            req = {
                "jsonrpc": "2.0",
                "id": f"cache-{fw}",
                "method": "tools/call",
                "params": {
                    "name": "cwv_generate_cache_config",
                    "arguments": {
                        "framework": fw,
                        "static_asset_ttl_days": 365
                    }
                }
            }
            resp = self.server.handle_request(req)
            self.assertFalse(resp["result"]["isError"])
            data = json.loads(resp["result"]["content"][0]["text"])
            self.assertEqual(data["framework"], fw)
            self.assertTrue(len(data["config_content"]) > 20)
            self.assertTrue(len(data["target_filename"]) > 2)

    def test_tool_cwv_generate_cache_config_invalid_framework(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": "cache-invalid",
            "method": "tools/call",
            "params": {
                "name": "cwv_generate_cache_config",
                "arguments": {
                    "framework": "unsupported_fw"
                }
            }
        }
        resp = self.server.handle_request(req)
        self.assertTrue(resp["result"]["isError"])

    def test_tool_cwv_generate_pwa(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {
                "name": "cwv_generate_pwa",
                "arguments": {
                    "name": "Speed Master Pro",
                    "theme_color": "#0055ff",
                    "background_color": "#111111"
                }
            }
        }
        resp = self.server.handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        pwa_data = json.loads(resp["result"]["content"][0]["text"])

        manifest = json.loads(pwa_data["manifest_json"])
        self.assertEqual(manifest["name"], "Speed Master Pro")
        self.assertEqual(manifest["theme_color"], "#0055ff")
        self.assertIn("CACHE_NAME", pwa_data["sw_js"])
        self.assertIn("serviceWorker.register", pwa_data["head_snippet"])

    def test_tool_cwv_generate_og_card(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "cwv_generate_og_card",
                "arguments": {
                    "title": "Super Performance Guide",
                    "description": "How to achieve 100 on Core Web Vitals.",
                    "url": "https://example.com/guide",
                    "twitter_handle": "@speed"
                }
            }
        }
        resp = self.server.handle_request(req)
        self.assertFalse(resp["result"]["isError"])
        og_data = json.loads(resp["result"]["content"][0]["text"])

        self.assertIn("og:title", og_data["meta_tags_html"])
        self.assertIn("twitter:card", og_data["meta_tags_html"])
        self.assertIn("@speed", og_data["meta_tags_html"])
        self.assertIn("Super Performance Guide", og_data["json_ld"])
        self.assertIn("<svg", og_data["svg_preview"])

    def test_tool_cwv_diff_performance(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f_a:
            f_a.write("<html><head><script src='bad.js'></script></head><body><img src='a.jpg'></body></html>")
            path_a = f_a.name

        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f_b:
            f_b.write(self.sample_html)
            path_b = f_b.name

        try:
            req = {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {
                    "name": "cwv_diff_performance",
                    "arguments": {
                        "target_a": path_a,
                        "target_b": path_b
                    }
                }
            }
            resp = self.server.handle_request(req)
            self.assertFalse(resp["result"]["isError"])
            diff_data = json.loads(resp["result"]["content"][0]["text"])

            self.assertIn("score_delta", diff_data)
            self.assertIn("verdict", diff_data)
            self.assertIn("metric_deltas", diff_data)
            self.assertIn("lcp", diff_data["metric_deltas"])
            self.assertIn("cls", diff_data["metric_deltas"])
        finally:
            if os.path.exists(path_a):
                os.unlink(path_a)
            if os.path.exists(path_b):
                os.unlink(path_b)

    def test_mcp_invalid_method_and_tool(self) -> None:
        # Invalid method
        req_bad_method = {"jsonrpc": "2.0", "id": 99, "method": "unknown_rpc"}
        resp = self.server.handle_request(req_bad_method)
        self.assertEqual(resp["error"]["code"], -32601)

        # Invalid tool name
        req_bad_tool = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "tools/call",
            "params": {"name": "non_existent_tool", "arguments": {}}
        }
        resp = self.server.handle_request(req_bad_tool)
        self.assertEqual(resp["error"]["code"], -32601)

    def test_generate_mcp_client_config(self) -> None:
        clients = ["claude", "cursor", "cline", "zed", "generic"]
        for c in clients:
            cfg = generate_mcp_client_config(c, python_path="python3", project_root="/dummy/root")
            self.assertIsInstance(cfg, dict)
            if c in ("claude", "cursor", "cline"):
                self.assertIn("mcpServers", cfg)
                self.assertIn("cwv-speed-engine", cfg["mcpServers"])
            elif c == "zed":
                self.assertIn("context_servers", cfg)
            elif c == "generic":
                self.assertEqual(cfg["name"], "cwv-speed-engine")

    def test_platform_diagnostics(self) -> None:
        diag = get_platform_diagnostics()
        self.assertIn("system", diag)
        self.assertIn("python", diag)
        self.assertIn("paths", diag)
        self.assertIn("stdlib_health", diag)
        self.assertTrue(diag["stdlib_health"]["json"])
    def test_mcp_stdio_stream(self) -> None:
        import io
        import sys

        init_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": MCP_PROTOCOL_VERSION}
        })
        ping_req = json.dumps({
            "jsonrpc": "2.0",
            "id": 2,
            "method": "ping"
        })
        bad_json = "NOT_A_VALID_JSON"

        input_stream = f"{init_req}\n{ping_req}\n{bad_json}\n\n"
        stdin_backup = sys.stdin
        stdout_backup = sys.stdout

        sys.stdin = io.StringIO(input_stream)
        sys.stdout = io.StringIO()

        try:
            self.server.run_stdio()
            output = sys.stdout.getvalue()
            lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
            self.assertEqual(len(lines), 3)

            # Response 1: initialize
            resp1 = json.loads(lines[0])
            self.assertEqual(resp1["id"], 1)
            self.assertEqual(resp1["result"]["serverInfo"]["name"], SERVER_NAME)

            # Response 2: ping
            resp2 = json.loads(lines[1])
            self.assertEqual(resp2["id"], 2)
            self.assertEqual(resp2["result"], {})

            # Response 3: parse error
            resp3 = json.loads(lines[2])
            self.assertIn("error", resp3)
            self.assertEqual(resp3["error"]["code"], -32700)
        finally:
            sys.stdin = stdin_backup
            sys.stdout = stdout_backup


if __name__ == "__main__":
    unittest.main()

