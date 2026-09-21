"use client";

import { useEffect, useRef } from "react";
import { Icon } from "./identity";
import type { HudActivityEvent } from "@/lib/desktop-types";
import { metric, uptimeLabel, type Telemetry } from "@/lib/telemetry";
import type { AkashiTask } from "@/lib/absolute-api";
import type { WorkspaceView } from "@/lib/platform";

export function ActivityInstrument({ events, connected }: { events: HudActivityEvent[]; connected: boolean }) {
  const list = useRef<HTMLOListElement>(null);
  const following = useRef(true);
  useEffect(() => { if (following.current && list.current) list.current.scrollTop = list.current.scrollHeight; }, [events]);
  return <section className="activity-instrument"><header><span><i />ACTIVITY LOG</span><small>{connected ? "LIVE" : "LOCAL"}<i /></small></header>
    <ol ref={list} aria-label="Gözlemlenen olaylar" role="log" aria-live="polite" onScroll={() => { const el = list.current!; following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 36; }}>
      {events.length === 0 && <li className="activity-empty">Henüz bir işlem yok. Konuş veya bir komut gönder.</li>}
      {events.map(event => <li key={event.id}><time dateTime={event.timestamp}>{Number.isNaN(Date.parse(event.timestamp)) ? "—" : new Date(event.timestamp).toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" })}</time><div><strong>{event.actor === "YOU" ? "You" : event.actor === "AKASHI" ? "Akashi" : "Core"}</strong><p>{event.label}</p></div></li>)}
    </ol><footer><span />{connected ? "CORE CONNECTED · OBSERVABLE EVENTS" : "CORE OFFLINE · LOCAL STATUS ONLY"}</footer>
  </section>;
}

export function SystemInstrument({ telemetry, ready }: { telemetry: Telemetry | null; ready: boolean }) {
  const rows: [string, number | null, string][] = [["CPU", telemetry?.cpu ?? null, "%"], ["RAM", telemetry?.ramPercent ?? null, "%"], ["GPU", telemetry?.gpu ?? null, "%"], ["TEMP", telemetry?.temperature ?? null, "°C"]];
  return <section className="system-instrument" aria-label="System monitor"><header><i />SYS MONITOR</header><dl>{rows.map(([label, value, unit]) => <div key={label}><dt>{label}</dt><span className="instrument-track"><i style={{ width: value === null ? "0%" : `${Math.max(0, Math.min(100, value))}%` }} /></span><dd>{metric(value, unit)}</dd></div>)}</dl><footer><span>UPTIME {uptimeLabel(telemetry?.uptime ?? null)}</span><span>{telemetry?.gpuName || "GPU · NO DATA"}</span><span>DESKTOP BODY <b data-ready={ready}>{ready ? "READY" : "OFFLINE"}</b></span></footer></section>;
}

export function AgentDock({ runtime, tasks, connected, onNavigate, onClose }: { runtime: DesktopRuntimeStatus | null; tasks: AkashiTask[]; connected: boolean; onNavigate: (view: WorkspaceView) => void; onClose: () => void }) {
  return <section className="agent-dock" aria-label="Agent Dock"><header><div><small>AUTONOMY HUB</small><h2>Agent Dock</h2></div><button type="button" aria-label="Agent Dock'u kapat" onClick={onClose}>×</button></header><p>Mevcut yetenekler ve gerçek yürütmeler. Planlanmış bir ajan, çalışan bir ajan değildir.</p>
    <div className="agent-capabilities">{runtime && Object.entries(runtime.components).map(([name, component]) => <article key={name}><span>{name.replaceAll("_", " ").toUpperCase()}</span><strong data-state={component.state}>{component.state}</strong></article>)}</div>
    <h3>EXECUTIONS</h3>{tasks.length ? <ol>{tasks.slice(0, 5).map(task => <li key={task.id}><strong>{task.title}</strong><span>{task.status} · {task.steps.filter(step => step.status === "completed").length}/{task.steps.length} steps</span></li>)}</ol> : <p>{connected ? "Aktif görev yok." : "Core bağlantısı yok. Görev durumu bilinmiyor."}</p>}
    <footer><button type="button" onClick={() => onNavigate("tasks")}><Icon name="tasks" />Görevler</button><button type="button" onClick={() => onNavigate("more")}><Icon name="research" />Intelligence</button><button type="button" onClick={() => onNavigate("devices")}><Icon name="devices" />Cihazlar</button></footer>
  </section>;
}
