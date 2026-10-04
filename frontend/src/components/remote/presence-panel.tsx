"use client";

// Owner's view of remote presence inside Spatial Lab: invite a device with
// explicit permissions, see what each connected device can provide, change or
// revoke its permissions (effective immediately), decide pending approvals and
// verify the tamper-evident audit trail.

import { useCallback, useEffect, useMemo, useState } from "react";

import type { BackendConfig } from "@/lib/api";
import { remoteOwnerApi, type PairingCode, type PresenceDevice } from "@/lib/remote/owner";
import { RemoteFailure, SCOPE_LABELS, type Approval } from "@/lib/remote/protocol";
import type { RemoteSessionClient } from "@/lib/remote/session";

const PRESETS: Array<{ id: string; label: string; note: string }> = [
  { id: "spatial-remote", label: "Spatial remote", note: "See and change the scene, share hands, voice scene commands, approve scene confirmations." },
  { id: "spatial-viewer", label: "Viewer", note: "See the scene only." },
  { id: "approver", label: "Approver", note: "Decide pending approvals (including general AKASHI tasks)." },
];
const SCOPE_ORDER = ["spatial.view", "spatial.control", "spatial.presence", "voice.spatial", "assistant.chat", "approvals.spatial", "approvals.general"];

function message(error: unknown): string {
  return error instanceof RemoteFailure || error instanceof Error ? error.message : String(error);
}

