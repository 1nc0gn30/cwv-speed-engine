"""
cwv-speed-engine: High-performance Core Web Vitals audit engine, optimizer, and MCP server.

Pure Python standard library with zero external runtime dependencies.
"""

from __future__ import annotations

from cwv_speed_engine.cli import main
from cwv_speed_engine.mcp_server import (
    MCP_PROTOCOL_VERSION,
    SERVER_NAME,
    SERVER_VERSION,
    AuditResult,
    DiagnosticFinding,
    MCPServer,
    VitalMetric,
    audit_html_content,
    audit_target,
    diff_performance,
    generate_cache_config,
    generate_mcp_client_config,
    generate_og_card,
    generate_pwa,
    get_platform_diagnostics,
    optimize_html,
    run_mcp_server,
)
from cwv_speed_engine.pwa_builder import PWABuilder, generate_pwa_bundle, PWABundle, PWAIcon, PWAShortcut
from cwv_speed_engine.og_builder import OpenGraphBuilder, generate_og_meta_tags
from cwv_speed_engine.diff_engine import PerformanceDiffEngine, compare_cwv_audits, rate_metric
from cwv_speed_engine.ci_gate import run_cwv_check, main as ci_gate_main
from cwv_speed_engine.loaf_analyzer import (
    LongAnimationFrameEntry,
    LongAnimationFrameScript,
    LoAFAttributionReport,
    analyze_loaf_entries,
    audit_html_for_loaf_risks,
)

__version__ = "1.0.0"
__author__ = "CWV Speed Engine Team"
__license__ = "MIT"

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "SERVER_NAME",
    "SERVER_VERSION",
    "MCP_PROTOCOL_VERSION",
    "main",
    "MCPServer",
    "run_mcp_server",
    "generate_mcp_client_config",
    "get_platform_diagnostics",
    "audit_target",
    "audit_html_content",
    "optimize_html",
    "generate_cache_config",
    "generate_pwa",
    "generate_og_card",
    "diff_performance",
    "AuditResult",
    "VitalMetric",
    "DiagnosticFinding",
    "PWABuilder",
    "generate_pwa_bundle",
    "PWABundle",
    "PWAIcon",
    "PWAShortcut",
    "OpenGraphBuilder",
    "generate_og_meta_tags",
    "PerformanceDiffEngine",
    "compare_cwv_audits",
    "rate_metric",
    "run_cwv_check",
    "ci_gate_main",
    "LongAnimationFrameEntry",
    "LongAnimationFrameScript",
    "LoAFAttributionReport",
    "analyze_loaf_entries",
    "audit_html_for_loaf_risks",
]
