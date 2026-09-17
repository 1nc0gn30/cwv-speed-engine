"""Speculation Rules & 103 Early Hints Instant Navigation Engine.

Generates W3C Speculation Rules API scripts (<script type="speculationrules">)
for instant zero-latency prerendering and prefetching, extracts navigational link graphs,
guards against unsafe speculative side-effects (e.g. cart, checkout, logout),
synthesizes RFC 8297 103 Early Hints Link headers across multi-cloud edge platforms,
and computes predictive Core Web Vitals (TTFB & LCP) savings.

100% Python Standard Library. Zero external dependencies.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple, Union


class SpeculationEagerness(str, Enum):
    """Browser trigger timing for speculative preloading."""

    IMMEDIATE = "immediate"      # As soon as speculationrules script is processed
    EAGER = "eager"              # On minor user intent (e.g., cursor moving toward link)
    MODERATE = "moderate"        # On hover (default browser recommendation: 200ms pointerdown/hover)
    CONSERVATIVE = "conservative" # Only on explicit mousedown / touchstart


class SpeculationAction(str, Enum):
    """Speculative execution depth."""

    PRERENDER = "prerender"  # Full background page lifecycle render (instant navigation)
    PREFETCH = "prefetch"    # Network cache fetch only (reduces network roundtrips)


# Paths with side-effects or sensitive authentication that MUST NOT be speculatively fetched
SAFE_EXCLUSION_PATTERNS: List[str] = [
    r"/logout",
    r"/sign-?out",
    r"/auth/",
    r"/api/",
    r"/cart",
    r"/checkout",
    r"/buy",
    r"/purchase",
    r"/admin",
    r"/dashboard/delete",
    r"/webhook",
    r"\.(?:pdf|zip|tar|gz|mp4|mp3|exe|bin)$",
]


@dataclass
class EarlyHintItem:
    """RFC 8297 103 Early Hints preload link directive."""

    url: str
    rel: str = "preload"
    as_type: str = "style"  # style, script, font, image, fetch
    crossorigin: bool = False
    nopush: bool = False

    def to_header_value(self) -> str:
        """Serialize to Link header format."""
        parts = [f"<{self.url}>", f"rel={self.rel}", f"as={self.as_type}"]
        if self.crossorigin:
            parts.append("crossorigin")
        if self.nopush:
            parts.append("nopush")
        return "; ".join(parts)


@dataclass
class SpeculationPlanReport:
    """Comprehensive analysis and synthesized assets for instant speculative navigation."""

    speculation_rules: Dict[str, Any]
    speculation_rules_script_tag: str
    early_hints_headers: List[str]
    prerender_urls: List[str]
    prefetch_urls: List[str]
    excluded_urls: List[str]
    estimated_ttfb_saving_ms: float
    estimated_lcp_saving_ms: float
    projected_new_ttfb_ms: float
    projected_new_lcp_ms: float
    server_configs: Dict[str, str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "speculation_rules": self.speculation_rules,
            "speculation_rules_script_tag": self.speculation_rules_script_tag,
            "early_hints_headers": self.early_hints_headers,
            "prerender_urls": self.prerender_urls,
            "prefetch_urls": self.prefetch_urls,
            "excluded_urls": self.excluded_urls,
            "estimated_ttfb_saving_ms": round(self.estimated_ttfb_saving_ms, 1),
            "estimated_lcp_saving_ms": round(self.estimated_lcp_saving_ms, 1),
            "projected_new_ttfb_ms": round(self.projected_new_ttfb_ms, 1),
            "projected_new_lcp_ms": round(self.projected_new_lcp_ms, 1),
            "server_configs": self.server_configs,
        }


def is_safe_for_speculation(url: str) -> bool:
    """Determine if a URL is safe to speculatively prefetch or prerender."""
    norm = url.lower()
    for pat in SAFE_EXCLUSION_PATTERNS:
        if re.search(pat, norm):
            return False
    return True


def extract_links_from_html(
    html_content: str,
    base_url: str = "https://example.com",
) -> Tuple[List[str], List[str]]:
    """Extract internal navigation URLs and separate safe targets from side-effect URLs.

    Returns:
        Tuple of (safe_internal_urls, excluded_urls)
    """
    base_parsed = urllib.parse.urlparse(base_url)
    base_domain = base_parsed.netloc.lower()

    # Find all anchor hrefs
    raw_hrefs = re.findall(r'<a\s+(?:[^>]*?\s+)?href=["\'](.*?)["\']', html_content, re.IGNORECASE)

    safe_urls: List[str] = []
    excluded_urls: List[str] = []
    seen: Set[str] = set()

    for href in raw_hrefs:
        clean_href = href.strip()
        if not clean_href or clean_href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        resolved = urllib.parse.urljoin(base_url, clean_href)
        p = urllib.parse.urlparse(resolved)

        # Only internal links
        if p.netloc and p.netloc.lower() != base_domain:
            continue

        path_only = p.path or "/"
        if p.query:
            path_only += f"?{p.query}"

        if path_only in seen:
            continue
        seen.add(path_only)

        if is_safe_for_speculation(path_only):
            safe_urls.append(path_only)
        else:
            excluded_urls.append(path_only)

    return safe_urls, excluded_urls


def synthesize_early_hints(html_content: str, max_hints: int = 8) -> List[EarlyHintItem]:
    """Inspect HTML and generate 103 Early Hints preload directives for critical stylesheets, fonts, and hero images."""
    hints: List[EarlyHintItem] = []
    seen: Set[str] = set()

    # 1. Critical CSS stylesheets in head
    head_match = re.search(r"<head[^>]*>(.*?)</head>", html_content, re.DOTALL | re.IGNORECASE)
    head_text = head_match.group(1) if head_match else html_content

    css_links = re.findall(r'<link\s+(?:[^>]*?\s+)?rel=["\']stylesheet["\'][^>]*?href=["\'](.*?)["\']', head_text, re.IGNORECASE)
    for css in css_links:
        css = css.strip()
        if css and css not in seen:
            seen.add(css)
            hints.append(EarlyHintItem(url=css, rel="preload", as_type="style"))
            if len(hints) >= max_hints:
                return hints

    # 2. Key web fonts (woff2)
    font_matches = re.findall(r'href=["\']([^"\']+\.woff2(?:[?#][^"\']*)?)["\']', head_text, re.IGNORECASE)
    for font in font_matches:
        font = font.strip()
        if font and font not in seen:
            seen.add(font)
            hints.append(EarlyHintItem(url=font, rel="preload", as_type="font", crossorigin=True))
            if len(hints) >= max_hints:
                return hints

    # 3. LCP Candidate Hero Images (fetchpriority="high")
    img_tags = re.findall(r'<img\s+[^>]*?>', html_content, re.IGNORECASE)
    for tag in img_tags:
        if re.search(r'fetchpriority=["\']high["\']', tag, re.IGNORECASE):
            src_m = re.search(r'src=["\'](.*?)["\']', tag, re.IGNORECASE)
            if src_m:
                img = src_m.group(1).strip()
                if img and img not in seen:
                    seen.add(img)
                    hints.append(EarlyHintItem(url=img, rel="preload", as_type="image"))
                    if len(hints) >= max_hints:
                        return hints

    return hints


def build_server_configs(hints: List[EarlyHintItem], rules_script_tag: str) -> Dict[str, str]:
    """Generate configuration snippets for Netlify, Vercel, Cloudflare, and Nginx."""
    link_headers = [h.to_header_value() for h in hints]

    # Netlify _headers
    netlify_lines = ["/*"]
    for lh in link_headers:
        netlify_lines.append(f"  Link: {lh}")
    netlify_conf = "\n".join(netlify_lines)

    # Cloudflare Workers / Pages _headers
    cf_conf = netlify_conf

    # Nginx early_hints / http2_push
    nginx_lines = ["# 103 Early Hints / HTTP Preloads"]
    for h in hints:
        cross = "; crossorigin" if h.crossorigin else ""
        nginx_lines.append(f'add_header Link "<{h.url}>; rel=preload; as={h.as_type}{cross}";')
    nginx_conf = "\n".join(nginx_lines)

    # Vercel vercel.json headers snippet
    vercel_obj = {
        "headers": [
            {
                "source": "/(.*)",
                "headers": [
                    {"key": "Link", "value": ", ".join(link_headers)}
                ] if link_headers else [],
            }
        ]
    }
    vercel_conf = json.dumps(vercel_obj, indent=2)

    return {
        "netlify_headers": netlify_conf,
        "cloudflare_headers": cf_conf,
        "nginx_conf": nginx_conf,
        "vercel_json": vercel_conf,
    }


def generate_speculation_rules(
    prerender_urls: Sequence[str],
    prefetch_urls: Optional[Sequence[str]] = None,
    prerender_eagerness: str = "moderate",
    prefetch_eagerness: str = "conservative",
) -> Dict[str, Any]:
    """Generate W3C-compliant Speculation Rules JSON dictionary."""
    rules: Dict[str, Any] = {}

    if prerender_urls:
        rules["prerender"] = [
            {
                "source": "list",
                "urls": list(prerender_urls),
                "eagerness": prerender_eagerness,
            }
        ]

    if prefetch_urls:
        rules["prefetch"] = [
            {
                "source": "list",
                "urls": list(prefetch_urls),
                "eagerness": prefetch_eagerness,
            }
        ]

    return rules


def inject_speculation_rules_into_html(html_content: str, script_tag: str) -> str:
    """Idempotently insert or replace <script type="speculationrules"> in <head>."""
    # Remove existing speculationrules script if present
    cleaned = re.sub(
        r'<script\s+type=["\']speculationrules["\'][^>]*?>.*?</script>\s*',
        "",
        html_content,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Insert into <head> or prepend
    if "</head>" in cleaned:
        return cleaned.replace("</head>", f"  {script_tag}\n</head>", 1)
    elif "<head>" in cleaned:
        return cleaned.replace("<head>", f"<head>\n  {script_tag}", 1)
    return f"{script_tag}\n{cleaned}"


def generate_speculation_plan(
    html_or_urls: Union[str, Sequence[str]],
    base_url: str = "https://example.com",
    aggressiveness: str = "balanced",  # "conservative", "balanced", "aggressive"
    max_prerender: int = 3,
    max_prefetch: int = 8,
    baseline_ttfb_ms: float = 650.0,
    baseline_lcp_ms: float = 2200.0,
) -> SpeculationPlanReport:
    """High-level generator creating speculation rules, early hints, server configs, and CWV telemetry."""
    if isinstance(html_or_urls, str):
        safe_urls, excluded = extract_links_from_html(html_or_urls, base_url=base_url)
        hints = synthesize_early_hints(html_or_urls)
    else:
        safe_urls = [u for u in html_or_urls if is_safe_for_speculation(u)]
        excluded = [u for u in html_or_urls if not is_safe_for_speculation(u)]
        hints = []

    # Partition URLs by priority
    if aggressiveness == "aggressive":
        prerender_eager = SpeculationEagerness.EAGER.value
        prefetch_eager = SpeculationEagerness.MODERATE.value
        prerender_slice = safe_urls[:max_prerender]
        prefetch_slice = safe_urls[max_prerender : max_prerender + max_prefetch]
    elif aggressiveness == "conservative":
        prerender_eager = SpeculationEagerness.CONSERVATIVE.value
        prefetch_eager = SpeculationEagerness.CONSERVATIVE.value
        prerender_slice = safe_urls[:1]  # At most 1 critical next page
        prefetch_slice = safe_urls[1 : 1 + max_prefetch]
    else:  # balanced
        prerender_eager = SpeculationEagerness.MODERATE.value
        prefetch_eager = SpeculationEagerness.MODERATE.value
        prerender_slice = safe_urls[:2]
        prefetch_slice = safe_urls[2 : 2 + max_prefetch]

    rules_dict = generate_speculation_rules(
        prerender_urls=prerender_slice,
        prefetch_urls=prefetch_slice,
        prerender_eagerness=prerender_eager,
        prefetch_eagerness=prefetch_eager,
    )

    rules_json = json.dumps(rules_dict, indent=2)
    script_tag = f'<script type="speculationrules">\n{rules_json}\n</script>'

    server_configs = build_server_configs(hints, script_tag)
    early_hints_headers = [h.to_header_value() for h in hints]

    # Core Web Vitals impact simulation:
    # Instant prerender navigation drops TTFB to near 0ms (internal browser IPC < 15ms)
    # and LCP to immediate render (sub-250ms).
    if prerender_slice:
        ttfb_saving = baseline_ttfb_ms * 0.95
        lcp_saving = baseline_lcp_ms * 0.85
    elif prefetch_slice:
        ttfb_saving = baseline_ttfb_ms * 0.60
        lcp_saving = baseline_lcp_ms * 0.45
    else:
        ttfb_saving = 0.0
        lcp_saving = 0.0

    new_ttfb = max(10.0, baseline_ttfb_ms - ttfb_saving)
    new_lcp = max(180.0, baseline_lcp_ms - lcp_saving)

    return SpeculationPlanReport(
        speculation_rules=rules_dict,
        speculation_rules_script_tag=script_tag,
        early_hints_headers=early_hints_headers,
        prerender_urls=prerender_slice,
        prefetch_urls=prefetch_slice,
        excluded_urls=excluded,
        estimated_ttfb_saving_ms=ttfb_saving,
        estimated_lcp_saving_ms=lcp_saving,
        projected_new_ttfb_ms=new_ttfb,
        projected_new_lcp_ms=new_lcp,
        server_configs=server_configs,
    )
