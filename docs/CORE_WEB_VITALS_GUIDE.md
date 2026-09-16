# Complete Google Core Web Vitals (CWV) Guide (2024–2026 Standards)

Core Web Vitals are Google's standardized metrics for measuring real-world user experience on the web. They form an essential ranking signal in Google Search and directly impact user bounce rate, session duration, and e-commerce conversion rates.

---

## 📊 Core Web Vitals Metric Matrix

| Metric | Full Name | Target (Good) | Needs Improvement | Poor |
|---|---|---|---|---|
| **LCP** | Largest Contentful Paint | **&le; 2.5s** | 2.5s – 4.0s | &gt; 4.0s |
| **CLS** | Cumulative Layout Shift | **&le; 0.10** | 0.10 – 0.25 | &gt; 0.25 |
| **INP** | Interaction to Next Paint | **&le; 200ms** | 200ms – 500ms | &gt; 500ms |
| **FCP** | First Contentful Paint | **&le; 1.8s** | 1.8s – 3.0s | &gt; 3.0s |
| **TTFB** | Time to First Byte | **&le; 800ms** | 800ms – 1800ms | &gt; 1800ms |

---

## 1. Largest Contentful Paint (LCP)

### What it Measures
The time from navigation start until the largest visible text block or image in the initial viewport is fully rendered.

### Common Bottlenecks & Causes
1. **Slow Resource Load Time**: Uncompressed PNG/JPEG hero images, large video banners, or unoptimized background images.
2. **Render-Blocking CSS and JavaScript**: Synchronous `<link rel="stylesheet">` or `<script>` tags in `<head>` preventing paint.
3. **Slow Server Response Times (TTFB)**: Uncached dynamic server rendering, slow database queries, or lack of CDN edge caching.
4. **Client-Side Rendering (CSR)**: Single Page Apps fetching data and injecting hero markup late in the execution pipeline.

### Step-by-Step Mitigation Checklist
- **Add `fetchpriority="high"` and `loading="eager"`** to the above-the-fold hero `<img>`.
- **Preload the Hero Asset**:
  ```html
  <link rel="preload" as="image" href="/hero.webp" fetchpriority="high">
  ```
- **Modern Next-Gen Formats**: Deliver AVIF and WebP images with responsive `srcset` definitions.
- **Preconnect to Critical Origins**:
  ```html
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  ```
- **Inline Critical CSS**: Put above-the-fold CSS directly in `<style>` inside `<head>`.

---

## 2. Cumulative Layout Shift (CLS)

### What it Measures
The sum total of all unexpected layout shifts occurring during the entire lifespan of the page.

$$\text{Layout Shift Score} = \text{Impact Fraction} \times \text{Distance Fraction}$$

### Common Bottlenecks & Causes
1. **Images & Iframes Without Explicit Dimensions**: Browser does not know the aspect ratio prior to resource download.
2. **FOIT / FOUT Web Fonts**: Custom web fonts swapping with fallback fonts of differing metric bounding boxes.
3. **Dynamically Injected Ads & Widgets**: Third-party scripts inserting DOM elements without reserved container heights.

### Step-by-Step Mitigation Checklist
- **Explicit Width & Height on All `<img>` and `<video>` tags**:
  ```html
  <img src="/photo.webp" width="800" height="500" alt="Product" style="max-width: 100%; height: auto;">
  ```
- **CSS `aspect-ratio` Containment**:
  ```css
  .card-media {
    aspect-ratio: 16 / 9;
    width: 100%;
  }
  ```
- **Font Display Swap with Size Adjustment**:
  ```css
  @font-face {
    font-family: 'CustomFont';
    src: url('/font.woff2') format('woff2');
    font-display: swap;
    size-adjust: 102.5%;
    ascent-override: 95%;
  }
  ```
- **Reserved Slots for Banners & Ads**:
  ```css
  .ad-slot {
    min-height: 250px;
    contain-intrinsic-size: 300px 250px;
    content-visibility: auto;
  }
  ```

---

## 3. Interaction to Next Paint (INP)

### What it Measures
Replaces First Input Delay (FID). INP measures the overall responsiveness of the page to all user clicks, taps, and keyboard interactions throughout the entire visit.

### Common Bottlenecks & Causes
1. **Long Tasks (> 50ms) on Main Thread**: Heavy JavaScript computation blocking user inputs.
2. **Excessive DOM Size (> 1,500 nodes)**: Huge style recalculation and layout passes.
3. **Synchronous Third-Party Scripts**: Analytics, chat widgets, and trackers running synchronous handlers.

### Step-by-Step Mitigation Checklist
- **Break Up Long Tasks with `scheduler.yield()`**:
  ```javascript
  async function processLargeData(items) {
    for (const item of items) {
      processItem(item);
      if ('scheduler' in window && 'yield' in window.scheduler) {
        await window.scheduler.yield();
      } else {
        await new Promise((resolve) => setTimeout(resolve, 0));
      }
    }
  }
  ```
- **Move Heavy Work to Web Workers**: Run physics, image processing, and heavy sorting off the main thread.
- **Debounce Event Listeners**: Wrap scroll, resize, and typing handlers in `requestAnimationFrame` or debouncers.
- **Defer Non-Critical Scripts**: Add `defer` or `async` to all external script tags.

---

## 4. First Contentful Paint (FCP) & Time to First Byte (TTFB)

- **FCP (&le; 1.8s)**: Unblock the critical rendering path. Ensure HTML document size is lean and no render-blocking CSS/JS blocks initial frame.
- **TTFB (&le; 800ms)**: Utilize edge caching (Netlify, Vercel, Cloudflare, Fastly), enable HTTP/2 or HTTP/3, and configure keep-alive connections.

---

## 🛠️ Automated Remediation with `cwv-speed-engine`

```bash
# Automated audit and report
cwv-speed audit https://example.com --device mobile

# Automated HTML transformation
cwv-speed optimize unoptimized.html -o index.html
```
