"""
Unit tests for OpenGraph & Social Meta Tag Builder (og_builder.py).
"""

import pytest
from cwv_speed_engine.og_builder import (
    OpenGraphBuilder,
    generate_og_meta_tags,
    _truncate,
    _infer_mime_type,
    _format_twitter_handle,
)


class TestOpenGraphBuilder:
    """Test suite for OpenGraphBuilder and generate_og_meta_tags."""

    def test_helpers(self):
        # Truncate
        assert _truncate("Short text", 20) == "Short text"
        assert _truncate("This is a long sentence that should truncate cleanly", 30) == "This is a long sentence..."

        # MIME types
        assert _infer_mime_type("https://example.com/banner.png") == "image/png"
        assert _infer_mime_type("https://example.com/photo.jpeg") == "image/jpeg"
        assert _infer_mime_type("https://example.com/graphic.webp") == "image/webp"
        assert _infer_mime_type("https://example.com/vector.svg") == "image/svg+xml"

        # Twitter handle
        assert _format_twitter_handle("johndoe") == "@johndoe"
        assert _format_twitter_handle("@johndoe") == "@johndoe"
        assert _format_twitter_handle("https://twitter.com/johndoe") == "@johndoe"
        assert _format_twitter_handle(None) is None

    def test_optimal_metadata_generation(self):
        title = "Core Web Vitals Speed Engine - Zero Overhead Optimizer"  # 55 chars (optimal)
        description = "Boost your website performance scores, optimize Core Web Vitals (LCP, CLS, INP), and automate CI performance quality gates with zero dependencies."  # 153 chars (optimal)
        url = "https://speed.example.com/engine"
        image = "https://speed.example.com/assets/og-cover.png"

        result = generate_og_meta_tags(
            title=title,
            description=description,
            url=url,
            image_url=image,
            site_name="SpeedPulse",
            twitter_handle="@speedpulse",
            card_type="summary_large_image",
            og_type="website",
            image_width=1200,
            image_height=630,
        )

        assert isinstance(result, dict)
        tags = result["tags"]

        # OpenGraph checks
        assert tags["og:title"] == title
        assert tags["og:description"] == description
        assert tags["og:url"] == url
        assert tags["og:type"] == "website"
        assert tags["og:site_name"] == "SpeedPulse"
        assert tags["og:image"] == image
        assert tags["og:image:width"] == "1200"
        assert tags["og:image:height"] == "630"
        assert tags["og:image:type"] == "image/png"

        # Twitter Card checks
        assert tags["twitter:card"] == "summary_large_image"
        assert tags["twitter:title"] == title
        assert tags["twitter:description"] == description
        assert tags["twitter:image"] == image
        assert tags["twitter:creator"] == "@speedpulse"

        # HTML formatting checks
        html_code = result["html"]
        assert '<meta property="og:title"' in html_code
        assert '<meta name="twitter:card"' in html_code
        assert '<link rel="canonical"' in html_code

        # High score on optimal input
        assert result["score"] >= 90
        assert result["status"] in ("excellent", "good")

    def test_article_metadata(self):
        result = generate_og_meta_tags(
            title="How to Optimize INP for Modern Single Page Applications",
            description="A comprehensive guide to debugging and optimizing Interaction to Next Paint (INP) in JavaScript-heavy web applications.",
            url="https://speed.example.com/blog/inp-optimization",
            image_url="https://speed.example.com/images/inp-hero.jpg",
            og_type="article",
            published_time="2026-09-15T08:00:00Z",
            modified_time="2026-09-16T12:00:00Z",
            author="Performance Expert",
            section="Web Performance",
            tags=["INP", "Web Vitals", "Optimization"],
        )

        tags = result["tags"]
        assert tags["og:type"] == "article"
        assert tags["article:published_time"] == "2026-09-15T08:00:00Z"
        assert tags["article:author"] == "Performance Expert"
        assert tags["article:section"] == "Web Performance"

        html_code = result["html"]
        assert '<meta property="article:published_time"' in html_code
        assert '<meta property="article:tag" content="INP"' in html_code

    def test_validation_warnings_and_penalties(self):
        # Test case: too short title, too short description, missing image, non-absolute url
        builder = OpenGraphBuilder(
            title="Short",  # 5 chars (<30)
            description="Too short",  # 9 chars (<70)
            url="/relative-path",  # Not absolute
            image_url=None,  # Missing image
        )
        validation = builder.validate()

        assert validation["score"] < 50
        assert validation["status"] == "poor"

        warning_fields = [w["field"] for w in validation["warnings"]]
        assert "title" in warning_fields
        assert "description" in warning_fields
        assert "image_url" in warning_fields
        assert "url" in warning_fields

    def test_simulated_previews(self):
        builder = OpenGraphBuilder(
            title="Ultra Long Title That Will Exceed Normal Search Engine Boundaries And Definitely Get Truncated In Results",
            description="Ultra long description that provides extensive details beyond what Google Search SERP snippet or Facebook/Twitter cards will display without appending an ellipsis at the end of the text.",
            url="https://example.com/category/product-slug",
            image_url="https://example.com/img.png",
            site_name="ExampleSite",
            twitter_handle="example",
        )
        previews = builder.generate_previews()

        assert "google_search" in previews
        assert "twitter_card" in previews
        assert "social_share" in previews

        # Google preview checks
        g = previews["google_search"]
        assert g["is_title_truncated"] is True
        assert g["is_desc_truncated"] is True
        assert g["url_display"] == "https://example.com > category > product-slug"

        # Twitter Card preview checks
        t = previews["twitter_card"]
        assert t["card_type"] == "summary_large_image"
        assert t["domain"] == "example.com"
        assert t["creator"] == "@example"

        # Social preview checks
        s = previews["social_share"]
        assert s["site_name"] == "ExampleSite"
        assert s["domain"] == "EXAMPLE.COM"

    def test_special_characters_escaping(self):
        builder = OpenGraphBuilder(
            title='Web & Mobile "Speed" Engine <v2>',
            description='Analyze "Core Web Vitals" & fix CLS < 0.1 & INP < 200ms today!',
            url="https://example.com/item?foo=1&bar=2",
            image_url="https://example.com/og.png?v=1&size=large",
        )
        html_code = builder.to_html()
        assert "&quot;Speed&quot;" in html_code or '"Speed"' not in html_code.split("<title>")[1]
        assert "&amp;" in html_code
        assert "<v2>" not in html_code  # Escaped to &lt;v2&gt;

    def test_image_dimension_warnings(self):
        builder = OpenGraphBuilder(
            title="Optimized Title for Web Vitals",
            description="Complete and comprehensive description for testing image warnings.",
            url="https://example.com",
            image_url="http://insecure.example.com/small.png",
            image_width=400,
            image_height=200,
        )
        val = builder.validate()
        warning_fields = [w["field"] for w in val["warnings"]]
        assert "image_dimensions" in warning_fields
        assert "image_url" in warning_fields
