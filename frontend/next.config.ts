import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Pin the trace root to this package. Next otherwise walks up looking for a
  // lockfile and can settle on an unrelated one outside the repository.
  outputFileTracingRoot: path.join(import.meta.dirname, "."),
  // Surfaced in the UI so an operator can tell which API a running instance
  // is actually talking to.
  env: {
    NEXT_PUBLIC_API_BASE_URL:
      process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000",
  },
};

export default nextConfig;
