/* eslint-disable @next/next/no-img-element -- authenticated image blobs are runtime-only */
"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { Icon } from "@/components/identity";
import type { BackendConfig } from "@/lib/api";
import {
  cancelTask,
  getSystemHealth,
  listDevices,
  listFiles,
  listMemories,
  listTasks,
  type AkashiTask,
  type MemoryEntry,
  type PairedDevice,
  type SystemHealth,
  type UploadedFile,
} from "@/lib/absolute-api";
import type { CenterStageEntity } from "@/lib/desktop-stage";
import type { DesktopMessage, HudActivityEvent } from "@/lib/desktop-types";
import {
  HUD_MODULES,
  type HudLayout,
  type HudModuleDefinition,
  type HudModuleId,
  type HudModuleState,
  type HudZoneId,
} from "@/lib/hud-modules";
import { memoryGB, metric, uptimeLabel, type Telemetry } from "@/lib/telemetry";
import type { VoiceState } from "@/lib/voice";

export type HudModuleData = {
  config: BackendConfig;
  connected: boolean;
  connectionLabel: string;
  telemetry: Telemetry | null;
  agentReady: boolean;
  desktopRuntime: DesktopRuntimeStatus | null;
  messages: DesktopMessage[];
  tasks: AkashiTask[];
  recentImages: string[];
  stageEntity: CenterStageEntity | null;
  visionMessage: DesktopMessage | null;
  events: HudActivityEvent[];
  voiceState: VoiceState;
  voiceLabel: string;
  fullVoiceActive: boolean;
};

function ModuleUnavailable({ label }: { label: string }) {
  return <p className="hud-module-empty">{label}</p>;
}

/* ---------- Core Telemetry / Sensors / Network (real Windows Agent data, already polled by the caller) ---------- */

