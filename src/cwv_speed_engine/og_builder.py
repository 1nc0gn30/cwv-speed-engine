"""
OpenGraph & Social Meta Tag Builder with Quality Scoring and SERP/Social Simulator.

Generates W3C/OpenGraph Protocol and Twitter Card meta tags, validates content
length and image dimensions against platform guidelines, calculates a quality score,
and simulates previews for Google Search, Twitter/X Cards, and Facebook/LinkedIn shares.

Zero external dependencies (pure Python standard library).
"""

import html
import re
import urllib.parse
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple, Union


# =============================================================================
# Helper Utilities
# =============================================================================

def _truncate(text: str, max_length: int, suffix: str = "...") -> str:
    """Truncate text cleanly at word boundaries if it exceeds max_length."""
    if len(text) <= max_length:
        return text
    truncated = text[:max_length - len(suffix)].rsplit(" ", 1)[0]
    return f"{truncated}{suffix}" if truncated else f"{text[:max_length - len(suffix)]}{suffix}"


def _infer_mime_type(image_url: str) -> str:
    """Infer image MIME type from URL extension."""
    parsed = urllib.parse.urlparse(image_url).path.lower()
    if parsed.endswith(".png"):
        return "image/png"
    elif parsed.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    elif parsed.endswith(".webp"):
        return "image/webp"
    elif parsed.endswith(".avif"):
        return "image/avif"
    elif parsed.endswith(".svg"):
        return "image/svg+xml"
    elif parsed.endswith(".gif"):
        return "image/gif"
    return "image/png"


def _format_twitter_handle(handle: Optional[str]) -> Optional[str]:
    """Ensure twitter handle starts with @ and contains no extra spaces or URL prefixes."""
    if not handle:
        return None
    h = handle.strip()
    # Strip URL prefixes if full profile URL was passed
    if "twitter.com/" in h or "x.com/" in h:
        h = h.split("/")[-1]
    h = re.sub(r"[^\w_]", "", h)
    return f"@{h}" if h else None


# =============================================================================
# OpenGraphBuilder Class
# =============================================================================

