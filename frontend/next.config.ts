import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: 'standalone',
  async rewrites() {
    // Read API_URL at runtime from environment variable
    const API_URL = process.env.API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://localhost:9000';
    return [
      {
        source: '/api/:path*',
        destination: `${API_URL}/api/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        // Everything else (HTML pages, API) revalidates via ETag so
        // rebuilds are visible without a hard refresh (was a server.js
        // patch; headers() survives standalone rebuilds)
        source: '/:path*',
        headers: [{ key: 'Cache-Control', value: 'no-cache' }],
      },
      {
        // Content-hashed assets keep the 1-year immutable cache.
        // Listed last: when several rules match, the later one wins.
        source: '/_next/static/:path*',
        headers: [{ key: 'Cache-Control', value: 'public, max-age=31536000, immutable' }],
      },
    ];
  },
};

export default nextConfig;
