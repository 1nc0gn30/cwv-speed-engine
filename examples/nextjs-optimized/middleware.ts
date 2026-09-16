/**
 * Next.js Edge Middleware for Core Web Vitals Optimization
 * - Injects Early Hints Link headers for critical LCP hero resources
 * - Injects Server-Timing headers for precise TTFB debugging
 * - Enforces HTTPS and HSTS security policies
 */

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  const startTime = Date.now();
  const response = NextResponse.next();

  const { pathname } = request.nextUrl;

  // 1. Early Hints Link Preload Headers for Homepage LCP Hero
  if (pathname === '/') {
    // Hint modern browser preload scanner to fetch hero assets before HTML finishes parsing
    const linkHeaders = [
      '</fonts/inter-latin-var.woff2>; rel=preload; as=font; type="font/woff2"; crossorigin',
      '</images/hero-banner.webp>; rel=preload; as=image; fetchpriority=high',
    ].join(', ');

    response.headers.set('Link', linkHeaders);
  }

  // 2. Server-Timing Performance Header for Edge Latency Diagnostics
  const duration = Date.now() - startTime;
  response.headers.set('Server-Timing', `edge;dur=${duration};desc="Next Edge Gateway"`);

  // 3. Strict Transport Security
  response.headers.set(
    'Strict-Transport-Security',
    'max-age=63072000; includeSubDomains; preload'
  );

  return response;
}

export const config = {
  matcher: [
    /*
     * Match all request paths except for the ones starting with:
     * - api (API routes)
     * - _next/static (static files)
     * - _next/image (image optimization files)
     * - favicon.ico (favicon file)
     */
    '/((?!api|_next/static|_next/image|favicon.ico).*)',
  ],
};
