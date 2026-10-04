"use client";

// AKASHI remote presence client (iPhone, Mac, another laptop...).
// Pairs once with a code from the owner, then joins Core as a scoped device:
// it renders the authoritative scene, sends touch / gesture / voice / UI input,
// shows approvals it may decide and the provenance of every change. Camera and
// microphone processing stay on this device.

import { useEffect, useState } from "react";

import { pairDevice, normalizeCoreUrl } from "@/lib/remote/device";
import { defaultVault, subtleAvailable, type StoredIdentity } from "@/lib/remote/identity";
import { RemoteFailure } from "@/lib/remote/protocol";

import RemoteSessionView from "./remote-session";

const CORE_KEY = "akashi-remote-core";

function guessDevice(): { name: string; type: string } {
  if (typeof navigator === "undefined") return { name: "Remote device", type: "phone" };
  const agent = navigator.userAgent;
  if (/iPhone/u.test(agent)) return { name: "iPhone", type: "phone" };
  if (/iPad/u.test(agent) || (/Macintosh/u.test(agent) && navigator.maxTouchPoints > 1)) return { name: "iPad", type: "tablet" };
  if (/Android/u.test(agent)) return { name: /Mobile/u.test(agent) ? "Android phone" : "Android tablet", type: /Mobile/u.test(agent) ? "phone" : "tablet" };
  if (/Macintosh/u.test(agent)) return { name: "Mac", type: "laptop" };
  if (/Windows/u.test(agent)) return { name: "Windows laptop", type: "laptop" };
  return { name: "Remote device", type: "laptop" };
}

function initialForm() {
  const params = typeof window !== "undefined" ? new URLSearchParams(window.location.search) : new URLSearchParams();
  let core = params.get("core") ?? "";
  if (!core) {
    try { core = localStorage.getItem(CORE_KEY) ?? ""; } catch { core = ""; }
  }
  const device = guessDevice();
  return { core, code: (params.get("code") ?? "").toUpperCase(), name: device.name, type: device.type };
}

function PairScreen({ onPaired }: { onPaired: (identity: StoredIdentity) => void }) {
  const [form, setForm] = useState(initialForm);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const secure = subtleAvailable();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const coreUrl = normalizeCoreUrl(form.core);
      try { localStorage.setItem(CORE_KEY, coreUrl); } catch { /* convenience only */ }
      const identity = await pairDevice({ coreUrl, code: form.code, name: form.name, deviceType: form.type });
      onPaired(identity);
    } catch (failure) {
      const code = failure instanceof RemoteFailure ? failure.code : "error";
      setError(code === "pairing_refused" ? "That code is invalid, used or expired. Ask for a new code on the AKASHI desktop."
        : code === "network" ? "AKASHI Core is unreachable from this device. Check the address, the network and HTTPS."
        : failure instanceof Error ? failure.message : String(failure));
    } finally {
      setBusy(false);
    }
  };

  return <main className="remote-app remote-pair" aria-label="Pair this device">
    <header><span>AKASHI · REMOTE PRESENCE</span><h1>Connect this device</h1></header>
    <p className="remote-muted">On the AKASHI desktop open <b>Spatial Lab → Devices → Invite device</b>. Enter the Core address and the one-time code shown there.
      This device only gets the permissions chosen on the desktop; it never receives the AKASHI access token.</p>
    {!secure && <p className="remote-warning" role="alert">This page is not a secure context (HTTPS or the AKASHI app), so a hardware-backed device key is unavailable.
      The device would pair with a weaker stored secret, and the camera and microphone are blocked by the browser here.</p>}
    <form onSubmit={submit} className="remote-form">
      <label>AKASHI Core address<input name="core" inputMode="url" autoComplete="url" placeholder="https://akashi.local:8443" value={form.core}
        onChange={(e) => setForm({ ...form, core: e.target.value })} required /></label>
      <label>Pairing code<input name="code" autoCapitalize="characters" autoComplete="one-time-code" maxLength={10} minLength={10} value={form.code}
        onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/[^A-Z0-9]/gu, "") })} required /></label>
      <label>Device name<input name="name" maxLength={100} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required /></label>
      <label>Device type<select name="type" value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
        <option value="phone">Phone</option><option value="tablet">Tablet</option><option value="laptop">Laptop</option><option value="desktop">Desktop</option>
      </select></label>
      <button type="submit" className="remote-primary" disabled={busy}>{busy ? "Pairing…" : "Pair device"}</button>
    </form>
    {error && <p className="remote-error" role="alert">{error}</p>}
  </main>;
}

export default function RemoteApp() {
  const [vault] = useState(defaultVault);
  const [identity, setIdentity] = useState<StoredIdentity | null | undefined>(undefined);

  useEffect(() => {
    let alive = true;
    vault.load().then((value) => { if (alive) setIdentity(value); }).catch(() => { if (alive) setIdentity(null); });
    return () => { alive = false; };
  }, [vault]);

  if (identity === undefined) return <main className="remote-app remote-loading">AKASHI remote…</main>;
  if (identity === null) return <PairScreen onPaired={setIdentity} />;
  return <RemoteSessionView key={identity.credential.deviceId} identity={identity}
    onUnpair={() => { void vault.clear().finally(() => setIdentity(null)); }} />;
}
