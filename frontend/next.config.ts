import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Produces a small self-contained server for Docker (see Dockerfile).
  output: "standalone",
};

export default nextConfig;
