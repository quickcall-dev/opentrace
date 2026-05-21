import type { NextConfig } from "next";
import path from "path";

const nextConfig: NextConfig = {
  output: "standalone",
  async redirects() {
    return [
      { source: "/", destination: "/sessions", permanent: false },
    ];
  },
  webpack: (config) => {
    config.resolve.alias["@"] = path.join(__dirname, ".");
    return config;
  },
};

export default nextConfig;
