"""
CWV Speed Studio UI Server (design influenced by Material 3) for cwv-speed-engine.
Zero-dependency, high-performance ThreadingHTTPServer providing REST APIs and
interactive web interface for Core Web Vitals auditing, automated HTML transformation,
PWA generation, caching headers, performance diffing, and AI Agent MCP hub.
"""

from __future__ import annotations

import argparse
import http.server
import io
import json
import logging
import os
import pathlib
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
import zipfile
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger("cwv_speed_engine.ui_server")

# Server start timestamp for uptime tracking
SERVER_START_TIME = time.time()


# ==============================================================================
# Core Web Vitals Auditing & Simulation Engine
# ==============================================================================

def audit_html_content(html: str, device: str = "mobile", url_context: str = "") -> Dict[str, Any]:
    """
    Performs a deterministic, standards-based Core Web Vitals audit directly
    on HTML content, checking for Google 2024+ thresholds.
    """
    if not html:
        return {
            "score": 0,
            "rating": "POOR",
            "device": device,
            "metrics": {
                "lcp": {"value": 5.0, "unit": "s", "rating": "POOR", "target": "< 2.5s"},
                "cls": {"value": 0.35, "unit": "", "rating": "POOR", "target": "< 0.10"},
                "inp": {"value": 450, "unit": "ms", "rating": "POOR", "target": "< 200ms"},
                "fcp": {"value": 3.2, "unit": "s", "rating": "POOR", "target": "< 1.8s"},
                "ttfb": {"value": 1200, "unit": "ms", "rating": "POOR", "target": "< 800ms"},
                "speed_index": {"value": 4.8, "unit": "s", "rating": "POOR", "target": "< 3.4s"},
            },
            "diagnostics": [],
            "summary": {"passed": 0, "warning": 0, "critical": 1, "total": 1},
        }

    diagnostics: List[Dict[str, Any]] = []

    # Factors affecting metrics
    lcp_penalties = 0.0
    cls_penalties = 0.0
    inp_penalties = 0
    fcp_penalties = 0.0
    ttfb_penalties = 0

    # 1. Images missing width and height attributes (CLS-01)
    img_tags = re.findall(r"<img\b([^>]*)>", html, re.IGNORECASE)
    missing_dims = 0
    missing_lazy = 0
    has_fetchpriority = False

    for idx, attrs in enumerate(img_tags):
        has_width = bool(re.search(r'\bwidth\s*=\s*["\']?\d+', attrs, re.IGNORECASE))
        has_height = bool(re.search(r'\bheight\s*=\s*["\']?\d+', attrs, re.IGNORECASE))
        has_aspect_ratio = "aspect-ratio" in attrs.lower() or "style" in attrs.lower() and "aspect-ratio" in attrs

        if not (has_width and has_height) and not has_aspect_ratio:
            missing_dims += 1

        if idx > 0 and 'loading="lazy"' not in attrs.lower() and "loading='lazy'" not in attrs.lower():
            missing_lazy += 1

        if 'fetchpriority="high"' in attrs.lower() or "fetchpriority='high'" in attrs.lower():
            has_fetchpriority = True

    if missing_dims > 0:
        cls_impact = min(0.35, missing_dims * 0.06)
        cls_penalties += cls_impact
        diagnostics.append({
            "rule_id": "CLS-01",
            "category": "Cumulative Layout Shift",
            "title": f"Image elements missing explicit width and height ({missing_dims} found)",
            "description": "Images without explicit dimensions cause layout reflows and unexpected shifts as images load.",
            "severity": "CRITICAL" if missing_dims > 2 else "WARNING",
            "impact": f"+{cls_impact:.3f} CLS",
            "recommendation": "Add width and height attributes or CSS aspect-ratio to all <img> elements.",
            "passed": False,
        })
    else:
        diagnostics.append({
            "rule_id": "CLS-01",
            "category": "Cumulative Layout Shift",
            "title": "All images have explicit dimensions",
            "description": "Image layout boxes are reserved prior to loading, preventing layout shifts.",
            "severity": "PASS",
            "impact": "0 CLS shift",
            "recommendation": "Maintain aspect-ratio and explicit dimensions for responsive images.",
            "passed": True,
        })

    # 2. Font Display Swap & Preconnect (CLS-02 & LCP-03)
    has_fonts = bool(re.search(r"fonts\.(googleapis|gstatic)\.com|@font-face", html, re.IGNORECASE))
    has_font_swap = "display=swap" in html or bool(re.search(r"font-display:\s*swap", html, re.IGNORECASE))
    has_font_preconnect = bool(re.search(r'<link[^>]*rel=["\']preconnect["\'][^>]*fonts\.', html, re.IGNORECASE))

    if has_fonts and not has_font_swap:
        cls_penalties += 0.08
        fcp_penalties += 0.3
        diagnostics.append({
            "rule_id": "CLS-02",
            "category": "Web Fonts",
            "title": "Web fonts missing font-display: swap",
            "description": "Without font-display: swap, text remains invisible (FOIT) until custom fonts load, then triggers layout shift.",
            "severity": "WARNING",
            "impact": "+0.080 CLS, +300ms FCP",
            "recommendation": "Append &display=swap to Google Fonts URLs or declare font-display: swap in @font-face rules.",
            "passed": False,
        })
    elif has_fonts:
        diagnostics.append({
            "rule_id": "CLS-02",
            "category": "Web Fonts",
            "title": "Font display swap configured properly",
            "description": "Fallback fonts render immediately, preventing Flash of Invisible Text.",
            "severity": "PASS",
            "impact": "Zero FOIT penalty",
            "recommendation": "Use size-adjust in font-face for ultra-tight fallback alignment.",
            "passed": True,
        })

    if has_fonts and not has_font_preconnect:
        lcp_penalties += 0.4
        fcp_penalties += 0.35
        diagnostics.append({
            "rule_id": "LCP-03",
            "category": "Resource Delivery",
            "title": "Missing preconnect for font CDN origins",
            "description": "Connecting early to third-party font hosts eliminates round-trip connection overhead.",
            "severity": "WARNING",
            "impact": "+400ms LCP, +350ms FCP",
            "recommendation": 'Add <link rel="preconnect" href="https://fonts.googleapis.com"> and <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin> to <head>.',
            "passed": False,
        })

    # 3. Synchronous / Render-blocking Scripts in <head> (INP-01 & LCP-02)
    head_match = re.search(r"<head\b[^>]*>(.*?)</head>", html, re.IGNORECASE | re.DOTALL)
    head_content = head_match.group(1) if head_match else ""

    scripts_in_head = re.findall(r"<script\b([^>]*)>", head_content, re.IGNORECASE)
    blocking_scripts = 0
    for s_attrs in scripts_in_head:
        if "src=" in s_attrs.lower():
            if "defer" not in s_attrs.lower() and "async" not in s_attrs.lower() and 'type="module"' not in s_attrs.lower():
                blocking_scripts += 1

    if blocking_scripts > 0:
        inp_penalties += blocking_scripts * 80
        fcp_penalties += blocking_scripts * 0.45
        lcp_penalties += blocking_scripts * 0.40
        diagnostics.append({
            "rule_id": "INP-01",
            "category": "Interaction to Next Paint",
            "title": f"Render-blocking scripts in <head> ({blocking_scripts} found)",
            "description": "Parser-blocking synchronous scripts stop DOM construction and increase Main Thread blocking time.",
            "severity": "CRITICAL" if blocking_scripts > 1 else "WARNING",
            "impact": f"+{blocking_scripts * 80}ms INP, +{blocking_scripts * 0.4:.1f}s FCP",
            "recommendation": "Add defer or async attribute to all external script tags or migrate them to type='module'.",
            "passed": False,
        })
    else:
        diagnostics.append({
            "rule_id": "INP-01",
            "category": "Interaction to Next Paint",
            "title": "No render-blocking scripts detected in <head>",
            "description": "Scripts are non-blocking or deferred, freeing main thread for early paint.",
            "severity": "PASS",
            "impact": "Optimal Main Thread interactivity",
            "recommendation": "Keep script execution chunked under 50ms using scheduler.yield().",
            "passed": True,
        })

    # 4. Hero / LCP Image Optimization (LCP-01)
    if len(img_tags) > 0:
        if not has_fetchpriority:
            lcp_penalties += 0.6
            diagnostics.append({
                "rule_id": "LCP-01",
                "category": "Largest Contentful Paint",
                "title": "LCP Hero image missing fetchpriority='high'",
                "description": "The primary hero image should be prioritized by the browser preload scanner.",
                "severity": "WARNING",
                "impact": "+600ms LCP delay",
                "recommendation": 'Add fetchpriority="high" and loading="eager" to the above-the-fold hero image.',
                "passed": False,
            })
        else:
            diagnostics.append({
                "rule_id": "LCP-01",
                "category": "Largest Contentful Paint",
                "title": "Hero image has fetchpriority='high'",
                "description": "The browser preload scanner prioritizes hero image fetch before stylesheet execution.",
                "severity": "PASS",
                "impact": "-600ms LCP win",
                "recommendation": "Ensure responsive srcset sources provide modern WebP/AVIF formats.",
                "passed": True,
            })

    # 5. Native Lazy Loading for Below-Fold Images (LCP-04)
    if missing_lazy > 1:
        lcp_penalties += min(0.5, missing_lazy * 0.08)
        diagnostics.append({
            "rule_id": "LCP-04",
            "category": "Resource Bandwidth",
            "title": f"Below-the-fold images missing loading='lazy' ({missing_lazy} found)",
            "description": "Downloading off-screen images competes with critical above-the-fold resources for network bandwidth.",
            "severity": "INFO",
            "impact": f"+{min(0.5, missing_lazy * 0.08):.2f}s Network Contention",
            "recommendation": 'Add loading="lazy" and decoding="async" to all non-hero images.',
            "passed": False,
        })

    # 6. Progressive Web App & Offline readiness (PWA-01)
    has_manifest = bool(re.search(r'<link[^>]*rel=["\']manifest["\']', html, re.IGNORECASE))
    has_sw = bool(re.search(r"serviceWorker\.register|navigator\.serviceWorker", html, re.IGNORECASE))

    if not has_manifest:
        diagnostics.append({
            "rule_id": "PWA-01",
            "category": "Progressive Web App",
            "title": "Missing Web App Manifest (<link rel='manifest'>)",
            "description": "Web app manifest enables app installation, splash screens, theme colors, and standalone display.",
            "severity": "INFO",
            "impact": "Installability & Offline caching",
            "recommendation": "Link a site.webmanifest file in the <head> with app icons and theme configuration.",
            "passed": False,
        })
    else:
        diagnostics.append({
            "rule_id": "PWA-01",
            "category": "Progressive Web App",
            "title": "Web App Manifest linked properly",
            "description": "PWA manifest is referenced in <head>.",
            "severity": "PASS",
            "impact": "Ready for installation",
            "recommendation": "Verify service worker precaching and background sync.",
            "passed": True,
        })

    # 7. OpenGraph and Social Discovery (OG-01)
    has_og_title = bool(re.search(r'<meta[^>]*property=["\']og:title["\']', html, re.IGNORECASE))
    has_og_image = bool(re.search(r'<meta[^>]*property=["\']og:image["\']', html, re.IGNORECASE))

    if not (has_og_title and has_og_image):
        diagnostics.append({
            "rule_id": "OG-01",
            "category": "Social & Search Discovery",
            "title": "Incomplete OpenGraph / Social Meta Tags",
            "description": "Missing og:title, og:image, or twitter:card reduces CTR on Google SERP and social channels.",
            "severity": "INFO",
            "impact": "Rich snippet preview",
            "recommendation": "Add OpenGraph meta tags for title, description, image, and canonical URL.",
            "passed": False,
        })

    # Calculate baseline values based on device
    is_mobile = device.lower() == "mobile"
    base_lcp = 1.6 if is_mobile else 1.1
    base_cls = 0.015
    base_inp = 85 if is_mobile else 45
    base_fcp = 1.1 if is_mobile else 0.7
    base_ttfb = 220 if is_mobile else 140

    calc_lcp = round(base_lcp + lcp_penalties, 2)
    calc_cls = round(base_cls + cls_penalties, 3)
    calc_inp = int(base_inp + inp_penalties)
    calc_fcp = round(base_fcp + fcp_penalties, 2)
    calc_ttfb = int(base_ttfb + ttfb_penalties)
    calc_speed_index = round(calc_fcp * 1.35 + calc_lcp * 0.4, 2)

    # Rate individual metrics
    def rate_lcp(v: float) -> str:
        return "GOOD" if v <= 2.5 else ("NEEDS_IMPROVEMENT" if v <= 4.0 else "POOR")

    def rate_cls(v: float) -> str:
        return "GOOD" if v <= 0.10 else ("NEEDS_IMPROVEMENT" if v <= 0.25 else "POOR")

    def rate_inp(v: int) -> str:
        return "GOOD" if v <= 200 else ("NEEDS_IMPROVEMENT" if v <= 500 else "POOR")

    def rate_fcp(v: float) -> str:
        return "GOOD" if v <= 1.8 else ("NEEDS_IMPROVEMENT" if v <= 3.0 else "POOR")

    def rate_ttfb(v: int) -> str:
        return "GOOD" if v <= 800 else ("NEEDS_IMPROVEMENT" if v <= 1800 else "POOR")

    # Overall Score calculation (0-100)
    score_pts = 100
    if calc_lcp > 2.5:
        score_pts -= min(35, int((calc_lcp - 2.5) * 16))
    if calc_cls > 0.10:
        score_pts -= min(35, int((calc_cls - 0.10) * 150))
    if calc_inp > 200:
        score_pts -= min(30, int((calc_inp - 200) / 12))
    if calc_fcp > 1.8:
        score_pts -= min(15, int((calc_fcp - 1.8) * 10))

    final_score = max(5, min(100, score_pts))
    rating = "GOOD" if final_score >= 90 else ("NEEDS_IMPROVEMENT" if final_score >= 50 else "POOR")

    passed_count = sum(1 for d in diagnostics if d.get("passed", False))
    critical_count = sum(1 for d in diagnostics if d.get("severity") == "CRITICAL")
    warning_count = sum(1 for d in diagnostics if d.get("severity") == "WARNING")
    info_count = sum(1 for d in diagnostics if d.get("severity") == "INFO")

    return {
        "score": final_score,
        "rating": rating,
        "device": device,
        "url": url_context,
        "metrics": {
            "lcp": {"value": calc_lcp, "unit": "s", "rating": rate_lcp(calc_lcp), "target": "< 2.5s"},
            "cls": {"value": calc_cls, "unit": "", "rating": rate_cls(calc_cls), "target": "< 0.10"},
            "inp": {"value": calc_inp, "unit": "ms", "rating": rate_inp(calc_inp), "target": "< 200ms"},
            "fcp": {"value": calc_fcp, "unit": "s", "rating": rate_fcp(calc_fcp), "target": "< 1.8s"},
            "ttfb": {"value": calc_ttfb, "unit": "ms", "rating": rate_ttfb(calc_ttfb), "target": "< 800ms"},
            "speed_index": {"value": calc_speed_index, "unit": "s", "rating": rate_fcp(calc_speed_index), "target": "< 3.4s"},
        },
        "diagnostics": diagnostics,
        "summary": {
            "passed": passed_count,
            "warning": warning_count,
            "critical": critical_count,
            "info": info_count,
            "total": len(diagnostics),
        },
        "timestamp": time.time(),
    }


