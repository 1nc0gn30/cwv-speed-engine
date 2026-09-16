"""
PWA Service Worker Engine & Web App Manifest Builder for cwv-speed-engine.

Generates W3C-compliant web app manifests, production-grade zero-dependency
Service Worker scripts with multi-strategy caching (cache-first, network-first,
stale-while-revalidate, offline fallback), HTML head meta tags, and registration snippets.

Zero external dependencies (pure Python standard library).
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field, asdict


# =============================================================================
# Helper Utilities
# =============================================================================

def _slugify(text: str) -> str:
    """Convert text into a URL and cache-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    return text.strip("-") or "pwa-app"


def _escape_js(text: str) -> str:
    """Safely escape text for inclusion in JavaScript single/double quoted strings."""
    return text.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("\n", "\\n")


# =============================================================================
# Data Models
# =============================================================================

@dataclass
class PWAIcon:
    """Specification for an icon entry in the Web App Manifest."""
    src: str
    sizes: str
    type: str = "image/png"
    purpose: str = "any"

    def to_dict(self) -> Dict[str, str]:
        return {
            "src": self.src,
            "sizes": self.sizes,
            "type": self.type,
            "purpose": self.purpose,
        }


@dataclass
class PWAShortcut:
    """Specification for a home-screen quick action shortcut."""
    name: str
    url: str
    short_name: Optional[str] = None
    description: Optional[str] = None
    icons: Optional[List[Dict[str, str]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "url": self.url,
        }
        if self.short_name:
            d["short_name"] = self.short_name
        if self.description:
            d["description"] = self.description
        if self.icons:
            d["icons"] = self.icons
        return d


@dataclass
class PWABundle:
    """Complete bundle containing all generated PWA assets and snippets."""
    manifest: Dict[str, Any]
    manifest_json: str
    service_worker_js: str
    offline_html: str
    html_head_tags: str
    registration_script: str
    icon_specifications: List[Dict[str, Any]]
    files: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest": self.manifest,
            "manifest_json": self.manifest_json,
            "service_worker_js": self.service_worker_js,
            "offline_html": self.offline_html,
            "html_head_tags": self.html_head_tags,
            "registration_script": self.registration_script,
            "icon_specifications": self.icon_specifications,
            "files": self.files,
        }


# =============================================================================
# PWABuilder Class
# =============================================================================

