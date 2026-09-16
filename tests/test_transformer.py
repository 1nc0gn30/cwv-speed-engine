"""Comprehensive test suite for transformer.py HTML Speed Optimizer."""

from __future__ import annotations

import re
import pytest
from cwv_speed_engine.transformer import HTMLSpeedTransformer, optimize_html_speed


SAMPLE_UNOPTIMIZED_HTML = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Unoptimized Site</title>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Roboto">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js"></script>
  <script src="/main.js"></script>
  <style>
    @font-face {
      font-family: 'LocalSerif';
      src: url('/fonts/serif.woff2') format('woff2');
    }
  </style>
</head>
<body>
  <div class="hero">
    <!-- Hero image mistakenly marked lazy -->
    <img src="/hero.jpg" alt="Hero Banner" loading="lazy">
  </div>
  <div class="gallery">
    <img src="/img1.jpg" alt="Gallery 1">
    <img src="/img2.jpg" alt="Gallery 2" loading="eager">
    <img src="/img3.jpg" alt="Gallery 3">
  </div>
</body>
</html>"""


def test_image_transformations():
    """Test hero image and below-the-fold image optimizations."""
    res = optimize_html_speed(SAMPLE_UNOPTIMIZED_HTML)
    html = res["transformed_html"]

    # 1. Hero image must not have loading="lazy", must have fetchpriority="high" and decoding="async"
    hero_match = re.search(r'<img[^>]*src="/hero\.jpg"[^>]*>', html)
    assert hero_match is not None
    hero_tag = hero_match.group(0)
    assert 'loading="lazy"' not in hero_tag
    assert 'fetchpriority="high"' in hero_tag
    assert 'decoding="async"' in hero_tag
    assert 'width="1200"' in hero_tag
    assert 'height="675"' in hero_tag

    # 2. Subsequent images (img1) should get loading="lazy", decoding="async", and dimensions
    img1_match = re.search(r'<img[^>]*src="/img1\.jpg"[^>]*>', html)
    assert img1_match is not None
    img1_tag = img1_match.group(0)
    assert 'loading="lazy"' in img1_tag
    assert 'decoding="async"' in img1_tag
    assert 'width="800"' in img1_tag
    assert 'height="600"' in img1_tag

    # 3. Explicit loading="eager" should be respected on img2
    img2_match = re.search(r'<img[^>]*src="/img2\.jpg"[^>]*>', html)
    assert img2_match is not None
    img2_tag = img2_match.group(0)
    assert 'loading="eager"' in img2_tag
    assert 'decoding="async"' in img2_tag


def test_font_and_preconnect_transformations():
    """Test Google Fonts display=swap injection and preconnect resource hints."""
    res = optimize_html_speed(SAMPLE_UNOPTIMIZED_HTML)
    html = res["transformed_html"]

    # Google fonts link should have display=swap
    assert "family=Roboto&display=swap" in html or "family=Roboto?display=swap" in html

    # Preconnect hints in head
    assert '<link rel="preconnect" href="https://fonts.googleapis.com">' in html
    assert '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>' in html

    # Inline @font-face should have font-display: swap
    assert "font-display: swap;" in html


def test_script_defer_transformations():
    """Test script deferral for external JS."""
    res = optimize_html_speed(SAMPLE_UNOPTIMIZED_HTML)
    html = res["transformed_html"]

    # External scripts should have defer
    assert '<script src="https://cdnjs.cloudflare.com/ajax/libs/lodash.js/4.17.21/lodash.min.js" defer></script>' in html or 'defer' in html
    assert '<script src="/main.js" defer></script>' in html

    # CDN resource hints for cdnjs
    assert '<link rel="preconnect" href="https://cdnjs.cloudflare.com" crossorigin>' in html


def test_idempotency():
    """Test that applying optimization multiple times produces stable idempotent output."""
    res1 = optimize_html_speed(SAMPLE_UNOPTIMIZED_HTML)
    html1 = res1["transformed_html"]

    res2 = optimize_html_speed(html1)
    html2 = res2["transformed_html"]

    assert html1 == html2
    # Ensure no duplicate attributes exist
    assert html2.count('fetchpriority="high"') == 1
    assert html2.count('<link rel="preconnect" href="https://fonts.googleapis.com">') == 1


def test_minification():
    """Test optional whitespace and comment minification."""
    html_with_comments = """<!DOCTYPE html>
    <html>
    <head>
      <!-- Critical SEO Meta -->
      <meta charset="UTF-8">
    </head>
    <body>
      <pre>  Preserve   Exact   Spacing  </pre>
      <div>
        <p>Text</p>
      </div>
    </body>
    </html>"""

    res = optimize_html_speed(html_with_comments, options={"minify": True})
    minified = res["transformed_html"]

    # Comment should be stripped
    assert "Critical SEO Meta" not in minified
    # Pre content should be intact
    assert "<pre>  Preserve   Exact   Spacing  </pre>" in minified
    # Whitespace between tags collapsed
    assert "><meta" in minified or "> <meta" in minified or "</head><body" in minified


def test_custom_options_and_self_closing():
    """Test custom dimension options, self-closing img tags, and scripts with type=module."""
    html = """<!DOCTYPE html>
    <html>
    <body>
      <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Poppins">
      <img src="/hero.png" />
      <img src="/card.png" />
      <script type="module" src="/module.js"></script>
      <script data-blocking="true" src="/critical.js"></script>
    </body>
    </html>"""

    res = optimize_html_speed(
        html,
        options={
            "hero_width": "1920",
            "hero_height": "1080",
            "default_width": "400",
            "default_height": "300",
        },
    )
    transformed = res["transformed_html"]

    # Head should be injected automatically before body with preconnect tags
    assert "<head>" in transformed
    assert '<link rel="preconnect" href="https://fonts.googleapis.com">' in transformed

    # Check custom dimensions
    assert 'width="1920"' in transformed
    assert 'height="1080"' in transformed
    assert 'width="400"' in transformed
    assert 'height="300"' in transformed

    # Module script and data-blocking script should NOT have defer added
    assert '<script type="module" src="/module.js"></script>' in transformed
    assert '<script data-blocking="true" src="/critical.js"></script>' in transformed