def audit_url(url: str, device: str = "mobile", timeout: int = 10) -> Dict[str, Any]:
    """
    Fetches a live URL, measures TTFB, inspects response headers,
    and runs the CWV audit on the returned HTML.
    """
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 CWVSpeedStudio/1.0"
            if device.lower() == "mobile"
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 CWVSpeedStudio/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }

    req = urllib.request.Request(url, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            t1 = time.time()
            ttfb_ms = int((t1 - t0) * 1000)
            raw_data = response.read()

            content_encoding = response.headers.get("Content-Encoding", "").lower()
            if content_encoding == "gzip":
                import gzip
                try:
                    raw_data = gzip.decompress(raw_data)
                except Exception:
                    pass
            elif content_encoding == "deflate":
                import zlib
                try:
                    raw_data = zlib.decompress(raw_data)
                except Exception:
                    pass

            charset = "utf-8"
            content_type = response.headers.get("Content-Type", "")
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()

            html = raw_data.decode(charset, errors="replace")
            res = audit_html_content(html, device=device, url_context=url)

            # Override measured TTFB
            res["metrics"]["ttfb"]["value"] = ttfb_ms
            res["metrics"]["ttfb"]["rating"] = "GOOD" if ttfb_ms <= 800 else ("NEEDS_IMPROVEMENT" if ttfb_ms <= 1800 else "POOR")
            res["response_headers"] = dict(response.headers)
            return res

    except Exception as e:
        logger.warning(f"Error fetching URL {url}: {e}")
        # Return realistic fallback audit for preview / mock environments
        mock_html = f"<!DOCTYPE html><html><head><title>Audited Site: {url}</title></head><body><h1>Audited Site</h1><p>Failed to connect: {e}</p></body></html>"
        res = audit_html_content(mock_html, device=device, url_context=url)
        res["fetch_error"] = str(e)
        return res


# ==============================================================================
# Automated HTML Speed Transformer
# ==============================================================================

def transform_html(html: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Applies speed optimizations to HTML:
    - Injects missing image dimensions & aspect-ratio
    - Injects loading="lazy" & decoding="async"
    - Injects font preconnects & display=swap
    - Defers blocking scripts in <head>
    - Preloads first hero image with fetchpriority="high"
    - Inlines critical CSS resets
    - Cleans up whitespace & comments
    """
    if not html:
        return {"optimized_html": "", "stats": {}, "changes": []}

    opt = {
        "dimensions": True,
        "lazy_loading": True,
        "font_preconnect": True,
        "defer_scripts": True,
        "preload_hero": True,
        "critical_css": True,
        "minify": False,
    }
    if options:
        opt.update(options)

    changes: List[str] = []
    working_html = html

    # 1. Font Preconnect & display=swap
    if opt.get("font_preconnect"):
        if "fonts.googleapis.com" in working_html and "display=swap" not in working_html:
            working_html = re.sub(
                r'(fonts\.googleapis\.com/css2?\?[^"\'\s>]+)',
                lambda m: m.group(1) + ("&amp;display=swap" if "&amp;" in m.group(1) else "&display=swap"),
                working_html
            )
            changes.append("Appended &display=swap to Google Fonts links to eliminate text flash (FOIT)")

        preconnect_tags = (
            '    <link rel="preconnect" href="https://fonts.googleapis.com">\n'
            '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        )
        if "fonts.googleapis.com" in working_html and 'rel="preconnect"' not in working_html:
            if "<head>" in working_html:
                working_html = working_html.replace("<head>", f"<head>\n{preconnect_tags}", 1)
            elif "<head " in working_html:
                working_html = re.sub(r"(<head[^>]*>)", rf"\1\n{preconnect_tags}", working_html, count=1)
            changes.append("Injected high-priority font preconnect hints for Google Fonts and GStatic")

    # 2. Defer Render-Blocking Scripts
    if opt.get("defer_scripts"):
        def defer_script_tag(match: re.Match) -> str:
            tag = match.group(0)
            if "src=" in tag.lower() and "defer" not in tag.lower() and "async" not in tag.lower() and 'type="module"' not in tag.lower():
                tag = re.sub(r"<script\b", '<script defer', tag, count=1, flags=re.IGNORECASE)
                return tag
            return tag

        # Apply inside <head>
        head_match = re.search(r"(<head\b[^>]*>)(.*?)(</head>)", working_html, re.IGNORECASE | re.DOTALL)
        if head_match:
            head_start, head_body, head_end = head_match.group(1), head_match.group(2), head_match.group(3)
            new_head_body = re.sub(r"<script\b[^>]*>", defer_script_tag, head_body, flags=re.IGNORECASE)
            if new_head_body != head_body:
                working_html = working_html[:head_match.start()] + head_start + new_head_body + head_end + working_html[head_match.end():]
                changes.append("Added 'defer' attribute to external scripts in <head> to unblock main thread")

    # 3. Image Dimensions & Aspect-Ratio + Lazy Loading + Hero Preload
    first_img_src = None
    img_counter = 0

    def transform_img_tag(match: re.Match) -> str:
        nonlocal first_img_src, img_counter
        tag = match.group(0)
        img_counter += 1

        src_match = re.search(r'src=["\']([^"\']+)["\']', tag, re.IGNORECASE)
        src = src_match.group(1) if src_match else ""

        if img_counter == 1:
            first_img_src = src
            # Hero image: Add fetchpriority="high" and loading="eager"
            if opt.get("preload_hero"):
                if 'fetchpriority=' not in tag.lower():
                    tag = re.sub(r"<img\b", '<img fetchpriority="high"', tag, count=1, flags=re.IGNORECASE)
                if 'loading=' not in tag.lower():
                    tag = re.sub(r"<img\b", '<img loading="eager"', tag, count=1, flags=re.IGNORECASE)
        else:
            # Below-fold image: Add loading="lazy" and decoding="async"
            if opt.get("lazy_loading"):
                if 'loading=' not in tag.lower():
                    tag = re.sub(r"<img\b", '<img loading="lazy"', tag, count=1, flags=re.IGNORECASE)
                if 'decoding=' not in tag.lower():
                    tag = re.sub(r"<img\b", '<img decoding="async"', tag, count=1, flags=re.IGNORECASE)

        # Fix Missing Dimensions
        if opt.get("dimensions"):
            has_width = bool(re.search(r'\bwidth\s*=', tag, re.IGNORECASE))
            has_height = bool(re.search(r'\bheight\s*=', tag, re.IGNORECASE))
            has_style = bool(re.search(r'\bstyle\s*=', tag, re.IGNORECASE))

            if not (has_width and has_height):
                if not has_width:
                    tag = re.sub(r"<img\b", '<img width="800"', tag, count=1, flags=re.IGNORECASE)
                if not has_height:
                    tag = re.sub(r"<img\b", '<img height="500"', tag, count=1, flags=re.IGNORECASE)

        return tag

    working_html = re.sub(r"<img\b[^>]*>", transform_img_tag, working_html, flags=re.IGNORECASE)
    if img_counter > 0:
        changes.append(f"Optimized {img_counter} image(s): injected explicit dimensions, native lazy loading, and decoding='async'")

    # 4. Preload Hero Image in <head>
    if opt.get("preload_hero") and first_img_src and not first_img_src.startswith("data:"):
        preload_hero_tag = f'    <link rel="preload" as="image" href="{first_img_src}" fetchpriority="high">\n'
        if f'href="{first_img_src}"' not in working_html or 'rel="preload"' not in working_html:
            if "<head>" in working_html:
                working_html = working_html.replace("<head>", f"<head>\n{preload_hero_tag}", 1)
            elif "<head " in working_html:
                working_html = re.sub(r"(<head[^>]*>)", rf"\1\n{preload_hero_tag}", working_html, count=1)
            changes.append(f"Added high-priority preload tag for LCP hero image: {first_img_src}")

    # 5. Critical CSS Reset Injection
    if opt.get("critical_css"):
        critical_style = (
            "    <style id=\"cwv-critical-reset\">\n"
            "      img, video { max-width: 100%; height: auto; display: block; }\n"
            "      .hero-lcp { content-visibility: visible; contain-intrinsic-size: 800px 500px; }\n"
            "      .below-fold { content-visibility: auto; contain-intrinsic-size: 1px 600px; }\n"
            "    </style>\n"
        )
        if "cwv-critical-reset" not in working_html:
            if "<head>" in working_html:
                working_html = working_html.replace("<head>", f"<head>\n{critical_style}", 1)
            elif "<head " in working_html:
                working_html = re.sub(r"(<head[^>]*>)", rf"\1\n{critical_style}", working_html, count=1)
            changes.append("Injected critical CSS reset with content-visibility containment to prevent layout reflows")

    # 6. Minification (Optional)
    if opt.get("minify"):
        # Remove comments except conditional comments
        working_html = re.sub(r"<!--(?!\[if).*?-->", "", working_html, flags=re.DOTALL)
        # Collapse extra whitespace
        working_html = re.sub(r"\n\s*\n", "\n", working_html)
        changes.append("Stripped superfluous HTML comments and normalized whitespace")

    original_size = len(html.encode("utf-8"))
    optimized_size = len(working_html.encode("utf-8"))
    savings_bytes = original_size - optimized_size

    return {
        "optimized_html": working_html,
        "changes": changes,
        "stats": {
            "original_bytes": original_size,
            "optimized_bytes": optimized_size,
            "savings_bytes": savings_bytes,
            "savings_percent": round((savings_bytes / max(1, original_size)) * 100, 1),
            "changes_count": len(changes),
        },
    }


# ==============================================================================
# PWA & Service Worker Studio Generator
# ==============================================================================

def generate_pwa(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Generates production-grade PWA web manifest, service worker with chosen
    caching strategy, offline fallback HTML, and integration snippet.
    """
    cfg = {
        "name": "CWV Speed App",
        "short_name": "SpeedApp",
        "theme_color": "#1a73e8",
        "background_color": "#ffffff",
        "start_url": "/",
        "display": "standalone",
        "orientation": "portrait-primary",
        "description": "High-performance Progressive Web App optimized for 100/100 Core Web Vitals.",
        "strategy": "stale-while-revalidate",
        "scope": "/",
    }
    if config:
        cfg.update(config)

    manifest_dict = {
        "$schema": "https://json.schemastore.org/web-manifest-combined.json",
        "name": cfg["name"],
        "short_name": cfg["short_name"],
        "description": cfg["description"],
        "start_url": cfg["start_url"],
        "scope": cfg["scope"],
        "display": cfg["display"],
        "orientation": cfg["orientation"],
        "theme_color": cfg["theme_color"],
        "background_color": cfg["background_color"],
        "categories": ["utilities", "productivity"],
        "icons": [
            {
                "src": "/icons/icon-192x192.png",
                "sizes": "192x192",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/icons/icon-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "any"
            },
            {
                "src": "/icons/icon-maskable-512x512.png",
                "sizes": "512x512",
                "type": "image/png",
                "purpose": "maskable"
            }
        ],
        "shortcuts": [
            {
                "name": "Speed Audit",
                "url": "/?tab=auditor",
                "description": "Launch Core Web Vitals audit"
            },
            {
                "name": "HTML Transformer",
                "url": "/?tab=transformer",
                "description": "Transform HTML for maximum speed"
            }
        ]
    }

    sw_strategy = cfg.get("strategy", "stale-while-revalidate")
    strategy_comment = {
        "stale-while-revalidate": "Stale-While-Revalidate: Returns cached content instantly while refreshing from network in the background.",
        "cache-first": "Cache-First: Serves cached static assets immediately; falls back to network only on cache miss.",
        "network-first": "Network-First: Tries fresh network fetch first; falls back to cache when offline.",
    }.get(sw_strategy, "Stale-While-Revalidate")

    sw_code = f"""/**
 * CWV Speed Studio - Service Worker
 * Strategy: {strategy_comment}
 */

const CACHE_NAME = 'speed-engine-v1.0.0';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/offline.html',
  '/site.webmanifest'
];

// 1. Install: Precache shell assets
self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {{
      return cache.addAll(STATIC_ASSETS);
    }}).then(() => self.skipWaiting())
  );
}});

// 2. Activate: Clear legacy caches
self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys().then((keys) => {{
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    }}).then(() => self.clients.claim())
  );
}});

// 3. Fetch Handler: {sw_strategy}
self.addEventListener('fetch', (event) => {{
  const request = event.request;
  const url = new URL(request.url);

  // Skip non-GET and chrome-extension schemes
  if (request.method !== 'GET' || !url.protocol.startsWith('http')) return;

  // HTML Navigation Requests: Stale-While-Revalidate with Offline Fallback
  if (request.mode === 'navigate') {{
    event.respondWith(
      caches.open(CACHE_NAME).then(async (cache) => {{
        const cachedResponse = await cache.match(request);
        const networkFetch = fetch(request).then((networkResponse) => {{
          if (networkResponse && networkResponse.status === 200) {{
            cache.put(request, networkResponse.clone());
          }}
          return networkResponse;
        }}).catch(() => cachedResponse || caches.match('/offline.html'));

        return cachedResponse || networkFetch;
      }})
    );
    return;
  }}

  // Static Assets (CSS, JS, Fonts, Images): Cache-First
  if (url.pathname.match(/\\.(js|css|woff2|webp|avif|png|jpg|svg)$/)) {{
    event.respondWith(
      caches.match(request).then((cached) => {{
        if (cached) return cached;
        return fetch(request).then((response) => {{
          if (response && response.status === 200) {{
            const copy = response.clone();
            caches.open(CACHE_NAME).then((c) => c.put(request, copy));
          }}
          return response;
        }});
      }})
    );
    return;
  }}

  // Default: Network with Cache Fallback
  event.respondWith(
    fetch(request).catch(() => caches.match(request))
  );
}});
"""

    offline_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Offline | {cfg["name"]}</title>
  <meta name="theme-color" content="{cfg["theme_color"]}">
  <style>
    :root {{
      --google-blue: {cfg["theme_color"]};
      --google-surface: #ffffff;
      --google-text: #202124;
      --google-subtext: #5f6368;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Google Sans", sans-serif;
      background: #f8f9fa;
      color: var(--google-text);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      margin: 0;
      padding: 24px;
      box-sizing: border-box;
    }}
    .offline-card {{
      background: var(--google-surface);
      border-radius: 24px;
      padding: 40px;
      max-width: 480px;
      text-align: center;
      box-shadow: 0 4px 20px rgba(0,0,0,0.08);
      border: 1px solid #dadce0;
    }}
    .offline-icon {{
      width: 72px;
      height: 72px;
      margin-bottom: 20px;
      fill: var(--google-blue);
    }}
    h1 {{
      font-size: 24px;
      margin: 0 0 12px;
      font-weight: 600;
    }}
    p {{
      color: var(--google-subtext);
      font-size: 15px;
      line-height: 1.5;
      margin: 0 0 28px;
    }}
    .retry-btn {{
      background: var(--google-blue);
      color: #ffffff;
      border: none;
      padding: 12px 28px;
      font-size: 15px;
      font-weight: 500;
      border-radius: 9999px;
      cursor: pointer;
      transition: background 0.2s;
    }}
    .retry-btn:hover {{
      background: #1557b0;
    }}
  </style>
</head>
<body>
  <div class="offline-card">
    <svg class="offline-icon" viewBox="0 0 24 24">
      <path d="M23.64 7c-.45-.34-4.93-3.79-11.64-3.79-6.72 0-11.19 3.45-11.64 3.78L12 21.5 23.64 7zM3.55 7.62C5.9 5.86 8.92 5 12 5c3.08 0 6.1.86 8.45 2.62L12 18.06 3.55 7.62z"/>
      <path d="M1 1l22 22 1.41-1.41L2.41-.41z"/>
    </svg>
    <h1>You're currently offline</h1>
    <p>Please check your internet connection. {cfg["name"]} has saved your cached resources for instant re-access.</p>
    <button class="retry-btn" onclick="window.location.reload()">Retry Connection</button>
  </div>
</body>
</html>"""

    html_snippet = f"""<!-- PWA Head Integration -->
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="{cfg["theme_color"]}">
<link rel="apple-touch-icon" href="/icons/icon-192x192.png">
<script>
  if ('serviceWorker' in navigator) {{
    window.addEventListener('load', () => {{
      navigator.serviceWorker.register('/sw.js')
        .then(reg => console.log('PWA ServiceWorker registered', reg.scope))
        .catch(err => console.error('PWA registration failed', err));
    }});
  }}
</script>"""

    return {
        "manifest": manifest_dict,
        "manifest_json": json.dumps(manifest_dict, indent=2),
        "service_worker": sw_code,
        "offline_html": offline_html,
        "html_snippet": html_snippet,
    }


# ==============================================================================
# OpenGraph & Social Preview Generator
# ==============================================================================

def generate_og(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Generates rich OpenGraph, Twitter Card, and Google Search preview metadata.
    """
    cfg = {
        "title": "CWV Speed Studio | Core Web Vitals Engine",
        "description": "High-performance Core Web Vitals optimization, instant HTML transformer, PWA generator, and AI MCP server.",
        "image": "https://example.com/og-speed-card.png",
        "url": "https://example.com/",
        "site_name": "CWV Speed Studio",
        "twitter_handle": "@CWVSpeedStudio",
    }
    if config:
        cfg.update(config)

    tags = [
        f'<title>{cfg["title"]}</title>',
        f'<meta name="description" content="{cfg["description"]}">',
        f'<link rel="canonical" href="{cfg["url"]}">',
        '<!-- OpenGraph / Facebook -->',
        '<meta property="og:type" content="website">',
        f'<meta property="og:url" content="{cfg["url"]}">',
        f'<meta property="og:title" content="{cfg["title"]}">',
        f'<meta property="og:description" content="{cfg["description"]}">',
        f'<meta property="og:image" content="{cfg["image"]}">',
        f'<meta property="og:site_name" content="{cfg["site_name"]}">',
        '<!-- Twitter Card -->',
        '<meta name="twitter:card" content="summary_large_image">',
        f'<meta name="twitter:site" content="{cfg["twitter_handle"]}">',
        f'<meta name="twitter:creator" content="{cfg["twitter_handle"]}">',
        f'<meta name="twitter:title" content="{cfg["title"]}">',
        f'<meta name="twitter:description" content="{cfg["description"]}">',
        f'<meta name="twitter:image" content="{cfg["image"]}">',
    ]

    html_snippet = "\n".join(tags)

    return {
        "html_snippet": html_snippet,
        "tags": tags,
        "preview_data": cfg,
    }


# ==============================================================================
# Performance Diff Comparator
# ==============================================================================

def compare_diff(baseline_input: Union[str, Dict[str, Any]], candidate_input: Union[str, Dict[str, Any]], device: str = "mobile") -> Dict[str, Any]:
    """
    Compares baseline vs candidate performance reports or HTML code.
    Returns delta points, metric improvements, and resolved diagnostic issues.
    """
    if isinstance(baseline_input, str):
        baseline_report = audit_html_content(baseline_input, device=device)
    else:
        baseline_report = baseline_input

    if isinstance(candidate_input, str):
        candidate_report = audit_html_content(candidate_input, device=device)
    else:
        candidate_report = candidate_input

    b_score = baseline_report.get("score", 0)
    c_score = candidate_report.get("score", 0)
    score_delta = c_score - b_score

    b_m = baseline_report.get("metrics", {})
    c_m = candidate_report.get("metrics", {})

    def get_delta(metric_name: str, round_digits: int = 2) -> Dict[str, Any]:
        b_val = b_m.get(metric_name, {}).get("value", 0)
        c_val = c_m.get(metric_name, {}).get("value", 0)
        delta_val = round(c_val - b_val, round_digits) if round_digits > 0 else int(c_val - b_val)
        improved = delta_val < 0  # for CWV, lower is faster/better
        return {
            "baseline": b_val,
            "candidate": c_val,
            "delta": delta_val,
            "improved": improved,
            "unit": b_m.get(metric_name, {}).get("unit", ""),
        }

    metric_deltas = {
        "lcp": get_delta("lcp", 2),
        "cls": get_delta("cls", 3),
        "inp": get_delta("inp", 0),
        "fcp": get_delta("fcp", 2),
        "ttfb": get_delta("ttfb", 0),
    }

    # Resolved issues: rules that failed in baseline but passed in candidate
    b_rules = {d.get("rule_id"): d for d in baseline_report.get("diagnostics", [])}
    c_rules = {d.get("rule_id"): d for d in candidate_report.get("diagnostics", [])}

    resolved_issues: List[Dict[str, Any]] = []
    for rule_id, b_diag in b_rules.items():
        if not b_diag.get("passed", False):
            c_diag = c_rules.get(rule_id)
            if c_diag and c_diag.get("passed", False):
                resolved_issues.append({
                    "rule_id": rule_id,
                    "title": b_diag.get("title", ""),
                    "category": b_diag.get("category", ""),
                    "resolved": True,
                })

    return {
        "baseline_score": b_score,
        "candidate_score": c_score,
        "score_delta": score_delta,
        "improved": score_delta > 0,
        "baseline_rating": baseline_report.get("rating", "POOR"),
        "candidate_rating": candidate_report.get("rating", "POOR"),
        "metric_deltas": metric_deltas,
        "resolved_issues": resolved_issues,
        "resolved_count": len(resolved_issues),
        "summary": (
            f"Score increased from {b_score} to {c_score} (+{score_delta} pts) with "
            f"{len(resolved_issues)} issue(s) resolved."
            if score_delta >= 0
            else f"Score shifted from {b_score} to {c_score} ({score_delta} pts)."
        ),
    }


# ==============================================================================
# Cache-Control & Headers Exporter
# ==============================================================================

def export_cache_headers(platform: str, custom_rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Generates production caching and security header configs for:
    - netlify (_headers & netlify.toml)
    - vercel (vercel.json)
    - nginx (nginx.conf)
    - cloudflare (_headers)
    - apache (.htaccess)
    - nextjs (next.config.js headers)
    """
    plat = platform.lower().strip()

    if plat == "netlify":
        filename = "_headers"
        content = """# Netlify High-Performance Cache & Security Headers
# 1. Immutable Static Hashed Assets (1 Year Cache)
/_next/static/*
  Cache-Control: public, max-age=31536000, immutable
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/static/*
  Cache-Control: public, max-age=31536000, immutable

# 2. Modern Font Formats (1 Year Cache + CORS)
/*.woff2
  Cache-Control: public, max-age=31536000, immutable
  Access-Control-Allow-Origin: *

# 3. Optimized Media & SVGs (30 Days Cache)
/*.webp
  Cache-Control: public, max-age=2592000, stale-while-revalidate=86400
/*.avif
  Cache-Control: public, max-age=2592000, stale-while-revalidate=86400
/*.svg
  Cache-Control: public, max-age=2592000, stale-while-revalidate=86400

# 4. Service Worker & Manifest (Never Cache / Instant Revalidate)
/sw.js
  Cache-Control: public, max-age=0, must-revalidate
/site.webmanifest
  Cache-Control: public, max-age=0, must-revalidate
/manifest.json
  Cache-Control: public, max-age=0, must-revalidate

# 5. HTML Pages (Instant Edge Revalidation with SWR)
/*
  Cache-Control: public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=()
"""
    elif plat == "vercel":
        filename = "vercel.json"
        config_obj = {
            "headers": [
                {
                    "source": "/(.*)\\.(js|css|woff2|avif|webp)",
                    "headers": [
                        {"key": "Cache-Control", "value": "public, max-age=31536000, immutable"}
                    ]
                },
                {
                    "source": "/(sw\\.js|site\\.webmanifest)",
                    "headers": [
                        {"key": "Cache-Control", "value": "public, max-age=0, must-revalidate"}
                    ]
                },
                {
                    "source": "/(.*)",
                    "headers": [
                        {"key": "X-Content-Type-Options", "value": "nosniff"},
                        {"key": "X-Frame-Options", "value": "SAMEORIGIN"},
                        {"key": "Referrer-Policy", "value": "strict-origin-when-cross-origin"},
                        {"key": "Cache-Control", "value": "public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400"}
                    ]
                }
            ]
        }
        content = json.dumps(config_obj, indent=2)

    elif plat == "nginx":
        filename = "nginx.conf"
        content = """# High-Performance Nginx Core Web Vitals Caching Config

# 1. Gzip & Brotli Compression
gzip on;
gzip_vary on;
gzip_proxied any;
gzip_comp_level 6;
gzip_types text/plain text/css text/xml application/json application/javascript application/rss+xml application/atom+xml image/svg+xml;

# 2. Immutable Static Assets (1 Year Cache)
location ~* \\.(?:css|js|woff2|woff|ttf|eot|avif|webp|png|jpg|jpeg|gif|ico|svg)$ {
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    add_header Access-Control-Allow-Origin "*";
    access_log off;
    tcp_nodelay off;
    open_file_cache max=3000 inactive=120s;
}

# 3. Service Worker & Manifest (No Cache)
location ~* (?:sw\\.js|site\\.webmanifest|manifest\\.json)$ {
    expires -1;
    add_header Cache-Control "public, max-age=0, must-revalidate";
}

# 4. HTML Navigation (Edge SWR Revalidation)
location / {
    add_header Cache-Control "public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400";
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    try_files $uri $uri/ /index.html;
}
"""

    elif plat == "cloudflare":
        filename = "_headers"
        content = """# Cloudflare Pages / Workers Cache Rules
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin

# Immutable Assets
/static/*
  Cache-Control: public, max-age=31536000, immutable
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/*.woff2
  Cache-Control: public, max-age=31536000, immutable

# Service Worker
/sw.js
  Cache-Control: public, max-age=0, must-revalidate
"""

    elif plat == "nextjs":
        filename = "next.config.js"
        content = """/** @type {import('next').NextConfig} */
const nextConfig = {
  // 1. Next.js High-Performance Image Optimization
  images: {
    formats: ['image/avif', 'image/webp'],
    deviceSizes: [640, 750, 828, 1080, 1200, 1920],
    minimumCacheTTL: 31536000,
  },
  // 2. Production Caching Headers
  async headers() {
    return [
      {
        source: '/_next/static/:path*',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }
        ],
      },
      {
        source: '/fonts/:path*',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=31536000, immutable' },
          { key: 'Access-Control-Allow-Origin', value: '*' }
        ],
      },
      {
        source: '/sw.js',
        headers: [
          { key: 'Cache-Control', value: 'public, max-age=0, must-revalidate' }
        ],
      },
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' }
        ],
      },
    ];
  },
};