class PWABuilder:
    """
    Builder engine for generating Progressive Web App (PWA) artifacts.
    Produces W3C Web Manifests, Service Worker scripts, offline fallback pages,
    and HTML header tags.
    """

    DEFAULT_ICON_SIZES = [72, 96, 128, 144, 152, 192, 384, 512]

    def __init__(
        self,
        app_name: str,
        short_name: Optional[str] = None,
        description: Optional[str] = None,
        theme_color: str = "#1a73e8",
        bg_color: str = "#ffffff",
        start_url: str = "/",
        display: str = "standalone",
        scope: str = "/",
        orientation: str = "portrait-primary",
        lang: str = "en",
        dir: str = "ltr",
        icon_sizes: Optional[List[int]] = None,
        icon_path_prefix: str = "/icons",
        categories: Optional[List[str]] = None,
        shortcuts: Optional[List[Union[PWAShortcut, Dict[str, Any]]]] = None,
        offline_url: str = "/offline.html",
        cache_version: Optional[str] = None,
        precache_urls: Optional[List[str]] = None,
        static_cache_name: Optional[str] = None,
        runtime_cache_name: Optional[str] = None,
        static_extensions: Optional[List[str]] = None,
        api_path_prefix: str = "/api/",
        sw_scope: str = "/",
    ) -> None:
        self.app_name = app_name.strip()
        self.short_name = (short_name or self.app_name[:12]).strip()
        self.description = description.strip() if description else f"{self.app_name} Web Application"
        self.theme_color = theme_color.strip()
        self.bg_color = bg_color.strip()
        self.start_url = start_url.strip()
        self.display = display.strip()
        self.scope = scope.strip()
        self.orientation = orientation.strip()
        self.lang = lang.strip()
        self.dir = dir.strip()
        self.icon_sizes = sorted(icon_sizes or self.DEFAULT_ICON_SIZES)
        self.icon_path_prefix = icon_path_prefix.rstrip("/")
        self.categories = categories or ["utilities", "productivity"]
        self.shortcuts = shortcuts or []
        self.offline_url = offline_url.strip()
        self.sw_scope = sw_scope.strip()

        # Cache naming
        slug = _slugify(self.app_name)
        ver = cache_version or "v1"
        self.cache_version = ver
        self.static_cache_name = static_cache_name or f"{slug}-static-{ver}"
        self.runtime_cache_name = runtime_cache_name or f"{slug}-runtime-{ver}"

        # Precache URLs
        base_precache = [self.start_url, self.offline_url]
        if precache_urls:
            base_precache.extend(precache_urls)
        # Deduplicate while preserving order
        self.precache_urls = list(dict.fromkeys(base_precache))

        # File extensions for static cache-first routing
        self.static_extensions = static_extensions or [
            "css", "js", "mjs", "png", "jpg", "jpeg", "webp", "avif",
            "svg", "gif", "ico", "woff", "woff2", "ttf", "eot", "otf", "mp3", "mp4"
        ]
        self.api_path_prefix = api_path_prefix

    def build_icons(self) -> List[Dict[str, str]]:
        """Generate manifest icons list including standard and maskable entries."""
        icons = []
        for size in self.icon_sizes:
            src = f"{self.icon_path_prefix}/icon-{size}x{size}.png"
            icons.append({
                "src": src,
                "sizes": f"{size}x{size}",
                "type": "image/png",
                "purpose": "any",
            })
            # Include maskable icons for 192 and 512 as required by modern PWA standards
            if size in (192, 512):
                icons.append({
                    "src": f"{self.icon_path_prefix}/icon-{size}x{size}-maskable.png",
                    "sizes": f"{size}x{size}",
                    "type": "image/png",
                    "purpose": "maskable",
                })
        return icons

    def build_manifest(self) -> Dict[str, Any]:
        """Construct the full W3C-compliant Web App Manifest dictionary."""
        manifest: Dict[str, Any] = {
            "name": self.app_name,
            "short_name": self.short_name,
            "description": self.description,
            "start_url": self.start_url,
            "scope": self.scope,
            "display": self.display,
            "orientation": self.orientation,
            "background_color": self.bg_color,
            "theme_color": self.theme_color,
            "lang": self.lang,
            "dir": self.dir,
            "categories": self.categories,
            "icons": self.build_icons(),
            "prefer_related_applications": False,
            "id": f"{self.start_url}?pwa_id=1",
        }

        # Process shortcuts
        formatted_shortcuts = []
        for s in self.shortcuts:
            if isinstance(s, PWAShortcut):
                formatted_shortcuts.append(s.to_dict())
            elif isinstance(s, dict):
                formatted_shortcuts.append(s)
        if formatted_shortcuts:
            manifest["shortcuts"] = formatted_shortcuts
        else:
            # Default helpful shortcut
            manifest["shortcuts"] = [
                {
                    "name": f"Open {self.short_name}",
                    "short_name": self.short_name,
                    "description": f"Open main view of {self.app_name}",
                    "url": self.start_url,
                    "icons": [{"src": f"{self.icon_path_prefix}/icon-96x96.png", "sizes": "96x96"}]
                }
            ]

        return manifest

    def build_manifest_json(self, indent: int = 2) -> str:
        """Render manifest as formatted JSON string."""
        return json.dumps(self.build_manifest(), indent=indent, ensure_ascii=False)

    def build_service_worker(self) -> str:
        """
        Generate production-grade, zero-dependency Service Worker script.
        Implements Cache-First, Network-First, Stale-While-Revalidate,
        and Offline Fallback strategies with safe lifecycle handling.
        """
        precache_json = json.dumps(self.precache_urls, indent=2)
        ext_pattern = "|".join(re.escape(ext) for ext in self.static_extensions)

        sw_code = f"""/**
 * Service Worker: {self.app_name}
 * Version: {self.cache_version}
 * Generated by cwv-speed-engine (Zero Runtime Dependencies)
 */

'use strict';

const STATIC_CACHE = '{self.static_cache_name}';
const RUNTIME_CACHE = '{self.runtime_cache_name}';
const OFFLINE_URL = '{self.offline_url}';
const PRECACHE_ASSETS = {precache_json};

const STATIC_EXT_REGEX = /\\.({ext_pattern})(\\?.*)?$/i;
const API_PREFIX = '{self.api_path_prefix}';

// ---------------------------------------------------------------------------
// 1. INSTALL EVENT: Pre-cache core shell and offline assets
// ---------------------------------------------------------------------------
self.addEventListener('install', (event) => {{
  event.waitUntil(
    caches.open(STATIC_CACHE)
      .then((cache) => {{
        return cache.addAll(PRECACHE_ASSETS).catch((err) => {{
          console.warn('[SW] Some precache assets failed to load:', err);
        }});
      }})
      .then(() => self.skipWaiting())
  );
}});

// ---------------------------------------------------------------------------
// 2. ACTIVATE EVENT: Cleanup stale caches and take immediate control
// ---------------------------------------------------------------------------
self.addEventListener('activate', (event) => {{
  event.waitUntil(
    caches.keys().then((cacheNames) => {{
      return Promise.all(
        cacheNames.map((cacheName) => {{
          if (cacheName !== STATIC_CACHE && cacheName !== RUNTIME_CACHE) {{
            console.log('[SW] Deleting legacy cache:', cacheName);
            return caches.delete(cacheName);
          }}
        }})
      );
    }}).then(() => self.clients.claim())
  );
}});

// ---------------------------------------------------------------------------
// 3. FETCH EVENT: Intelligent Multi-Strategy Request Router
// ---------------------------------------------------------------------------
self.addEventListener('fetch', (event) => {{
  const request = event.request;
  const url = new URL(request.url);

  // Ignore non-GET requests or non-HTTP/HTTPS schemes (e.g. chrome-extension:)
  if (request.method !== 'GET' || !url.protocol.startsWith('http')) {{
    return;
  }}

  // Strategy A: HTML Navigation Requests -> Network-First with Offline Fallback
  if (request.mode === 'navigate' || (request.headers.get('accept') && request.headers.get('accept').includes('text/html'))) {{
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {{
          if (networkResponse && networkResponse.status === 200) {{
            const copy = networkResponse.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }}
          return networkResponse;
        }})
        .catch(async () => {{
          // Check runtime or static cache for matching HTML
          const cachedResponse = await caches.match(request);
          if (cachedResponse) {{
            return cachedResponse;
          }}
          // Fallback to designated offline page
          const offlineResponse = await caches.match(OFFLINE_URL);
          if (offlineResponse) {{
            return offlineResponse;
          }}
          return new Response(
            '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Offline</title></head>' +
            '<body style="font-family:sans-serif;padding:2rem;text-align:center;">' +
            '<h1>You are currently offline</h1><p>Please check your connection and try again.</p></body></html>',
            {{ status: 503, headers: {{ 'Content-Type': 'text/html' }} }}
          );
        }})
    );
    return;
  }}

  // Strategy B: API Calls -> Network-First with short-term cache fallback
  if (url.pathname.startsWith(API_PREFIX)) {{
    event.respondWith(
      fetch(request)
        .then((networkResponse) => {{
          if (networkResponse && networkResponse.status === 200) {{
            const copy = networkResponse.clone();
            caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
          }}
          return networkResponse;
        }})
        .catch(() => caches.match(request))
    );
    return;
  }}

  // Strategy C: Static Assets (Images, Fonts, CSS, JS) -> Cache-First
  if (STATIC_EXT_REGEX.test(url.pathname)) {{
    event.respondWith(
      caches.match(request).then((cachedResponse) => {{
        if (cachedResponse) {{
          return cachedResponse;
        }}
        return fetch(request).then((networkResponse) => {{
          if (networkResponse && networkResponse.status === 200) {{
            const copy = networkResponse.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(request, copy));
          }}
          return networkResponse;
        }}).catch((err) => {{
          console.warn('[SW] Failed to fetch static asset:', request.url, err);
          return new Response('', {{ status: 408, statusText: 'Request Timeout' }});
        }});
      }})
    );
    return;
  }}

  // Strategy D: All Other Requests -> Stale-While-Revalidate
  event.respondWith(
    caches.match(request).then((cachedResponse) => {{
      const fetchPromise = fetch(request).then((networkResponse) => {{
        if (networkResponse && networkResponse.status === 200) {{
          const copy = networkResponse.clone();
          caches.open(RUNTIME_CACHE).then((cache) => cache.put(request, copy));
        }}
        return networkResponse;
      }}).catch(() => {{
        // Network failed; cachedResponse will be returned if available
      }});
      return cachedResponse || fetchPromise;
    }})
  );
}});
"""
        return sw_code.strip() + "\n"

    def build_offline_page(self) -> str:
        """Generate a sleek, responsive, accessible offline fallback HTML page."""
        html_code = f"""<!DOCTYPE html>
<html lang="{self.lang}" dir="{self.dir}">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="{self.theme_color}">
  <title>Offline | {self.app_name}</title>
  <style>
    :root {{
      --primary: {self.theme_color};
      --bg: {self.bg_color};
      --text: #1f2937;
      --muted: #6b7280;
      --card-bg: #ffffff;
      --border: #e5e7eb;
    }}
    @media (prefers-color-scheme: dark) {{
      :root {{
        --bg: #111827;
        --text: #f9fafb;
        --muted: #9ca3af;
        --card-bg: #1f2937;
        --border: #374151;
      }}
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
      background-color: var(--bg);
      color: var(--text);
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 1.5rem;
      text-align: center;
    }}
    .card {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 1rem;
      padding: 2.5rem 2rem;
      max-width: 480px;
      width: 100%;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    }}
    .icon-wrapper {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      width: 72px;
      height: 72px;
      border-radius: 50%;
      background: rgba(26, 115, 232, 0.1);
      color: var(--primary);
      margin-bottom: 1.5rem;
    }}
    h1 {{
      font-size: 1.5rem;
      font-weight: 700;
      margin-bottom: 0.75rem;
    }}
    p {{
      color: var(--muted);
      font-size: 0.95rem;
      line-height: 1.5;
      margin-bottom: 2rem;
    }}
    .actions {{
      display: flex;
      flex-direction: column;
      gap: 0.75rem;
    }}
    .btn {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 0.75rem 1.5rem;
      font-size: 0.95rem;
      font-weight: 600;
      border-radius: 0.5rem;
      cursor: pointer;
      text-decoration: none;
      transition: all 0.2s ease;
      border: none;
    }}
    .btn-primary {{
      background-color: var(--primary);
      color: #ffffff;
    }}
    .btn-primary:hover {{
      opacity: 0.9;
      transform: translateY(-1px);
    }}
    .btn-secondary {{
      background: transparent;
      color: var(--text);
      border: 1px solid var(--border);
    }}
    .btn-secondary:hover {{
      background: rgba(0, 0, 0, 0.05);
    }}
    .status-indicator {{
      margin-top: 1.5rem;
      font-size: 0.8rem;
      color: var(--muted);
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
    }}
    .status-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: #ef4444;
    }}
  </style>
</head>
<body>
  <main class="card" role="main">
    <div class="icon-wrapper" aria-hidden="true">
      <svg width="36" height="36" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <line x1="1" y1="1" x2="23" y2="23"></line>
        <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55"></path>
        <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39"></path>
        <path d="M10.71 5.05A16 16 0 0 1 22.58 9"></path>
        <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88"></path>
        <path d="M8.53 16.11a6 6 0 0 1 6.95 0"></path>
        <line x1="12" y1="20" x2="12.01" y2="20"></line>
      </svg>
    </div>
    <h1>You're Offline</h1>
    <p>It looks like you've lost internet connection. Check your network or try reloading when you are back online.</p>
    <div class="actions">
      <button class="btn btn-primary" onclick="window.location.reload()">Try Again</button>
      <a class="btn btn-secondary" href="{self.start_url}">Go to Homepage</a>
    </div>
    <div class="status-indicator">
      <span class="status-dot" id="dot"></span>
      <span id="status-text">Disconnected</span>
    </div>
  </main>
  <script>
    window.addEventListener('online', () => {{
      document.getElementById('dot').style.backgroundColor = '#10b981';
      document.getElementById('status-text').textContent = 'Back online! Reloading...';
      setTimeout(() => window.location.reload(), 800);
    }});
  </script>
</body>
</html>
"""
        return html_code.strip() + "\n"

    def build_html_head(self) -> str:
        """Generate HTML `<head>` tags for manifest, PWA theme, and Apple mobile meta."""
        app_name_safe = self.app_name.replace('"', '&quot;')
        short_name_safe = self.short_name.replace('"', '&quot;')
        lines = [
            f'<link rel="manifest" href="/site.webmanifest">',
            f'<meta name="theme-color" content="{self.theme_color}">',
            f'<meta name="mobile-web-app-capable" content="yes">',
            f'<meta name="apple-mobile-web-app-capable" content="yes">',
            f'<meta name="apple-mobile-web-app-status-bar-style" content="default">',
            f'<meta name="apple-mobile-web-app-title" content="{short_name_safe}">',
            f'<link rel="apple-touch-icon" href="{self.icon_path_prefix}/icon-192x192.png">',
        ]
        return "\n".join(lines)

    def build_registration_script(self, sw_url: str = "/sw.js") -> str:
        """Generate client-side Service Worker registration JavaScript snippet."""
        return f"""<script>
  if ('serviceWorker' in navigator) {{
    window.addEventListener('load', () => {{
      navigator.serviceWorker.register('{sw_url}', {{ scope: '{self.sw_scope}' }})
        .then((registration) => {{
          console.log('[PWA] ServiceWorker registered with scope:', registration.scope);
          registration.onupdatefound = () => {{
            const installingWorker = registration.installing;
            if (installingWorker) {{
              installingWorker.onstatechange = () => {{
                if (installingWorker.state === 'installed' && navigator.serviceWorker.controller) {{
                  console.log('[PWA] New content is available; please refresh.');
                }}
              }};
            }}
          }};
        }})
        .catch((error) => {{
          console.error('[PWA] ServiceWorker registration failed:', error);
        }});
    }});
  }}
</script>"""

    def build_bundle(self) -> PWABundle:
        """Generate the complete PWA bundle with all files and metadata."""
        manifest_dict = self.build_manifest()
        manifest_json = self.build_manifest_json()
        sw_js = self.build_service_worker()
        offline_html = self.build_offline_page()
        head_tags = self.build_html_head()
        reg_script = self.build_registration_script()
        icons = self.build_icons()

        files = {
            "site.webmanifest": manifest_json,
            "manifest.json": manifest_json,
            "sw.js": sw_js,
            "offline.html": offline_html,
            "register-sw.js": reg_script.replace("<script>", "").replace("</script>", "").strip(),
        }

        return PWABundle(
            manifest=manifest_dict,
            manifest_json=manifest_json,
            service_worker_js=sw_js,
            offline_html=offline_html,
            html_head_tags=head_tags,
            registration_script=reg_script,
            icon_specifications=icons,
            files=files,
        )

    def export_to_directory(self, output_dir: Union[str, Path]) -> Dict[str, str]:
        """
        Write all bundle files to the specified directory.
        Creates output directory and parent folders if necessary.
        """
        out_path = Path(output_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        bundle = self.build_bundle()
        written_paths: Dict[str, str] = {}

        for filename, content in bundle.files.items():
            file_dest = out_path / filename
            file_dest.write_text(content, encoding="utf-8")
            written_paths[filename] = str(file_dest)

        return written_paths


# =============================================================================
# Functional API
# =============================================================================

def generate_pwa_bundle(
    app_name: str,
    short_name: Optional[str] = None,
    description: Optional[str] = None,
    theme_color: str = "#1a73e8",
    bg_color: str = "#ffffff",
    start_url: str = "/",
    display: str = "standalone",
    scope: str = "/",
    orientation: str = "portrait-primary",
    lang: str = "en",
    dir: str = "ltr",
    icon_sizes: Optional[List[int]] = None,
    icon_path_prefix: str = "/icons",
    categories: Optional[List[str]] = None,
    shortcuts: Optional[List[Dict[str, Any]]] = None,
    offline_url: str = "/offline.html",
    cache_version: Optional[str] = None,
    precache_urls: Optional[List[str]] = None,
    static_extensions: Optional[List[str]] = None,
    api_path_prefix: str = "/api/",
) -> Dict[str, Any]:
    """
    Generate complete Progressive Web App bundle dictionary.

    Returns:
        Dict containing 'manifest', 'manifest_json', 'service_worker_js',
        'offline_html', 'html_head_tags', 'registration_script', 'icon_specifications', 'files'.
    """
    builder = PWABuilder(
        app_name=app_name,
        short_name=short_name,
        description=description,
        theme_color=theme_color,
        bg_color=bg_color,
        start_url=start_url,
        display=display,
        scope=scope,
        orientation=orientation,
        lang=lang,
        dir=dir,
        icon_sizes=icon_sizes,
        icon_path_prefix=icon_path_prefix,
        categories=categories,
        shortcuts=shortcuts,
        offline_url=offline_url,
        cache_version=cache_version,
        precache_urls=precache_urls,
        static_extensions=static_extensions,
        api_path_prefix=api_path_prefix,
    )
    bundle = builder.build_bundle()
    return bundle.to_dict()
