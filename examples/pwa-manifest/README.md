# Progressive Web App (PWA) & Offline Speed Architecture

This directory provides a production-grade Progressive Web App setup with:
1. `site.webmanifest`: Complies with modern W3C standards (maskable icons, shortcuts, category metadata).
2. `sw.js`: Multi-tiered caching service worker (Cache-First for static assets, Stale-While-Revalidate for HTML, Network-First for API).
3. `offline.html`: Material 3 offline fallback page.

---

## 🛠️ Installation & Head Registration

Add the following snippet to your `<head>` tag:

```html
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#1a73e8">
<link rel="apple-touch-icon" href="/icons/icon-192x192.png">

<script>
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js')
        .then((reg) => console.log('PWA ServiceWorker registered with scope:', reg.scope))
        .catch((err) => console.error('PWA ServiceWorker registration failed:', err));
    });
  }
</script>
```

---

## 🚀 Instant Generation via CLI / UI

You can generate customized PWA bundles via `cwv-speed-engine`:

```bash
# In the Google Speed Studio Web UI:
# Navigate to the "PWA & Service Worker Studio" tab and click "Download PWA Bundle (.zip)"
```