module.exports = nextConfig;
"""
    else:  # apache default
        filename = ".htaccess"
        content = """# Apache Core Web Vitals Speed Headers
<IfModule mod_expires.c>
  ExpiresActive On
  ExpiresDefault "access plus 1 month"
  ExpiresByType text/html "access plus 0 seconds"
  ExpiresByType application/javascript "access plus 1 year"
  ExpiresByType text/css "access plus 1 year"
  ExpiresByType font/woff2 "access plus 1 year"
  ExpiresByType image/webp "access plus 1 year"
  ExpiresByType image/avif "access plus 1 year"
</IfModule>

<IfModule mod_headers.c>
  <FilesMatch "\\.(js|css|woff2|webp|avif)$">
    Header set Cache-Control "public, max-age=31536000, immutable"
  </FilesMatch>
  <FilesMatch "(sw\\.js|manifest\\.json)$">
    Header set Cache-Control "public, max-age=0, must-revalidate"
  </FilesMatch>
</IfModule>
"""

    return {
        "platform": plat,
        "filename": filename,
        "content": content,
    }


# ==============================================================================
# AI Agent & Model Context Protocol (MCP) Hub
# ==============================================================================

def get_mcp_config(client: str = "claude") -> Dict[str, Any]:
    """
    Returns ready-to-use configuration for MCP clients (Claude Desktop, Cursor, Cline, Zed).
    """
    cli = client.lower().strip()
    python_exe = sys.executable or "python3"

    configs = {
        "claude": {
            "mcpServers": {
                "cwv-speed-engine": {
                    "command": python_exe,
                    "args": ["-m", "cwv_speed_engine.mcp_server"],
                    "env": {
                        "PYTHONPATH": "src"
                    }
                }
            }
        },
        "cursor": {
            "mcp": {
                "servers": {
                    "cwv-speed-engine": {
                        "command": python_exe,
                        "args": ["-m", "cwv_speed_engine.mcp_server"]
                    }
                }
            }
        },
        "cline": {
            "mcpServers": {
                "cwv-speed-engine": {
                    "command": python_exe,
                    "args": ["-m", "cwv_speed_engine.mcp_server"],
                    "disabled": False,
                    "autoApprove": [
                        "audit_url",
                        "audit_html",
                        "transform_html",
                        "generate_pwa",
                        "generate_cache_headers"
                    ]
                }
            }
        },
        "zed": {
            "context_servers": [
                {
                    "id": "cwv-speed-engine",
                    "command": {
                        "path": python_exe,
                        "args": ["-m", "cwv_speed_engine.mcp_server"]
                    }
                }
            ]
        }
    }

    selected = configs.get(cli, configs["claude"])
    return {
        "client": cli,
        "config": selected,
        "json_str": json.dumps(selected, indent=2),
        "available_tools": [
            {
                "name": "audit_url",
                "description": "Performs comprehensive Core Web Vitals audit on a live URL.",
                "parameters": {"url": "string", "device": "mobile | desktop"}
            },
            {
                "name": "audit_html",
                "description": "Audits raw HTML content for LCP, CLS, INP, FCP, and TTFB bottlenecks.",
                "parameters": {"html": "string", "device": "mobile | desktop"}
            },
            {
                "name": "transform_html",
                "description": "Automated speed optimization of HTML markup (dimensions, lazy load, fonts, defer).",
                "parameters": {"html": "string", "options": "object"}
            },
            {
                "name": "generate_pwa",
                "description": "Generates PWA manifest, service worker caching code, and offline fallback.",
                "parameters": {"name": "string", "short_name": "string", "theme_color": "string", "strategy": "string"}
            },
            {
                "name": "generate_cache_headers",
                "description": "Generates optimized Cache-Control headers for Netlify, Vercel, Nginx, or Next.js.",
                "parameters": {"platform": "netlify | vercel | nginx | cloudflare | nextjs"}
            },
            {
                "name": "compare_performance",
                "description": "Compares baseline vs candidate performance diff and calculates score improvement.",
                "parameters": {"baseline_html": "string", "candidate_html": "string"}
            }
        ]
    }


# ==============================================================================
# Zip Archive Export Bundle
# ==============================================================================

def create_zip_bundle(bundle_type: str, data: Dict[str, Any]) -> bytes:
    """
    Creates an in-memory zip archive for downloading PWA bundles, optimized HTML,
    or production configs.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if bundle_type == "pwa":
            pwa_res = generate_pwa(data)
            zf.writestr("site.webmanifest", pwa_res["manifest_json"])
            zf.writestr("sw.js", pwa_res["service_worker"])
            zf.writestr("offline.html", pwa_res["offline_html"])
            zf.writestr("pwa-head-snippet.html", pwa_res["html_snippet"])
            zf.writestr("README.md", "# PWA Production Bundle\n\nGenerated by CWV Speed Studio.\nPlace `site.webmanifest`, `sw.js`, and `offline.html` in your public root directory.")

        elif bundle_type == "optimized_html":
            raw_html = data.get("html", "<!DOCTYPE html><html><body><h1>Speed Studio</h1></body></html>")
            opt_res = transform_html(raw_html, data.get("options", {}))
            zf.writestr("index.optimized.html", opt_res["optimized_html"])
            zf.writestr("optimization-report.json", json.dumps(opt_res["stats"], indent=2))

        else:  # starter kit default
            pwa_res = generate_pwa(data)
            zf.writestr("site.webmanifest", pwa_res["manifest_json"])
            zf.writestr("sw.js", pwa_res["service_worker"])
            zf.writestr("offline.html", pwa_res["offline_html"])
            zf.writestr("_headers", export_cache_headers("netlify")["content"])
            zf.writestr("vercel.json", export_cache_headers("vercel")["content"])
            zf.writestr("nginx.conf", export_cache_headers("nginx")["content"])
            zf.writestr("next.config.js", export_cache_headers("nextjs")["content"])
            zf.writestr("claude_desktop_config.json", get_mcp_config("claude")["json_str"])

    buf.seek(0)
    return buf.getvalue()


