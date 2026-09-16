# Core Web Vitals Production Reference Architectures

This directory contains battle-tested production examples for maximizing website performance, passing Google Core Web Vitals, and integrating `cwv-speed-engine` into your development lifecycle.

---

## 📂 Production Reference Examples

| Directory | Stack / Target | Focus Areas |
|---|---|---|
| [`nextjs-optimized/`](./nextjs-optimized/) | Next.js 14/15 App Router | `next/image` AVIF, font self-hosting, Early Hints edge middleware, immutable headers |
| [`astro-speed/`](./astro-speed/) | Astro (Zero-JS Island Architecture) | `<SpeedHead />` component, sharp image processing, inlined critical CSS |
| [`pwa-manifest/`](./pwa-manifest/) | Modern PWA & Offline Support | W3C `site.webmanifest`, tiered `sw.js` (SWR + Cache-First), Material 3 `offline.html` |
| [`nginx-caching/`](./nginx-caching/) | Nginx Edge Proxy | Open file cache, Gzip/Brotli, 1-year immutable caching, sub-50ms TTFB |
| [`mcp-clients/`](./mcp-clients/) | AI Coding Agents (Claude, Cursor, Cline, Zed) | Ready-to-copy JSON configuration files for Model Context Protocol integration |

---

## ⚡ Quick Start Testing

You can audit any example locally using `cwv-speed-engine`:

```bash
# Launch interactive Google Material 3 Speed Studio
python -m cwv_speed_engine.ui_server --port 8448 --open
```
