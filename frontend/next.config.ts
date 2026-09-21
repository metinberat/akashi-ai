import type { NextConfig } from "next";

const isMobileDevelopment =
  process.env.AKASHI_MOBILE_DEV === "1" ||
  process.env.AKASHI_ANDROID_DEV === "1";

const nextConfig: NextConfig = {
  output: "export",
  // Public capability flag only. Backend URL and access token are entered at runtime.
  env: {
    NEXT_PUBLIC_AKASHI_ALLOW_HTTP: isMobileDevelopment ? "1" : "0",
  },
};

export default nextConfig;