# ==============================================================================
# Fallback HTML (Used if public/index.html is missing on disk)
# ==============================================================================

FALLBACK_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CWV Speed Studio | Core Web Vitals Engine</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8f9fa; color: #202124; margin: 0; padding: 24px; }
    .container { max-width: 900px; margin: 0 auto; background: #fff; padding: 32px; border-radius: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    h1 { color: #1a73e8; font-size: 24px; display: flex; align-items: center; gap: 8px; }
    .badge { background: #e8f0fe; color: #1a73e8; padding: 4px 12px; border-radius: 12px; font-size: 13px; font-weight: 500; }
  </style>
</head>
<body>
  <div class="container">
    <h1>⚡ CWV Speed Studio <span class="badge">Running</span></h1>
    <p>Core Web Vitals Speed Engine server is active. Please place <code>public/index.html</code> in the project directory for full Web Studio UI (design influenced by Material 3).</p>
    <p>API endpoints are active at <code>/api/audit</code>, <code>/api/optimize</code>, <code>/api/pwa/generate</code>, <code>/api/diff</code>, and <code>/api/health</code>.</p>
  </div>
</body>
</html>
"""


# ==============================================================================
# HTTP Request Handler
# ==============================================================================

class SpeedStudioRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    REST API & Static File Request Handler for Google Speed Studio.
    Zero external dependencies, supports full CORS, JSON APIs, and Zip downloads.
    """

    def __init__(self, *args, directory: Optional[str] = None, **kwargs):
        if directory is None:
            # Look for public/ directory relative to repository root
            base_dir = pathlib.Path(__file__).resolve().parent.parent.parent
            public_dir = base_dir / "public"
            directory = str(public_dir) if public_dir.exists() else str(base_dir)
        super().__init__(*args, directory=directory, **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(f"{self.address_string()} - - [{self.log_date_time_string()}] {format % args}")

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status: int, data: Any) -> None:
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length <= 0:
                return {}
            raw_body = self.rfile.read(content_length).decode("utf-8")
            return json.loads(raw_body) if raw_body else {}
        except Exception as e:
            logger.warning(f"Error parsing JSON request body: {e}")
            return {}

    def do_GET(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Health check
        if path == "/api/health":
            self._send_json(200, {
                "status": "healthy",
                "version": "1.0.0",
                "service": "cwv-speed-engine-ui",
                "uptime_seconds": round(time.time() - SERVER_START_TIME, 2),
                "timestamp": time.time(),
            })
            return

        # MCP Config endpoint
        if path == "/api/mcp/config":
            params = urllib.parse.parse_qs(parsed_url.query)
            client = params.get("client", ["claude"])[0]
            self._send_json(200, get_mcp_config(client))
            return

        # Cache Header Exporter endpoint
        if path == "/api/cache/export":
            params = urllib.parse.parse_qs(parsed_url.query)
            platform = params.get("platform", ["netlify"])[0]
            self._send_json(200, export_cache_headers(platform))
            return

        # Serve UI index.html
        if path in ("/", "/index.html"):
            index_path = pathlib.Path(self.directory) / "index.html"
            if index_path.exists():
                try:
                    content = index_path.read_bytes()
                    self.send_response(200)
                    self._send_cors_headers()
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception as e:
                    logger.warning(f"Error reading {index_path}: {e}")

            # Fallback to embedded HTML
            content = FALLBACK_INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Default static file handling
        super().do_GET()

    def do_POST(self) -> None:
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        body = self._read_json_body()

        # 1. Auditor endpoint
        if path == "/api/audit":
            url = body.get("url", "").strip()
            raw_html = body.get("html", "")
            device = body.get("device", "mobile")

            if url:
                report = audit_url(url, device=device)
            elif raw_html:
                report = audit_html_content(raw_html, device=device)
            else:
                self._send_json(400, {"error": "Missing 'url' or 'html' in request body", "status": 400})
                return

            self._send_json(200, report)
            return

        # 2. HTML Transformer endpoint
        if path == "/api/optimize" or path == "/api/transform":
            raw_html = body.get("html", "")
            if not raw_html:
                self._send_json(400, {"error": "Missing 'html' field in request body", "status": 400})
                return
            options = body.get("options", {})
            result = transform_html(raw_html, options=options)
            self._send_json(200, result)
            return

        # 3. PWA Generation endpoint
        if path == "/api/pwa/generate":
            result = generate_pwa(body)
            self._send_json(200, result)
            return

        # 4. OpenGraph Generation endpoint
        if path == "/api/og/generate":
            result = generate_og(body)
            self._send_json(200, result)
            return

        # 5. Performance Diff endpoint
        if path == "/api/diff" or path == "/api/compare":
            baseline = body.get("baseline")
            candidate = body.get("candidate")
            device = body.get("device", "mobile")

            if not baseline or not candidate:
                self._send_json(400, {"error": "Missing 'baseline' or 'candidate' in request body", "status": 400})
                return

            # Support nested objects {url: ...} or {html: ...} or raw strings
            if isinstance(baseline, dict):
                baseline_str = baseline.get("html") or baseline.get("url", "")
            else:
                baseline_str = str(baseline)

            if isinstance(candidate, dict):
                candidate_str = candidate.get("html") or candidate.get("url", "")
            else:
                candidate_str = str(candidate)

            diff_result = compare_diff(baseline_str, candidate_str, device=device)
            self._send_json(200, diff_result)
            return

        # 6. Cache Headers export endpoint
        if path == "/api/cache/export":
            platform = body.get("platform", "netlify")
            result = export_cache_headers(platform, body.get("custom_rules"))
            self._send_json(200, result)
            return

        # 7. MCP config endpoint
        if path == "/api/mcp/config":
            client = body.get("client", "claude")
            result = get_mcp_config(client)
            self._send_json(200, result)
            return

        # 8. Zip bundle export endpoint
        if path == "/api/export-zip":
            bundle_type = body.get("bundle_type", "pwa")
            data = body.get("data", {})
            zip_bytes = create_zip_bundle(bundle_type, data)

            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="cwv-speed-{bundle_type}-bundle.zip"')
            self.send_header("Content-Length", str(len(zip_bytes)))
            self.end_headers()
            self.wfile.write(zip_bytes)
            return

        # Unknown POST endpoint
        self._send_json(404, {"error": f"Endpoint {path} not found", "status": 404})


# ==============================================================================
# Server Factory & Runner Helpers
# ==============================================================================

def create_server(host: str = "127.0.0.1", port: int = 8448, directory: Optional[str] = None) -> http.server.ThreadingHTTPServer:
    """
    Creates and configures a ThreadingHTTPServer instance for CWV Speed Studio.
    """
    handler = lambda *args, **kwargs: SpeedStudioRequestHandler(*args, directory=directory, **kwargs)
    server = http.server.ThreadingHTTPServer((host, port), handler)
    return server


def start_ui_server(
    host: str = "127.0.0.1",
    port: int = 8448,
    open_browser: bool = False,
    blocking: bool = True,
    directory: Optional[str] = None,
) -> Union[http.server.ThreadingHTTPServer, Tuple[http.server.ThreadingHTTPServer, threading.Thread]]:
    """
    Starts the CWV Speed Studio web UI server.
    If blocking=False, starts in a daemon thread and returns (server, thread).
    """
    server = create_server(host, port, directory=directory)
    url = f"http://{host}:{port}/"
    print(f"\n==================================================================")
    print(f"⚡ CWV Speed Studio - Core Web Vitals Optimization Engine")
    print(f"==================================================================")
    print(f"🌐 Web UI:  {url}")
    print(f"🔌 REST API: {url}api/health")
    print(f"📁 Serving: {directory or 'public/'}")
    print(f"==================================================================\n")

    if open_browser:
        try:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
        except Exception as e:
            logger.debug(f"Could not open browser automatically: {e}")

    if blocking:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down CWV Speed Studio...")
            server.shutdown()
        return server
    else:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread


# ==============================================================================
# CLI Entry Point
# ==============================================================================

def main() -> None:
    """CLI launcher for CWV Speed Studio UI Server."""
    parser = argparse.ArgumentParser(
        description="CWV Speed Studio UI Server (cwv-speed-engine)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host interface (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8448, help="Port to bind (default: 8448)")
    parser.add_argument("--open", action="store_true", help="Automatically open browser")
    parser.add_argument("--dir", default=None, help="Custom directory to serve static assets from")

    args = parser.parse_args()
    start_ui_server(
        host=args.host,
        port=args.port,
        open_browser=args.open,
        blocking=True,
        directory=args.dir,
    )


if __name__ == "__main__":
    main()
