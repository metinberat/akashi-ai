"use client";

import dynamic from "next/dynamic";

// The remote presence thin client (iPhone, Mac, another laptop). Client-only:
// WebCrypto, IndexedDB, WebSocket, camera and three.js live in the browser.
const RemoteApp = dynamic(() => import("@/components/remote/remote-app"), {
  ssr: false,
  loading: () => <main className="remote-app remote-loading">AKASHI remote…</main>,
});

export default function RemotePage() {
  return <RemoteApp />;
}
