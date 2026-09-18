"""Web Performance Budget & Network Latency Simulator.

Enforces strict Core Web Vitals resource weight budgets (Scripts, Styles, Fonts, Images),
simulates multi-generational network throttling (Slow 3G, Fast 3G, 4G, 5G), computes
mobile CPU parse/compile overhead for INP protection, and synthesizes standard
Lighthouse `budget.json` configurations for CI pipelines.

100% Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

import json
import math
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union


class ResourceType(str, Enum):
    """Categorization of web assets subject to performance budgeting."""

    SCRIPT = "script"
    STYLESHEET = "stylesheet"
    IMAGE = "image"
    FONT = "font"
    DOCUMENT = "document"
    MEDIA = "media"
    OTHER = "other"


@dataclass(frozen=True)
class NetworkCondition:
    """Network connection profile with downstream bandwidth and round-trip time."""

    name: str
    bandwidth_kbps: float  # Kilobits per second
    rtt_ms: float          # Round-trip latency in milliseconds
    description: str


# Predefined network simulation profiles based on Chrome DevTools and WebPageTest standards
NETWORK_PROFILES: Dict[str, NetworkCondition] = {
    "slow_3g": NetworkCondition(
        name="Slow 3G",
        bandwidth_kbps=400.0,
        rtt_ms=400.0,
        description="High-latency, constrained cellular connection (400 Kbps, 400ms RTT)",
    ),
    "fast_3g": NetworkCondition(
        name="Fast 3G",
        bandwidth_kbps=1600.0,
        rtt_ms=150.0,
        description="Standard mobile 3G / congested LTE (1.6 Mbps, 150ms RTT)",
    ),
    "regular_4g": NetworkCondition(
        name="Regular 4G",
        bandwidth_kbps=10000.0,
        rtt_ms=50.0,
        description="Typical North American & European 4G LTE (10 Mbps, 50ms RTT)",
    ),
    "fast_5g": NetworkCondition(
        name="Fast 5G / Fiber",
        bandwidth_kbps=50000.0,
        rtt_ms=20.0,
        description="High-speed 5G or residential fiber (50 Mbps, 20ms RTT)",
    ),
}

# Industry standard Core Web Vitals mobile budgets (in Kilobytes)
DEFAULT_MOBILE_BUDGETS: Dict[str, float] = {
    ResourceType.SCRIPT.value: 170.0,       # Initial JS transfer (compressed)
    ResourceType.STYLESHEET.value: 50.0,    # Render-blocking CSS
    ResourceType.FONT.value: 100.0,          # Web fonts
    ResourceType.IMAGE.value: 250.0,         # Hero & above-the-fold images
    ResourceType.DOCUMENT.value: 30.0,       # HTML document
    "total": 500.0,                          # Total page weight threshold
}


@dataclass
class ResourceEntry:
    """An individual web asset evaluated during a performance budget audit."""

    url: str
    resource_type: ResourceType
    size_bytes: int
    transfer_bytes: int  # Estimated compressed wire transfer size
    is_critical: bool = False  # Blocks initial render (head scripts/styles)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "resource_type": self.resource_type.value,
            "size_bytes": self.size_bytes,
            "size_kb": round(self.size_bytes / 1024.0, 2),
            "transfer_bytes": self.transfer_bytes,
            "transfer_kb": round(self.transfer_bytes / 1024.0, 2),
            "is_critical": self.is_critical,
        }


@dataclass
class BudgetThreshold:
    """Budget limit and compliance status for a specific asset category."""

    resource_type: str
    budget_kb: float
    actual_kb: float
    percent_used: float
    status: str  # 'PASS', 'WARNING', 'FAIL'
    overage_kb: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class NetworkSimulation:
    """Simulated download and parse latency under a specific network profile."""

    profile_name: str
    bandwidth_kbps: float
    rtt_ms: float
    download_time_ms: float
    estimated_cpu_parse_ms: float
    estimated_tti_ms: float
    lcp_delay_risk_ms: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class INPBudgetBreakdown:
    """Interaction to Next Paint (INP) latency allocation and main-thread risk."""

    input_delay_budget_ms: float = 50.0
    processing_budget_ms: float = 100.0
    presentation_delay_budget_ms: float = 50.0
    total_budget_ms: float = 200.0  # CWV "Good" threshold
    estimated_js_main_thread_cost_ms: float = 0.0
    risk_level: str = "LOW"  # 'LOW', 'MEDIUM', 'HIGH'
    explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PerformanceBudgetReport:
    """Comprehensive performance budget and network simulation report."""

    target_name: str
    total_transfer_kb: float
    total_budget_kb: float
    is_passing: bool
    items: List[BudgetThreshold] = field(default_factory=list)
    network_simulations: List[NetworkSimulation] = field(default_factory=list)
    inp_breakdown: INPBudgetBreakdown = field(default_factory=INPBudgetBreakdown)
    recommendations: List[str] = field(default_factory=list)
    lighthouse_budget_json: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_name": self.target_name,
            "total_transfer_kb": self.total_transfer_kb,
            "total_budget_kb": self.total_budget_kb,
            "is_passing": self.is_passing,
            "items": [item.to_dict() for item in self.items],
            "network_simulations": [sim.to_dict() for sim in self.network_simulations],
            "inp_breakdown": self.inp_breakdown.to_dict(),
            "recommendations": list(self.recommendations),
            "lighthouse_budget_json": self.lighthouse_budget_json,
        }


def parse_html_resource_weights(html_content: str, base_url: str = "https://example.com") -> List[ResourceEntry]:
    """Extract and estimate resource weights from HTML markup.
    
    Zero-external dependency heuristic parser that identifies scripts, styles,
    images, and fonts with conservative gzip compression estimations.
    """
    entries: List[ResourceEntry] = []
    
    # 1. Document itself
    doc_raw = len(html_content.encode("utf-8"))
    doc_transfer = int(doc_raw * 0.35)  # ~65% compression ratio for HTML
    entries.append(
        ResourceEntry(
            url=base_url,
            resource_type=ResourceType.DOCUMENT,
            size_bytes=doc_raw,
            transfer_bytes=doc_transfer,
            is_critical=True,
        )
    )

    # 2. External Scripts (<script src="...">)
    script_pattern = re.compile(r'<script\b([^>]*)>', re.IGNORECASE)
    for match in script_pattern.finditer(html_content):
        attrs = match.group(1)
        src_match = re.search(r'src=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        is_async_or_defer = bool(re.search(r'\b(async|defer)\b', attrs, re.IGNORECASE))
        if src_match:
            src = src_match.group(1)
            # Standard estimated web script bundle size (average ~45KB compressed, 140KB raw if unknown)
            est_raw = 140 * 1024
            est_transfer = 45 * 1024
            entries.append(
                ResourceEntry(
                    url=urllib.parse.urljoin(base_url, src),
                    resource_type=ResourceType.SCRIPT,
                    size_bytes=est_raw,
                    transfer_bytes=est_transfer,
                    is_critical=not is_async_or_defer,
                )
            )

    # Inline Scripts (<script>...</script>)
    inline_script_pattern = re.compile(r'<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>', re.IGNORECASE | re.DOTALL)
    for idx, match in enumerate(inline_script_pattern.finditer(html_content)):
        code = match.group(1).strip()
        if code:
            raw = len(code.encode("utf-8"))
            transfer = max(100, int(raw * 0.4))
            entries.append(
                ResourceEntry(
                    url=f"{base_url}#inline-script-{idx + 1}",
                    resource_type=ResourceType.SCRIPT,
                    size_bytes=raw,
                    transfer_bytes=transfer,
                    is_critical=True,
                )
            )

    # 3. External Stylesheets (<link rel="stylesheet" href="...">)
    link_pattern = re.compile(r'<link\b([^>]*)>', re.IGNORECASE)
    for match in link_pattern.finditer(html_content):
        attrs = match.group(1)
        rel_match = re.search(r'rel=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        href_match = re.search(r'href=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if not href_match:
            continue
        href = href_match.group(1)
        rel = (rel_match.group(1) if rel_match else "").lower()

        if "stylesheet" in rel:
            est_raw = 60 * 1024
            est_transfer = 18 * 1024
            entries.append(
                ResourceEntry(
                    url=urllib.parse.urljoin(base_url, href),
                    resource_type=ResourceType.STYLESHEET,
                    size_bytes=est_raw,
                    transfer_bytes=est_transfer,
                    is_critical=True,
                )
            )
        elif "preload" in rel and 'as="font"' in attrs:
            est_transfer = 28 * 1024  # WOFF2 average size
            entries.append(
                ResourceEntry(
                    url=urllib.parse.urljoin(base_url, href),
                    resource_type=ResourceType.FONT,
                    size_bytes=est_transfer,
                    transfer_bytes=est_transfer,
                    is_critical=False,
                )
            )

    # Inline Styles (<style>...</style>)
    inline_style_pattern = re.compile(r'<style[^>]*>(.*?)</style>', re.IGNORECASE | re.DOTALL)
    for idx, match in enumerate(inline_style_pattern.finditer(html_content)):
        css = match.group(1).strip()
        if css:
            raw = len(css.encode("utf-8"))
            transfer = max(100, int(raw * 0.35))
            entries.append(
                ResourceEntry(
                    url=f"{base_url}#inline-style-{idx + 1}",
                    resource_type=ResourceType.STYLESHEET,
                    size_bytes=raw,
                    transfer_bytes=transfer,
                    is_critical=True,
                )
            )

    # 4. Images (<img src="...">)
    img_pattern = re.compile(r'<img\b([^>]*)>', re.IGNORECASE)
    for match in img_pattern.finditer(html_content):
        attrs = match.group(1)
        src_match = re.search(r'src=["\']([^"\']+)["\']', attrs, re.IGNORECASE)
        if src_match:
            src = src_match.group(1)
            is_lazy = 'loading="lazy"' in attrs.lower() or "loading='lazy'" in attrs.lower()
            # Images are already binary compressed
            est_transfer = 45 * 1024
            entries.append(
                ResourceEntry(
                    url=urllib.parse.urljoin(base_url, src),
                    resource_type=ResourceType.IMAGE,
                    size_bytes=est_transfer,
                    transfer_bytes=est_transfer,
                    is_critical=not is_lazy,
                )
            )

    return entries


def simulate_network_transfer(
    total_bytes: int,
    js_bytes: int,
    profile: NetworkCondition,
) -> NetworkSimulation:
    """Calculate network transfer latency and CPU parse/compile time."""
    # Wire transfer time in milliseconds = RTT + (bits / (kbps * 1000)) * 1000
    bandwidth_bps = profile.bandwidth_kbps * 1000.0
    bits = total_bytes * 8.0
    raw_transfer_sec = bits / bandwidth_bps if bandwidth_bps > 0 else 0.0
    download_ms = round(profile.rtt_ms + (raw_transfer_sec * 1000.0), 1)

    # Mid-tier mobile CPU compile & parse cost (~1.1 ms per 1KB of JavaScript)
    js_kb = js_bytes / 1024.0
    cpu_parse_ms = round(js_kb * 1.1, 1)

    # Estimated Time to Interactive / First CPU Idle
    tti_ms = round(download_ms + cpu_parse_ms, 1)

    # Largest Contentful Paint delay risk (approx 75% of critical path network latency)
    lcp_risk_ms = round(download_ms * 0.75, 1)

    return NetworkSimulation(
        profile_name=profile.name,
        bandwidth_kbps=profile.bandwidth_kbps,
        rtt_ms=profile.rtt_ms,
        download_time_ms=download_ms,
        estimated_cpu_parse_ms=cpu_parse_ms,
        estimated_tti_ms=tti_ms,
        lcp_delay_risk_ms=lcp_risk_ms,
    )


def audit_performance_budget(
    html_or_resources: Union[str, List[ResourceEntry]],
    custom_budgets: Optional[Dict[str, float]] = None,
    target_name: str = "Page Audit",
) -> PerformanceBudgetReport:
    """Audit assets against Core Web Vitals performance budgets and simulate real-world conditions."""
    if isinstance(html_or_resources, str):
        resources = parse_html_resource_weights(html_or_resources)
    else:
        resources = list(html_or_resources)

    budgets = dict(DEFAULT_MOBILE_BUDGETS)
    if custom_budgets:
        budgets.update(custom_budgets)

    # Group actual transfer sizes by category
    type_totals_bytes: Dict[str, int] = {rt.value: 0 for rt in ResourceType}
    for res in resources:
        type_totals_bytes[res.resource_type.value] += res.transfer_bytes

    total_actual_bytes = sum(type_totals_bytes.values())
    total_actual_kb = round(total_actual_bytes / 1024.0, 2)
    total_budget_kb = budgets.get("total", 500.0)

    items: List[BudgetThreshold] = []
    is_all_passing = True

    # Check each budgeted category
    for cat, budget_limit in budgets.items():
        if cat == "total":
            actual_kb = total_actual_kb
        else:
            actual_kb = round(type_totals_bytes.get(cat, 0) / 1024.0, 2)

        percent = round((actual_kb / budget_limit * 100.0), 1) if budget_limit > 0 else 0.0
        overage = max(0.0, round(actual_kb - budget_limit, 2))

        if actual_kb > budget_limit:
            status = "FAIL"
            is_all_passing = False
        elif percent >= 85.0:
            status = "WARNING"
        else:
            status = "PASS"

        items.append(
            BudgetThreshold(
                resource_type=cat,
                budget_kb=budget_limit,
                actual_kb=actual_kb,
                percent_used=percent,
                status=status,
                overage_kb=overage,
            )
        )

    # Run network condition simulations
    js_transfer_bytes = type_totals_bytes.get(ResourceType.SCRIPT.value, 0)
    simulations: List[NetworkSimulation] = []
    for prof in NETWORK_PROFILES.values():
        simulations.append(simulate_network_transfer(total_actual_bytes, js_transfer_bytes, prof))

    # INP breakdown and main-thread risk calculation
    js_kb = js_transfer_bytes / 1024.0
    main_thread_cost = round(js_kb * 1.1, 1)
    if main_thread_cost > 120.0:
        inp_risk = "HIGH"
        inp_exp = f"Estimated main-thread script execution ({main_thread_cost:.1f}ms) severely exceeds INP processing budget (100ms)."
    elif main_thread_cost > 60.0:
        inp_risk = "MEDIUM"
        inp_exp = f"Moderate script overhead ({main_thread_cost:.1f}ms); long interaction tasks risk exceeding 200ms threshold."
    else:
        inp_risk = "LOW"
        inp_exp = f"Script volume is lean ({main_thread_cost:.1f}ms cost); ample headroom for 50ms input delay and 100ms processing."

    inp_breakdown = INPBudgetBreakdown(
        estimated_js_main_thread_cost_ms=main_thread_cost,
        risk_level=inp_risk,
        explanation=inp_exp,
    )

    # Actionable recommendations
    recommendations: List[str] = []
    if type_totals_bytes.get(ResourceType.SCRIPT.value, 0) / 1024.0 > budgets.get(ResourceType.SCRIPT.value, 170.0):
        recommendations.append("Code-split non-critical JavaScript using dynamic imports; load analytics/widgets via web workers or defer.")
    if type_totals_bytes.get(ResourceType.STYLESHEET.value, 0) / 1024.0 > budgets.get(ResourceType.STYLESHEET.value, 50.0):
        recommendations.append("Extract and inline critical CSS; load global stylesheets asynchronously using media='print' onload hack.")
    if type_totals_bytes.get(ResourceType.IMAGE.value, 0) / 1024.0 > budgets.get(ResourceType.IMAGE.value, 250.0):
        recommendations.append("Convert heavy JPG/PNG images to modern AVIF/WebP formats and enforce loading='lazy' on all below-the-fold pictures.")
    if total_actual_kb > total_budget_kb:
        recommendations.append(f"Total page payload ({total_actual_kb:.1f} KB) exceeds the 500 KB mobile CWV ceiling. Apply Brotli compression.")

    if not recommendations:
        recommendations.append("All resource categories are within strict mobile Core Web Vitals thresholds. Ready for production release.")

    # Lighthouse budget.json synthesis
    lh_budget = generate_lighthouse_budget_json_config(items)

    return PerformanceBudgetReport(
        target_name=target_name,
        total_transfer_kb=total_actual_kb,
        total_budget_kb=total_budget_kb,
        is_passing=is_all_passing,
        items=items,
        network_simulations=simulations,
        inp_breakdown=inp_breakdown,
        recommendations=recommendations,
        lighthouse_budget_json=lh_budget,
    )


def generate_lighthouse_budget_json_config(items: List[BudgetThreshold]) -> Dict[str, Any]:
    """Synthesize standard Lighthouse budget.json configuration file."""
    resource_budget_entries: List[Dict[str, Any]] = []
    for item in items:
        if item.resource_type == "total":
            resource_budget_entries.append({
                "resourceType": "total",
                "budget": int(item.budget_kb),
            })
        else:
            resource_budget_entries.append({
                "resourceType": item.resource_type,
                "budget": int(item.budget_kb),
            })

    return {
        "budgets": [
            {
                "path": "/*",
                "resourceSizes": resource_budget_entries,
                "resourceCounts": [
                    {"resourceType": "script", "budget": 8},
                    {"resourceType": "stylesheet", "budget": 3},
                    {"resourceType": "font", "budget": 4},
                ],
            }
        ]
    }


def render_ascii_budget_report(report: PerformanceBudgetReport) -> str:
    """Render an elegant ANSI/ASCII terminal card with progress meters and network tables."""
    lines = [
        "╔══════════════════════════════════════════════════════════════════════════════╗",
        "║  ✦ CORE WEB VITALS PERFORMANCE BUDGET & NETWORK SIMULATOR                   ║",
        "╠══════════════════════════════════════════════════════════════════════════════╣",
        f"║  Target:            {report.target_name:<58} ║",
        f"║  Total Transfer:    {report.total_transfer_kb} KB / {report.total_budget_kb} KB ({'PASS' if report.is_passing else 'EXCEEDED'})" + " " * (45 - len(str(report.total_transfer_kb)) - len(str(report.total_budget_kb))) + "║",
        "╟──────────────────────────────────────────────────────────────────────────────╢",
        "║  Resource Category       Actual       Budget     Used   Status                ║",
        "╟──────────────────────────────────────────────────────────────────────────────╢",
    ]

    for item in report.items:
        bar_len = 16
        filled = min(bar_len, int((item.percent_used / 100.0) * bar_len))
        bar = "█" * filled + "░" * (bar_len - filled)
        status_tag = f"[{item.status:^7}]"
        name_str = f"{item.resource_type.title():<15}"
        actual_str = f"{item.actual_kb:>6.1f} KB"
        budget_str = f"{item.budget_kb:>6.1f} KB"
        pct_str = f"{item.percent_used:>5.1f}%"
        lines.append(f"║  {name_str} {actual_str}  {budget_str}  {pct_str}  {bar} {status_tag} ║")

    lines.extend([
        "╟──────────────────────────────────────────────────────────────────────────────╢",
        "║  Multi-Network Download & TTI Simulation:                                    ║",
        "║  Profile           Bandwidth     RTT       Download    CPU Parse   Est. TTI  ║",
        "╟──────────────────────────────────────────────────────────────────────────────╢",
    ])

    for sim in report.network_simulations:
        p_name = f"{sim.profile_name:<16}"
        bw_str = f"{sim.bandwidth_kbps:>6.0f} Kbps"
        rtt_str = f"{sim.rtt_ms:>4.0f}ms"
        dl_str = f"{sim.download_time_ms:>7.0f}ms"
        cpu_str = f"{sim.estimated_cpu_parse_ms:>6.0f}ms"
        tti_str = f"{sim.estimated_tti_ms:>7.0f}ms"
        lines.append(f"║  {p_name} {bw_str}  {rtt_str}    {dl_str}     {cpu_str}    {tti_str} ║")

    lines.extend([
        "╟──────────────────────────────────────────────────────────────────────────────╢",
        f"║  INP Latency Safety Rating: [{report.inp_breakdown.risk_level}] ({report.inp_breakdown.estimated_js_main_thread_cost_ms:.1f}ms script execution cost) ║",
        f"║  • {report.inp_breakdown.explanation[:70]:<74}║",
        "╟──────────────────────────────────────────────────────────────────────────────╢",
        "║  Optimization Recommendations:                                               ║",
    ])

    for rec in report.recommendations:
        chunks = [rec[i:i+70] for i in range(0, len(rec), 70)]
        for ch in chunks:
            lines.append(f"║  • {ch:<72}║")

    lines.append("╚══════════════════════════════════════════════════════════════════════════════╝")
    return "\n".join(lines)
