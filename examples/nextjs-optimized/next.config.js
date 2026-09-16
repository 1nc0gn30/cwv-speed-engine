/**
 * Next.js 14/15 Production Speed Configuration
 * Optimized for 100/100 Core Web Vitals (LCP < 1.2s, CLS 0, INP < 50ms)
 *
 * @type {import('next').NextConfig}
 */
const nextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  compress: true,

  // 1. Next.js Image Optimization Pipeline
  images: {
    formats: ['image/avif', 'image/webp'],
    deviceSizes: [640, 750, 828, 1080, 1200, 1920, 2048],
    imageSizes: [16, 32, 48, 64, 96, 128, 256, 384],
    minimumCacheTTL: 31536000, // 1 year immutable image caching
    dangerouslyAllowSVG: true,
    contentDispositionType: 'attachment',
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },

  // 2. Experimental Compilation Optimizations
  experimental: {
    optimizePackageImports: [
      'lucide-react',
      '@heroicons/react',
      'framer-motion',
      'date-fns',
      'lodash-es',
    ],
    optimizeCss: true, // Inlines critical CSS & purges unused CSS chunks
    scrollRestoration: true,
  },

  // 3. Granular Production Caching and Security Headers
  async headers() {
    return [
      {
        // Immutable Next.js static asset bundles (JS, CSS chunks)
        source: '/_next/static/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
        ],
      },
      {
        // Immutable WOFF2 web fonts
        source: '/fonts/:path*',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable',
          },
          {
            key: 'Access-Control-Allow-Origin',
            value: '*',
          },
        ],
      },
      {
        // Service Worker: must never be cached across deployments
        source: '/sw.js',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=0, must-revalidate',
          },
          {
            key: 'Service-Worker-Allowed',
            value: '/',
          },
        ],
      },
      {
        // Web Manifest: instant revalidation
        source: '/(site\\.webmanifest|manifest\\.json)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=0, must-revalidate',
          },
          {
            key: 'Content-Type',
            value: 'application/manifest+json; charset=utf-8',
          },
        ],
      },
      {
        // HTML Pages & Dynamic Routes: Edge SWR revalidation
        source: '/:path*',
        headers: [
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
          {
            key: 'X-Frame-Options',
            value: 'SAMEORIGIN',
          },
          {
            key: 'Referrer-Policy',
            value: 'strict-origin-when-cross-origin',
          },
          {
            key: 'Permissions-Policy',
            value: 'camera=(), microphone=(), geolocation=()',
          },
          {
            key: 'Cache-Control',
            value: 'public, max-age=0, must-revalidate, s-maxage=3600, stale-while-revalidate=86400',
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
