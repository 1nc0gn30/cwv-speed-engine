"""Core Web Vitals (CWV) Performance Auditor and Speed Analyzer.

Evaluates HTML markup and HTTP response headers across 9 diagnostic heuristics:
  1. Viewport Meta Configuration (Responsive Rendering)
  2. Image Dimensions & Layout Stability (CLS)
  3. Image Loading Strategy (LCP & Lazy Loading)
  4. Render-Blocking CSS & JS Resources (FCP / LCP)
  5. Web Font Optimization (Preconnect, Display Swap & Preload)
  6. Resource Hints (Preconnect, DNS-Prefetch, Preload)
  7. DOM Size & Nesting Depth
  8. Cache-Control & Compression Headers (TTFB & Caching)
  9. Third-Party Script Impact (INP / Main Thread Latency)

Zero external runtime dependencies - pure Python stdlib.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple, Union


VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"
}

KNOWN_THIRD_PARTY_DOMAINS = [
    "googletagmanager.com",
    "google-analytics.com",
    "analytics.google.com",
    "facebook.net",
    "connect.facebook.net",
    "hotjar.com",
    "clarity.ms",
    "segment.com",
    "segment.io",
    "intercom.io",
    "intercomcdn.com",
    "tiktok.com",
    "adsbygoogle.js",
    "doubleclick.net",
    "ads.twitter.com",
    "snap.licdn.com",
    "hs-scripts.com",
    "fullstory.com",
    "criteo.net",
    "yandex.ru",
]

KNOWN_CDN_DOMAINS = [
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "ajax.googleapis.com",
    "code.jquery.com",
    "stackpath.bootstrapcdn.com",
]


class _CWVHTMLParser(HTMLParser):
    """Custom event-driven HTML parser for extracting CWV performance indicators."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.total_elements: int = 0
        self.max_depth: int = 0
        self._tag_stack: List[str] = []
        self._in_head: bool = False
        self._in_body: bool = False
        self._in_style: bool = False
        self._current_style_text: List[str] = []

        # Tag storage
        self.meta_tags: List[Dict[str, str]] = []
        self.link_tags: List[Dict[str, str]] = []
        self.script_tags: List[Dict[str, Any]] = []
        self.img_tags: List[Dict[str, Any]] = []
        self.style_blocks: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}
        self.total_elements += 1

        if tag_lower == "head":
            self._in_head = True
        elif tag_lower == "body":
            self._in_head = False
            self._in_body = True
        elif tag_lower == "style":
            self._in_style = True
            self._current_style_text = []

        if tag_lower not in VOID_TAGS:
            self._tag_stack.append(tag_lower)
            if len(self._tag_stack) > self.max_depth:
                self.max_depth = len(self._tag_stack)
        else:
            current_depth = len(self._tag_stack) + 1
            if current_depth > self.max_depth:
                self.max_depth = current_depth

        # Collect specific elements
        if tag_lower == "meta":
            self.meta_tags.append(attr_dict)
        elif tag_lower == "link":
            attr_dict["_in_head"] = self._in_head
            self.link_tags.append(attr_dict)
        elif tag_lower == "script":
            attr_dict["_in_head"] = self._in_head
            attr_dict["_in_body"] = self._in_body
            self.script_tags.append(attr_dict)
        elif tag_lower == "img":
            attr_dict["_index"] = len(self.img_tags)
            self.img_tags.append(attr_dict)

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "head":
            self._in_head = False
        elif tag_lower == "style":
            self._in_style = False
            if self._current_style_text:
                self.style_blocks.append("".join(self._current_style_text))
                self._current_style_text = []

        if tag_lower in self._tag_stack:
            # Pop stack up to matching tag to handle slightly unclosed markup gracefully
            while self._tag_stack:
                popped = self._tag_stack.pop()
                if popped == tag_lower:
                    break

    def handle_data(self, data: str) -> None:
        if self._in_style:
            self._current_style_text.append(data)


