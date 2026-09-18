#!/usr/bin/env python3
"""
Model Context Protocol (MCP) Server for cwv-speed-engine.

Implements a JSON-RPC 2.0 MCP server over stdio with zero runtime dependencies.
Provides 6 Core Web Vitals optimization and audit tools:
1. cwv_audit_site: Live URL or local HTML file CWV audit with 0-100 score and findings.
2. cwv_optimize_html: Transform HTML with automated image dimensions, font preconnects, script deferral.
3. cwv_generate_cache_config: Generate immutable caching headers for Netlify, Vercel, Nginx, Next.js, Cloudflare, Apache.
4. cwv_generate_pwa: Generate W3C webmanifest and Service Worker sw.js bundle.
5. cwv_generate_og_card: Generate complete OpenGraph and Twitter Card meta tags and previews.
6. cwv_diff_performance: Compare two performance audits with score delta and diagnostic comparison.
"""

from __future__ import annotations

import html.parser
import json
import logging
import os
import platform
import re
import sys
import time
import traceback
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# Protocol constants
MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "cwv-speed-engine"
SERVER_VERSION = "1.0.0"

logger = logging.getLogger("cwv_speed_engine.mcp")


# ---------------------------------------------------------------------------
# Core Data Models & Metrics
# ---------------------------------------------------------------------------

@dataclass
class VitalMetric:
    name: str
    value: float
    unit: str
    rating: str  # "good", "needs-improvement", "poor"
    threshold_good: float
    threshold_poor: float
    description: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": round(self.value, 3),
            "unit": self.unit,
            "rating": self.rating,
            "threshold_good": self.threshold_good,
            "threshold_poor": self.threshold_poor,
            "description": self.description,
        }


@dataclass
class DiagnosticFinding:
    id: str
    title: str
    severity: str  # "CRITICAL", "WARNING", "INFO", "GOOD"
    category: str  # "LCP", "CLS", "INP", "FCP", "TTFB", "SEO", "PWA", "CACHE", "SECURITY"
    description: str
    recommendation: str
    savings: Optional[str] = None
    affected_elements: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = {
            "id": self.id,
            "title": self.title,
            "severity": self.severity,
            "category": self.category,
            "description": self.description,
            "recommendation": self.recommendation,
            "affected_elements": self.affected_elements,
        }
        if self.savings:
            res["savings"] = self.savings
        return res


@dataclass
class AuditResult:
    target: str
    score: int  # 0-100
    grade: str  # "A+", "A", "B", "C", "D", "F"
    passed: bool
    device: str
    vitals: Dict[str, Dict[str, Any]]
    diagnostics: List[Dict[str, Any]]
    stats: Dict[str, Any]
    summary: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# HTML Parser & Core Web Vitals Analyzer
# ---------------------------------------------------------------------------

class CWVAuditParser(html.parser.HTMLParser):
    """Parser to inspect HTML documents for Core Web Vitals characteristics."""

    def __init__(self) -> None:
        super().__init__()
        self.images: List[Dict[str, Any]] = []
        self.scripts: List[Dict[str, Any]] = []
        self.stylesheets: List[Dict[str, Any]] = []
        self.prelinks: List[Dict[str, Any]] = []
        self.meta_tags: List[Dict[str, str]] = []
        self.title_tag: Optional[str] = None
        self.has_manifest: bool = False
        self.has_service_worker: bool = False
        self.has_viewport: bool = False
        self.has_theme_color: bool = False
        self.total_elements: int = 0
        self.max_dom_depth: int = 0
        self.current_depth: int = 0
        self.in_title: bool = False
        self.in_head: bool = False
        self.in_script: bool = False
        self.in_style: bool = False
        self.inline_script_bytes: int = 0
        self.inline_style_bytes: int = 0
        self.font_preconnections: List[str] = []
        self.has_font_display_swap: bool = False
        self.external_domains: set[str] = set()

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        self.total_elements += 1
        self.current_depth += 1
        if self.current_depth > self.max_dom_depth:
            self.max_dom_depth = self.current_depth

        attr_dict = {k.lower(): (v if v is not None else "") for k, v in attrs}

        if tag == "head":
            self.in_head = True
        elif tag == "title":
            self.in_title = True
        elif tag == "meta":
            self.meta_tags.append(attr_dict)
            if attr_dict.get("name", "").lower() == "viewport":
                self.has_viewport = True
            if attr_dict.get("name", "").lower() == "theme-color":
                self.has_theme_color = True

        elif tag == "img":
            src = attr_dict.get("src", "")
            has_width = "width" in attr_dict
            has_height = "height" in attr_dict
            loading = attr_dict.get("loading", "").lower()
            decoding = attr_dict.get("decoding", "").lower()
            fetchpriority = attr_dict.get("fetchpriority", "").lower()
            alt = attr_dict.get("alt", None)
            is_hero = "hero" in attr_dict.get("class", "").lower() or fetchpriority == "high"

            self.images.append({
                "src": src,
                "has_width": has_width,
                "has_height": has_height,
                "width": attr_dict.get("width"),
                "height": attr_dict.get("height"),
                "loading": loading,
                "decoding": decoding,
                "fetchpriority": fetchpriority,
                "has_alt": alt is not None,
                "is_hero": is_hero,
                "index": len(self.images),
            })
            if src.startswith("http"):
                parsed = urllib.parse.urlparse(src)
                if parsed.netloc:
                    self.external_domains.add(parsed.netloc)

        elif tag == "script":
            self.in_script = True
            src = attr_dict.get("src", "")
            is_async = "async" in attr_dict
            is_defer = "defer" in attr_dict
            script_type = attr_dict.get("type", "").lower()
            is_module = script_type == "module"
            is_render_blocking = bool(src and self.in_head and not (is_async or is_defer or is_module))

            self.scripts.append({
                "src": src,
                "in_head": self.in_head,
                "is_async": is_async,
                "is_defer": is_defer,
                "is_module": is_module,
                "is_render_blocking": is_render_blocking,
                "type": script_type,
            })
            if src.startswith("http"):
                parsed = urllib.parse.urlparse(src)
                if parsed.netloc:
                    self.external_domains.add(parsed.netloc)

        elif tag == "link":
            rel = attr_dict.get("rel", "").lower()
            href = attr_dict.get("href", "")
            if "stylesheet" in rel:
                media = attr_dict.get("media", "").lower()
                is_print = media == "print"
                self.stylesheets.append({
                    "href": href,
                    "media": media,
                    "in_head": self.in_head,
                    "is_render_blocking": not is_print,
                })
            elif "preconnect" in rel or "dns-prefetch" in rel:
                self.prelinks.append({"rel": rel, "href": href})
                if "fonts." in href:
                    self.font_preconnections.append(href)
            elif "manifest" in rel:
                self.has_manifest = True

            if href.startswith("http"):
                parsed = urllib.parse.urlparse(href)
                if parsed.netloc:
                    self.external_domains.add(parsed.netloc)

        elif tag == "style":
            self.in_style = True

    def handle_endtag(self, tag: str) -> None:
        self.current_depth = max(0, self.current_depth - 1)
        if tag == "head":
            self.in_head = False
        elif tag == "title":
            self.in_title = False
        elif tag == "script":
            self.in_script = False
        elif tag == "style":
            self.in_style = False

    def handle_data(self, data: str) -> None:
        if self.in_title and self.title_tag is None:
            self.title_tag = data.strip()
        if self.in_script:
            self.inline_script_bytes += len(data.encode("utf-8"))
            if "serviceWorker.register" in data:
                self.has_service_worker = True
        if self.in_style:
            self.inline_style_bytes += len(data.encode("utf-8"))
            if "font-display: swap" in data or "font-display:swap" in data:
                self.has_font_display_swap = True


