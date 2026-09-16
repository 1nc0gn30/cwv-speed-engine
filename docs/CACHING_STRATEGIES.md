# High-Performance Caching & HTTP Headers Guide

Proper caching is the single most effective way to eliminate server latency, minimize bandwidth consumption, and achieve sub-50ms Time to First Byte (TTFB).

---

## 🎯 The Three Golden Rules of Web Caching

1. **Fingerprinted Static Assets (CSS, JS, Fonts, Images)**:
   - Cache forever (1 year): `Cache-Control: public, max-age=31536000, immutable`.
   - Never revalidate. When code changes, the build system generates a new unique hash in the filename (e.g. `bundle.a8f92b.js`).

2. **HTML Pages & Navigation Routes**:
   - Never store stale HTML permanently.
   - Use Edge SWR: `Cache-Control: public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400`.
   - The browser always revalidates with the edge CDN. The CDN serves instantaneous cached HTML while fetching the origin in the background.

3. **Service Workers & PWA Manifests**:
   - Must never be cached: `Cache-Control: public, max-age=0, must-revalidate`.

---

## 📜 Complete Directives Reference

| Directive | Type | Purpose |
|---|---|---|
| `public` | Response | Allows caching by both browser and intermediate CDN edge caches. |
| `private` | Response | Only user's browser may cache (for authenticated pages). |
| `max-age=<sec>` | Response | Duration in seconds the browser considers the resource fresh. |
| `s-maxage=<sec>` | Response | Overrides `max-age` for shared edge caches (CDNs). |
| `immutable` | Response | Informs browser the resource will never change; skips revalidation on user refresh. |
| `must-revalidate` | Response | Tells browser stale resources must not be used without contacting the server. |
| `stale-while-revalidate=<sec>` | Response | Allows serving stale cache while updating in the background. |
| `stale-if-error=<sec>` | Response | Allows serving stale cache if the origin server returns 500/502 error. |

---

## 🚀 Platform Configuration Recipes

### 1. Netlify (`_headers`)

```text
# Immutable static assets
/static/*
  Cache-Control: public, max-age=31536000, immutable
/_next/static/*
  Cache-Control: public, max-age=31536000, immutable

# Modern Fonts
/*.woff2
  Cache-Control: public, max-age=31536000, immutable
  Access-Control-Allow-Origin: *

# HTML Pages
/*
  Cache-Control: public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400
  X-Content-Type-Options: nosniff
  X-Frame-Options: SAMEORIGIN
  Referrer-Policy: strict-origin-when-cross-origin
```

---

### 2. Vercel (`vercel.json`)

```json
{
  "headers": [
    {
      "source": "/(.*)\\.(js|css|woff2|avif|webp)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=31536000, immutable" }
      ]
    },
    {
      "source": "/(.*)",
      "headers": [
        { "key": "Cache-Control", "value": "public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400" },
        { "key": "X-Content-Type-Options", "value": "nosniff" },
        { "key": "X-Frame-Options", "value": "SAMEORIGIN" }
      ]
    }
  ]
}
```

---

### 3. Nginx (`nginx.conf`)

```nginx
location ~* \.(?:css|js|woff2|woff|ttf|avif|webp|png|jpg|svg)$ {
    expires 1y;
    add_header Cache-Control "public, max-age=31536000, immutable";
    access_log off;
}

location / {
    add_header Cache-Control "public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400";
    try_files $uri $uri/ /index.html;
}
```

---

## 🔄 Service Worker vs Browser HTTP Cache

```
[ Incoming Browser Request ]
            │
            ▼
    [ Service Worker ]  <─── Handles custom offline routing & background sync
      ├── Cache Match? (CacheStorage API)
      └── Network Fetch
            │
            ▼
    [ Browser HTTP Cache ]  <─── Governed by Cache-Control headers
      ├── Fresh? (max-age / immutable)
      └── Conditional Request (ETag / If-None-Match)
            │
            ▼
    [ CDN Edge Cache ]  <─── Governed by s-maxage / stale-while-revalidate
            │
            ▼
    [ Origin Web Server ]
```
