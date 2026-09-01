import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./src/i18n/request.ts");

const nextConfig: NextConfig = {
  // Static landing page — deployed to Vercel as a fully static export
  // (no server runtime needed, free tier friendly).
  output: "export",
  images: { unoptimized: true },
};

export default withNextIntl(nextConfig);
