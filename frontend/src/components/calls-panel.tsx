"use client";

import { useEffect, useMemo, useState } from "react";

import type { BackendConfig } from "@/lib/api";
import {
  getPhoneCalls,
  getPhoneStatus,
  hangUpPhoneCall,
  type PhoneCall,
  type PhoneStatus,
} from "@/lib/phone-api";

type CallsPanelProps = {
  config: BackendConfig;
  connected: boolean;
};

const terminalStates = new Set(["ended", "failed"]);

function formatDuration(seconds: number): string {
  const bounded = Math.max(0, Math.floor(seconds));
  const minutes = Math.floor(bounded / 60).toString().padStart(2, "0");
  const remainder = (bounded % 60).toString().padStart(2, "0");
  return `${minutes}:${remainder}`;
}

function currentDuration(call: PhoneCall, now: number): number {
  if (call.ended_at) return call.duration_seconds;
  const start = call.connected_at || call.answered_at || call.started_at;
  const startMs = Date.parse(start);
  return Number.isFinite(startMs) ? Math.max(call.duration_seconds, (now - startMs) / 1_000) : call.duration_seconds;
}

export function CallsPanel({ config, connected }: CallsPanelProps) {
  const [status, setStatus] = useState<PhoneStatus | null>(null);
  const [calls, setCalls] = useState<PhoneCall[]>([]);
  const [error, setError] = useState("");
  const [ending, setEnding] = useState(false);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!connected || !config.baseUrl) return;
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const refresh = async () => {
      try {
        const nextStatus = await getPhoneStatus(config, controller.signal);
        const nextCalls = nextStatus.enabled
          ? await getPhoneCalls(config, controller.signal)
          : [];
        if (!disposed) {
          setStatus(nextStatus);
          setCalls(nextCalls);
          setError("");
        }
      } catch (value) {
        if (!disposed && !controller.signal.aborted) {
          setError(value instanceof Error ? value.message : "Çağrı durumu alınamadı.");
        }
      } finally {
        if (!disposed) timer = setTimeout(refresh, status?.enabled ? 1_500 : 15_000);
      }
    };

    void refresh();
    return () => {
      disposed = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [config, connected, status?.enabled]);

  const active = useMemo(() => calls.find((call) => !terminalStates.has(call.state)), [calls]);
  const visible = active || calls[0];
  const transcript = visible?.transcript.slice(-4) || [];

  useEffect(() => {
    if (!active) return;
    const clock = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(clock);
  }, [active]);

  const hangUp = async () => {
    if (!active || ending) return;
    setEnding(true);
    try {
      const ended = await hangUpPhoneCall(config, active.id);
      setCalls((items) => items.map((item) => item.id === ended.id ? ended : item));
      setError("");
    } catch (value) {
      setError(value instanceof Error ? value.message : "Çağrı sonlandırılamadı.");
    } finally {
      setEnding(false);
    }
  };

  const stateLabel = !connected
    ? "CORE OFFLINE"
    : status === null
      ? "CHECKING"
    : !status?.enabled
      ? "DISABLED"
      : active?.state.replace("_", " ").toUpperCase() || "READY";

  return <section className="calls-panel" aria-label="AKASHI telefon çağrıları">
    <header>
      <div><p className="eyebrow">CALLS / VERIMOR</p><h4>{active ? active.caller_number : "AKASHI Line"}</h4></div>
      <span className={`state-pill ${active ? "active" : ""}`}>{stateLabel}</span>
    </header>
    {!connected ? <p className="calls-empty">Core bağlantısı kurulduğunda telefon durumu burada görünür.</p> : status === null ? <p className="calls-empty">Telefon hattı denetleniyor.</p> : !status.enabled ? <p className="calls-empty">Telefon hattı sunucu ayarlarında kapalı. Web ve mobil işlevler etkilenmez.</p> : !visible ? <p className="calls-empty">Aktif veya kayıtlı çağrı yok.</p> : <>
      <div className="calls-meta"><span>{visible.direction === "inbound" ? "INBOUND" : "OUTBOUND"}</span><strong>{formatDuration(currentDuration(visible, now))}</strong></div>
      <div className="calls-transcript" aria-live="polite">
        {transcript.length ? transcript.map((entry) => <p key={`${entry.timestamp}-${entry.role}`}><b>{entry.role === "caller" ? "CALLER" : "AKASHI"}</b><span>{entry.content}</span></p>) : <p><span>Canlı transcript çağrı bağlandığında burada görünür.</span></p>}
      </div>
      {active && <button type="button" className="calls-hangup" disabled={ending} onClick={() => void hangUp()}>{ending ? "ENDING…" : "HANG UP"}</button>}
    </>}
    {error && <p className="calls-error">{error}</p>}
  </section>;
}
