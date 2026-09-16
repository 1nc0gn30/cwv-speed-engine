"""
Unit tests for PWA Service Worker Engine & Web App Manifest Builder (pwa_builder.py).
"""

import json
import os
import tempfile
from pathlib import Path
import pytest

from cwv_speed_engine.pwa_builder import (
    PWABuilder,
    PWABundle,
    PWAIcon,
    PWAShortcut,
    generate_pwa_bundle,
    _slugify,
)


class TestPWABuilder:
    """Test suite for PWABuilder and generate_pwa_bundle."""

    def test_slugify(self):
        assert _slugify("My App 2026!") == "my-app-2026"
        assert _slugify("Speed & Performance") == "speed-performance"
        assert _slugify("---") == "pwa-app"

    def test_generate_pwa_bundle_defaults(self):
        bundle = generate_pwa_bundle(app_name="SpeedPulse")

        assert isinstance(bundle, dict)
        assert "manifest" in bundle
        assert "manifest_json" in bundle
        assert "service_worker_js" in bundle
        assert "offline_html" in bundle
        assert "html_head_tags" in bundle
        assert "registration_script" in bundle
        assert "icon_specifications" in bundle
        assert "files" in bundle

        # Check Manifest Fields
        manifest = bundle["manifest"]
        assert manifest["name"] == "SpeedPulse"
        assert manifest["short_name"] == "SpeedPulse"
        assert manifest["theme_color"] == "#1a73e8"
        assert manifest["background_color"] == "#ffffff"
        assert manifest["display"] == "standalone"
        assert manifest["start_url"] == "/"
        assert manifest["scope"] == "/"
        assert manifest["prefer_related_applications"] is False

        # Check Icons
        icons = manifest["icons"]
        assert len(icons) >= 8
        sizes = [icon["sizes"] for icon in icons]
        assert "192x192" in sizes
        assert "512x512" in sizes

        # Check Maskable Icon
        maskable_icons = [icon for icon in icons if icon["purpose"] == "maskable"]
        assert len(maskable_icons) >= 2  # 192 and 512

    def test_custom_pwa_bundle_parameters(self):
        custom_shortcuts = [
            {"name": "Dashboard", "url": "/dashboard"},
            {"name": "Audit", "url": "/audit"},
        ]
        bundle = generate_pwa_bundle(
            app_name="Super Store Pro",
            short_name="SuperStore",
            description="Ultra-fast e-commerce experience",
            theme_color="#000000",
            bg_color="#121212",
            start_url="/home",
            scope="/app/",
            display="fullscreen",
            orientation="landscape",
            icon_sizes=[192, 512],
            categories=["shopping", "finance"],
            shortcuts=custom_shortcuts,
            cache_version="v2.4",
            precache_urls=["/css/theme.css", "/js/bundle.js"],
        )

        manifest = bundle["manifest"]
        assert manifest["name"] == "Super Store Pro"
        assert manifest["short_name"] == "SuperStore"
        assert manifest["theme_color"] == "#000000"
        assert manifest["background_color"] == "#121212"
        assert manifest["start_url"] == "/home"
        assert manifest["scope"] == "/app/"
        assert manifest["display"] == "fullscreen"
        assert manifest["orientation"] == "landscape"
        assert manifest["categories"] == ["shopping", "finance"]
        assert len(manifest["shortcuts"]) == 2
        assert manifest["shortcuts"][0]["name"] == "Dashboard"

        # Check Service Worker contents
        sw = bundle["service_worker_js"]
        assert "super-store-pro-static-v2.4" in sw
        assert "super-store-pro-runtime-v2.4" in sw
        assert "/css/theme.css" in sw
        assert "/js/bundle.js" in sw
        assert "/home" in sw
        assert "/offline.html" in sw

    def test_service_worker_strategies_and_lifecycle(self):
        builder = PWABuilder(
            app_name="FastWeb",
            cache_version="v1.0",
            offline_url="/custom-offline.html",
        )
        sw = builder.build_service_worker()

        # Lifecycle checks
        assert "self.addEventListener('install'" in sw
        assert "self.skipWaiting()" in sw
        assert "self.addEventListener('activate'" in sw
        assert "self.clients.claim()" in sw
        assert "caches.delete(cacheName)" in sw

        # Multi-strategy routing checks
        assert "request.mode === 'navigate'" in sw  # HTML navigation network-first
        assert "/custom-offline.html" in sw        # Offline fallback
        assert "STATIC_EXT_REGEX" in sw            # Static cache-first
        assert "caches.match(request)" in sw       # Cache lookup
        assert "API_PREFIX" in sw                  # API network-first

    def test_offline_page_rendering(self):
        builder = PWABuilder(
            app_name="DocEngine",
            theme_color="#ff5500",
            bg_color="#fafafa",
            lang="en",
        )
        offline_html = builder.build_offline_page()

        assert "<!DOCTYPE html>" in offline_html
        assert "DocEngine" in offline_html
        assert "#ff5500" in offline_html
        assert "#fafafa" in offline_html
        assert "window.location.reload()" in offline_html
        assert "window.addEventListener('online'" in offline_html
        assert 'role="main"' in offline_html

    def test_html_head_tags_and_registration(self):
        builder = PWABuilder(
            app_name="My PWA Application",
            short_name="MyPWA",
            theme_color="#3b82f6",
        )
        head = builder.build_html_head()
        assert '<link rel="manifest" href="/site.webmanifest">' in head
        assert '<meta name="theme-color" content="#3b82f6">' in head
        assert '<meta name="apple-mobile-web-app-title" content="MyPWA">' in head
        assert '<link rel="apple-touch-icon"' in head

        reg = builder.build_registration_script("/service-worker.js")
        assert "navigator.serviceWorker.register('/service-worker.js'" in reg
        assert "registration.onupdatefound" in reg

    def test_export_to_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            builder = PWABuilder(app_name="ExportTestApp", theme_color="#10b981")
            files_written = builder.export_to_directory(tmpdir)

            assert "site.webmanifest" in files_written
            assert "sw.js" in files_written
            assert "offline.html" in files_written
            assert "register-sw.js" in files_written

            # Verify files actually exist on disk
            for filename, path_str in files_written.items():
                p = Path(path_str)
                assert p.exists()
                assert p.stat().st_size > 0

            # Validate generated JSON manifest
            manifest_content = Path(files_written["site.webmanifest"]).read_text(encoding="utf-8")
            parsed_manifest = json.loads(manifest_content)
            assert parsed_manifest["name"] == "ExportTestApp"
            assert parsed_manifest["theme_color"] == "#10b981"

    def test_pwa_shortcut_dataclass_and_custom_extensions(self):
        shortcut_obj = PWAShortcut(
            name="Quick Scan",
            url="/scan",
            short_name="Scan",
            description="Perform instant CWV audit",
            icons=[{"src": "/icons/scan-96.png", "sizes": "96x96"}]
        )
        builder = PWABuilder(
            app_name="App With Shortcuts",
            shortcuts=[shortcut_obj],
            static_extensions=["wasm", "json", "woff2"],
            api_path_prefix="/v1/api/",
        )
        manifest = builder.build_manifest()
        assert len(manifest["shortcuts"]) == 1
        assert manifest["shortcuts"][0]["name"] == "Quick Scan"
        assert manifest["shortcuts"][0]["url"] == "/scan"

        sw = builder.build_service_worker()
        assert "wasm|json|woff2" in sw
        assert "/v1/api/" in sw
