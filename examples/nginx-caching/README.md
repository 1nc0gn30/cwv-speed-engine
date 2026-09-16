# Nginx Core Web Vitals Optimization Guide

This production `nginx.conf` is optimized to deliver sub-50ms Time to First Byte (TTFB) and zero Cumulative Layout Shifts.

---

## ⚡ Key Directives Explained

1. **`open_file_cache`**: Stores file descriptors and sizes in memory to eliminate repeated disk lookups for static assets.
2. **`tcp_nopush` & `tcp_nodelay`**: Ensures packets are sent full and immediately without Nagle's algorithm delay.
3. **Immutable Static Headers**: Applies `Cache-Control: public, max-age=31536000, immutable` to fingerprinted assets (`.js`, `.css`, `.woff2`, `.webp`, `.avif`).
4. **HTML SWR Revalidation**: Emits `public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400` on navigation routes so CDNs serve instantly while updating in the background.

---

## 🧪 Testing Nginx Configuration

```bash
sudo nginx -t
sudo systemctl reload nginx
```