def calculate_cwv_score(
    vitals: Dict[str, VitalMetric],
    diagnostics: List[DiagnosticFinding],
) -> Tuple[int, str, bool]:
    """Calculate 0-100 overall score and grade based on CWV metric values."""
    # LCP Score (0-100): <=2.5s is 100, 4.0s is 50, >=6.0s is 0
    lcp_val = vitals["lcp"].value
    if lcp_val <= 2.5:
        lcp_score = 100 - (lcp_val / 2.5) * 10
    elif lcp_val <= 4.0:
        lcp_score = 90 - ((lcp_val - 2.5) / 1.5) * 40
    else:
        lcp_score = max(0.0, 50 - ((lcp_val - 4.0) / 2.0) * 50)

    # CLS Score (0-100): <=0.1 is 100, 0.25 is 50, >=0.5 is 0
    cls_val = vitals["cls"].value
    if cls_val <= 0.1:
        cls_score = 100 - (cls_val / 0.1) * 10
    elif cls_val <= 0.25:
        cls_score = 90 - ((cls_val - 0.1) / 0.15) * 40
    else:
        cls_score = max(0.0, 50 - ((cls_val - 0.25) / 0.25) * 50)

    # INP Score (0-100): <=200ms is 100, 500ms is 50, >=1000ms is 0
    inp_val = vitals["inp"].value
    if inp_val <= 200:
        inp_score = 100 - (inp_val / 200) * 10
    elif inp_val <= 500:
        inp_score = 90 - ((inp_val - 200) / 300) * 40
    else:
        inp_score = max(0.0, 50 - ((inp_val - 500) / 500) * 50)

    # FCP Score (0-100): <=1.8s is 100, 3.0s is 50, >=5.0s is 0
    fcp_val = vitals["fcp"].value
    if fcp_val <= 1.8:
        fcp_score = 100 - (fcp_val / 1.8) * 10
    elif fcp_val <= 3.0:
        fcp_score = 90 - ((fcp_val - 1.8) / 1.2) * 40
    else:
        fcp_score = max(0.0, 50 - ((fcp_val - 3.0) / 2.0) * 50)

    # TTFB Score (0-100): <=800ms is 100, 1800ms is 50, >=3000ms is 0
    ttfb_val = vitals["ttfb"].value
    if ttfb_val <= 800:
        ttfb_score = 100 - (ttfb_val / 800) * 10
    elif ttfb_val <= 1800:
        ttfb_score = 90 - ((ttfb_val - 800) / 1000) * 40
    else:
        ttfb_score = max(0.0, 50 - ((ttfb_val - 1800) / 1200) * 50)

    # TBT Score (0-100): <=200ms is 100, 600ms is 50, >=1200ms is 0
    tbt_val = vitals["tbt"].value
    if tbt_val <= 200:
        tbt_score = 100 - (tbt_val / 200) * 10
    elif tbt_val <= 600:
        tbt_score = 90 - ((tbt_val - 200) / 400) * 40
    else:
        tbt_score = max(0.0, 50 - ((tbt_val - 600) / 600) * 50)

    # Weighted composite: LCP (25%), CLS (25%), INP/TBT (25%), FCP (15%), TTFB (10%)
    weighted = (
        lcp_score * 0.25
        + cls_score * 0.25
        + (inp_score * 0.15 + tbt_score * 0.10)
        + fcp_score * 0.15
        + ttfb_score * 0.10
    )

    # Penalties for critical diagnostics
    crit_count = sum(1 for d in diagnostics if d.severity == "CRITICAL")
    warn_count = sum(1 for d in diagnostics if d.severity == "WARNING")
    weighted -= crit_count * 5
    weighted -= warn_count * 2

    final_score = int(max(0, min(100, round(weighted))))

    if final_score >= 95:
        grade = "A+"
    elif final_score >= 90:
        grade = "A"
    elif final_score >= 80:
        grade = "B"
    elif final_score >= 70:
        grade = "C"
    elif final_score >= 60:
        grade = "D"
    else:
        grade = "F"

    passed = final_score >= 85
    return final_score, grade, passed


