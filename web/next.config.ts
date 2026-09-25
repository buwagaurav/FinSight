import type { NextConfig } from "next";

const API_URL = process.env.FINSIGHT_API_URL ?? "http://localhost:8010";

const nextConfig: NextConfig = {
  // The AI assistant can take a minute or more to research an answer; the default proxy timeout is 30s.
  experimental: { proxyTimeout: 180_000 },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