class OpenGraphBuilder:
    """
    Builder and Validator for OpenGraph, Twitter Card, and SEO meta tags.
    """

    # Recommendation Boundaries
    TITLE_MIN_OPTIMAL = 40
    TITLE_MAX_OPTIMAL = 60
    TITLE_HARD_MAX = 70

    DESC_MIN_OPTIMAL = 120
    DESC_MAX_OPTIMAL = 160
    DESC_HARD_MAX = 200

    def __init__(
        self,
        title: str,
        description: str,
        url: str,
        image_url: Optional[str] = None,
        site_name: Optional[str] = None,
        twitter_handle: Optional[str] = None,
        twitter_site: Optional[str] = None,
        card_type: str = "summary_large_image",
        og_type: str = "website",
        locale: str = "en_US",
        alternate_locales: Optional[List[str]] = None,
        canonical_url: Optional[str] = None,
        image_alt: Optional[str] = None,
        image_width: int = 1200,
        image_height: int = 630,
        published_time: Optional[str] = None,
        modified_time: Optional[str] = None,
        author: Optional[str] = None,
        section: Optional[str] = None,
        tags: Optional[List[str]] = None,
        robots: str = "index, follow",
    ) -> None:
        self.title = title.strip()
        self.description = description.strip()
        self.url = url.strip()
        self.image_url = image_url.strip() if image_url else None
        self.site_name = site_name.strip() if site_name else None
        self.twitter_handle = _format_twitter_handle(twitter_handle)
        self.twitter_site = _format_twitter_handle(twitter_site) or self.twitter_handle
        self.card_type = card_type.strip()
        self.og_type = og_type.strip()
        self.locale = locale.strip()
        self.alternate_locales = alternate_locales or []
        self.canonical_url = canonical_url.strip() if canonical_url else self.url
        self.image_alt = image_alt.strip() if image_alt else self.title
        self.image_width = image_width
        self.image_height = image_height
        self.published_time = published_time
        self.modified_time = modified_time
        self.author = author
        self.section = section
        self.tags = tags or []
        self.robots = robots

    def build_tag_dictionary(self) -> Dict[str, str]:
        """Generate key-value dictionary of all meta tags."""
        tags: Dict[str, str] = {}

        # Standard SEO
        tags["title"] = self.title
        tags["description"] = self.description
        tags["robots"] = self.robots
        if self.canonical_url:
            tags["canonical"] = self.canonical_url

        # OpenGraph Essential
        tags["og:title"] = self.title
        tags["og:description"] = self.description
        tags["og:url"] = self.canonical_url or self.url
        tags["og:type"] = self.og_type
        if self.site_name:
            tags["og:site_name"] = self.site_name
        tags["og:locale"] = self.locale

        # OpenGraph Image
        if self.image_url:
            tags["og:image"] = self.image_url
            if self.image_url.startswith("https://"):
                tags["og:image:secure_url"] = self.image_url
            tags["og:image:width"] = str(self.image_width)
            tags["og:image:height"] = str(self.image_height)
            tags["og:image:alt"] = self.image_alt
            tags["og:image:type"] = _infer_mime_type(self.image_url)

        # Article specifics
        if self.og_type == "article":
            if self.published_time:
                tags["article:published_time"] = self.published_time
            if self.modified_time:
                tags["article:modified_time"] = self.modified_time
            if self.author:
                tags["article:author"] = self.author
            if self.section:
                tags["article:section"] = self.section

        # Twitter Cards
        tags["twitter:card"] = self.card_type
        tags["twitter:title"] = self.title
        tags["twitter:description"] = self.description
        if self.image_url:
            tags["twitter:image"] = self.image_url
            tags["twitter:image:alt"] = self.image_alt
        if self.twitter_site:
            tags["twitter:site"] = self.twitter_site
        if self.twitter_handle:
            tags["twitter:creator"] = self.twitter_handle

        return tags

    def validate(self) -> Dict[str, Any]:
        """
        Validate metadata against platform best practices and compute quality score.
        Returns:
            Dict containing 'score', 'status', 'warnings', 'checks'
        """
        score = 100
        warnings: List[Dict[str, str]] = []
        checks: Dict[str, Any] = {}

        # 1. Title validation
        title_len = len(self.title)
        checks["title_length"] = title_len
        if not self.title:
            score -= 30
            warnings.append({
                "severity": "error",
                "field": "title",
                "message": "Title is empty.",
                "recommendation": "Provide a descriptive title between 40 and 60 characters."
            })
        elif title_len < 30:
            score -= 10
            warnings.append({
                "severity": "warning",
                "field": "title",
                "message": f"Title is short ({title_len} chars). Optimal length is {self.TITLE_MIN_OPTIMAL}-{self.TITLE_MAX_OPTIMAL} chars.",
                "recommendation": "Expand title with brand or primary keyword."
            })
        elif title_len > self.TITLE_HARD_MAX:
            score -= 10
            warnings.append({
                "severity": "warning",
                "field": "title",
                "message": f"Title is long ({title_len} chars). May be truncated on SERP and social cards (> {self.TITLE_MAX_OPTIMAL} chars).",
                "recommendation": "Shorten title to avoid truncation ellipsis."
            })
        elif title_len > self.TITLE_MAX_OPTIMAL:
            score -= 3
            warnings.append({
                "severity": "info",
                "field": "title",
                "message": f"Title ({title_len} chars) is slightly above optimal {self.TITLE_MAX_OPTIMAL} chars.",
                "recommendation": "Trim slightly if crucial keywords are at the end."
            })

        # 2. Description validation
        desc_len = len(self.description)
        checks["description_length"] = desc_len
        if not self.description:
            score -= 30
            warnings.append({
                "severity": "error",
                "field": "description",
                "message": "Description is empty.",
                "recommendation": "Provide a compelling description between 120 and 160 characters."
            })
        elif desc_len < 70:
            score -= 12
            warnings.append({
                "severity": "warning",
                "field": "description",
                "message": f"Description is too short ({desc_len} chars). Optimal is {self.DESC_MIN_OPTIMAL}-{self.DESC_MAX_OPTIMAL} chars.",
                "recommendation": "Add a clear value proposition or call to action."
            })
        elif desc_len > self.DESC_HARD_MAX:
            score -= 10
            warnings.append({
                "severity": "warning",
                "field": "description",
                "message": f"Description exceeds {self.DESC_HARD_MAX} chars ({desc_len} chars) and will be truncated on mobile/desktop cards.",
                "recommendation": "Keep description under 160 chars for full display."
            })
        elif desc_len > self.DESC_MAX_OPTIMAL:
            score -= 3
            warnings.append({
                "severity": "info",
                "field": "description",
                "message": f"Description ({desc_len} chars) is slightly above optimal {self.DESC_MAX_OPTIMAL} chars.",
                "recommendation": "Verify important summary is in the first 150 characters."
            })

        # 3. Image validation
        checks["has_image"] = bool(self.image_url)
        if not self.image_url:
            score -= 25
            warnings.append({
                "severity": "error",
                "field": "image_url",
                "message": "Missing og:image. Social shares will display without banner media.",
                "recommendation": "Add an absolute HTTPS image URL (recommended 1200x630px)."
            })
        else:
            if not self.image_url.startswith(("http://", "https://")):
                score -= 15
                warnings.append({
                    "severity": "error",
                    "field": "image_url",
                    "message": f"Image URL '{self.image_url}' is not absolute.",
                    "recommendation": "Social crawlers require fully-qualified absolute URLs (https://...)."
                })
            elif self.image_url.startswith("http://"):
                score -= 5
                warnings.append({
                    "severity": "warning",
                    "field": "image_url",
                    "message": "Image URL uses unencrypted HTTP. Some platforms block mixed content.",
                    "recommendation": "Switch image URL to HTTPS."
                })

            if self.image_width < 600 or self.image_height < 315:
                score -= 8
                warnings.append({
                    "severity": "warning",
                    "field": "image_dimensions",
                    "message": f"Image dimensions ({self.image_width}x{self.image_height}) are below the recommended minimum (600x315).",
                    "recommendation": "Use 1200x630 for high-DPI large image cards."
                })

        # 4. URL & Canonical Validation
        if not self.url.startswith(("http://", "https://")):
            score -= 10
            warnings.append({
                "severity": "error",
                "field": "url",
                "message": f"Page URL '{self.url}' must be a fully-qualified absolute URL.",
                "recommendation": "Include protocol (e.g. https://example.com/page)."
            })

        # 5. Twitter Handle
        if not self.twitter_handle and not self.twitter_site:
            score -= 3
            warnings.append({
                "severity": "info",
                "field": "twitter_handle",
                "message": "No Twitter/X creator or site handle provided.",
                "recommendation": "Add @handle for brand attribution on X/Twitter."
            })

        score = max(0, min(100, score))
        status = "excellent" if score >= 90 else "good" if score >= 75 else "needs_improvement" if score >= 50 else "poor"

        return {
            "score": score,
            "status": status,
            "warnings": warnings,
            "checks": checks,
        }

    def generate_previews(self) -> Dict[str, Any]:
        """
        Generate simulated preview payloads for Google Search, Twitter Cards,
        and Social Share platforms (Facebook/LinkedIn/Slack).
        """
        # Parse breadcrumb
        parsed_url = urllib.parse.urlparse(self.url)
        domain = parsed_url.netloc or "example.com"
        path_segments = [s for s in parsed_url.path.strip("/").split("/") if s]
        breadcrumb = f"https://{domain}" + (" > " + " > ".join(path_segments) if path_segments else "")

        # Google Search Preview
        google_title = _truncate(self.title, 60)
        google_desc = _truncate(self.description, 155)
        google_preview = {
            "title": google_title,
            "url_display": breadcrumb,
            "description": google_desc,
            "is_title_truncated": len(self.title) > 60,
            "is_desc_truncated": len(self.description) > 155,
        }

        # Twitter Card Preview
        twitter_title = _truncate(self.title, 70)
        twitter_desc = _truncate(self.description, 200)
        twitter_preview = {
            "card_type": self.card_type,
            "title": twitter_title,
            "description": twitter_desc,
            "image": self.image_url,
            "image_alt": self.image_alt,
            "domain": domain,
            "creator": self.twitter_handle,
            "site": self.twitter_site,
        }

        # Facebook / LinkedIn / Social Share Preview
        social_title = _truncate(self.title, 65)
        social_desc = _truncate(self.description, 150)
        social_preview = {
            "site_name": self.site_name or domain,
            "title": social_title,
            "description": social_desc,
            "image_url": self.image_url,
            "domain": domain.upper(),
            "url": self.canonical_url or self.url,
        }

        return {
            "google_search": google_preview,
            "twitter_card": twitter_preview,
            "social_share": social_preview,
        }

    def to_html(self, indent: str = "  ") -> str:
        """
        Format metadata into a clean HTML `<head>` snippet with organized comments.
        """
        escape = html.escape
        lines: List[str] = []

        # Standard SEO
        lines.append(f"{indent}<!-- Primary SEO Meta Tags -->")
        lines.append(f"{indent}<title>{escape(self.title)}</title>")
        lines.append(f'{indent}<meta name="title" content="{escape(self.title)}" />')
        lines.append(f'{indent}<meta name="description" content="{escape(self.description)}" />')
        lines.append(f'{indent}<meta name="robots" content="{escape(self.robots)}" />')
        if self.canonical_url:
            lines.append(f'{indent}<link rel="canonical" href="{escape(self.canonical_url)}" />')

        # Open Graph / Facebook
        lines.append("")
        lines.append(f"{indent}<!-- Open Graph / Facebook -->")
        lines.append(f'{indent}<meta property="og:type" content="{escape(self.og_type)}" />')
        lines.append(f'{indent}<meta property="og:url" content="{escape(self.canonical_url or self.url)}" />')
        lines.append(f'{indent}<meta property="og:title" content="{escape(self.title)}" />')
        lines.append(f'{indent}<meta property="og:description" content="{escape(self.description)}" />')
        lines.append(f'{indent}<meta property="og:locale" content="{escape(self.locale)}" />')
        if self.site_name:
            lines.append(f'{indent}<meta property="og:site_name" content="{escape(self.site_name)}" />')

        if self.image_url:
            lines.append(f'{indent}<meta property="og:image" content="{escape(self.image_url)}" />')
            if self.image_url.startswith("https://"):
                lines.append(f'{indent}<meta property="og:image:secure_url" content="{escape(self.image_url)}" />')
            lines.append(f'{indent}<meta property="og:image:width" content="{self.image_width}" />')
            lines.append(f'{indent}<meta property="og:image:height" content="{self.image_height}" />')
            lines.append(f'{indent}<meta property="og:image:alt" content="{escape(self.image_alt)}" />')
            lines.append(f'{indent}<meta property="og:image:type" content="{_infer_mime_type(self.image_url)}" />')

        for alt_loc in self.alternate_locales:
            lines.append(f'{indent}<meta property="og:locale:alternate" content="{escape(alt_loc)}" />')

        if self.og_type == "article":
            if self.published_time:
                lines.append(f'{indent}<meta property="article:published_time" content="{escape(self.published_time)}" />')
            if self.modified_time:
                lines.append(f'{indent}<meta property="article:modified_time" content="{escape(self.modified_time)}" />')
            if self.author:
                lines.append(f'{indent}<meta property="article:author" content="{escape(self.author)}" />')
            if self.section:
                lines.append(f'{indent}<meta property="article:section" content="{escape(self.section)}" />')
            for tag in self.tags:
                lines.append(f'{indent}<meta property="article:tag" content="{escape(tag)}" />')

        # Twitter Card
        lines.append("")
        lines.append(f"{indent}<!-- Twitter / X -->")
        lines.append(f'{indent}<meta name="twitter:card" content="{escape(self.card_type)}" />')
        lines.append(f'{indent}<meta name="twitter:url" content="{escape(self.canonical_url or self.url)}" />')
        lines.append(f'{indent}<meta name="twitter:title" content="{escape(self.title)}" />')
        lines.append(f'{indent}<meta name="twitter:description" content="{escape(self.description)}" />')
        if self.image_url:
            lines.append(f'{indent}<meta name="twitter:image" content="{escape(self.image_url)}" />')
            lines.append(f'{indent}<meta name="twitter:image:alt" content="{escape(self.image_alt)}" />')
        if self.twitter_site:
            lines.append(f'{indent}<meta name="twitter:site" content="{escape(self.twitter_site)}" />')
        if self.twitter_handle:
            lines.append(f'{indent}<meta name="twitter:creator" content="{escape(self.twitter_handle)}" />')

        return "\n".join(lines)

    def generate(self) -> Dict[str, Any]:
        """
        Generate complete OpenGraph package including tags, HTML, validation score, and previews.
        """
        tags = self.build_tag_dictionary()
        html_code = self.to_html()
        validation = self.validate()
        previews = self.generate_previews()

        return {
            "tags": tags,
            "html": html_code,
            "score": validation["score"],
            "status": validation["status"],
            "warnings": validation["warnings"],
            "validation": validation,
            "previews": previews,
        }