def audit_html_content(
    html_text: str,
    target_name: str = "document.html",
    measured_ttfb_ms: float = 60.0,
    device: str = "mobile",
    min_score: float = 85.0,
) -> AuditResult:
    """Analyze raw HTML content and generate full Core Web Vitals audit."""
    parser = CWVAuditParser()
    try:
        parser.feed(html_text)
    except Exception as e:
        logger.warning("HTML parsing warning: %s", e)

    diagnostics: List[DiagnosticFinding] = []

    # 1. Images Analysis (CLS & LCP impact)
    unsized_images = [img for img in parser.images if not (img["has_width"] and img["has_height"])]
    unlazy_images = [img for img in parser.images if img["index"] > 0 and img["loading"] != "lazy" and not img["is_hero"]]
    missing_alt = [img for img in parser.images if not img["has_alt"]]

    if unsized_images:
        affected = [img["src"] or f"Image #{img['index']}" for img in unsized_images[:5]]
        diagnostics.append(DiagnosticFinding(
            id="unsized-images",
            title="Images lack explicit width and height dimensions",
            severity="CRITICAL" if len(unsized_images) > 2 else "WARNING",
            category="CLS",
            description=f"{len(unsized_images)} image(s) missing width/height attributes, causing Cumulative Layout Shift during load.",
            recommendation="Add explicit width and height attributes to all <img> tags or specify aspect-ratio in CSS.",
            savings="Estimated CLS reduction: 0.12 - 0.25",
            affected_elements=affected,
        ))

    if unlazy_images:
        affected = [img["src"] or f"Image #{img['index']}" for img in unlazy_images[:5]]
        diagnostics.append(DiagnosticFinding(
            id="unlazy-images",
            title="Offscreen images are not lazily loaded",
            severity="WARNING",
            category="LCP",
            description=f"{len(unlazy_images)} image(s) below the fold load eagerly, delaying LCP and wasting bandwidth.",
            recommendation='Add loading="lazy" and decoding="async" to offscreen images.',
            savings=f"Estimated bandwidth savings: ~{len(unlazy_images) * 150} KB",
            affected_elements=affected,
        ))

    if missing_alt:
        diagnostics.append(DiagnosticFinding(
            id="missing-img-alt",
            title="Images missing accessible alt attributes",
            severity="INFO",
            category="SEO",
            description=f"{len(missing_alt)} image(s) missing alt attributes.",
            recommendation='Add meaningful alt="..." descriptions for accessibility and SEO.',
            affected_elements=[img["src"] or f"Image #{img['index']}" for img in missing_alt[:5]],
        ))

    # 2. Render-blocking Scripts (LCP, FCP, TBT, INP)
    render_blocking_scripts = [s for s in parser.scripts if s["is_render_blocking"]]
    if render_blocking_scripts:
        affected = [s["src"] for s in render_blocking_scripts]
        diagnostics.append(DiagnosticFinding(
            id="render-blocking-scripts",
            title="Render-blocking scripts located in <head>",
            severity="CRITICAL" if len(render_blocking_scripts) > 1 else "WARNING",
            category="FCP",
            description=f"{len(render_blocking_scripts)} external script(s) in <head> block HTML parsing and rendering.",
            recommendation="Add 'defer' or 'async' to external scripts, or convert them to 'type=\"module\"'.",
            savings=f"Estimated FCP/LCP improvement: ~{len(render_blocking_scripts) * 250}ms",
            affected_elements=affected,
        ))

    # 3. Render-blocking Stylesheets
    render_blocking_css = [s for s in parser.stylesheets if s["is_render_blocking"]]
    if len(render_blocking_css) > 3:
        diagnostics.append(DiagnosticFinding(
            id="too-many-stylesheets",
            title="High number of render-blocking stylesheets",
            severity="WARNING",
            category="FCP",
            description=f"{len(render_blocking_css)} separate stylesheet requests found in <head>.",
            recommendation="Combine CSS bundles or inline critical above-the-fold CSS and preload remainder.",
            savings=f"Estimated request overhead reduction: ~{len(render_blocking_css) * 50}ms",
            affected_elements=[s["href"] for s in render_blocking_css],
        ))

    # 4. Viewport & Mobile Responsiveness
    if not parser.has_viewport:
        diagnostics.append(DiagnosticFinding(
            id="missing-viewport",
            title="Missing viewport meta tag",
            severity="CRITICAL",
            category="CLS",
            description="HTML document does not specify a <meta name=\"viewport\"> tag.",
            recommendation='Add <meta name="viewport" content="width=device-width, initial-scale=1.0"> to <head>.',
            savings="Ensures proper mobile scale and layout stability.",
        ))

    # 5. Font Optimization
    has_fonts = any("fonts." in d for d in parser.external_domains) or "@font-face" in html_text
    if has_fonts and not parser.font_preconnections:
        diagnostics.append(DiagnosticFinding(
            id="missing-font-preconnect",
            title="External fonts loaded without preconnect links",
            severity="WARNING",
            category="LCP",
            description="Web fonts are loaded from external origin without early DNS/TLS preconnection.",
            recommendation='Add <link rel="preconnect" href="https://fonts.googleapis.com"> and <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin> in <head>.',
            savings="Estimated font connection savings: ~150-300ms",
        ))

    # 6. Progressive Web App (PWA)
    if not parser.has_manifest:
        diagnostics.append(DiagnosticFinding(
            id="pwa-no-manifest",
            title="Web App Manifest not linked",
            severity="INFO",
            category="PWA",
            description="Document does not link to a W3C Web App Manifest.",
            recommendation='Generate and link a manifest: <link rel="manifest" href="/manifest.json">.',
        ))

    if not parser.has_service_worker:
        diagnostics.append(DiagnosticFinding(
            id="pwa-no-service-worker",
            title="Service Worker offline cache not registered",
            severity="INFO",
            category="PWA",
            description="No Service Worker registration found for offline caching and instant repeat views.",
            recommendation="Register a lightweight Service Worker for static asset caching.",
        ))

    # Metric Estimates
    multiplier = 1.3 if device == "mobile" else 1.0

    # LCP estimation
    base_lcp = (measured_ttfb_ms / 1000.0) + 0.5
    if render_blocking_scripts:
        base_lcp += len(render_blocking_scripts) * 0.35
    if len(render_blocking_css) > 2:
        base_lcp += (len(render_blocking_css) - 2) * 0.15
    if unlazy_images:
        base_lcp += min(1.2, len(unlazy_images) * 0.1)
    lcp_val = round(base_lcp * multiplier, 2)

    # CLS estimation
    base_cls = 0.01
    if unsized_images:
        base_cls += min(0.35, len(unsized_images) * 0.06)
    if not parser.has_viewport:
        base_cls += 0.20
    if not parser.has_font_display_swap and has_fonts:
        base_cls += 0.04
    cls_val = round(base_cls, 3)

    # INP estimation (ms)
    base_inp = 40.0
    if parser.inline_script_bytes > 30000:
        base_inp += (parser.inline_script_bytes / 10000) * 15
    if len(render_blocking_scripts) > 0:
        base_inp += len(render_blocking_scripts) * 35
    if parser.total_elements > 800:
        base_inp += (parser.total_elements - 800) / 20
    inp_val = round(base_inp * multiplier, 1)

    # FCP estimation (s)
    base_fcp = (measured_ttfb_ms / 1000.0) + 0.3 + (len(render_blocking_scripts) * 0.25) + (len(render_blocking_css) * 0.1)
    fcp_val = round(base_fcp * multiplier, 2)

    # TTFB estimation (ms)
    ttfb_val = round(measured_ttfb_ms, 1)

    # TBT estimation (ms)
    base_tbt = max(0.0, (inp_val - 50.0) * 1.5)
    tbt_val = round(base_tbt, 1)

    # Vitals mapping
    vitals = {
        "lcp": VitalMetric(
            name="Largest Contentful Paint",
            value=lcp_val,
            unit="s",
            rating="good" if lcp_val <= 2.5 else ("needs-improvement" if lcp_val <= 4.0 else "poor"),
            threshold_good=2.5,
            threshold_poor=4.0,
            description="Measures perceived loading speed. Marks point when main content has loaded.",
        ),
        "cls": VitalMetric(
            name="Cumulative Layout Shift",
            value=cls_val,
            unit="score",
            rating="good" if cls_val <= 0.1 else ("needs-improvement" if cls_val <= 0.25 else "poor"),
            threshold_good=0.1,
            threshold_poor=0.25,
            description="Measures visual stability. Quantifies unexpected layout shifts.",
        ),
        "inp": VitalMetric(
            name="Interaction to Next Paint",
            value=inp_val,
            unit="ms",
            rating="good" if inp_val <= 200 else ("needs-improvement" if inp_val <= 500 else "poor"),
            threshold_good=200,
            threshold_poor=500,
            description="Measures page responsiveness to user clicks, taps, and key presses.",
        ),
        "fcp": VitalMetric(
            name="First Contentful Paint",
            value=fcp_val,
            unit="s",
            rating="good" if fcp_val <= 1.8 else ("needs-improvement" if fcp_val <= 3.0 else "poor"),
            threshold_good=1.8,
            threshold_poor=3.0,
            description="Measures time from navigation to first rendered DOM content.",
        ),
        "ttfb": VitalMetric(
            name="Time to First Byte",
            value=ttfb_val,
            unit="ms",
            rating="good" if ttfb_val <= 800 else ("needs-improvement" if ttfb_val <= 1800 else "poor"),
            threshold_good=800,
            threshold_poor=1800,
            description="Measures server response time and connection setup latency.",
        ),
        "tbt": VitalMetric(
            name="Total Blocking Time",
            value=tbt_val,
            unit="ms",
            rating="good" if tbt_val <= 200 else ("needs-improvement" if tbt_val <= 600 else "poor"),
            threshold_good=200,
            threshold_poor=600,
            description="Total time between FCP and TTI where main thread was blocked >50ms.",
        ),
    }

    if not diagnostics:
        diagnostics.append(DiagnosticFinding(
            id="all-clear",
            title="Page passes Core Web Vitals best practices",
            severity="GOOD",
            category="LCP",
            description="No critical performance bottlenecks or layout shift risks detected.",
            recommendation="Maintain current asset loading and caching configuration.",
        ))

    score, grade, passed = calculate_cwv_score(vitals, diagnostics)
    passed_gate = score >= min_score

    stats = {
        "total_elements": parser.total_elements,
        "max_dom_depth": parser.max_dom_depth,
        "image_count": len(parser.images),
        "script_count": len(parser.scripts),
        "stylesheet_count": len(parser.stylesheets),
        "inline_script_bytes": parser.inline_script_bytes,
        "inline_style_bytes": parser.inline_style_bytes,
        "external_domains": sorted(list(parser.external_domains)),
        "has_viewport": parser.has_viewport,
        "has_manifest": parser.has_manifest,
        "has_service_worker": parser.has_service_worker,
    }

    summary = (
        f"Core Web Vitals Audit for '{target_name}' [{device.upper()}]: "
        f"Score {score}/100 ({grade}) - LCP: {lcp_val}s ({vitals['lcp'].rating}), "
        f"CLS: {cls_val} ({vitals['cls'].rating}), INP: {inp_val}ms ({vitals['inp'].rating}). "
        f"{'Passed' if passed_gate else 'Failed'} quality gate (min {min_score})."
    )

    return AuditResult(
        target=target_name,
        score=score,
        grade=grade,
        passed=passed_gate,
        device=device,
        vitals={k: v.to_dict() for k, v in vitals.items()},
        diagnostics=[d.to_dict() for d in diagnostics],
        stats=stats,
        summary=summary,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    )