function CoreTelemetryModule({ telemetry }: { telemetry: Telemetry | null }) {
  if (!telemetry) return <ModuleUnavailable label="TELEMETRY UNAVAILABLE" />;
  const rows: Array<[string, string]> = [
    ["CPU", metric(telemetry.cpu)],
    ["RAM", metric(telemetry.ramPercent)],
    ["GPU", metric(telemetry.gpu)],
    ["TEMP", metric(telemetry.temperature, "°C")],
  ];
  return <>
    <div className="hud-metrics">{rows.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>
    <footer className="hud-module-footer">UPTIME {uptimeLabel(telemetry.uptime)} · RAM {memoryGB(telemetry.ramUsed)} / {memoryGB(telemetry.ramTotal)}</footer>
  </>;
}

function SensorsModule({ telemetry }: { telemetry: Telemetry | null }) {
  if (!telemetry) return <ModuleUnavailable label="SENSORS UNAVAILABLE" />;
  const vramPercent = telemetry.vramTotal ? ((telemetry.vramUsed ?? 0) / telemetry.vramTotal) * 100 : null;
  const gauges: Array<[string, number | null, string]> = [
    ["GPU TEMP", telemetry.temperature, "°C"],
    ["DISK", telemetry.disk, "%"],
    ["VRAM", vramPercent, "%"],
  ];
  return <div className="hud-gauges">
    {gauges.map(([label, value, suffix]) => <div key={label} className="hud-gauge">
      <span>{label}</span>
      <div className="hud-gauge-track"><i style={{ width: value === null ? "0%" : `${Math.min(100, value)}%` }} /></div>
      <strong>{value === null ? "—" : `${Math.round(value)}${suffix}`}</strong>
    </div>)}
    {telemetry.gpuName && <small className="hud-module-caption">{telemetry.gpuName}</small>}
  </div>;
}

function NetworkModule({ connected, connectionLabel, telemetry, coreMode }: { connected: boolean; connectionLabel: string; telemetry: Telemetry | null; coreMode?: string }) {
  return <div className="hud-rows">
    <div><span>CORE LINK</span><strong data-state={connected ? "online" : "offline"}>{connectionLabel}</strong></div>
    <div><span>OS NETWORK</span><strong data-state={telemetry?.network ? "online" : "offline"}>{telemetry?.network === null || telemetry?.network === undefined ? "UNAVAILABLE" : telemetry.network ? "ONLINE" : "OFFLINE"}</strong></div>
    <div><span>MODE</span><strong>{coreMode ? coreMode.toUpperCase() : "—"}</strong></div>
  </div>;
}

/* ---------- Active Processes (direct local Windows Agent call, same pattern as telemetry) ---------- */

type ProcessInfo = { pid: number; name: string; status: string; memory_percent: number };

function parseProcesses(payload: unknown): ProcessInfo[] | null {
  if (!payload || typeof payload !== "object") return null;
  const root = payload as { ok?: boolean; data?: { processes?: unknown } };
  if (!root.ok || !Array.isArray(root.data?.processes)) return null;
  return root.data.processes as ProcessInfo[];
}

function useProcesses(agentReady: boolean) {
  const [processes, setProcesses] = useState<ProcessInfo[] | null>(null);
  useEffect(() => {
    if (!agentReady || !window.akashiDesktop?.agent) return;
    let active = true;
    const refresh = async () => {
      try {
        const result = await window.akashiDesktop!.agent.execute("list_processes", { limit: 10 }, false);
        if (active) setProcesses(parseProcesses(result));
      } catch {
        if (active) setProcesses(null);
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 6000);
    return () => { active = false; window.clearInterval(timer); };
  }, [agentReady]);
  return processes;
}

function ActiveProcessesModule({ agentReady }: { agentReady: boolean }) {
  const processes = useProcesses(agentReady);
  if (!agentReady) return <ModuleUnavailable label="WINDOWS AGENT OFFLINE" />;
  if (!processes) return <ModuleUnavailable label="LOADING…" />;
  return <ol className="hud-process-list">
    {processes.slice(0, 8).map((process) => <li key={process.pid}><span>{process.name}</span><strong>{process.memory_percent.toFixed(1)}%</strong></li>)}
  </ol>;
}

/* ---------- Analytics (derived from real session state, no invented numbers) ---------- */

function AnalyticsModule({ messages, tasks, recentImages }: { messages: DesktopMessage[]; tasks: AkashiTask[]; recentImages: string[] }) {
  const tasksActive = tasks.filter((task) => ["queued", "planning", "running", "waiting_for_approval"].includes(task.status)).length;
  const tasksDone = tasks.filter((task) => task.status === "completed").length;
  const researchRuns = tasks.reduce((sum, task) => sum + task.steps.filter((step) => step.tool === "research.web").length, 0);
  const rows: Array<[string, number]> = [
    ["MESSAGES", messages.length],
    ["TASKS ACTIVE", tasksActive],
    ["TASKS DONE", tasksDone],
    ["RESEARCH RUNS", researchRuns],
    ["IMAGES", recentImages.length],
  ];
  return <div className="hud-metrics hud-metrics-wide">{rows.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div>;
}

/* ---------- System Coordinates (runtime + endpoint, real desktop runtime state) ---------- */

function hostFromUrl(url: string) {
  try { return new URL(url).host || url || "—"; } catch { return url || "—"; }
}

function SystemCoordinatesModule({ desktopRuntime, baseUrl }: { desktopRuntime: DesktopRuntimeStatus | null; baseUrl: string }) {
  if (!desktopRuntime) return <ModuleUnavailable label="RUNTIME UNAVAILABLE" />;
  const components: Array<[string, DesktopRuntimeComponent]> = [
    ["CORE", desktopRuntime.components.core],
    ["AGENT", desktopRuntime.components.agent],
    ["OLLAMA", desktopRuntime.components.ollama],
    ["COMFYUI", desktopRuntime.components.comfyui],
    ["VOICE", desktopRuntime.components.voice],
  ];
  return <>
    <div className="hud-rows">
      <div><span>MODE</span><strong>{desktopRuntime.coreMode.toUpperCase()}</strong></div>
      <div><span>ENDPOINT</span><strong>{hostFromUrl(baseUrl)}</strong></div>
    </div>
    <ul className="hud-component-list">
      {components.map(([label, component]) => <li key={label} data-state={component.state.toLowerCase()}><span>{label}</span><strong>{component.state}</strong></li>)}
    </ul>
  </>;
}

/* ---------- Data Streams (live backend dependency health) ---------- */

function useSystemHealth(config: BackendConfig, connected: boolean) {
  const [health, setHealth] = useState<SystemHealth | null>(null);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const refresh = async () => {
      try { const next = await getSystemHealth(config); if (active) setHealth(next); } catch { /* keep last known */ }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, connected]);
  return health;
}

function DataStreamsModule({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const health = useSystemHealth(config, connected);
  if (!connected) return <ModuleUnavailable label="CORE OFFLINE" />;
  if (!health) return <ModuleUnavailable label="LOADING…" />;
  const rows: Array<[string, { status: string; detail: string }]> = [
    ["CORE", health.core], ["AUTH", health.auth], ["MODEL", health.model], ["OLLAMA", health.ollama],
    ["IMAGES", health.images], ["RESEARCH", health.research], ["DESKTOP", health.desktop_agent],
  ];
  return <ul className="hud-component-list">
    {rows.map(([label, dependency]) => <li key={label} data-state={dependency.status} title={dependency.detail}><span>{label}</span><strong>{dependency.status.replaceAll("_", " ").toUpperCase()}</strong></li>)}
  </ul>;
}

/* ---------- Tasks (real AKASHI task queue: name, status, tool, progress, started time, result, cancel) ---------- */

function useTasksPoll(config: BackendConfig, connected: boolean, seed: AkashiTask[]) {
  const [tasks, setTasks] = useState<AkashiTask[]>(seed);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const refresh = async () => { try { const next = await listTasks(config); if (active) setTasks(next); } catch { /* keep last known */ } };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, connected]);
  return [tasks, setTasks] as const;
}

function TasksModule({ config, connected, seed }: { config: BackendConfig; connected: boolean; seed: AkashiTask[] }) {
  const [tasks, setTasks] = useTasksPoll(config, connected, seed);
  if (tasks.length === 0) return <ModuleUnavailable label="NO TASKS" />;
  return <ol className="hud-task-list">
    {tasks.slice(0, 6).map((task) => <li key={task.id} data-status={task.status}>
      <div className="hud-task-heading"><strong>{task.title}</strong><span>{task.status.replaceAll("_", " ").toUpperCase()}</span></div>
      <div className="hud-task-progress"><i style={{ width: `${Math.min(100, Math.max(0, task.progress))}%` }} /></div>
      <div className="hud-task-meta">
        <span>{task.steps.filter((step) => step.status === "completed").length} / {task.steps.length} STEP · {task.steps[0]?.tool ?? "—"}</span>
        <time>{new Date(task.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
      </div>
      {task.error && <p className="hud-task-error">{task.error}</p>}
      <div className="hud-task-actions">
        {["queued", "planning", "running", "waiting_for_approval"].includes(task.status) && <button type="button" className="text-button danger" onClick={() => void cancelTask(config, task.id).then((next) => setTasks((prev) => prev.map((item) => (item.id === next.id ? next : item)))).catch(() => undefined)}>Cancel</button>}
        {task.result != null && <details><summary>Inspect result</summary><pre>{JSON.stringify(task.result, null, 2).slice(0, 1200)}</pre></details>}
      </div>
    </li>)}
  </ol>;
}

/* ---------- Research / Vision (latest real context from this session) ---------- */

function ResearchModule({ entity }: { entity: CenterStageEntity | null }) {
  if (!entity) return <ModuleUnavailable label="NO ACTIVE RESEARCH" />;
  return <>
    <div className="hud-rows">
      <div><span>CONFIDENCE</span><strong>{entity.confidence.toUpperCase()}</strong></div>
      <div><span>SOURCES</span><strong>{entity.sources.length}</strong></div>
    </div>
    <p className="hud-module-text">{entity.title}</p>
  </>;
}

function VisionModule({ message }: { message: DesktopMessage | null }) {
  if (!message) return <ModuleUnavailable label="NO VISION CAPTURE" />;
  return <p className="hud-module-text">{message.content.slice(0, 220)}</p>;
}

/* ---------- Files / Devices / Memory (real backend-fetched lists, polled while open) ---------- */

function useFilesPoll(config: BackendConfig, connected: boolean) {
  const [files, setFiles] = useState<UploadedFile[]>([]);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const refresh = async () => { try { const next = await listFiles(config); if (active) setFiles(next); } catch { /* keep last known */ } };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 12000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, connected]);
  return files;
}

function FilesModule({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const files = useFilesPoll(config, connected);
  if (!connected) return <ModuleUnavailable label="CORE OFFLINE" />;
  if (files.length === 0) return <ModuleUnavailable label="NO FILES UPLOADED" />;
  return <ul className="hud-item-list">{files.slice(0, 6).map((file) => <li key={file.id}><span>{file.name}</span><strong>{(file.size / 1024).toFixed(0)} KB</strong></li>)}</ul>;
}

function useDevicesPoll(config: BackendConfig, connected: boolean) {
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const refresh = async () => { try { const next = await listDevices(config); if (active) setDevices(next); } catch { /* keep last known */ } };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 12000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, connected]);
  return devices;
}

