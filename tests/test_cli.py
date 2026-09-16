"""
Unit test suite for Command Line Interface (CLI) in cwv-speed-engine.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

from cwv_speed_engine.cli import main


class TestCLI(unittest.TestCase):
    """Test suite for CLI subcommands and options."""

    def setUp(self) -> None:
        self.sample_html = """<!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <title>Optimized Test Page</title>
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <script src="https://example.com/app.js" defer></script>
        </head>
        <body>
          <h1>Welcome</h1>
          <img src="/img1.webp" width="800" height="600" loading="lazy" alt="Test 1">
        </body>
        </html>"""

        self.tmp_dir = tempfile.mkdtemp()
        self.html_file = os.path.join(self.tmp_dir, "index.html")
        with open(self.html_file, "w", encoding="utf-8") as f:
            f.write(self.sample_html)

    def tearDown(self) -> None:
        import shutil
        if os.path.exists(self.tmp_dir):
            shutil.rmtree(self.tmp_dir)

    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout_io = io.StringIO()
        stderr_io = io.StringIO()
        with redirect_stdout(stdout_io), redirect_stderr(stderr_io):
            try:
                code = main(args)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 0
        return code, stdout_io.getvalue(), stderr_io.getvalue()

    def test_cli_help(self) -> None:
        code, out, _ = self.run_cli(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("cwv-engine", out)
        self.assertIn("audit", out)
        self.assertIn("optimize", out)
        self.assertIn("cache", out)

    def test_cli_no_args(self) -> None:
        code, out, _ = self.run_cli([])
        self.assertEqual(code, 0)
        self.assertIn("usage:", out.lower())

    def test_cli_audit_text_output(self) -> None:
        code, out, _ = self.run_cli(["audit", self.html_file, "--min-score", "50", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("CORE WEB VITALS SPEED AUDIT", out)
        self.assertIn("Target:", out)
        self.assertIn("Score:", out)
        self.assertIn("Largest Contentful Paint", out)
        self.assertIn("Cumulative Layout Shift", out)
        self.assertIn("QUALITY GATE PASSED", out)

    def test_cli_audit_json_output(self) -> None:
        code, out, _ = self.run_cli(["audit", self.html_file, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("score", data)
        self.assertIn("vitals", data)
        self.assertIn("lcp", data["vitals"])
        self.assertTrue(data["passed"])

    def test_cli_check_pass(self) -> None:
        code, out, _ = self.run_cli(["check", self.html_file, "--min-score", "50"])
        self.assertEqual(code, 0)
        self.assertIn("PASSED", out)

    def test_cli_check_fail(self) -> None:
        # Require 100 on an imperfect page to trigger fail exit code
        code, out, _ = self.run_cli(["check", self.html_file, "--min-score", "100"])
        self.assertEqual(code, 1)
        self.assertIn("FAILED", out)

    def test_cli_optimize(self) -> None:
        unopt_path = os.path.join(self.tmp_dir, "unopt.html")
        out_path = os.path.join(self.tmp_dir, "opt.html")
        with open(unopt_path, "w", encoding="utf-8") as f:
            f.write("<html><head><script src='lib.js'></script></head><body><img src='hero.jpg'><img src='b.jpg'></body></html>")

        code, out, _ = self.run_cli(["optimize", unopt_path, "--output", out_path])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(out_path))

        with open(out_path, "r", encoding="utf-8") as f:
            opt_content = f.read()
        self.assertIn("loading=\"lazy\"", opt_content)
        self.assertIn("defer", opt_content)

    def test_cli_optimize_json(self) -> None:
        code, out, _ = self.run_cli(["optimize", self.html_file, "--json"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("actions_taken", data)
        self.assertIn("actions_count", data)

    def test_cli_cache_generator(self) -> None:
        cache_dir = os.path.join(self.tmp_dir, "cache_out")
        code, out, _ = self.run_cli(["cache", "--framework", "vercel", "--output-dir", cache_dir])
        self.assertEqual(code, 0)
        target_file = os.path.join(cache_dir, "vercel.json")
        self.assertTrue(os.path.exists(target_file))

        code_j, out_j, _ = self.run_cli(["cache", "--framework", "netlify", "--json"])
        self.assertEqual(code_j, 0)
        net_data = json.loads(out_j)
        self.assertEqual(net_data["framework"], "netlify")
        self.assertEqual(net_data["target_filename"], "netlify.toml")

    def test_cli_pwa_generator(self) -> None:
        pwa_dir = os.path.join(self.tmp_dir, "pwa_out")
        code, out, _ = self.run_cli(["pwa", "--name", "Fast PWA App", "--output-dir", pwa_dir])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(os.path.join(pwa_dir, "manifest.json")))
        self.assertTrue(os.path.exists(os.path.join(pwa_dir, "sw.js")))
        self.assertTrue(os.path.exists(os.path.join(pwa_dir, "pwa_head.html")))

    def test_cli_og_generator(self) -> None:
        og_out = os.path.join(self.tmp_dir, "og_tags.html")
        code, out, _ = self.run_cli(["og", "--title", "My Fast Site", "--desc", "Speed Site", "--output", og_out])
        self.assertEqual(code, 0)
        self.assertTrue(os.path.exists(og_out))
        with open(og_out, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("og:title", content)
        self.assertIn("My Fast Site", content)

    def test_cli_diff(self) -> None:
        html_b = os.path.join(self.tmp_dir, "b.html")
        with open(html_b, "w", encoding="utf-8") as f:
            f.write("<html><head><script src='bad.js'></script></head><body><img src='bad.jpg'></body></html>")

        code, out, _ = self.run_cli(["diff", html_b, self.html_file, "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("PERFORMANCE AUDIT COMPARISON (DIFF)", out)
        self.assertIn("METRIC COMPARISON", out)
        self.assertIn("Overall Score:", out)

    def test_cli_diff_json(self) -> None:
        html_b = os.path.join(self.tmp_dir, "b.html")
        with open(html_b, "w", encoding="utf-8") as f:
            f.write("<html><head><script src='bad.js'></script></head><body><img src='bad.jpg'></body></html>")

        code, out, _ = self.run_cli(["diff", html_b, self.html_file, "--json"])
        self.assertEqual(code, 0)
        diff_data = json.loads(out)
        self.assertIn("score_delta", diff_data)
        self.assertIn("verdict", diff_data)

    def test_cli_mcp_tools(self) -> None:
        code, out, _ = self.run_cli(["mcp", "--tools", "--no-color"])
        self.assertEqual(code, 0)
        self.assertIn("cwv_audit_site", out)
        self.assertIn("cwv_optimize_html", out)
        self.assertIn("cwv_generate_cache_config", out)

    def test_cli_mcp_config(self) -> None:
        code, out, _ = self.run_cli(["mcp", "--config", "claude"])
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertIn("mcpServers", data)

        code_all, out_all, _ = self.run_cli(["mcp", "--config", "all"])
        self.assertEqual(code_all, 0)
        all_data = json.loads(out_all)
        self.assertIn("claude", all_data)
        self.assertIn("cursor", all_data)
        self.assertIn("cline", all_data)
        self.assertIn("zed", all_data)

    def test_cli_platform(self) -> None:
        code, out, _ = self.run_cli(["platform", "--json"])
        self.assertEqual(code, 0)
        diag = json.loads(out)
        self.assertIn("system", diag)
        self.assertIn("python", diag)

        code_txt, out_txt, _ = self.run_cli(["platform", "--no-color"])
        self.assertEqual(code_txt, 0)
        self.assertIn("MULTI-OS PLATFORM DIAGNOSTICS", out_txt)

    def test_cli_test_subcommand(self) -> None:
        code, out, _ = self.run_cli(["test"])
        self.assertEqual(code, 0)
        self.assertIn("All internal engine verification checks PASSED", out)

    def test_cli_test_flag(self) -> None:
        code, out, _ = self.run_cli(["--test"])
        self.assertEqual(code, 0)
        self.assertIn("All internal engine verification checks PASSED", out)

    def test_cli_version(self) -> None:
        code, out, _ = self.run_cli(["--version"])
        self.assertEqual(code, 0)
        self.assertIn("cwv-speed-engine", out)


if __name__ == "__main__":
    unittest.main()