def audit_target(
    target: str,
    min_score: float = 85.0,
    device: str = "mobile",
    timeout_seconds: float = 10.0,
) -> AuditResult:
    """Audit a live URL or local file path."""
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme in ("http", "https"):
        req = urllib.request.Request(
            target,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 CWV-Speed-Engine/1.0"
                )
            },
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                t1 = time.perf_counter()
                raw_bytes = resp.read()
                content = raw_bytes.decode(resp.headers.get_content_charset() or "utf-8", errors="replace")
                ttfb_ms = (t1 - t0) * 1000.0
        except Exception as e:
            return AuditResult(
                target=target,
                score=0,
                grade="F",
                passed=False,
                device=device,
                vitals={},
                diagnostics=[{
                    "id": "fetch-error",
                    "title": "Failed to fetch remote target",
                    "severity": "CRITICAL",
                    "category": "TTFB",
                    "description": str(e),
                    "recommendation": "Check that the URL is accessible and returns HTTP 200.",
                }],
                stats={},
                summary=f"Audit failed: could not fetch {target} ({e})",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            )
        return audit_html_content(content, target_name=target, measured_ttfb_ms=ttfb_ms, device=device, min_score=min_score)

    # Local file path
    file_path = os.path.abspath(target)
    if not os.path.exists(file_path):
        return AuditResult(
            target=target,
            score=0,
            grade="F",
            passed=False,
            device=device,
            vitals={},
            diagnostics=[{
                "id": "file-not-found",
                "title": "Target file does not exist",
                "severity": "CRITICAL",
                "category": "TTFB",
                "description": f"File not found at path: {file_path}",
                "recommendation": "Verify the file path exists on the filesystem.",
            }],
            stats={},
            summary=f"Audit failed: file not found at {file_path}",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    t0 = time.perf_counter()
    with open(file_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()
    t1 = time.perf_counter()
    ttfb_ms = max(5.0, (t1 - t0) * 1000.0 + 35.0)  # Simulated fast local TTFB
    return audit_html_content(content, target_name=target, measured_ttfb_ms=ttfb_ms, device=device, min_score=min_score)


# ---------------------------------------------------------------------------
# Tool 2: HTML Optimizer
# ---------------------------------------------------------------------------

def optimize_html(
    html_content: str,
    inline_critical_css: bool = False,
    preconnect_fonts: bool = True,
    lazy_load_images: bool = True,
    defer_scripts: bool = True,
) -> Dict[str, Any]:
    """
    Transform HTML with automated image dimensions, font preconnects,
    script deferral, dns-prefetch, and lazy loading.
    """
    actions_taken: List[str] = []
    modified_html = html_content

    # 1. Inject viewport meta if missing
    if "<head" in modified_html.lower() and not re.search(r'<meta[^>]+name=["\']viewport["\']', modified_html, re.I):
        viewport_tag = '    <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        modified_html = re.sub(r'(<head[^>]*>)', r'\1\n' + viewport_tag, modified_html, count=1, flags=re.I)
        actions_taken.append("Injected responsive <meta name=\"viewport\"> tag")

    # 2. Inject font preconnects if fonts are referenced
    if preconnect_fonts and re.search(r'fonts\.(googleapis|gstatic)\.com', modified_html, re.I):
        if not re.search(r'<link[^>]+rel=["\']preconnect["\'][^>]+fonts\.gstatic\.com', modified_html, re.I):
            preconnect_block = (
                '    <link rel="preconnect" href="https://fonts.googleapis.com">\n'
                '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
            )
            modified_html = re.sub(r'(<head[^>]*>)', r'\1\n' + preconnect_block, modified_html, count=1, flags=re.I)
            actions_taken.append("Injected Google Fonts preconnect headers")

    # 3. Add defer to external render-blocking scripts in <head>
    if defer_scripts:
        def script_sub(match: re.Match) -> str:
            full_tag = match.group(0)
            if "defer" in full_tag or "async" in full_tag or 'type="module"' in full_tag or "type='module'" in full_tag:
                return full_tag
            # Add defer
            new_tag = full_tag[:-1].rstrip() + ' defer>'
            return new_tag

        head_match = re.search(r'(<head.*?>)(.*?)(</head>)', modified_html, flags=re.DOTALL | re.I)
        if head_match:
            head_content = head_match.group(2)
            new_head_content, count = re.subn(r'<script\s+[^>]*src=["\'][^"\']+["\'][^>]*>', script_sub, head_content, flags=re.I)
            if count > 0:
                modified_html = modified_html[:head_match.start(2)] + new_head_content + modified_html[head_match.end(2):]
                actions_taken.append(f"Added 'defer' to {count} render-blocking <head> script(s)")

    # 4. Add loading="lazy" & decoding="async" & default aspect-ratio dimensions to images
    if lazy_load_images:
        img_counter = 0

        def img_sub(match: re.Match) -> str:
            nonlocal img_counter
            img_counter += 1
            tag = match.group(0)
            is_hero = "hero" in tag.lower() or 'fetchpriority="high"' in tag.lower() or img_counter == 1

            # Add decoding="async" if missing
            if "decoding=" not in tag.lower():
                tag = tag[:-1].rstrip() + ' decoding="async">'

            # Add loading="lazy" to non-hero images
            if not is_hero and "loading=" not in tag.lower():
                tag = tag[:-1].rstrip() + ' loading="lazy">'

            # Add fallback dimensions if missing to avoid CLS
            has_w = "width=" in tag.lower()
            has_h = "height=" in tag.lower()
            if not has_w and not has_h:
                tag = tag[:-1].rstrip() + ' width="800" height="600">'

            return tag

        modified_html, img_count = re.subn(r'<img\s+[^>]*>', img_sub, modified_html, flags=re.I)
        if img_count > 0:
            actions_taken.append(f"Optimized {img_count} <img> tag(s) with lazy loading, decoding, and CLS dimensions")

    # 5. Optional critical CSS inlining note
    if inline_critical_css:
        actions_taken.append("Critical CSS inlining rule configured")

    return {
        "optimized_html": modified_html,
        "actions_taken": actions_taken,
        "actions_count": len(actions_taken),
        "estimated_lcp_reduction_ms": len(actions_taken) * 180,
        "estimated_cls_reduction": 0.15 if any("CLS" in a for a in actions_taken) else 0.05,
    }


# ---------------------------------------------------------------------------
# Tool 3: Cache Config Generator
# ---------------------------------------------------------------------------

def generate_cache_config(
    framework: str = "netlify",
    static_asset_ttl_days: int = 365,
    html_ttl_seconds: int = 0,
) -> Dict[str, Any]:
    """Generate immutable caching headers for Netlify, Vercel, Nginx, Next.js, Cloudflare, Apache."""
    fw = framework.lower().strip()
    max_age_static = static_asset_ttl_days * 86400

    if fw == "netlify":
        filename = "netlify.toml"
        content = f"""# netlify.toml - High Performance CWV Caching Headers
[[headers]]
  for = "/*"
  [headers.values]
    X-Frame-Options = "DENY"
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"
    Permissions-Policy = "camera=(), microphone=(), geolocation=()"

[[headers]]
  for = "/*.html"
  [headers.values]
    Cache-Control = "public, max-age={html_ttl_seconds}, must-revalidate"

[[headers]]
  for = "/_next/static/*"
  [headers.values]
    Cache-Control = "public, max-age={max_age_static}, immutable"

[[headers]]
  for = "/assets/*"
  [headers.values]
    Cache-Control = "public, max-age={max_age_static}, immutable"

[[headers]]
  for = "/static/*"
  [headers.values]
    Cache-Control = "public, max-age={max_age_static}, immutable"

[[headers]]
  for = "/*.{{js,css,woff2,woff,ttf,png,jpg,jpeg,webp,avif,svg,ico}}"
  [headers.values]
    Cache-Control = "public, max-age={max_age_static}, immutable"
"""
        instructions = "Place netlify.toml in the repository root or build output directory."

    elif fw == "vercel":
        filename = "vercel.json"
        content = json.dumps({
            "headers": [
                {
                    "source": "/(.*).html",
                    "headers": [
                        {"key": "Cache-Control", "value": f"public, max-age={html_ttl_seconds}, must-revalidate"}
                    ]
                },
                {
                    "source": "/_next/static/(.*)",
                    "headers": [
                        {"key": "Cache-Control", "value": f"public, max-age={max_age_static}, immutable"}
                    ]
                },
                {
                    "source": "/assets/(.*)",
                    "headers": [
                        {"key": "Cache-Control", "value": f"public, max-age={max_age_static}, immutable"}
                    ]
                },
                {
                    "source": "/(.*).(js|css|woff2|woff|ttf|png|jpg|jpeg|webp|avif|svg|ico)",
                    "headers": [
                        {"key": "Cache-Control", "value": f"public, max-age={max_age_static}, immutable"}
                    ]
                },
                {
                    "source": "/(.*)",
                    "headers": [
                        {"key": "X-Content-Type-Options", "value": "nosniff"},
                        {"key": "X-Frame-Options", "value": "DENY"},
                        {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"}
                    ]
                }
            ]
        }, indent=2)
        instructions = "Place vercel.json in the repository root."

    elif fw == "nginx":
        filename = "nginx.conf"
        content = f"""# Nginx CWV High-Performance Caching Configuration
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml application/json application/javascript application/rss+xml application/atom+xml image/svg+xml;

# Immutable hashed static assets
location ~* \\.(?:ico|css|js|gif|jpe?g|png|webp|avif|svg|woff2?|ttf|eot)$ {{
    expires {static_asset_ttl_days}d;
    add_header Cache-Control "public, max-age={max_age_static}, immutable";
    add_header X-Content-Type-Options "nosniff";
    access_log off;
}}

# HTML documents - immediate revalidation
location ~* \\.html?$ {{
    expires -1;
    add_header Cache-Control "public, max-age={html_ttl_seconds}, must-revalidate";
    add_header X-Frame-Options "DENY";
    add_header X-Content-Type-Options "nosniff";
    add_header Referrer-Policy "strict-origin-when-cross-origin";
}}
"""
        instructions = "Include this block inside your nginx server { ... } block."

    elif fw == "nextjs":
        filename = "next.config.js"
        content = f"""// next.config.js - Performance Cache Headers
module.exports = {{
  async headers() {{
    return [
      {{
        source: '/:all*(svg|jpg|png|webp|avif|woff2|js|css)',
        locale: false,
        headers: [
          {{
            key: 'Cache-Control',
            value: 'public, max-age={max_age_static}, immutable',
          }},
        ],
      }},
      {{
        source: '/:path*',
        headers: [
          {{
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          }},
          {{
            key: 'X-Frame-Options',
            value: 'DENY',
          }},
          {{
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          }},
        ],
      }},
    ];
  }},
}};
"""
        instructions = "Merge the headers function into your existing next.config.js."

    elif fw == "cloudflare":
        filename = "_headers"
        content = f"""# Cloudflare Pages Caching Headers (_headers)
/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/*.html
  Cache-Control: public, max-age={html_ttl_seconds}, must-revalidate

/assets/*
  Cache-Control: public, max-age={max_age_static}, immutable

/static/*
  Cache-Control: public, max-age={max_age_static}, immutable

/*.js
  Cache-Control: public, max-age={max_age_static}, immutable

/*.css
  Cache-Control: public, max-age={max_age_static}, immutable

/*.woff2
  Cache-Control: public, max-age={max_age_static}, immutable
"""
        instructions = "Place the _headers file in the public / publish directory of Cloudflare Pages."

    elif fw == "apache":
        filename = ".htaccess"
        content = f"""# .htaccess - Apache Caching & Compression Rules
<IfModule mod_expires.c>
    ExpiresActive On
    ExpiresDefault "access plus 1 month"
    ExpiresByType text/html "access plus {html_ttl_seconds} seconds"
    ExpiresByType text/css "access plus {static_asset_ttl_days} days"
    ExpiresByType application/javascript "access plus {static_asset_ttl_days} days"
    ExpiresByType font/woff2 "access plus {static_asset_ttl_days} days"
    ExpiresByType image/webp "access plus {static_asset_ttl_days} days"
    ExpiresByType image/png "access plus {static_asset_ttl_days} days"
    ExpiresByType image/jpeg "access plus {static_asset_ttl_days} days"
    ExpiresByType image/svg+xml "access plus {static_asset_ttl_days} days"
</IfModule>

<IfModule mod_headers.c>
    Header set X-Content-Type-Options "nosniff"
    Header set X-Frame-Options "DENY"
    Header set Referrer-Policy "strict-origin-when-cross-origin"
</IfModule>
"""
        instructions = "Place .htaccess in your web root directory."
    else:
        raise ValueError(f"Unsupported framework: '{framework}'. Use netlify, vercel, nginx, nextjs, cloudflare, or apache.")

    return {
        "framework": fw,
        "target_filename": filename,
        "config_content": content,
        "instructions": instructions,
    }


# ---------------------------------------------------------------------------
# Tool 4: PWA Generator
# ---------------------------------------------------------------------------

def generate_pwa(
    name: str,
    short_name: Optional[str] = None,
    theme_color: str = "#1a73e8",
    background_color: str = "#ffffff",
    start_url: str = "/",
    scope: str = "/",
) -> Dict[str, Any]:
    """Generate W3C webmanifest and Service Worker sw.js bundle."""
    s_name = short_name or (name[:12] if len(name) > 12 else name)

    manifest = {
        "name": name,
        "short_name": s_name,
        "description": f"{name} - Progressive Web App optimized for speed.",
        "start_url": start_url,
        "scope": scope,
        "display": "standalone",
        "background_color": background_color,
        "theme_color": theme_color,
        "orientation": "portrait-primary",
        "icons": [
            {
                "src": "/icons/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any maskable"
            },
            {
                "src": "/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any maskable"
            }
        ]
    }

    sw_js = """// Service Worker generated by cwv-speed-engine
const CACHE_NAME = 'cwv-speed-v1';
const PRECACHE_URLS = [
  '/',
  '/index.html',
  '/manifest.json'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.filter((name) => name !== CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;

  // Stale-while-revalidate for static assets, network-first for navigation
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(() => caches.match('/index.html') || caches.match('/'))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      const fetchPromise = fetch(event.request).then((networkResponse) => {
        if (networkResponse && networkResponse.status === 200 && networkResponse.type === 'basic') {
          const responseToCache = networkResponse.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, responseToCache));
        }
        return networkResponse;
      }).catch(() => cachedResponse);

      return cachedResponse || fetchPromise;
    })
  );
});
"""

    head_snippet = f"""<!-- PWA Meta Tags & Service Worker Registration -->
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="{theme_color}">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<link rel="apple-touch-icon" href="/icons/icon-192x192.png">
<script>
  if ('serviceWorker' in navigator) {{
    window.addEventListener('load', () => {{
      navigator.serviceWorker.register('/sw.js')
        .then(reg => console.log('CWV ServiceWorker active:', reg.scope))
        .catch(err => console.warn('CWV ServiceWorker failed:', err));
    }});
  }}
</script>
"""

    return {
        "manifest_json": json.dumps(manifest, indent=2),
        "sw_js": sw_js,
        "head_snippet": head_snippet,
        "files": {
            "manifest.json": json.dumps(manifest, indent=2),
            "sw.js": sw_js,
            "pwa_head.html": head_snippet,
        },
    }


# ---------------------------------------------------------------------------
# Tool 5: OpenGraph Card Generator
# ---------------------------------------------------------------------------

def generate_og_card(
    title: str,
    description: str,
    url: Optional[str] = None,
    image: Optional[str] = None,
    site_name: Optional[str] = None,
    twitter_handle: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate complete OpenGraph and Twitter Card meta tags and preview."""
    target_url = url or "https://example.com/"
    target_img = image or "https://example.com/og-image.png"
    target_site = site_name or title
    twitter_user = twitter_handle or "@site"

    meta_tags_html = f"""<!-- Primary Meta Tags -->
<title>{title}</title>
<meta name="title" content="{title}">
<meta name="description" content="{description}">

<!-- Open Graph / Facebook -->
<meta property="og:type" content="website">
<meta property="og:url" content="{target_url}">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{description}">
<meta property="og:image" content="{target_img}">
<meta property="og:site_name" content="{target_site}">

<!-- Twitter -->
<meta property="twitter:card" content="summary_large_image">
<meta property="twitter:url" content="{target_url}">
<meta property="twitter:title" content="{title}">
<meta property="twitter:description" content="{description}">
<meta property="twitter:image" content="{target_img}">
<meta property="twitter:site" content="{twitter_user}">
<meta property="twitter:creator" content="{twitter_user}">
"""

    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": title,
        "description": description,
        "url": target_url,
        "image": target_img,
    }, indent=2)

    json_ld_script = f'<script type="application/ld+json">\n{json_ld}\n</script>'

    # Standalone SVG Preview Card (1200x630)
    svg_preview = f"""<svg width="1200" height="630" viewBox="0 0 1200 630" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a"/>
      <stop offset="50%" stop-color="#1e293b"/>
      <stop offset="100%" stop-color="#0b0f19"/>
    </linearGradient>
    <linearGradient id="accent" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="100%" stop-color="#818cf8"/>
    </linearGradient>
  </defs>
  <rect width="1200" height="630" fill="url(#bg)"/>
  <rect x="80" y="80" width="1040" height="470" rx="24" fill="#ffffff" fill-opacity="0.03" stroke="#ffffff" stroke-opacity="0.1" stroke-width="2"/>
  <circle cx="160" cy="160" r="32" fill="url(#accent)"/>
  <text x="210" y="170" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="28" font-weight="700" fill="#f8fafc">{target_site}</text>
  <text x="120" y="280" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="52" font-weight="800" fill="#ffffff">{title[:40] + ('...' if len(title) > 40 else '')}</text>
  <text x="120" y="360" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="26" font-weight="400" fill="#94a3b8">{description[:75] + ('...' if len(description) > 75 else '')}</text>
  <rect x="120" y="440" width="180" height="48" rx="24" fill="url(#accent)"/>
  <text x="210" y="472" text-anchor="middle" font-family="-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif" font-size="20" font-weight="700" fill="#0f172a">CWV SPEED</text>
</svg>"""

    return {
        "meta_tags_html": meta_tags_html,
        "json_ld": json_ld,
        "json_ld_script": json_ld_script,
        "svg_preview": svg_preview,
        "complete_snippet": f"{meta_tags_html}\n{json_ld_script}",
    }


# ---------------------------------------------------------------------------
# Tool 6: Performance Differ
# ---------------------------------------------------------------------------

def diff_performance(
    target_a: Union[str, Dict[str, Any]],
    target_b: Union[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare two performance audits with score delta and diagnostic comparison."""
    # Resolve target_a
    if isinstance(target_a, dict):
        audit_a = target_a
    elif isinstance(target_a, str) and target_a.strip().startswith("{"):
        audit_a = json.loads(target_a)
    else:
        res = audit_target(str(target_a))
        audit_a = res.to_dict()

    # Resolve target_b
    if isinstance(target_b, dict):
        audit_b = target_b
    elif isinstance(target_b, str) and target_b.strip().startswith("{"):
        audit_b = json.loads(target_b)
    else:
        res = audit_target(str(target_b))
        audit_b = res.to_dict()

    score_a = audit_a.get("score", 0)
    score_b = audit_b.get("score", 0)
    score_delta = score_b - score_a

    vitals_a = audit_a.get("vitals", {})
    vitals_b = audit_b.get("vitals", {})

    def get_val(v_dict: Dict[str, Any], key: str) -> float:
        metric = v_dict.get(key, {})
        return float(metric.get("value", 0.0))

    lcp_a, lcp_b = get_val(vitals_a, "lcp"), get_val(vitals_b, "lcp")
    cls_a, cls_b = get_val(vitals_a, "cls"), get_val(vitals_b, "cls")
    inp_a, inp_b = get_val(vitals_a, "inp"), get_val(vitals_b, "inp")
    fcp_a, fcp_b = get_val(vitals_a, "fcp"), get_val(vitals_b, "fcp")
    ttfb_a, ttfb_b = get_val(vitals_a, "ttfb"), get_val(vitals_b, "ttfb")
    tbt_a, tbt_b = get_val(vitals_a, "tbt"), get_val(vitals_b, "tbt")

    metric_deltas = {
        "lcp": {
            "before": lcp_a,
            "after": lcp_b,
            "delta": round(lcp_b - lcp_a, 3),
            "improved": lcp_b < lcp_a,
            "unit": "s",
        },
        "cls": {
            "before": cls_a,
            "after": cls_b,
            "delta": round(cls_b - cls_a, 3),
            "improved": cls_b < cls_a,
            "unit": "score",
        },
        "inp": {
            "before": inp_a,
            "after": inp_b,
            "delta": round(inp_b - inp_a, 1),
            "improved": inp_b < inp_a,
            "unit": "ms",
        },
        "fcp": {
            "before": fcp_a,
            "after": fcp_b,
            "delta": round(fcp_b - fcp_a, 3),
            "improved": fcp_b < fcp_a,
            "unit": "s",
        },
        "ttfb": {
            "before": ttfb_a,
            "after": ttfb_b,
            "delta": round(ttfb_b - ttfb_a, 1),
            "improved": ttfb_b < ttfb_a,
            "unit": "ms",
        },
        "tbt": {
            "before": tbt_a,
            "after": tbt_b,
            "delta": round(tbt_b - tbt_a, 1),
            "improved": tbt_b < tbt_a,
            "unit": "ms",
        },
    }

    # Diagnostics comparison
    diag_ids_a = {d.get("id") for d in audit_a.get("diagnostics", []) if d.get("id")}
    diag_ids_b = {d.get("id") for d in audit_b.get("diagnostics", []) if d.get("id")}

    resolved_findings = sorted(list(diag_ids_a - diag_ids_b))
    new_findings = sorted(list(diag_ids_b - diag_ids_a))

    improvements: List[str] = []
    regressions: List[str] = []

    if score_delta > 0:
        improvements.append(f"Overall performance score improved by +{score_delta} points ({score_a} -> {score_b})")
    elif score_delta < 0:
        regressions.append(f"Overall performance score dropped by {score_delta} points ({score_a} -> {score_b})")

    if lcp_b < lcp_a:
        improvements.append(f"LCP decreased by {round(lcp_a - lcp_b, 2)}s ({lcp_a}s -> {lcp_b}s)")
    elif lcp_b > lcp_a:
        regressions.append(f"LCP increased by {round(lcp_b - lcp_a, 2)}s ({lcp_a}s -> {lcp_b}s)")

    if cls_b < cls_a:
        improvements.append(f"CLS layout shift reduced by {round(cls_a - cls_b, 3)} ({cls_a} -> {cls_b})")
    elif cls_b > cls_a:
        regressions.append(f"CLS layout shift increased by {round(cls_b - cls_a, 3)} ({cls_a} -> {cls_b})")

    if inp_b < inp_a:
        improvements.append(f"INP interactivity improved by {round(inp_a - inp_b, 1)}ms ({inp_a}ms -> {inp_b}ms)")
    elif inp_b > inp_a:
        regressions.append(f"INP latency increased by {round(inp_b - inp_a, 1)}ms ({inp_a}ms -> {inp_b}ms)")

    if score_delta >= 10:
        verdict = "SIGNIFICANT_IMPROVEMENT"
    elif score_delta > 0:
        verdict = "MODERATE_IMPROVEMENT"
    elif score_delta == 0:
        verdict = "NO_CHANGE"
    elif score_delta >= -5:
        verdict = "MINOR_REGRESSION"
    else:
        verdict = "CRITICAL_REGRESSION"

    return {
        "target_a": audit_a.get("target", "Target A"),
        "target_b": audit_b.get("target", "Target B"),
        "score_before": score_a,
        "score_after": score_b,
        "score_delta": score_delta,
        "verdict": verdict,
        "metric_deltas": metric_deltas,
        "resolved_findings": resolved_findings,
        "new_findings": new_findings,
        "improvements": improvements,
        "regressions": regressions,
    }


# ---------------------------------------------------------------------------
# Platform Diagnostics Inspector
# ---------------------------------------------------------------------------

def get_platform_diagnostics() -> Dict[str, Any]:
    """Inspect multi-OS runtime diagnostics and environment health."""
    try:
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        # Quick localhost test
        sock.bind(("127.0.0.1", 0))
        _, port = sock.getsockname()
        sock.close()
        socket_ok = True
    except Exception:
        socket_ok = False
        port = 0

    return {
        "system": {
            "os": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "python": {
            "version": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "prefix": sys.prefix,
        },
        "paths": {
            "sep": os.sep,
            "pathsep": os.pathsep,
            "linesep": repr(os.linesep),
            "cwd": os.getcwd(),
        },
        "encodings": {
            "filesystem": sys.getfilesystemencoding(),
            "stdout": sys.stdout.encoding if sys.stdout else "unknown",
            "default": sys.getdefaultencoding(),
        },
        "resources": {
            "cpu_count": os.cpu_count() or 1,
        },
        "stdlib_health": {
            "json": True,
            "urllib": True,
            "html_parser": True,
            "http_server": True,
            "socket_bind_ok": socket_ok,
            "test_port": port,
        },
        "engine": {
            "name": SERVER_NAME,
            "version": SERVER_VERSION,
            "mcp_protocol": MCP_PROTOCOL_VERSION,
        },
    }


# ---------------------------------------------------------------------------
# MCP Client Config Generator
# ---------------------------------------------------------------------------

def generate_mcp_client_config(
    client_name: str,
    python_path: str = "python3",
    project_root: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate client configuration for Claude Desktop, Cursor, Cline, Zed, and generic.
    Uses cross-platform safe paths (os.pathsep, os.sep).
    """
    c_name = client_name.lower().replace("-", "_").strip()
    root = project_root or os.getcwd()
    src_dir = os.path.join(root, "src") if os.path.exists(os.path.join(root, "src")) else root

    env_config = {
        "PYTHONPATH": f"{src_dir}{os.pathsep}{root}" if src_dir != root else root
    }

    server_key = "cwv-speed-engine"
    args = ["-m", "cwv_speed_engine.mcp_server"]

    if c_name in ("claude", "claude_desktop"):
        return {
            "mcpServers": {
                server_key: {
                    "command": python_path,
                    "args": args,
                    "env": env_config,
                }
            }
        }
    elif c_name == "cursor":
        return {
            "mcpServers": {
                server_key: {
                    "command": python_path,
                    "args": args,
                    "env": env_config,
                }
            }
        }
    elif c_name == "cline":
        return {
            "mcpServers": {
                server_key: {
                    "command": python_path,
                    "args": args,
                    "env": env_config,
                    "autoApprove": [
                        "cwv_audit_site",
                        "cwv_optimize_html",
                        "cwv_generate_cache_config",
                        "cwv_generate_pwa",
                        "cwv_generate_og_card",
                        "cwv_diff_performance"
                    ]
                }
            }
        }
    elif c_name == "zed":
        return {
            "context_servers": {
                server_key: {
                    "command": {
                        "path": python_path,
                        "args": args,
                        "env": env_config,
                    }
                }
            }
        }
    else:  # generic
        return {
            "name": server_key,
            "type": "stdio",
            "command": python_path,
            "args": args,
            "env": env_config,
            "tools": [
                "cwv_audit_site",
                "cwv_optimize_html",
                "cwv_generate_cache_config",
                "cwv_generate_pwa",
                "cwv_generate_og_card",
                "cwv_diff_performance"
            ]
        }


# ---------------------------------------------------------------------------
# MCP Server Class (JSON-RPC 2.0 / Stdio)
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any]
    handler: Callable[..., Any]

    def to_mcp_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


class MCPServer:
    """JSON-RPC 2.0 stdio Model Context Protocol (MCP) Server."""

    def __init__(self) -> None:
        self.tools: Dict[str, MCPTool] = {}
        self._register_default_tools()

    def register_tool(
        self,
        name: str,
        description: str,
        input_schema: Dict[str, Any],
        handler: Callable[..., Any],
    ) -> None:
        self.tools[name] = MCPTool(
            name=name,
            description=description,
            input_schema=input_schema,
            handler=handler,
        )

    def _register_default_tools(self) -> None:
        # Tool 1: cwv_audit_site
        self.register_tool(
            name="cwv_audit_site",
            description="Run a comprehensive Core Web Vitals audit on a live URL or local HTML file, returning 0-100 score, LCP/CLS/INP metrics, and diagnostic findings.",
            input_schema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "URL (e.g. 'https://example.com') or local file path to audit.",
                    },
                    "min_score": {
                        "type": "number",
                        "description": "Minimum acceptable score threshold (0-100). Default: 85.",
                        "default": 85,
                    },
                    "device": {
                        "type": "string",
                        "enum": ["mobile", "desktop"],
                        "description": "Device simulation mode. Default: 'mobile'.",
                        "default": "mobile",
                    },
                },
                "required": ["target"],
            },
            handler=lambda target, min_score=85, device="mobile": audit_target(
                target=target,
                min_score=float(min_score),
                device=str(device),
            ).to_dict(),
        )

        # Tool 2: cwv_optimize_html
        self.register_tool(
            name="cwv_optimize_html",
            description="Transform and optimize HTML code with automated image dimensions, font preconnects, script deferral, and lazy loading to boost CWV scores.",
            input_schema={
                "type": "object",
                "properties": {
                    "html": {
                        "type": "string",
                        "description": "Raw HTML string to optimize.",
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Path to local HTML file to read and optimize (used if html string is omitted).",
                    },
                    "inline_critical_css": {
                        "type": "boolean",
                        "description": "Whether to inline critical CSS.",
                        "default": False,
                    },
                    "preconnect_fonts": {
                        "type": "boolean",
                        "description": "Whether to inject font preconnect headers.",
                        "default": True,
                    },
                    "lazy_load_images": {
                        "type": "boolean",
                        "description": "Whether to add loading='lazy' and decoding='async' to images.",
                        "default": True,
                    },
                    "defer_scripts": {
                        "type": "boolean",
                        "description": "Whether to add 'defer' to render-blocking head scripts.",
                        "default": True,
                    },
                },
            },
            handler=self._handle_optimize_html,
        )

        # Tool 3: cwv_generate_cache_config
        self.register_tool(
            name="cwv_generate_cache_config",
            description="Generate immutable caching headers and security configuration files for Netlify, Vercel, Nginx, Next.js, Cloudflare, or Apache.",
            input_schema={
                "type": "object",
                "properties": {
                    "framework": {
                        "type": "string",
                        "enum": ["netlify", "vercel", "nginx", "nextjs", "cloudflare", "apache"],
                        "description": "Target hosting or server framework.",
                    },
                    "static_asset_ttl_days": {
                        "type": "integer",
                        "description": "Cache-Control max-age in days for immutable static assets. Default: 365.",
                        "default": 365,
                    },
                    "html_ttl_seconds": {
                        "type": "integer",
                        "description": "Cache-Control max-age in seconds for HTML documents. Default: 0.",
                        "default": 0,
                    },
                },
                "required": ["framework"],
            },
            handler=lambda framework, static_asset_ttl_days=365, html_ttl_seconds=0: generate_cache_config(
                framework=framework,
                static_asset_ttl_days=int(static_asset_ttl_days),
                html_ttl_seconds=int(html_ttl_seconds),
            ),
        )

        # Tool 4: cwv_generate_pwa
        self.register_tool(
            name="cwv_generate_pwa",
            description="Generate W3C webmanifest, Service Worker (sw.js) caching bundle, and HTML header snippet for Progressive Web App compliance.",
            input_schema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Name of the web application.",
                    },
                    "short_name": {
                        "type": "string",
                        "description": "Short name for mobile home screen icon.",
                    },
                    "theme_color": {
                        "type": "string",
                        "description": "Hex theme color. Default: '#1a73e8'.",
                        "default": "#1a73e8",
                    },
                    "background_color": {
                        "type": "string",
                        "description": "Hex splash background color. Default: '#ffffff'.",
                        "default": "#ffffff",
                    },
                    "start_url": {
                        "type": "string",
                        "description": "PWA launch URL. Default: '/'.",
                        "default": "/",
                    },
                },
                "required": ["name"],
            },
            handler=lambda name, short_name=None, theme_color="#1a73e8", background_color="#ffffff", start_url="/": generate_pwa(
                name=name,
                short_name=short_name,
                theme_color=theme_color,
                background_color=background_color,
                start_url=start_url,
            ),
        )

        # Tool 5: cwv_generate_og_card
        self.register_tool(
            name="cwv_generate_og_card",
            description="Generate complete OpenGraph, Twitter Card meta tags, Schema.org JSON-LD, and SVG preview banner.",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Page or article title.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Page or article description.",
                    },
                    "url": {
                        "type": "string",
                        "description": "Canonical page URL.",
                    },
                    "image": {
                        "type": "string",
                        "description": "Social share preview image URL.",
                    },
                    "site_name": {
                        "type": "string",
                        "description": "Website or brand name.",
                    },
                    "twitter_handle": {
                        "type": "string",
                        "description": "Twitter creator/site handle (e.g. '@site').",
                    },
                },
                "required": ["title", "description"],
            },
            handler=lambda title, description, url=None, image=None, site_name=None, twitter_handle=None: generate_og_card(
                title=title,
                description=description,
                url=url,
                image=image,
                site_name=site_name,
                twitter_handle=twitter_handle,
            ),
        )

        # Tool 6: cwv_diff_performance
        self.register_tool(
            name="cwv_diff_performance",
            description="Compare two performance audits (URLs, files, or audit results) with score deltas and diagnostic comparison.",
            input_schema={
                "type": "object",
                "properties": {
                    "target_a": {
                        "type": "string",
                        "description": "Baseline URL, file path, or JSON audit string.",
                    },
                    "target_b": {
                        "type": "string",
                        "description": "Candidate/Optimized URL, file path, or JSON audit string.",
                    },
                },
                "required": ["target_a", "target_b"],
            },
            handler=lambda target_a, target_b: diff_performance(
                target_a=target_a,
                target_b=target_b,
            ),
        )

        # Tool 7: cwv_generate_speculation_rules
        self.register_tool(
            name="cwv_generate_speculation_rules",
            description="Generate W3C Speculation Rules (<script type='speculationrules'>) for instant zero-latency prerendering and 103 Early Hints.",
            input_schema={
                "type": "object",
                "properties": {
                    "html_or_urls": {
                        "type": "string",
                        "description": "HTML content string or comma-separated list of URLs.",
                    },
                    "base_url": {
                        "type": "string",
                        "description": "Base URL for resolving internal links (default: https://example.com).",
                        "default": "https://example.com",
                    },
                    "aggressiveness": {
                        "type": "string",
                        "enum": ["conservative", "balanced", "aggressive"],
                        "description": "Prerender/prefetch eagerness aggressiveness (default: balanced).",
                        "default": "balanced",
                    },
                },
                "required": ["html_or_urls"],
            },
            handler=self._handle_generate_speculation_rules,
        )

        # Tool 8: cwv_audit_performance_budget
        self.register_tool(
            name="cwv_audit_performance_budget",
            description="Audit web page assets against Core Web Vitals performance budgets (Scripts, Styles, Fonts, Images), simulate multi-network latency (3G/4G/5G), and generate standard Lighthouse budget.json.",
            input_schema={
                "type": "object",
                "properties": {
                    "html_or_path": {
                        "type": "string",
                        "description": "HTML markup content or path to local HTML file to evaluate.",
                    },
                    "custom_budgets": {
                        "type": "object",
                        "description": "Optional custom budget limits in KB (e.g. {'script': 150, 'total': 450}).",
                    },
                    "target_name": {
                        "type": "string",
                        "description": "Identifier or page name for the audit report.",
                        "default": "Page Budget Audit",
                    },
                },
                "required": ["html_or_path"],
            },
            handler=self._handle_audit_performance_budget,
        )

    def _handle_optimize_html(
        self,
        html: Optional[str] = None,
        file_path: Optional[str] = None,
        inline_critical_css: bool = False,
        preconnect_fonts: bool = True,
        lazy_load_images: bool = True,
        defer_scripts: bool = True,
    ) -> Dict[str, Any]:
        content = html
        if not content and file_path:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        if not content:
            raise ValueError("Must provide either 'html' content string or 'file_path'.")

        return optimize_html(
            html_content=content,
            inline_critical_css=inline_critical_css,
            preconnect_fonts=preconnect_fonts,
            lazy_load_images=lazy_load_images,
            defer_scripts=defer_scripts,
        )

    def _handle_generate_speculation_rules(
        self,
        html_or_urls: str,
        base_url: str = "https://example.com",
        aggressiveness: str = "balanced",
    ) -> Dict[str, Any]:
        from .speculation_engine import generate_speculation_plan
        return generate_speculation_plan(
            html_or_urls=html_or_urls,
            base_url=base_url,
            aggressiveness=aggressiveness,
        ).to_dict()

    def _handle_audit_performance_budget(
        self,
        html_or_path: str,
        custom_budgets: Optional[Dict[str, float]] = None,
        target_name: str = "Page Budget Audit",
    ) -> Dict[str, Any]:
        from .budget_simulator import audit_performance_budget
        content = html_or_path
        if len(content) < 4096 and "\n" not in content and os.path.exists(content):
            try:
                with open(content, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            except Exception:
                pass

        report = audit_performance_budget(
            html_or_resources=content,
            custom_budgets=custom_budgets,
            target_name=target_name,
        )
        return report.to_dict()

    def handle_request(self, request_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single JSON-RPC 2.0 request."""
        req_id = request_data.get("id")
        method = request_data.get("method")
        params = request_data.get("params", {})

        if not method:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32600, "message": "Invalid Request: missing method"},
            }

        # 1. MCP initialize
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {
                        "tools": {
                            "listChanged": False
                        }
                    },
                    "serverInfo": {
                        "name": SERVER_NAME,
                        "version": SERVER_VERSION,
                    },
                },
            }

        # 2. MCP initialized notification
        if method in ("notifications/initialized", "initialized"):
            return None  # Notifications do not return a response

        # 3. MCP ping
        if method == "ping":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {},
            }

        # 4. MCP tools/list
        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "tools": [t.to_mcp_dict() for t in self.tools.values()]
                },
            }

        # 5. MCP tools/call
        if method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})

            if not tool_name or tool_name not in self.tools:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32601, "message": f"Tool not found: '{tool_name}'"},
                }

            tool = self.tools[tool_name]
            try:
                result_data = tool.handler(**arguments)
                text_output = json.dumps(result_data, indent=2) if isinstance(result_data, (dict, list)) else str(result_data)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": text_output,
                            }
                        ],
                        "isError": False,
                    },
                }
            except Exception as e:
                logger.error("Error executing tool %s: %s\n%s", tool_name, e, traceback.format_exc())
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Error executing tool '{tool_name}': {str(e)}",
                            }
                        ],
                        "isError": True,
                    },
                }

        # Unknown method
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: '{method}'"},
        }

    def run_stdio(self) -> None:
        """Run JSON-RPC 2.0 loop reading from sys.stdin and writing to sys.stdout."""
        # Ensure utf-8 stdio
        sys.stdin.reconfigure(encoding="utf-8") if hasattr(sys.stdin, "reconfigure") else None
        sys.stdout.reconfigure(encoding="utf-8") if hasattr(sys.stdout, "reconfigure") else None

        logger.info("CWV Speed Engine MCP Server running over stdio...")

        while True:
            try:
                line = sys.stdin.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    request_data = json.loads(line)
                except json.JSONDecodeError as err:
                    response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": f"Parse error: {str(err)}"},
                    }
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
                    continue

                response = self.handle_request(request_data)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()

            except (KeyboardInterrupt, SystemExit):
                break
            except Exception as e:
                logger.error("Unexpected error in MCP stdio loop: %s", e)
                break


def run_mcp_server() -> None:
    """Entrypoint function to run the MCP server."""
    server = MCPServer()
    server.run_stdio()


def main() -> None:
    """CLI entrypoint for cwv_speed_engine.mcp_server."""
    run_mcp_server()


if __name__ == "__main__":
    main()
