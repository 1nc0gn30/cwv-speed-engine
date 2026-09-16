import { defineConfig, passthroughImageService } from 'astro/config';

/**
 * Astro High-Performance Core Web Vitals Configuration
 * - Zero JS shipped by default (Island architecture)
 * - Automatic image conversion to WebP/AVIF with Sharp
 * - Inlines stylesheets under 4kb to prevent render-blocking FCP
 * - Prefetches links on hover/viewport for sub-100ms transitions
 */
export default defineConfig({
  site: 'https://speed-demo.example.com',
  output: 'static',
  build: {
    inlineStylesheets: 'auto', // Inlines small CSS into <head>
    assets: '_astro',
  },
  prefetch: {
    prefetchAll: true,
    defaultStrategy: 'hover',
  },
  image: {
    service: {
      entrypoint: 'astro/assets/services/sharp',
    },
    domains: ['images.unsplash.com', 'assets.example.com'],
  },
  compressHTML: true,
});