class PerformanceAuditor:
    """Core Web Vitals auditor and diagnostic heuristics engine."""

    def __init__(self, html_or_url: str, headers: Optional[Dict[str, str]] = None) -> None:
        self.input_source: str = html_or_url
        self.html_str: str = ""
        self.headers: Dict[str, str] = {}
        self.is_url: bool = False
        self.fetched_url: Optional[str] = None
        self.findings: List[Dict[str, Any]] = []

        # Heuristic result cache
        self.heuristics_data: Dict[str, Any] = {}

        self.headers_provided: bool = (headers is not None)
        if headers:
            self.headers = {k.lower(): v for k, v in headers.items()}

        self._load_source(html_or_url)

    def _load_source(self, source: str) -> None:
        stripped = source.strip()
        if stripped.startswith("http://") or stripped.startswith("https://"):
            self.is_url = True
            self.fetched_url = stripped
            self._fetch_url(stripped)
        elif stripped.startswith("file://"):
            parsed = urllib.parse.urlparse(stripped)
            file_path = urllib.request.url2pathname(parsed.path)
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                self.html_str = f.read()
        else:
            self.html_str = source

    def _fetch_url(self, url: str) -> None:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "CWV-Speed-Engine/1.0 (+https://github.com/cwv-speed-engine)",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=12) as response:
                # Capture headers if not explicitly supplied
                if not self.headers:
                    resp_headers = getattr(response, "headers", {})
                    if hasattr(resp_headers, "items"):
                        self.headers = {k.lower(): v for k, v in resp_headers.items()}
                    elif isinstance(resp_headers, dict):
                        self.headers = {k.lower(): v for k, v in resp_headers.items()}
                raw_bytes = response.read()

                # Handle gzip / deflate / plain text
                content_encoding = self.headers.get("content-encoding", "").lower()
                if "gzip" in content_encoding:
                    import gzip
                    try:
                        raw_bytes = gzip.decompress(raw_bytes)
                    except Exception:
                        pass
                elif "deflate" in content_encoding:
                    import zlib
                    try:
                        raw_bytes = zlib.decompress(raw_bytes)
                    except Exception:
                        pass

                # Detect charset
                resp_headers = getattr(response, "headers", None)
                charset = "utf-8"
                if resp_headers is not None and hasattr(resp_headers, "get_content_charset"):
                    charset = resp_headers.get_content_charset() or "utf-8"
                self.html_str = raw_bytes.decode(charset, errors="replace")
        except Exception as e:
            # Fallback to empty html with critical fetch error finding
            self.html_str = f"<!-- Fetch error: {str(e)} -->"
            self.findings.append({
                "id": "CWV-FETCH-FAILED",
                "category": "network",
                "severity": "CRITICAL",
                "title": f"Failed to fetch target URL: {url}",
                "description": f"Network fetch failed with error: {str(e)}",
                "offenders": [url],
                "remediation": "Verify server accessibility, firewall settings, and network connectivity.",
            })

    def audit(self) -> Dict[str, Any]:
        """Execute full Core Web Vitals audit and return structured metrics and findings."""
        parser = _CWVHTMLParser()
        try:
            parser.feed(self.html_str)
            parser.close()
        except Exception:
            pass

        self.findings = [f for f in self.findings if f.get("id") == "CWV-FETCH-FAILED"]

        # Run 9 Diagnostic Heuristics
        h_viewport = self._audit_viewport(parser)
        h_images_dim = self._audit_image_dimensions(parser)
        h_images_load = self._audit_image_loading(parser)
        h_render_blocking = self._audit_render_blocking(parser)
        h_fonts = self._audit_web_fonts(parser)
        h_hints = self._audit_resource_hints(parser)
        h_dom = self._audit_dom_size(parser)
        h_caching = self._audit_caching_compression()
        h_third_party = self._audit_third_party_scripts(parser)

        self.heuristics_data = {
            "viewport": h_viewport,
            "image_dimensions": h_images_dim,
            "image_loading": h_images_load,
            "render_blocking": h_render_blocking,
            "font_optimization": h_fonts,
            "resource_hints": h_hints,
            "dom_size": h_dom,
            "caching_compression": h_caching,
            "third_party_scripts": h_third_party,
        }

        # Calculate metrics and score
        metrics = self._calculate_metrics()
        overall_score = self._calculate_overall_score(metrics)
        rating = self._get_rating(overall_score)

        # Build summary
        summary = {
            "total_findings": len(self.findings),
            "critical": sum(1 for f in self.findings if f["severity"] == "CRITICAL"),
            "high": sum(1 for f in self.findings if f["severity"] == "HIGH"),
            "medium": sum(1 for f in self.findings if f["severity"] == "MEDIUM"),
            "low": sum(1 for f in self.findings if f["severity"] == "LOW"),
            "info": sum(1 for f in self.findings if f["severity"] == "INFO"),
        }

        return {
            "url": self.fetched_url or (self.input_source if self.is_url else "inline_html"),
            "score": overall_score,
            "rating": rating,
            "metrics": metrics,
            "heuristics": self.heuristics_data,
            "findings": self.findings,
            "summary": summary,
        }

    # -------------------------------------------------------------------------
    # Heuristic 1: Viewport Meta
    # -------------------------------------------------------------------------
    def _audit_viewport(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        viewport_tag = None
        for m in parser.meta_tags:
            if m.get("name", "").lower() == "viewport":
                viewport_tag = m
                break

        if not viewport_tag:
            self.findings.append({
                "id": "CWV-VIEWPORT-MISSING",
                "category": "viewport",
                "severity": "CRITICAL",
                "title": "Missing Mobile Viewport Meta Tag",
                "description": "Pages without a viewport tag render at desktop widths on mobile, causing severe layout degradation and poor responsive rendering.",
                "offenders": ["<head> (no viewport meta tag found)"],
                "remediation": '<meta name="viewport" content="width=device-width, initial-scale=1">',
            })
            return {"status": "FAIL", "has_viewport": False, "details": "Missing viewport tag"}

        content = viewport_tag.get("content", "").lower()
        has_device_width = "width=device-width" in content
        has_initial_scale = "initial-scale=1" in content or "initial-scale=1.0" in content
        restricts_zoom = "user-scalable=no" in content or "maximum-scale=1" in content

        issues = []
        if not has_device_width:
            issues.append("Missing width=device-width")
            self.findings.append({
                "id": "CWV-VIEWPORT-NO-DEVICE-WIDTH",
                "category": "viewport",
                "severity": "HIGH",
                "title": "Viewport Meta Missing width=device-width",
                "description": "Without width=device-width, mobile browsers emulate desktop layout widths.",
                "offenders": [f'<meta name="viewport" content="{content}">'],
                "remediation": '<meta name="viewport" content="width=device-width, initial-scale=1">',
            })

        if not has_initial_scale:
            issues.append("Missing initial-scale=1")
            self.findings.append({
                "id": "CWV-VIEWPORT-NO-SCALE",
                "category": "viewport",
                "severity": "MEDIUM",
                "title": "Viewport Meta Missing initial-scale=1",
                "description": "Initial scale ensures 1:1 pixel rendering on mobile devices.",
                "offenders": [f'<meta name="viewport" content="{content}">'],
                "remediation": '<meta name="viewport" content="width=device-width, initial-scale=1">',
            })

        if restricts_zoom:
            issues.append("Restricts user zooming")
            self.findings.append({
                "id": "CWV-VIEWPORT-SCALABLE-DISABLED",
                "category": "viewport",
                "severity": "MEDIUM",
                "title": "Viewport Disables User Zooming (Accessibility Anti-pattern)",
                "description": "user-scalable=no or maximum-scale=1 harms accessibility and fails WCAG 2.1.",
                "offenders": [f'<meta name="viewport" content="{content}">'],
                "remediation": '<meta name="viewport" content="width=device-width, initial-scale=1">',
            })

        status = "PASS" if not issues else "WARN" if len(issues) == 1 and issues[0] == "Restricts user zooming" else "FAIL"
        return {
            "status": status,
            "has_viewport": True,
            "content": content,
            "has_device_width": has_device_width,
            "has_initial_scale": has_initial_scale,
            "restricts_zoom": restricts_zoom,
        }

    # -------------------------------------------------------------------------
    # Heuristic 2: Image Dimensions & Layout Stability (CLS)
    # -------------------------------------------------------------------------
    def _audit_image_dimensions(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        total_images = len(parser.img_tags)
        images_missing_dimensions: List[Dict[str, Any]] = []

        for img in parser.img_tags:
            has_width = bool(img.get("width", "").strip())
            has_height = bool(img.get("height", "").strip())
            style = img.get("style", "").lower()
            has_aspect_style = "aspect-ratio" in style or ("width" in style and "height" in style)

            if not ((has_width and has_height) or has_aspect_style):
                src = img.get("src", "") or img.get("data-src", "") or "(no-src)"
                images_missing_dimensions.append({
                    "src": src,
                    "index": img.get("_index", 0),
                    "attributes": {k: v for k, v in img.items() if not k.startswith("_")},
                })

        if images_missing_dimensions:
            offenders = [f'<img src="{item["src"]}">' for item in images_missing_dimensions[:6]]
            if len(images_missing_dimensions) > 6:
                offenders.append(f"...and {len(images_missing_dimensions) - 6} more images")

            self.findings.append({
                "id": "CWV-IMG-NO-DIM",
                "category": "cls",
                "severity": "HIGH",
                "title": f"Images Missing Explicit Dimensions ({len(images_missing_dimensions)} found)",
                "description": "Images without width and height attributes trigger layout shifts (CLS) when loaded, shifting content down.",
                "offenders": offenders,
                "remediation": 'Add explicit width and height attributes (e.g. <img src="hero.jpg" width="800" height="450">) or CSS aspect-ratio.',
            })

        return {
            "total_images": total_images,
            "missing_dimensions_count": len(images_missing_dimensions),
            "status": "PASS" if not images_missing_dimensions else "FAIL",
            "offending_images": [item["src"] for item in images_missing_dimensions],
        }

    # -------------------------------------------------------------------------
    # Heuristic 3: Image Loading Strategy (LCP & Lazy Loading)
    # -------------------------------------------------------------------------
    def _audit_image_loading(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        if not parser.img_tags:
            return {"status": "PASS", "hero_image": None, "subsequent_images_count": 0}

        hero_img = parser.img_tags[0]
        hero_loading = hero_img.get("loading", "").lower()
        hero_priority = hero_img.get("fetchpriority", "").lower()
        hero_src = hero_img.get("src", "") or "(hero-image)"

        # 1. Hero image must not be lazy
        if hero_loading == "lazy":
            self.findings.append({
                "id": "CWV-HERO-LAZY",
                "category": "lcp",
                "severity": "CRITICAL",
                "title": "LCP Hero Image Has loading='lazy'",
                "description": "Lazy-loading the first above-the-fold image delays LCP by waiting for layout calculation before initiating image request.",
                "offenders": [f'<img src="{hero_src}" loading="lazy">'],
                "remediation": f'Remove loading="lazy" and add fetchpriority="high" to your hero image:\n<img src="{hero_src}" fetchpriority="high" decoding="async">',
            })

        # 2. Hero image should have fetchpriority="high"
        if hero_priority != "high":
            self.findings.append({
                "id": "CWV-HERO-NO-PRIORITY",
                "category": "lcp",
                "severity": "MEDIUM",
                "title": "Hero Image Missing fetchpriority='high'",
                "description": "Prioritizing the primary hero image instructs the browser to download LCP assets before non-critical resources.",
                "offenders": [f'<img src="{hero_src}">'],
                "remediation": f'<img src="{hero_src}" fetchpriority="high" decoding="async">',
            })

        # 3. Subsequent images below the fold
        subsequent_missing_lazy = []
        subsequent_missing_async_decoding = []
        for img in parser.img_tags[1:]:
            src = img.get("src", "") or "(image)"
            if img.get("loading", "").lower() != "lazy":
                subsequent_missing_lazy.append(src)
            if img.get("decoding", "").lower() != "async":
                subsequent_missing_async_decoding.append(src)

        if subsequent_missing_lazy:
            self.findings.append({
                "id": "CWV-IMG-NO-LAZY",
                "category": "lcp",
                "severity": "LOW",
                "title": f"Subsequent Images Missing loading='lazy' ({len(subsequent_missing_lazy)} found)",
                "description": "Off-screen images should be lazy-loaded to avoid competing with critical network bandwidth.",
                "offenders": [f'<img src="{s}">' for s in subsequent_missing_lazy[:5]],
                "remediation": 'Add loading="lazy" to all below-the-fold <img> elements.',
            })

        if subsequent_missing_async_decoding:
            self.findings.append({
                "id": "CWV-IMG-NO-ASYNC-DECODING",
                "category": "performance",
                "severity": "LOW",
                "title": f"Images Missing decoding='async' ({len(subsequent_missing_async_decoding)} found)",
                "description": "decoding='async' unblocks the main rendering thread while the browser decodes images in the background.",
                "offenders": [f'<img src="{s}">' for s in subsequent_missing_async_decoding[:5]],
                "remediation": 'Add decoding="async" to all <img> elements.',
            })

        status = "FAIL" if hero_loading == "lazy" else "WARN" if hero_priority != "high" or subsequent_missing_lazy else "PASS"
        return {
            "status": status,
            "hero_src": hero_src,
            "hero_has_lazy": hero_loading == "lazy",
            "hero_has_high_priority": hero_priority == "high",
            "subsequent_images_count": len(parser.img_tags) - 1,
            "subsequent_missing_lazy_count": len(subsequent_missing_lazy),
        }

    # -------------------------------------------------------------------------
    # Heuristic 4: Render-Blocking CSS & JS
    # -------------------------------------------------------------------------
    def _audit_render_blocking(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        blocking_css: List[str] = []
        blocking_js: List[str] = []

        # CSS stylesheets in head
        for link in parser.link_tags:
            rel = link.get("rel", "").lower()
            href = link.get("href", "")
            media = link.get("media", "").lower()

            if "stylesheet" in rel and href:
                # print media is not render-blocking for screen
                if media != "print":
                    blocking_css.append(href)

        # JS scripts
        for script in parser.script_tags:
            src = script.get("src", "")
            is_async = "async" in script
            is_defer = "defer" in script
            script_type = script.get("type", "").lower()
            is_module = script_type in ("module", "module-shim")

            if src and not (is_async or is_defer or is_module):
                blocking_js.append(src)

        if blocking_css:
            self.findings.append({
                "id": "CWV-RENDER-BLOCKING-CSS",
                "category": "fcp",
                "severity": "HIGH",
                "title": f"Render-Blocking CSS Stylesheets ({len(blocking_css)} found)",
                "description": "Synchronous CSS stylesheets in <head> block the browser from painting pixels until fully downloaded and parsed.",
                "offenders": [f'<link rel="stylesheet" href="{css}">' for css in blocking_css],
                "remediation": 'Inline critical CSS rules and load secondary styles via <link rel="preload" as="style" onload="this.onload=null;this.rel=\'stylesheet\'">.',
            })

        if blocking_js:
            self.findings.append({
                "id": "CWV-RENDER-BLOCKING-JS",
                "category": "fcp",
                "severity": "HIGH",
                "title": f"Render-Blocking Synchronous JavaScript ({len(blocking_js)} found)",
                "description": "Synchronous <script> tags block DOM parsing and delay First Contentful Paint.",
                "offenders": [f'<script src="{js}">' for js in blocking_js],
                "remediation": 'Add defer or async attribute: <script src="..." defer></script> or use type="module".',
            })

        status = "PASS" if not (blocking_css or blocking_js) else "FAIL"
        return {
            "status": status,
            "blocking_css_count": len(blocking_css),
            "blocking_css_files": blocking_css,
            "blocking_js_count": len(blocking_js),
            "blocking_js_files": blocking_js,
        }

    # -------------------------------------------------------------------------
    # Heuristic 5: Web Font Optimization
    # -------------------------------------------------------------------------
    def _audit_web_fonts(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        has_google_fonts = False
        google_fonts_urls: List[str] = []
        has_display_swap_in_url = False

        preconnect_origins = set()
        for link in parser.link_tags:
            rel = link.get("rel", "").lower()
            href = link.get("href", "")
            if "preconnect" in rel:
                parsed = urllib.parse.urlparse(href)
                if parsed.netloc:
                    preconnect_origins.add(parsed.netloc.lower())

            if "stylesheet" in rel:
                if "fonts.googleapis.com" in href or "fonts.bunny.net" in href:
                    has_google_fonts = True
                    google_fonts_urls.append(href)
                    if "display=swap" in href or "display=optional" in href:
                        has_display_swap_in_url = True

        # Check font-display in inline style blocks
        style_has_font_face = False
        style_missing_swap = False
        font_face_regex = re.compile(r"@font-face\s*\{([^}]+)\}", re.IGNORECASE | re.DOTALL)

        for style_text in parser.style_blocks:
            matches = font_face_regex.findall(style_text)
            if matches:
                style_has_font_face = True
                for block in matches:
                    if "font-display" not in block.lower():
                        style_missing_swap = True
                        break

        # Font preloads
        font_preloads = [
            link.get("href", "")
            for link in parser.link_tags
            if "preload" in link.get("rel", "").lower() and link.get("as", "").lower() == "font"
        ]

        # Evaluate Findings
        if has_google_fonts:
            missing_preconnect = []
            if "fonts.googleapis.com" not in preconnect_origins:
                missing_preconnect.append("https://fonts.googleapis.com")
            if "fonts.gstatic.com" not in preconnect_origins:
                missing_preconnect.append("https://fonts.gstatic.com")

            if missing_preconnect:
                self.findings.append({
                    "id": "CWV-FONT-NO-PRECONNECT",
                    "category": "fonts",
                    "severity": "HIGH",
                    "title": "Google Fonts Missing Preconnect Resource Hints",
                    "description": "Preconnecting to Google Fonts domains saves 100-300ms of DNS resolution and TLS handshake time during initial paint.",
                    "offenders": missing_preconnect,
                    "remediation": '<link rel="preconnect" href="https://fonts.googleapis.com">\n<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
                })

            if not has_display_swap_in_url:
                self.findings.append({
                    "id": "CWV-FONT-NO-SWAP",
                    "category": "fonts",
                    "severity": "HIGH",
                    "title": "Google Fonts Missing &display=swap Parameter",
                    "description": "Without display=swap, browsers hide text (FOIT - Flash of Invisible Text) while fonts are downloading.",
                    "offenders": google_fonts_urls,
                    "remediation": 'Append "&display=swap" to your Google Fonts stylesheet URL.',
                })

        if style_has_font_face and style_missing_swap:
            self.findings.append({
                "id": "CWV-FONT-DISPLAY-MISSING",
                "category": "fonts",
                "severity": "MEDIUM",
                "title": "@font-face Missing font-display: swap",
                "description": "Custom @font-face rules without font-display block text rendering during font network requests.",
                "offenders": ["@font-face rule in <style> block"],
                "remediation": "Add `font-display: swap;` inside your @font-face CSS definition.",
            })

        status = "PASS"
        if has_google_fonts and (not has_display_swap_in_url or "fonts.gstatic.com" not in preconnect_origins):
            status = "FAIL"
        elif style_has_font_face and style_missing_swap:
            status = "WARN"

        return {
            "status": status,
            "has_google_fonts": has_google_fonts,
            "google_fonts_urls": google_fonts_urls,
            "has_display_swap": has_display_swap_in_url,
            "font_preloads_count": len(font_preloads),
            "custom_font_face_count": 1 if style_has_font_face else 0,
        }

    # -------------------------------------------------------------------------
    # Heuristic 6: Resource Hints
    # -------------------------------------------------------------------------
    def _audit_resource_hints(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        preconnect_urls = []
        dns_prefetch_urls = []
        preload_urls = []

        for link in parser.link_tags:
            rel = link.get("rel", "").lower()
            href = link.get("href", "")
            if "preconnect" in rel:
                preconnect_urls.append(href)
            if "dns-prefetch" in rel:
                dns_prefetch_urls.append(href)
            if "preload" in rel:
                preload_urls.append({"href": href, "as": link.get("as", "")})

        # Identify external CDN origins in scripts/links without hints
        external_origins = set()
        for s in parser.script_tags:
            src = s.get("src", "")
            if src.startswith("http://") or src.startswith("https://") or src.startswith("//"):
                parsed = urllib.parse.urlparse(src if not src.startswith("//") else f"https:{src}")
                if parsed.netloc:
                    external_origins.add(parsed.netloc.lower())

        for l in parser.link_tags:
            href = l.get("href", "")
            if href.startswith("http://") or href.startswith("https://") or href.startswith("//"):
                parsed = urllib.parse.urlparse(href if not href.startswith("//") else f"https:{href}")
                if parsed.netloc:
                    external_origins.add(parsed.netloc.lower())

        hinted_domains = {
            urllib.parse.urlparse(u).netloc.lower()
            for u in (preconnect_urls + dns_prefetch_urls)
            if urllib.parse.urlparse(u).netloc
        }

        unhinted_cdns = [
            d for d in external_origins
            if d in KNOWN_CDN_DOMAINS and d not in hinted_domains and not d.startswith("fonts.")
        ]

        if unhinted_cdns:
            self.findings.append({
                "id": "CWV-HINT-MISSING-PRECONNECT",
                "category": "network",
                "severity": "LOW",
                "title": f"Missing Resource Hints for Key CDNs ({len(unhinted_cdns)} found)",
                "description": "Adding preconnect or dns-prefetch for third-party CDNs reduces asset fetch latency.",
                "offenders": unhinted_cdns,
                "remediation": "\n".join(f'<link rel="preconnect" href="https://{d}">' for d in unhinted_cdns),
            })

        return {
            "preconnect_count": len(preconnect_urls),
            "dns_prefetch_count": len(dns_prefetch_urls),
            "preload_count": len(preload_urls),
            "preconnect_urls": preconnect_urls,
            "dns_prefetch_urls": dns_prefetch_urls,
            "unhinted_cdns": unhinted_cdns,
        }

    # -------------------------------------------------------------------------
    # Heuristic 7: DOM Size & Depth
    # -------------------------------------------------------------------------
    def _audit_dom_size(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        total_nodes = parser.total_elements
        max_depth = parser.max_depth

        if total_nodes > 1400:
            self.findings.append({
                "id": "CWV-DOM-SIZE-EXCESSIVE",
                "category": "dom",
                "severity": "CRITICAL",
                "title": f"Excessive DOM Node Count ({total_nodes} elements)",
                "description": "Excessive DOM size (> 1400 nodes) causes high memory usage, prolonged style recalcs, and degrades INP.",
                "offenders": [f"Total DOM Nodes: {total_nodes} (recommended < 800)"],
                "remediation": "Simplify component tree, paginate or virtualize long lists, and remove hidden offscreen markup.",
            })
        elif total_nodes > 800:
            self.findings.append({
                "id": "CWV-DOM-SIZE-WARNING",
                "category": "dom",
                "severity": "MEDIUM",
                "title": f"High DOM Node Count ({total_nodes} elements)",
                "description": "Large DOM trees (> 800 nodes) increase layout calculation overhead and delay rendering.",
                "offenders": [f"Total DOM Nodes: {total_nodes}"],
                "remediation": "Refactor complex wrapper tags and virtualize lengthy dynamic DOM content.",
            })

        if max_depth > 32:
            self.findings.append({
                "id": "CWV-DOM-DEPTH-EXCESSIVE",
                "category": "dom",
                "severity": "HIGH",
                "title": f"Excessive DOM Nesting Depth (Depth: {max_depth})",
                "description": "DOM trees nested deeper than 32 levels significantly slow down browser CSS selector matching and layout passes.",
                "offenders": [f"Max Nesting Depth: {max_depth} (recommended <= 32)"],
                "remediation": "Flatten HTML hierarchy by removing redundant div/wrapper containers.",
            })

        status = "FAIL" if (total_nodes > 1400 or max_depth > 32) else "WARN" if total_nodes > 800 else "PASS"
        return {
            "status": status,
            "total_elements": total_nodes,
            "max_nesting_depth": max_depth,
        }

    # -------------------------------------------------------------------------
    # Heuristic 8: Cache-Control & Compression Headers
    # -------------------------------------------------------------------------
    def _audit_caching_compression(self) -> Dict[str, Any]:
        if not self.headers_provided and not self.is_url:
            return {
                "status": "INFO",
                "has_headers": False,
                "message": "Response headers not available for static HTML string audit.",
            }

        content_encoding = self.headers.get("content-encoding", "").lower()
        cache_control = self.headers.get("cache-control", "").lower()

        is_compressed = any(enc in content_encoding for enc in ("gzip", "br", "zstd", "deflate"))
        has_cache_control = bool(cache_control)

        if not is_compressed:
            self.findings.append({
                "id": "CWV-HEADER-NO-COMPRESSION",
                "category": "network",
                "severity": "HIGH",
                "title": "Missing Text Compression (Gzip / Brotli)",
                "description": "Serving uncompressed HTML/CSS/JS payloads drastically increases page transfer time and delays FCP/LCP.",
                "offenders": [f"Content-Encoding: {content_encoding or '(none)'}"],
                "remediation": "Enable Gzip or Brotli compression on your CDN or web server (e.g. gzip on / brotli on in Nginx).",
            })

        if not has_cache_control:
            self.findings.append({
                "id": "CWV-HEADER-NO-CACHE-CONTROL",
                "category": "network",
                "severity": "HIGH",
                "title": "Missing Cache-Control Header",
                "description": "Without explicit Cache-Control headers, browsers use heuristic caching or re-fetch on every navigation.",
                "offenders": ["Cache-Control: (missing)"],
                "remediation": "Add 'Cache-Control: public, max-age=0, must-revalidate, stale-while-revalidate=86400' for HTML pages.",
            })

        status = "PASS" if (is_compressed and has_cache_control) else "FAIL"
        return {
            "status": status,
            "has_headers": True,
            "content_encoding": content_encoding,
            "is_compressed": is_compressed,
            "cache_control": cache_control,
            "has_cache_control": has_cache_control,
        }

    # -------------------------------------------------------------------------
    # Heuristic 9: Third-Party Script Impact
    # -------------------------------------------------------------------------
    def _audit_third_party_scripts(self, parser: _CWVHTMLParser) -> Dict[str, Any]:
        detected_third_parties = []
        blocking_third_parties = []

        for script in parser.script_tags:
            src = script.get("src", "")
            if not src:
                continue

            for domain in KNOWN_THIRD_PARTY_DOMAINS:
                if domain in src.lower():
                    is_async = "async" in script
                    is_defer = "defer" in script
                    is_module = script.get("type", "").lower() == "module"
                    info = {"src": src, "domain": domain, "async": is_async, "defer": is_defer}
                    detected_third_parties.append(info)

                    if not (is_async or is_defer or is_module):
                        blocking_third_parties.append(src)
                    break

        if blocking_third_parties:
            self.findings.append({
                "id": "CWV-THIRDPARTY-BLOCKING-SCRIPT",
                "category": "inp",
                "severity": "HIGH",
                "title": f"Synchronous Third-Party Analytics/Tag Manager ({len(blocking_third_parties)} found)",
                "description": "Third-party tags without async or defer execute synchronously, freezing main thread CPU and spiking INP.",
                "offenders": [f'<script src="{s}">' for s in blocking_third_parties],
                "remediation": "Load third-party analytics and trackers asynchronously: <script src=\"...\" async></script>",
            })

        if len(detected_third_parties) >= 5:
            self.findings.append({
                "id": "CWV-THIRDPARTY-HEAVY-TAGS",
                "category": "inp",
                "severity": "MEDIUM",
                "title": f"Heavy Third-Party Script Burden ({len(detected_third_parties)} third-party scripts)",
                "description": "Running numerous third-party marketing tags consumes main-thread execution time and harms INP.",
                "offenders": [item["src"] for item in detected_third_parties],
                "remediation": "Consolidate marketing tags via server-side tagging (GTM Server-Side) or delay execution until user interaction.",
            })

        status = "PASS" if not blocking_third_parties else "FAIL"
        return {
            "status": status,
            "detected_count": len(detected_third_parties),
            "blocking_count": len(blocking_third_parties),
            "third_party_scripts": detected_third_parties,
        }

    # -------------------------------------------------------------------------
    # Metrics & Scoring Engine
    # -------------------------------------------------------------------------
    def _calculate_metrics(self) -> Dict[str, Any]:
        """Estimate realistic CWV values based on detected technical indicators."""
        # 1. LCP (Largest Contentful Paint)
        lcp_ms = 1600.0
        h_img_load = self.heuristics_data.get("image_loading", {})
        h_render = self.heuristics_data.get("render_blocking", {})
        h_fonts = self.heuristics_data.get("font_optimization", {})

        if h_img_load.get("hero_has_lazy"):
            lcp_ms += 1400.0
        elif not h_img_load.get("hero_has_high_priority") and h_img_load.get("hero_src"):
            lcp_ms += 350.0

        lcp_ms += (h_render.get("blocking_css_count", 0) * 400.0)
        lcp_ms += (h_render.get("blocking_js_count", 0) * 450.0)

        if h_fonts.get("has_google_fonts") and not h_fonts.get("has_display_swap"):
            lcp_ms += 300.0

        lcp_score = self._score_from_thresholds(lcp_ms, good=2500.0, poor=4000.0, invert=True)

        # 2. CLS (Cumulative Layout Shift)
        cls_val = 0.01
        h_img_dim = self.heuristics_data.get("image_dimensions", {})
        missing_dim_count = h_img_dim.get("missing_dimensions_count", 0)
        cls_val += min(missing_dim_count * 0.08, 0.45)

        if h_fonts.get("has_google_fonts") and not h_fonts.get("has_display_swap"):
            cls_val += 0.05

        cls_score = self._score_from_thresholds(cls_val, good=0.10, poor=0.25, invert=True)

        # 3. INP (Interaction to Next Paint) / FID
        inp_ms = 60.0
        h_third_party = self.heuristics_data.get("third_party_scripts", {})
        h_dom = self.heuristics_data.get("dom_size", {})

        inp_ms += (h_third_party.get("blocking_count", 0) * 90.0)
        inp_ms += (h_render.get("blocking_js_count", 0) * 60.0)

        dom_nodes = h_dom.get("total_elements", 0)
        if dom_nodes > 1400:
            inp_ms += 200.0
        elif dom_nodes > 800:
            inp_ms += 90.0

        inp_score = self._score_from_thresholds(inp_ms, good=200.0, poor=500.0, invert=True)

        # 4. FCP (First Contentful Paint)
        fcp_ms = 1000.0
        fcp_ms += (h_render.get("blocking_css_count", 0) * 450.0)
        fcp_ms += (h_render.get("blocking_js_count", 0) * 400.0)
        h_caching = self.heuristics_data.get("caching_compression", {})
        if h_caching.get("has_headers") and not h_caching.get("is_compressed"):
            fcp_ms += 500.0

        fcp_score = self._score_from_thresholds(fcp_ms, good=1800.0, poor=3000.0, invert=True)

        # 5. TTFB (Time to First Byte)
        ttfb_ms = 220.0
        if h_caching.get("has_headers"):
            if not h_caching.get("has_cache_control"):
                ttfb_ms += 250.0
            if not h_caching.get("is_compressed"):
                ttfb_ms += 350.0

        ttfb_score = self._score_from_thresholds(ttfb_ms, good=800.0, poor=1800.0, invert=True)

        return {
            "lcp": {
                "name": "Largest Contentful Paint",
                "estimated_value": round(lcp_ms, 1),
                "unit": "ms",
                "score": lcp_score,
                "rating": self._get_rating(lcp_score),
                "status": "Good" if lcp_ms <= 2500 else "Needs Improvement" if lcp_ms <= 4000 else "Poor",
            },
            "cls": {
                "name": "Cumulative Layout Shift",
                "estimated_value": round(cls_val, 3),
                "unit": "unitless",
                "score": cls_score,
                "rating": self._get_rating(cls_score),
                "status": "Good" if cls_val <= 0.10 else "Needs Improvement" if cls_val <= 0.25 else "Poor",
            },
            "inp": {
                "name": "Interaction to Next Paint",
                "estimated_value": round(inp_ms, 1),
                "unit": "ms",
                "score": inp_score,
                "rating": self._get_rating(inp_score),
                "status": "Good" if inp_ms <= 200 else "Needs Improvement" if inp_ms <= 500 else "Poor",
            },
            "fcp": {
                "name": "First Contentful Paint",
                "estimated_value": round(fcp_ms, 1),
                "unit": "ms",
                "score": fcp_score,
                "rating": self._get_rating(fcp_score),
                "status": "Good" if fcp_ms <= 1800 else "Needs Improvement" if fcp_ms <= 3000 else "Poor",
            },
            "ttfb": {
                "name": "Time to First Byte",
                "estimated_value": round(ttfb_ms, 1),
                "unit": "ms",
                "score": ttfb_score,
                "rating": self._get_rating(ttfb_score),
                "status": "Good" if ttfb_ms <= 800 else "Needs Improvement" if ttfb_ms <= 1800 else "Poor",
            },
        }

    def _score_from_thresholds(self, val: float, good: float, poor: float, invert: bool = True) -> int:
        """Calculate a smooth 0-100 score given good (90+) and poor (<50) thresholds."""
        if invert:
            if val <= good:
                # 90 to 100
                ratio = max(0.0, val / good)
                score = 100 - (ratio * 10)
            elif val <= poor:
                # 50 to 89
                ratio = (val - good) / (poor - good)
                score = 89 - (ratio * 39)
            else:
                # 0 to 49
                excess = val - poor
                score = max(0, 49 - int(excess / 20.0))
        else:
            if val >= good:
                score = 90 + int(min(10.0, (val - good) / 10.0))
            elif val >= poor:
                ratio = (val - poor) / (good - poor)
                score = 50 + int(ratio * 39)
            else:
                score = max(0, int(val / poor * 49))

        return int(max(0, min(100, round(score))))

    def _calculate_overall_score(self, metrics: Dict[str, Any]) -> int:
        # Standard CWV weighted distribution:
        # LCP: 25%, CLS: 25%, INP: 20%, FCP: 15%, TTFB: 15%
        w_lcp = metrics["lcp"]["score"] * 0.25
        w_cls = metrics["cls"]["score"] * 0.25
        w_inp = metrics["inp"]["score"] * 0.20
        w_fcp = metrics["fcp"]["score"] * 0.15
        w_ttfb = metrics["ttfb"]["score"] * 0.15

        base_score = w_lcp + w_cls + w_inp + w_fcp + w_ttfb

        # Apply deduction for critical findings
        critical_count = sum(1 for f in self.findings if f["severity"] == "CRITICAL")
        penalty = critical_count * 15.0

        final_score = max(0, min(100, int(round(base_score - penalty))))
        return final_score

    def _get_rating(self, score: int) -> str:
        if score >= 90:
            return "Good"
        elif score >= 50:
            return "Needs Improvement"
        return "Poor"


def audit_core_web_vitals(html_or_url: str, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Audit an HTML document or URL against Core Web Vitals diagnostic heuristics.

    Args:
        html_or_url: Raw HTML string or HTTP/HTTPS/file URL.
        headers: Optional dictionary of HTTP response headers.

    Returns:
        Structured audit report with overall score, metrics, findings, and remediation.
    """
    auditor = PerformanceAuditor(html_or_url, headers=headers)
    return auditor.audit()
