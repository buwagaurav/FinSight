import type { NextConfig } from "next";

const API_URL = process.env.FINSIGHT_API_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  // The AI assistant can take a minute or more to research an answer; the default proxy timeout is 30s.
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    // "fallback": only paths Next.js doesn't handle itself go to the API. A plain rewrite would run before
    // dynamic routes and send the sign-in routes (/api/auth/...) to the backend.
    return { beforeFiles: [], afterFiles: [], fallback: [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }] };
  },
};

export default nextConfig;
