import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit .next/standalone (minimal server.js + traced deps) so the production
  // Docker image can run `node server.js`. Required by the production Dockerfile.
  output: "standalone",
};

export default nextConfig;
