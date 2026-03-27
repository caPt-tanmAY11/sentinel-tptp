// dashboards/middleware.ts

import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

// These paths are PUBLIC — accessible without any login
// They are customer-facing pages sent via email links
const PUBLIC_PATHS = [
  '/report',
  '/grievance',
  '/login',
  '/api/interventions/acknowledge',
  '/api/grievances/submit',
];

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow all public paths and their sub-routes
  const isPublic = PUBLIC_PATHS.some((path) => pathname.startsWith(path));
  if (isPublic) {
    return NextResponse.next();
  }

  // Allow Next.js internals
  if (
    pathname.startsWith('/_next') ||
    pathname.startsWith('/favicon') ||
    pathname === '/'
  ) {
    return NextResponse.next();
  }

  // For /dashboard routes — auth is handled client-side by Zustand/localStorage
  // Middleware just ensures headers are clean and passes through
  return NextResponse.next();
}

export const config = {
  matcher: ['/((?!_next/static|_next/image|favicon.ico).*)'],
};
