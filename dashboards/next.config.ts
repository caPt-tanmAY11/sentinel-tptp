import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  turbopack: {
    root: './',
  },
  async rewrites() {
    return {
      // beforeFiles: run before Next.js checks pages/API routes (we don't need this)
      beforeFiles: [],

      // afterFiles: run after pages but before fallback (we don't need this either)
      afterFiles: [],

      // fallback: ONLY runs if no Next.js page OR API route matched first
      // This means /api/interventions/send, /api/interventions/acknowledge,
      // and /api/grievances/submit are handled by Next.js (they exist as files)
      // while everything else like /customers, /portfolio/metrics etc. goes to FastAPI
      fallback: [
        {
          source: '/api/:path*',
          destination: `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8001'}/:path*`,
        },
      ],
    };
  },
};

export default nextConfig;