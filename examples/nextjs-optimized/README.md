# Next.js 14/15 Core Web Vitals Optimization Blueprint

This production reference example demonstrates how to achieve a consistent **100/100 Google PageSpeed / Core Web Vitals score** on Next.js 14 (App Router) and Next.js 15.

---

## ⚡ Key Optimizations Implemented

### 1. Zero-CLS Image Strategy (`next/image`)
- Configured AVIF and WebP generation with automatic responsive sizes.
- Set `minimumCacheTTL: 31536000` (1 year) to ensure optimized images are never re-encoded repeatedly on CDN edge nodes.
- Always provide explicit `width` and `height` (or `fill` with parent `aspect-ratio` containment).
- Hero image declared with `priority={true}` and `fetchPriority="high"`.

```tsx
import Image from 'next/image';

export function HeroSection() {
  return (
    <div className="relative aspect-[16/9] w-full max-w-5xl overflow-hidden rounded-2xl">
      <Image
        src="/images/hero-banner.jpg"
        alt="Core Web Vitals Hero"
        fill
        priority
        sizes="(max-width: 768px) 100vw, (max-width: 1200px) 80vw, 1200px"
        className="object-cover"
      />
    </div>
  );
}
```

---

### 2. Next.js Edge Middleware (`middleware.ts`)
- Injects HTTP `Link: <...>; rel=preload; as=font` headers to warm connections and stream critical fonts before HTML execution.
- Emits `Server-Timing` headers to isolate edge vs database execution latency for TTFB tuning.

---

### 3. Font Optimization (`next/font`)
Use `next/font/google` with automatic self-hosting and zero layout shifts:

```tsx
import { Inter } from 'next/font/google';

const inter = Inter({
  subsets: ['latin'],
  display: 'swap',
  variable: '--font-inter',
  adjustFontFallback: true, // Eliminates layout shift during font swap
});
```

---

### 4. Granular Cache-Control Headers (`next.config.js`)
- `/_next/static/*`: `public, max-age=31536000, immutable` (fingerprinted JS/CSS chunks).
- `/fonts/*`: `public, max-age=31536000, immutable`.
- `/:path*` (HTML pages): `public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400`.

---

## 🚀 Auditing with `cwv-speed-engine`

Audit your Next.js application using the CLI:

```bash
cwv-speed audit https://localhost:3000 --device mobile
```