# =============================================================================
# Functional API
# =============================================================================

def generate_og_meta_tags(
    title: str,
    description: str,
    url: str,
    image_url: Optional[str] = None,
    site_name: Optional[str] = None,
    twitter_handle: Optional[str] = None,
    twitter_site: Optional[str] = None,
    card_type: str = "summary_large_image",
    og_type: str = "website",
    locale: str = "en_US",
    alternate_locales: Optional[List[str]] = None,
    canonical_url: Optional[str] = None,
    image_alt: Optional[str] = None,
    image_width: int = 1200,
    image_height: int = 630,
    published_time: Optional[str] = None,
    modified_time: Optional[str] = None,
    author: Optional[str] = None,
    section: Optional[str] = None,
    tags: Optional[List[str]] = None,
    robots: str = "index, follow",
) -> Dict[str, Any]:
    """
    Generate complete OpenGraph and Twitter Card metadata package.

    Returns:
        Dict containing 'tags', 'html', 'score', 'status', 'warnings', 'validation', 'previews'.
    """
    builder = OpenGraphBuilder(
        title=title,
        description=description,
        url=url,
        image_url=image_url,
        site_name=site_name,
        twitter_handle=twitter_handle,
        twitter_site=twitter_site,
        card_type=card_type,
        og_type=og_type,
        locale=locale,
        alternate_locales=alternate_locales,
        canonical_url=canonical_url,
        image_alt=image_alt,
        image_width=image_width,
        image_height=image_height,
        published_time=published_time,
        modified_time=modified_time,
        author=author,
        section=section,
        tags=tags,
        robots=robots,
    )
    return builder.generate()