export function RemotePresencePanel({ config, client, onClose }: { config: BackendConfig; client: RemoteSessionClient | null; onClose: () => void }) {
  const api = useMemo(() => remoteOwnerApi(config), [config]);
  const [devices, setDevices] = useState<PresenceDevice[]>([]);
  const [code, setCode] = useState<PairingCode | null>(null);
  const [preset, setPreset] = useState("spatial-remote");
  const [chat, setChat] = useState(false);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [audit, setAudit] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  const refresh = useCallback(async () => {
    try {
      const [list, pending] = await Promise.all([api.devices(), api.approvals()]);
      setDevices(list.devices);
      setApprovals(pending.approvals);
    } catch (failure) {
      setError(message(failure));
    }
  }, [api]);

  useEffect(() => {
    const first = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => { void refresh(); setNow(Date.now()); }, 3000);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
  }, [refresh]);
  useEffect(() => client?.on("approvals.changed", (m) => setApprovals(m.body.approvals as Approval[])), [client]);

  const act = async (work: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try { await work(); await refresh(); } catch (failure) { setError(message(failure)); } finally { setBusy(false); }
  };

  const invite = () => act(async () => {
    const label = "Invited from Spatial Lab";
    const input = preset === "spatial-remote" && chat
      ? { scopes: ["spatial.view", "spatial.control", "spatial.presence", "voice.spatial", "approvals.spatial", "assistant.chat"], label }
      : { preset, label };
    setCode(await api.createPairingCode(input));
  });

  const coreIsLoopback = /^https?:\/\/(localhost|127\.|\[::1\])/iu.test(config.baseUrl || "");
  const remoteUrl = typeof window !== "undefined" && window.location.protocol.startsWith("http") ? `${window.location.origin}/remote` : null;
  const expiresIn = code ? Math.max(0, Math.round((Date.parse(code.expires_at) - now) / 1000)) : 0;

  return <section className="spatial-panel remote-presence" aria-label="Remote devices">
    <header><span>REMOTE PRESENCE</span><strong>Devices</strong><button type="button" className="spatial-link" onClick={onClose}>Close</button></header>
    {error && <p className="spatial-banner" role="alert">{error}</p>}

    <div className="remote-presence-invite">
      <h4>Invite a device</h4>
      <label>Permissions<select value={preset} onChange={(e) => setPreset(e.target.value)} aria-label="Permission preset">
        {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}</select></label>
      <small className="spatial-muted">{PRESETS.find((p) => p.id === preset)?.note}</small>
      {preset === "spatial-remote" && <label><input type="checkbox" checked={chat} onChange={(e) => setChat(e.target.checked)} /> Also allow AKASHI conversation (scene-bounded actions only)</label>}
      <button type="button" disabled={busy} onClick={() => void invite()}>Create pairing code</button>
      {code && <div className="remote-presence-code" data-testid="pairing-code">
        <strong>{code.code}</strong>
        <small>One-time · expires in {expiresIn} s · {code.scopes.map((s) => SCOPE_LABELS[s]?.en ?? s).join(", ")}</small>
        <small>On the device open {remoteUrl ? <code>{remoteUrl}</code> : "AKASHI → Remote presence"} and enter the Core address{config.baseUrl ? <> <code>{config.baseUrl}</code></> : null} and this code.</small>
        {code.endpoints.length > 0 && <small>Advertised Core addresses: {code.endpoints.join(", ")}</small>}
        {coreIsLoopback && <small className="spatial-warning">This Core address only works on this PC. Other devices need a LAN or tunnel HTTPS address (AKASHI_REMOTE_ENDPOINTS).</small>}
      </div>}
    </div>

    <h4>Paired devices</h4>
    {devices.length === 0 && <p className="spatial-muted">No remote device is paired.</p>}
    <ul className="remote-presence-devices">{devices.filter((d) => !d.revoked).map((device) => {
      const live = device.sessions.filter((s) => s.state !== "closed");
      return <li key={device.id} data-device={device.id} data-online={live.length > 0}>
        <div><strong>{device.name}</strong> <small>{device.device_type} · {device.credential === "key" ? "device key" : "stored secret (weaker)"} · {live.length ? `${live[0].state} via ${live[0].transport ?? "—"}` : "offline"}</small></div>
        {live[0] && <small className="spatial-muted">{live[0].capabilities.filter((c) => c.state === "active" || c.state === "available").map((c) => c.state === "active" ? `${c.name} ●` : c.name).join(" · ")}</small>}
        <fieldset className="remote-presence-scopes" disabled={busy}><legend>Permissions (apply immediately)</legend>
          {SCOPE_ORDER.map((scope) => <label key={scope}><input type="checkbox" checked={device.grants.includes(scope)}
            onChange={(e) => void act(() => api.setScopes(device.id, e.target.checked ? [...device.grants, scope] : device.grants.filter((g) => g !== scope)))} />
            {SCOPE_LABELS[scope]?.en ?? scope}</label>)}
        </fieldset>
        <button type="button" className="spatial-danger" disabled={busy}
          onClick={() => { if (window.confirm(`Revoke ${device.name}? It is disconnected at once and must be paired again.`)) void act(() => api.revoke(device.id)); }}>Revoke</button>
      </li>;
    })}</ul>

    <h4>Pending approvals</h4>
    {approvals.length === 0 ? <p className="spatial-muted">Nothing is waiting.</p> : <ul className="remote-presence-approvals">{approvals.map((item) => <li key={item.id}>
      <strong>{item.title}</strong><small>{item.reason}</small><small>Requested by {item.requested_by.en ?? "AKASHI"}</small>
      <div className="spatial-button-row"><button type="button" className="spatial-danger" disabled={busy} onClick={() => void act(() => api.decide(item.id, true))}>Approve</button>
        <button type="button" disabled={busy} onClick={() => void act(() => api.decide(item.id, false))}>Deny</button></div>
    </li>)}</ul>}

    <h4>Audit trail</h4>
    <div className="spatial-button-row"><button type="button" disabled={busy} onClick={() => void act(async () => {
      const result = await api.verifyAudit();
      setAudit(result.verified ? "Verified: the hash chain of every pairing, session, revocation and approval is intact." : `Integrity check FAILED: ${result.reason}`);
    })}>Verify audit trail</button></div>
    {audit && <p className="spatial-muted" role="status">{audit}</p>}
  </section>;
}