function DevicesModule({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const devices = useDevicesPoll(config, connected);
  if (!connected) return <ModuleUnavailable label="CORE OFFLINE" />;
  if (devices.length === 0) return <ModuleUnavailable label="NO PAIRED DEVICES" />;
  return <ul className="hud-item-list">{devices.map((device) => <li key={device.id}><span>{device.name}</span><strong data-state={device.online ? "online" : "offline"}>{device.online ? "ONLINE" : "OFFLINE"}</strong></li>)}</ul>;
}

function useMemoriesPoll(config: BackendConfig, connected: boolean) {
  const [memories, setMemories] = useState<MemoryEntry[]>([]);
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const refresh = async () => { try { const next = await listMemories(config); if (active) setMemories(next); } catch { /* keep last known */ } };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 20000);
    return () => { active = false; window.clearInterval(timer); };
  }, [config, connected]);
  return memories;
}

function MemoryModule({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const memories = useMemoriesPoll(config, connected);
  if (!connected) return <ModuleUnavailable label="CORE OFFLINE" />;
  if (memories.length === 0) return <ModuleUnavailable label="NO MEMORY ENTRIES" />;
  return <ul className="hud-item-list hud-memory-list">{memories.slice(0, 5).map((entry) => <li key={entry.id}><span>{entry.content.slice(0, 60)}</span><strong>{entry.category.toUpperCase()}</strong></li>)}</ul>;
}

/* ---------- Create / Activity / Voice (already-available session state) ---------- */

function CreateModule({ recentImages }: { recentImages: string[] }) {
  if (recentImages.length === 0) return <ModuleUnavailable label="NO IMAGES GENERATED" />;
  return <div className="hud-thumb-grid">{recentImages.slice(0, 4).map((src) => <img key={src} src={src} alt="AKASHI görsel çıktısı" />)}</div>;
}

function ActivityModule({ events }: { events: HudActivityEvent[] }) {
  if (events.length === 0) return <ModuleUnavailable label="NO OBSERVABLE ACTIVITY" />;
  return <div className="hud-activity-list">{events.slice(0, 8).map((event) => <article key={event.id}><time>{event.timestamp}</time><p><strong>{event.actor}</strong>{event.label}</p></article>)}</div>;
}

function VoiceModule({ voiceState, voiceLabel, fullVoiceActive }: { voiceState: VoiceState; voiceLabel: string; fullVoiceActive: boolean }) {
  return <div className="hud-rows">
    <div><span>STATE</span><strong data-state={voiceState}>{voiceState.toUpperCase()}</strong></div>
    <div><span>SESSION</span><strong>{fullVoiceActive ? "FULL VOICE" : "SINGLE SHOT"}</strong></div>
    <div><span>LABEL</span><strong>{voiceLabel}</strong></div>
  </div>;
}

function renderModuleBody(id: HudModuleId, data: HudModuleData): ReactNode {
  switch (id) {
    case "core-telemetry": return <CoreTelemetryModule telemetry={data.telemetry} />;
    case "sensors": return <SensorsModule telemetry={data.telemetry} />;
    case "network": return <NetworkModule connected={data.connected} connectionLabel={data.connectionLabel} telemetry={data.telemetry} coreMode={data.desktopRuntime?.coreMode} />;
    case "active-processes": return <ActiveProcessesModule agentReady={data.agentReady} />;
    case "analytics": return <AnalyticsModule messages={data.messages} tasks={data.tasks} recentImages={data.recentImages} />;
    case "system-coordinates": return <SystemCoordinatesModule desktopRuntime={data.desktopRuntime} baseUrl={data.config.baseUrl} />;
    case "data-streams": return <DataStreamsModule config={data.config} connected={data.connected} />;
    case "tasks": return <TasksModule config={data.config} connected={data.connected} seed={data.tasks} />;
    case "research": return <ResearchModule entity={data.stageEntity} />;
    case "vision": return <VisionModule message={data.visionMessage} />;
    case "files": return <FilesModule config={data.config} connected={data.connected} />;
    case "devices": return <DevicesModule config={data.config} connected={data.connected} />;
    case "create": return <CreateModule recentImages={data.recentImages} />;
    case "activity": return <ActivityModule events={data.events} />;
    case "voice": return <VoiceModule voiceState={data.voiceState} voiceLabel={data.voiceLabel} fullVoiceActive={data.fullVoiceActive} />;
    case "memory": return <MemoryModule config={data.config} connected={data.connected} />;
    default: return null;
  }
}

/* ---------- Shared module frame + docking zones ---------- */

function ModuleFrame({ def, state, onCollapse, onPin, onMove, onClose, children }: {
  def: HudModuleDefinition;
  state: HudModuleState;
  onCollapse: () => void;
  onPin: () => void;
  onMove: () => void;
  onClose: () => void;
  children: ReactNode;
}) {
  return <section className="hud-module" data-pinned={state.pinned ? "true" : "false"}>
    <header>
      <Icon name={def.icon} />
      <div className="hud-module-heading"><strong>{def.label}</strong><span>{def.kicker}</span></div>
      <div className="hud-module-controls">
        <button type="button" onClick={onPin} aria-pressed={state.pinned} aria-label={`${def.label} modülünü sabitle`} title="Pin"><Icon name="pin" /></button>
        <button type="button" onClick={onMove} aria-label={`${def.label} modülünü diğer rayına taşı`} title="Move rail" className="hud-module-move">{state.zone === "left" ? "→" : "←"}</button>
        <button type="button" onClick={onCollapse} aria-expanded={!state.collapsed} aria-label={state.collapsed ? `${def.label} modülünü genişlet` : `${def.label} modülünü daralt`} className="hud-module-chevron" data-open={state.collapsed ? "false" : "true"}><Icon name="chevron" /></button>
        <button type="button" onClick={onClose} aria-label={`${def.label} modülünü kapat`}>×</button>
      </div>
    </header>
    {!state.collapsed && <div className="hud-module-body">{children}</div>}
  </section>;
}

export function HudZone({ zone, layout, data, onCollapse, onPin, onMove, onClose }: {
  zone: HudZoneId;
  layout: HudLayout;
  data: HudModuleData;
  onCollapse: (id: HudModuleId) => void;
  onPin: (id: HudModuleId) => void;
  onMove: (id: HudModuleId) => void;
  onClose: (id: HudModuleId) => void;
}) {
  const modules = HUD_MODULES
    .filter((module) => layout[module.id].enabled && layout[module.id].zone === zone)
    .sort((a, b) => Number(layout[b.id].pinned) - Number(layout[a.id].pinned));
  if (modules.length === 0) return null;
  return <div className={`hud-zone hud-zone-${zone}`} aria-label={`${zone === "left" ? "Sol" : "Sağ"} HUD modülleri`}>
    {modules.map((module) => <ModuleFrame
      key={module.id}
      def={module}
      state={layout[module.id]}
      onCollapse={() => onCollapse(module.id)}
      onPin={() => onPin(module.id)}
      onMove={() => onMove(module.id)}
      onClose={() => onClose(module.id)}
    >{renderModuleBody(module.id, data)}</ModuleFrame>)}
  </div>;
}

/* ---------- Module Inventory / HUD toolbox ---------- */

export function ModuleInventory({ open, onToggleOpen, layout, toggleModule, togglePinned, moveZone }: {
  open: boolean;
  onToggleOpen: () => void;
  layout: HudLayout;
  toggleModule: (id: HudModuleId) => void;
  togglePinned: (id: HudModuleId) => void;
  moveZone: (id: HudModuleId) => void;
}) {
  const activeCount = HUD_MODULES.filter((module) => layout[module.id].enabled).length;
  return <div className="hud-inventory">
    <button type="button" className="hud-inventory-toggle" aria-expanded={open} aria-controls="hud-inventory-panel" onClick={onToggleOpen} aria-label="Module Inventory" title="Module Inventory">
      <Icon name="grid" /><small>{activeCount || ""}</small>
    </button>
    {open && <div className="hud-inventory-panel" id="hud-inventory-panel">
      <header><span>MODULE INVENTORY</span><small>{activeCount} / {HUD_MODULES.length} ACTIVE</small></header>
      <div className="hud-inventory-list">
        {HUD_MODULES.map((module) => {
          const state = layout[module.id];
          return <div className="hud-inventory-row" key={module.id} data-enabled={state.enabled ? "true" : "false"}>
            <button type="button" className="hud-inventory-main" onClick={() => toggleModule(module.id)} aria-pressed={state.enabled}>
              <Icon name={module.icon} />
              <span><strong>{module.label}</strong><small>{module.description}</small></span>
            </button>
            <div className="hud-inventory-actions">
              <button type="button" className="hud-inventory-zone" disabled={!state.enabled} onClick={() => moveZone(module.id)} title="Rayı değiştir">{state.zone.toUpperCase()}</button>
              <button type="button" aria-pressed={state.pinned} disabled={!state.enabled} onClick={() => togglePinned(module.id)} title="Sabitle"><Icon name="pin" /></button>
            </div>
          </div>;
        })}
      </div>
    </div>}
  </div>;
}
