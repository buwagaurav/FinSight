import type { NextConfig } from "next";

const API_URL = process.env.FINSIGHT_API_URL ?? "http://localhost:8010";

// The site's public address for sign-in. Netlify runs the server under its internal "main--<site>.netlify.app"
// host; without this Auth.js sends Google that address, and the sign-in cookies (set on the public domain) are
// missing when Google returns, which Auth.js reports as "a problem with the server configuration".
// AUTH_URL wins when set; otherwise the production site's main URL, which Netlify provides to builds as URL.
const SITE_URL = process.env.AUTH_URL || (process.env.CONTEXT === "production" ? process.env.URL : "") || "";

// Where the browser may connect: this site, and the API when it lives on another domain (Render)
const PUBLIC_API = (() => { try { return new URL(process.env.NEXT_PUBLIC_API_URL ?? "").origin; } catch { return ""; } })();

// Security headers for every page. The content policy limits scripts, data requests, frames and form posts to this
// site (plus the API, and Google for sign-in); Next.js needs inline scripts and styles without a nonce setup.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: https:",                       // Google profile pictures
  "font-src 'self' data:",
  `connect-src 'self' ${PUBLIC_API}`.trim(),
  "frame-ancestors 'none'",                            // no clickjacking: the site can't be framed
  "form-action 'self' https://accounts.google.com",    // sign-in posts here, then redirects to Google
  "base-uri 'self'",
  "object-src 'none'",
  "upgrade-insecure-requests",
].join("; ");
const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()" },
];

const nextConfig: NextConfig = {
  env: { FINSIGHT_SITE_URL: SITE_URL },
  poweredByHeader: false,   // don't advertise the framework
  async headers() {
    // development needs eval and a hot-reload socket, which the policy would block
    return process.env.NODE_ENV === "production" ? [{ source: "/:path*", headers: SECURITY_HEADERS }] : [];
  },
  // The AI assistant can take a minute or more to research an answer; the default proxy timeout is 30s.
  experimental: {
    proxyTimeout: 180_000,
    // Turbopack's on-disk build cache records server environment values (AUTH_SECRET etc.). Netlify stores that
    // cache between builds and its secret scanner (rightly) blocks the deploy. The build is fast without it.
    turbopackFileSystemCacheForBuild: false,
  },
  async rewrites() {
    // "fallback": only paths Next.js doesn't handle itself go to the API. A plain rewrite would run before
    // dynamic routes and send the sign-in routes (/api/auth/...) to the backend.
    return { beforeFiles: [], afterFiles: [], fallback: [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }] };
  },
};

export default nextConfig;
