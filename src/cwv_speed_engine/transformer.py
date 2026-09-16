"""Core Web Vitals HTML Speed Transformer.

Performs automated, idempotent HTML speed optimizations:
  - Image Layout Stability (injects width/height or aspect ratios)
  - Hero Image Optimization (removes lazy loading, adds fetchpriority="high" & decoding="async")
  - Below-the-fold Image Optimization (adds loading="lazy" & decoding="async")
  - Web Font Optimization (injects Google Fonts preconnect hints & display=swap)
  - Inline @font-face Optimization (injects font-display: swap)
  - Render-Blocking Script Deferral (adds defer/async to external scripts)
  - CDN Resource Hints (injects dns-prefetch and preconnect for external CDNs)
  - Optional Whitespace & Comment Minification

Zero external runtime dependencies - pure Python stdlib.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple


KNOWN_CDN_DOMAINS = [
    "cdnjs.cloudflare.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdn.tailwindcss.com",
    "ajax.googleapis.com",
    "code.jquery.com",
    "stackpath.bootstrapcdn.com",
    "cdn.skypack.dev",
    "esm.sh",
]


class HTMLSpeedTransformer:
    """Automated HTML transformer for Core Web Vitals optimization."""

    def __init__(self, html_str: str, options: Optional[Dict[str, Any]] = None) -> None:
        self.raw_html: str = html_str
        self.options: Dict[str, Any] = options or {}
        self.modifications: List[Dict[str, Any]] = []

        # Default options
        self.inject_dimensions: bool = self.options.get("inject_dimensions", True)
        self.default_width: str = str(self.options.get("default_width", "800"))
        self.default_height: str = str(self.options.get("default_height", "600"))
        self.hero_width: str = str(self.options.get("hero_width", "1200"))
        self.hero_height: str = str(self.options.get("hero_height", "675"))
        self.defer_scripts: bool = self.options.get("defer_scripts", True)
        self.inject_font_hints: bool = self.options.get("inject_font_hints", True)
        self.inject_cdn_hints: bool = self.options.get("inject_cdn_hints", True)
        self.optimize_fonts: bool = self.options.get("optimize_fonts", True)
        self.minify: bool = self.options.get("minify", False)

    def transform(self) -> Dict[str, Any]:
        """Execute all HTML speed transformations idempotently.

        Returns:
            Dict containing transformed_html, modifications list, and count.
        """
        html = self.raw_html

        # 1. Optimize <img> tags (Hero fetchpriority & Lazy loading & dimensions)
        html = self._transform_images(html)

        # 2. Optimize Google Fonts URLs (&display=swap)
        if self.optimize_fonts:
            html = self._transform_google_fonts_urls(html)

        # 3. Optimize inline @font-face rules in <style>
        if self.optimize_fonts:
            html = self._transform_inline_font_face(html)

        # 4. Defer render-blocking scripts
        if self.defer_scripts:
            html = self._transform_scripts(html)

        # 5. Inject Head Resource Hints (Fonts & CDNs)
        if self.inject_font_hints or self.inject_cdn_hints:
            html = self._inject_head_resource_hints(html)

        # 6. Optional minification
        if self.minify:
            html = self._minify_html(html)

        return {
            "transformed_html": html,
            "modifications": self.modifications,
            "modifications_count": len(self.modifications),
        }

    # -------------------------------------------------------------------------
    # 1. Image Optimization
    # -------------------------------------------------------------------------
    def _transform_images(self, html: str) -> str:
        # Regex to match <img> tags
        img_pattern = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
        matches = list(img_pattern.finditer(html))
        if not matches:
            return html

        img_count = len(matches)
        hero_modified = False
        lazy_count = 0
        dim_count = 0

        # Replace from end to beginning to preserve string offsets
        result_html = html
        for idx in reversed(range(img_count)):
            match = matches[idx]
            original_tag = match.group(0)
            raw_attrs = match.group(1)
            is_self_closing = raw_attrs.rstrip().endswith("/")
            if is_self_closing:
                raw_attrs = raw_attrs.rstrip()[:-1]

            attrs = self._parse_attributes(raw_attrs)
            modified = False

            is_hero = (idx == 0)

            if is_hero:
                # Hero image optimization:
                # Remove loading="lazy" if present
                if attrs.get("loading", "").lower() == "lazy":
                    del attrs["loading"]
                    modified = True
                    hero_modified = True

                # Add fetchpriority="high" if not set
                if attrs.get("fetchpriority", "").lower() != "high":
                    attrs["fetchpriority"] = "high"
                    modified = True
                    hero_modified = True

                # Add decoding="async" if not set
                if "decoding" not in attrs:
                    attrs["decoding"] = "async"
                    modified = True

                # Dimensions if missing
                has_w = bool(attrs.get("width", "").strip())
                has_h = bool(attrs.get("height", "").strip())
                has_aspect = "aspect-ratio" in attrs.get("style", "").lower()
                if self.inject_dimensions and not ((has_w and has_h) or has_aspect):
                    if not has_w:
                        attrs["width"] = self.hero_width
                    if not has_h:
                        attrs["height"] = self.hero_height
                    modified = True
                    dim_count += 1
            else:
                # Subsequent images:
                # Add loading="lazy" if not present and not loading="eager"
                if "loading" not in attrs:
                    attrs["loading"] = "lazy"
                    modified = True
                    lazy_count += 1

                # Add decoding="async" if not present
                if "decoding" not in attrs:
                    attrs["decoding"] = "async"
                    modified = True

                # Dimensions if missing
                has_w = bool(attrs.get("width", "").strip())
                has_h = bool(attrs.get("height", "").strip())
                has_aspect = "aspect-ratio" in attrs.get("style", "").lower()
                if self.inject_dimensions and not ((has_w and has_h) or has_aspect):
                    if not has_w:
                        attrs["width"] = self.default_width
                    if not has_h:
                        attrs["height"] = self.default_height
                    modified = True
                    dim_count += 1

            if modified:
                new_tag = self._build_tag("img", attrs, self_closing=is_self_closing)
                start, end = match.span()
                result_html = result_html[:start] + new_tag + result_html[end:]

        if hero_modified:
            self.modifications.append({
                "type": "image_hero",
                "description": "Optimized LCP hero image with fetchpriority='high', decoding='async', and removed lazy loading.",
            })

        if lazy_count > 0:
            self.modifications.append({
                "type": "image_lazy",
                "count": lazy_count,
                "description": f"Added loading='lazy' and decoding='async' to {lazy_count} below-the-fold image(s).",
            })

        if dim_count > 0:
            self.modifications.append({
                "type": "image_dimensions",
                "count": dim_count,
                "description": f"Injected explicit width/height dimensions onto {dim_count} image(s) to eliminate CLS.",
            })

        return result_html

    # -------------------------------------------------------------------------
    # 2. Google Fonts Optimization (&display=swap)
    # -------------------------------------------------------------------------
    def _transform_google_fonts_urls(self, html: str) -> str:
        link_pattern = re.compile(r"<link\b([^>]*)>", re.IGNORECASE)
        matches = list(link_pattern.finditer(html))
        if not matches:
            return html

        swap_added_count = 0
        result_html = html

        for match in reversed(matches):
            original_tag = match.group(0)
            raw_attrs = match.group(1)
            is_self_closing = raw_attrs.rstrip().endswith("/")
            if is_self_closing:
                raw_attrs = raw_attrs.rstrip()[:-1]

            attrs = self._parse_attributes(raw_attrs)
            rel = attrs.get("rel", "").lower()
            href = attrs.get("href", "")

            if "stylesheet" in rel and ("fonts.googleapis.com" in href or "fonts.bunny.net" in href):
                if "display=" not in href:
                    sep = "&" if "?" in href else "?"
                    new_href = f"{href}{sep}display=swap"
                    attrs["href"] = new_href
                    new_tag = self._build_tag("link", attrs, self_closing=is_self_closing)
                    start, end = match.span()
                    result_html = result_html[:start] + new_tag + result_html[end:]
                    swap_added_count += 1

        if swap_added_count > 0:
            self.modifications.append({
                "type": "font_display_swap_url",
                "count": swap_added_count,
                "description": f"Appended &display=swap to {swap_added_count} Google Fonts stylesheet URL(s).",
            })

        return result_html

    # -------------------------------------------------------------------------
    # 3. Inline @font-face Optimization
    # -------------------------------------------------------------------------
    def _transform_inline_font_face(self, html: str) -> str:
        style_pattern = re.compile(r"(<style\b[^>]*>)(.*?)(</style>)", re.IGNORECASE | re.DOTALL)
        font_face_regex = re.compile(r"(@font-face\s*\{)([^}]+)(\})", re.IGNORECASE)

        mod_count = 0

        def replace_font_face(match_style: re.Match) -> str:
            nonlocal mod_count
            open_tag = match_style.group(1)
            style_content = match_style.group(2)
            close_tag = match_style.group(3)

            def inject_swap(ff_match: re.Match) -> str:
                nonlocal mod_count
                prefix = ff_match.group(1)
                body = ff_match.group(2)
                suffix = ff_match.group(3)

                if "font-display" not in body.lower():
                    mod_count += 1
                    # Append font-display: swap inside block
                    body_stripped = body.rstrip()
                    if not body_stripped.endswith(";"):
                        body_stripped += ";"
                    return f"{prefix}{body_stripped}\n  font-display: swap;\n{suffix}"
                return ff_match.group(0)

            new_content = font_face_regex.sub(inject_swap, style_content)
            return f"{open_tag}{new_content}{close_tag}"

        transformed = style_pattern.sub(replace_font_face, html)
        if mod_count > 0:
            self.modifications.append({
                "type": "font_display_swap_inline",
                "count": mod_count,
                "description": f"Injected font-display: swap into {mod_count} inline @font-face rule(s).",
            })

        return transformed

    # -------------------------------------------------------------------------
    # 4. Script Deferral
    # -------------------------------------------------------------------------
    def _transform_scripts(self, html: str) -> str:
        script_pattern = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
        matches = list(script_pattern.finditer(html))
        if not matches:
            return html

        defer_count = 0
        result_html = html

        for match in reversed(matches):
            raw_attrs = match.group(1)
            body = match.group(2)
            attrs = self._parse_attributes(raw_attrs)

            src = attrs.get("src", "")
            script_type = attrs.get("type", "").lower()

            # Skip inline scripts, modules, already deferred/async, or intentionally blocking scripts
            is_blocking = "data-blocking" in attrs or "data-cfasync" in attrs
            has_async = "async" in attrs
            has_defer = "defer" in attrs
            is_module = script_type in ("module", "module-shim")

            if src and not (has_async or has_defer or is_module or is_blocking):
                attrs["defer"] = True
                new_tag_open = self._build_tag("script", attrs, self_closing=False)
                new_script = f"{new_tag_open}{body}</script>"
                start, end = match.span()
                result_html = result_html[:start] + new_script + result_html[end:]
                defer_count += 1

        if defer_count > 0:
            self.modifications.append({
                "type": "script_defer",
                "count": defer_count,
                "description": f"Added defer attribute to {defer_count} render-blocking external script(s).",
            })

        return result_html

    # -------------------------------------------------------------------------
    # 5. Inject Head Resource Hints
    # -------------------------------------------------------------------------
    def _inject_head_resource_hints(self, html: str) -> str:
        # Check if Google Fonts are used
        has_google_fonts = "fonts.googleapis.com" in html or "fonts.gstatic.com" in html

        # Check for CDNs used
        detected_cdns = []
        for cdn in KNOWN_CDN_DOMAINS:
            if cdn in html:
                detected_cdns.append(cdn)

        tags_to_inject = []

        # Google Fonts Preconnect
        if has_google_fonts and self.inject_font_hints:
            if '<link rel="preconnect" href="https://fonts.googleapis.com"' not in html and "https://fonts.googleapis.com" not in self._get_existing_preconnects(html):
                tags_to_inject.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
            if '<link rel="preconnect" href="https://fonts.gstatic.com"' not in html and "https://fonts.gstatic.com" not in self._get_existing_preconnects(html):
                tags_to_inject.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')

        # CDN Preconnect / DNS-prefetch
        if self.inject_cdn_hints:
            existing_hints = self._get_existing_preconnects(html)
            for cdn in detected_cdns:
                origin = f"https://{cdn}"
                if origin not in existing_hints and cdn not in ("fonts.googleapis.com", "fonts.gstatic.com"):
                    tags_to_inject.append(f'<link rel="dns-prefetch" href="https://{cdn}">')
                    tags_to_inject.append(f'<link rel="preconnect" href="https://{cdn}" crossorigin>')

        if not tags_to_inject:
            return html

        injection_block = "\n  " + "\n  ".join(tags_to_inject)

        # Inject inside <head>
        head_match = re.search(r"(<head\b[^>]*>)", html, re.IGNORECASE)
        if head_match:
            insert_pos = head_match.end()
            # If charset meta exists right after head, insert after charset/viewport
            meta_viewport = re.search(r"(<meta\b[^>]*viewport[^>]*>|<meta\b[^>]*charset[^>]*>)", html[insert_pos:insert_pos + 400], re.IGNORECASE)
            if meta_viewport:
                insert_pos += meta_viewport.end()

            result_html = html[:insert_pos] + injection_block + html[insert_pos:]
            self.modifications.append({
                "type": "resource_hints_injected",
                "count": len(tags_to_inject),
                "description": f"Injected {len(tags_to_inject)} resource hint(s) (preconnect / dns-prefetch) into <head>.",
            })
            return result_html

        # If no <head> exists, insert at top or before <body>
        body_match = re.search(r"(<body\b[^>]*>)", html, re.IGNORECASE)
        if body_match:
            insert_pos = body_match.start()
            result_html = html[:insert_pos] + f"<head>{injection_block}\n</head>\n" + html[insert_pos:]
            self.modifications.append({
                "type": "resource_hints_injected",
                "count": len(tags_to_inject),
                "description": f"Created <head> and injected {len(tags_to_inject)} resource hint(s).",
            })
            return result_html

        return f"<head>{injection_block}\n</head>\n" + html

    def _get_existing_preconnects(self, html: str) -> set:
        links = re.findall(r"<link\b[^>]*>", html, re.IGNORECASE)
        origins = set()
        for link in links:
            if "preconnect" in link.lower() or "dns-prefetch" in link.lower():
                href_match = re.search(r'href=["\']([^"\']+)["\']', link, re.IGNORECASE)
                if href_match:
                    origins.add(href_match.group(1).rstrip("/"))
        return origins

    # -------------------------------------------------------------------------
    # 6. Minification
    # -------------------------------------------------------------------------
    def _minify_html(self, html: str) -> str:
        # Preserve <pre>, <code>, <textarea>, <script>, <style> contents
        placeholders: Dict[str, str] = {}
        counter = 0

        def stash_block(match: re.Match) -> str:
            nonlocal counter
            key = f"__CWV_STASH_{counter}__"
            counter += 1
            placeholders[key] = match.group(0)
            return key

        # Stash preserved tags
        stashed = re.sub(
            r"<(pre|code|textarea|script|style)\b[^>]*>.*?</\1>",
            stash_block,
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )

        # Remove standard HTML comments (preserving conditional comments <!--[if ...]> and <!--#...-->)
        stashed = re.sub(r"<!--(?!\s*\[if|\s*#).*?-->", "", stashed, flags=re.DOTALL)

        # Collapse whitespace between tags
        stashed = re.sub(r">\s+<", "><", stashed)

        # Collapse repeated spaces
        stashed = re.sub(r"[ \t]+", " ", stashed)

        # Restore stashed blocks
        for key, orig in placeholders.items():
            stashed = stashed.replace(key, orig)

        self.modifications.append({
            "type": "html_minification",
            "description": "Collapsed redundant whitespace and removed non-critical HTML comments.",
        })
        return stashed.strip()

    # -------------------------------------------------------------------------
    # Attribute Parsing & Tag Building Helpers
    # -------------------------------------------------------------------------
    def _parse_attributes(self, raw_attrs: str) -> Dict[str, Any]:
        """Parse raw tag attribute string into a dictionary."""
        attrs: Dict[str, Any] = {}
        # Matches: name="value", name='value', name=value, name
        attr_regex = re.compile(
            r'([a-zA-Z0-9_\-:@.]+)(?:\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+)))?',
        )

        for match in attr_regex.finditer(raw_attrs):
            name = match.group(1)
            v_double = match.group(2)
            v_single = match.group(3)
            v_unquoted = match.group(4)

            if v_double is not None:
                val = v_double
            elif v_single is not None:
                val = v_single
            elif v_unquoted is not None:
                val = v_unquoted
            else:
                val = True  # Boolean attribute like defer, async, disabled

            attrs[name] = val

        return attrs

    def _build_tag(self, tag_name: str, attrs: Dict[str, Any], self_closing: bool = False) -> str:
        """Reconstruct HTML tag string from attribute dictionary."""
        parts = [f"<{tag_name}"]
        for name, val in attrs.items():
            if val is True:
                parts.append(f"{name}")
            elif val is False or val is None:
                continue
            else:
                escaped_val = str(val).replace('"', "&quot;")
                parts.append(f'{name}="{escaped_val}"')

        suffix = " />" if self_closing else ">"
        return " ".join(parts) + suffix


def optimize_html_speed(html_str: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Optimize HTML markup for maximum Core Web Vitals speed and stability.

    Args:
        html_str: Raw HTML source string.
        options: Optional configuration dictionary.

    Returns:
        Dictionary with transformed_html, modifications list, and count.
    """
    transformer = HTMLSpeedTransformer(html_str, options=options)
    return transformer.transform()
