import type { NextConfig } from "next";

// Where the Next.js server forwards /api calls when NEXT_PUBLIC_API_TARGET=proxy (one address, one tunnel, no CORS).
const BACKEND_INTERNAL_URL = (process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");

const nextConfig: NextConfig = {
  // Produces a small self-contained server for Docker (see Dockerfile).
  output: "standalone",
  // `npm run dev` only serves its dev scripts to these other hosts (needed when the site is opened through ngrok).
  allowedDevOrigins: ["*.ngrok-free.app", "*.ngrok-free.dev", "*.ngrok.app", "*.ngrok.io"],
  // Ads take a while to upload and stream: give proxied requests enough time.
  experimental: { proxyTimeout: 300_000 },
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${BACKEND_INTERNAL_URL}/api/:path*` },
      { source: "/health", destination: `${BACKEND_INTERNAL_URL}/health` },
    ];
  },
};

export default nextConfig;
