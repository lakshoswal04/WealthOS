import type { NextConfig } from "next";

/** The analytics pages moved under /analysis when the trading surfaces took
 *  the top level; old links and bookmarks keep working. The Copilot page is
 *  now the AI chat at /home. */
const MOVED: [string, string][] = [
  ["/overview", "/analysis/overview"],
  ["/risk", "/analysis/risk"],
  ["/goals", "/analysis/goals"],
  ["/insights", "/analysis/insights"],
  ["/research", "/analysis/model-lab"],
  ["/data-quality", "/analysis/data-quality"],
  ["/copilot", "/home"],
  ["/dashboard", "/home"],
];

const nextConfig: NextConfig = {
  async redirects() {
    return MOVED.map(([source, destination]) => ({ source, destination, permanent: false }));
  },
};

export default nextConfig;
