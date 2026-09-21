import type { CapacitorConfig } from "@capacitor/cli";

const isMobileDev =
  process.env.AKASHI_MOBILE_DEV === "1" ||
  process.env.AKASHI_ANDROID_DEV === "1";

const config: CapacitorConfig = {
  appId: "com.akashiai.app",
  appName: "AKASHİ AI",
  webDir: "out",
  // HTTP is permitted only for explicit local/LAN development builds.
  // AKASHI_ANDROID_DEV remains an alias for existing Android workflows.
  ...(isMobileDev
    ? { server: { androidScheme: "http", cleartext: true } }
    : {}),
};

export default config;
