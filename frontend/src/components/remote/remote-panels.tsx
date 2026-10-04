"use client";

import { useEffect, useState } from "react";

import type { DeviceCredential } from "@/lib/remote/identity";
import { SCOPE_LABELS, type Approval, type CapabilityReport } from "@/lib/remote/protocol";
import type { RemoteSessionClient, SessionMetrics } from "@/lib/remote/session";
import type { CompactEvent, RosterEntry } from "@/lib/remote/spatial";

export type Reply = { reply: string; route?: string; query?: string; confirmation?: { token: string; question: string } };

export function ApprovalList({ approvals, busy, onDecide }: { approvals: Approval[]; busy: boolean; onDecide: (approval: Approval, approve: boolean) => void }) {
  return <section className="remote-sheet" aria-label="Pending approvals">
    <header><span>APPROVALS</span><strong>{approvals.length ? `${approvals.length} waiting` : "Nothing waiting"}</strong></header>
    {approvals.length === 0 && <p className="remote-muted">Requests that need a person&apos;s decision appear here: what would happen, why it needs approval and who asked.</p>}
    <ul className="remote-list">{approvals.map((item) => <li key={item.id} data-approval={item.id} data-scope={item.scope}>
      <strong>{item.title}</strong>
      <p>{item.reason}</p>
      <small>Requested by {item.requested_by.en ?? "AKASHI"} · {item.scope === "spatial" ? "Spatial Lab" : "AKASHI"}{item.expires_in !== null ? ` · expires in ${Math.max(0, Math.round(item.expires_in))} s` : ""}</small>
      <div className="remote-actions">
        <button type="button" className="remote-danger" disabled={busy} onClick={() => onDecide(item, true)}>Approve</button>
        <button type="button" disabled={busy} onClick={() => onDecide(item, false)}>Deny</button>
      </div>
    </li>)}</ul>
  </section>;
}

export function HistoryList({ events, me }: { events: CompactEvent[]; me: string | null }) {
  const recent = [...events].reverse().slice(0, 12);
  return <section className="remote-sheet" aria-label="Scene history">
    <header><span>HISTORY</span><strong>Why things changed</strong></header>
    {recent.length === 0 && <p className="remote-muted">Changes made while this device is connected appear here with who made them.</p>}
    <ol className="remote-list remote-history">{recent.map((event) => <li key={event.seq} data-seq={event.seq} data-mine={event.origin.session === me}>
      <strong>#{event.seq} {event.kind === "undo" ? "Undo" : event.kind === "redo" ? "Redo" : event.summary ?? event.command}</strong>
      <small>{event.origin.session === me ? "You — " : ""}{event.origin.en}</small>
    </li>)}</ol>
  </section>;
}

export function RosterList({ roster, me, capabilities, scopes, credential, onUnpair }: {
  roster: RosterEntry[]; me: string | null; capabilities: CapabilityReport[]; scopes: string[]; credential: DeviceCredential; onUnpair: () => void;
}) {
  return <section className="remote-sheet" aria-label="Connected devices">
    <header><span>DEVICES</span><strong>{roster.length} in this scene</strong></header>
    <ul className="remote-list">{roster.map((entry) => <li key={entry.session} data-session={entry.session}>
      <strong>{entry.device.name}{entry.session === me ? " (this device)" : ""}</strong>
      <small>{entry.device.kind === "owner" ? "AKASHI owner" : entry.device.device_type} · {entry.state}{entry.transport ? ` · ${entry.transport}` : ""}</small>
      <small>{entry.capabilities.filter((c) => c.state === "active" || c.state === "available").map((c) => c.state === "active" ? `${c.name} ●` : c.name).join(" · ")}</small>
    </li>)}</ul>
    <h3>This device</h3>
    <p className="remote-muted">{credential.credential === "key" ? "Identified by a device key that cannot leave this device." : "Identified by a stored secret (weaker: paired from an insecure page)."}</p>
    <ul className="remote-chips" aria-label="Permissions">{scopes.map((scope) => <li key={scope}>{SCOPE_LABELS[scope]?.en ?? scope}</li>)}</ul>
    <ul className="remote-chips remote-capabilities" aria-label="Capabilities">{capabilities.map((c) => <li key={c.name} data-state={c.state}>{c.name}: {c.state}</li>)}</ul>
    <p className="remote-muted">Camera frames and microphone audio are processed on this device. AKASHI receives hand positions, gestures, transcripts and commands — never video.</p>
    <button type="button" className="remote-danger" onClick={() => { if (window.confirm("Forget this pairing? You will need a new code to reconnect.")) onUnpair(); }}>Forget this pairing</button>
  </section>;
}

export function RemoteDebug({ client, revision, digest, syncMode, resyncs }: { client: RemoteSessionClient; revision: number | null; digest: string | null; syncMode: string | null; resyncs: number }) {
  const [metrics, setMetrics] = useState<SessionMetrics>(() => client.metrics());
  useEffect(() => {
    const timer = window.setInterval(() => setMetrics(client.metrics()), 500);
    return () => window.clearInterval(timer);
  }, [client]);
  const errors = Object.entries(metrics.errors).map(([code, count]) => `${code}×${count}`).join(" · ") || "none";
  return <section className="remote-sheet remote-debug" aria-label="Remote debug">
    <header><span>DEBUG</span><strong>Session and sync</strong></header>
    <dl>
      <div><dt>Session</dt><dd>{metrics.sessionId ?? "—"} · {metrics.state} · {metrics.transport ?? "—"}</dd></div>
      <div><dt>RTT</dt><dd>last {metrics.rttMs.last?.toFixed(0) ?? "—"} ms · p50 {metrics.rttMs.p50?.toFixed(0) ?? "—"} · p95 {metrics.rttMs.p95?.toFixed(0) ?? "—"}</dd></div>
      <div><dt>Traffic</dt><dd>sent {metrics.sent} · received {metrics.received} · retransmits {metrics.retransmits} · dedup acks {metrics.duplicatesAcked}</dd></div>
      <div><dt>Resilience</dt><dd>reconnects {metrics.reconnects} · handshakes {metrics.handshakes} · offline {(metrics.offlineMs / 1000).toFixed(1)} s · pending {metrics.pending}</dd></div>
      <div><dt>Scene</dt><dd>rev {revision ?? "—"} · {digest?.slice(0, 18) ?? "—"} · last sync {syncMode ?? "—"} · syncs {resyncs} · cursor {metrics.cursor}</dd></div>
      <div><dt>Errors</dt><dd>{errors}</dd></div>
    </dl>
  </section>;
}
