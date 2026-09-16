# Astro Speed & Core Web Vitals Optimization Blueprint

Astro is designed for content-focused websites, offering **Zero JavaScript by default**. This example details the optimal configuration and `<SpeedHead />` component to score a perfect **100/100 Core Web Vitals score**.

---

## 🚀 Key Advantages in Astro

1. **Island Architecture**: Client-side JavaScript is only loaded when an interactive component is explicitly marked with `client:visible` or `client:idle`.
2. **Sharp Image Optimization**: Automatically generates modern WebP and AVIF formats with responsive srcset attributes.
3. **Critical CSS Inlining**: Inlines styles under 4kb directly into the HTML document to achieve sub-0.6s First Contentful Paint (FCP).

---

## 🛠️ Usage

Import `SpeedHead.astro` in your main layout:

```astro
---
import SpeedHead from '../components/SpeedHead.astro';
---

<!DOCTYPE html>
<html lang="en">
  <head>
    <SpeedHead
      title="Astro High Speed Experience"
      description="Optimized with cwv-speed-engine for 100/100 Core Web Vitals."
      heroImagePreload="/images/hero-lcp.webp"
    />
  </head>
  <body>
    <slot />
  </body>
</html>
```
