import { useCallback, useEffect, useState } from "react";

import type { IconName } from "@/components/identity";

export type HudZoneId = "left" | "right";

export type HudModuleId =
  | "core-telemetry"
  | "active-processes"
  | "sensors"
  | "analytics"
  | "system-coordinates"
  | "data-streams"
  | "tasks"
  | "research"
  | "vision"
  | "files"
  | "devices"
  | "create"
  | "activity"
  | "voice"
  | "network"
  | "memory";

export type HudModuleDefinition = {
  id: HudModuleId;
  label: string;
  kicker: string;
  icon: IconName;
  defaultZone: HudZoneId;
  description: string;
};

export const HUD_MODULES: HudModuleDefinition[] = [
  { id: "core-telemetry", label: "Core Telemetry", kicker: "CPU / RAM / GPU", icon: "pulse", defaultZone: "left", description: "CPU, RAM, GPU, VRAM, temperature and uptime from the Windows Agent." },
  { id: "sensors", label: "Sensors", kicker: "THERMAL / DISK", icon: "target", defaultZone: "left", description: "GPU temperature, disk usage and VRAM pressure readouts." },
  { id: "network", label: "Network", kicker: "LINK STATE", icon: "network", defaultZone: "left", description: "Core connection, OS network link and runtime mode." },
  { id: "active-processes", label: "Active Processes", kicker: "WINDOWS AGENT", icon: "activity", defaultZone: "right", description: "Live process list from the paired Windows Agent, by memory share." },
  { id: "analytics", label: "Analytics", kicker: "SESSION COUNTS", icon: "research", defaultZone: "right", description: "Messages, tasks, research runs and images generated this session." },
  { id: "system-coordinates", label: "System Coordinates", kicker: "RUNTIME / ENDPOINT", icon: "target", defaultZone: "right", description: "Core mode, endpoint and per-component runtime state." },
  { id: "data-streams", label: "Data Streams", kicker: "SERVICE HEALTH", icon: "stream", defaultZone: "right", description: "Live dependency health for core, auth, model, research and images." },
  { id: "tasks", label: "Tasks", kicker: "AGENT QUEUE", icon: "tasks", defaultZone: "right", description: "Queued, running and completed AKASHI tasks with cancel/inspect." },
  { id: "research", label: "Research", kicker: "ACTIVE INQUIRY", icon: "research", defaultZone: "right", description: "Latest research context, confidence and verified sources." },
  { id: "vision", label: "Vision", kicker: "CAPTURE STATE", icon: "image", defaultZone: "right", description: "Most recent vision capture processed by the router." },
  { id: "files", label: "Files", kicker: "UPLOADS", icon: "files", defaultZone: "right", description: "Uploaded, analyzable files available as chat context." },
  { id: "devices", label: "Devices", kicker: "PAIRED BRIDGE", icon: "devices", defaultZone: "right", description: "Paired devices and their online/offline state." },
  { id: "create", label: "Create", kicker: "GENERATED MEDIA", icon: "create", defaultZone: "right", description: "Images generated this session." },
  { id: "activity", label: "Activity", kicker: "OBSERVABLE LOG", icon: "activity", defaultZone: "right", description: "Observed actions and tool events, most recent first." },
  { id: "voice", label: "Voice", kicker: "SESSION STATE", icon: "mic", defaultZone: "left", description: "LISTENING / THINKING / SPEAKING / INTERRUPTED voice state." },
  { id: "memory", label: "Memory", kicker: "DURABLE CONTEXT", icon: "memory", defaultZone: "right", description: "Recently stored durable memory entries." },
];

export type HudModuleState = {
  enabled: boolean;
  collapsed: boolean;
  pinned: boolean;
  zone: HudZoneId;
};

export type HudLayout = Record<HudModuleId, HudModuleState>;

const STORAGE_KEY = "akashi_hud_layout_v1";

const DEFAULT_ENABLED: ReadonlySet<HudModuleId> = new Set(["activity", "core-telemetry"]);

/** Every module starts closed except Activity and Core Telemetry - the "minimal
 * essential runtime information" the clean default HUD keeps on screen. */
function defaultLayout(): HudLayout {
  const layout = {} as HudLayout;
  for (const definition of HUD_MODULES) {
    layout[definition.id] = { enabled: DEFAULT_ENABLED.has(definition.id), collapsed: false, pinned: false, zone: definition.defaultZone };
  }
  return layout;
}

function loadLayout(): HudLayout {
  const layout = defaultLayout();
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return layout;
    const parsed = JSON.parse(raw) as Partial<Record<HudModuleId, Partial<HudModuleState>>>;
    for (const definition of HUD_MODULES) {
      const saved = parsed[definition.id];
      if (!saved) continue;
      layout[definition.id] = {
        enabled: Boolean(saved.enabled),
        collapsed: Boolean(saved.collapsed),
        pinned: Boolean(saved.pinned),
        zone: saved.zone === "left" || saved.zone === "right" ? saved.zone : definition.defaultZone,
      };
    }
  } catch {
    return defaultLayout();
  }
  return layout;
}

/**
 * DesktopCommandCenter (and therefore this hook) only ever mounts after the
 * client-kind detection effect in page.tsx flips to "desktop", i.e. strictly
 * post-hydration — so reading localStorage in the lazy initializer is safe
 * and avoids a synchronous setState-in-effect render cascade.
 */
export function useHudLayout() {
  const [layout, setLayout] = useState<HudLayout>(() => (typeof window === "undefined" ? defaultLayout() : loadLayout()));

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(layout));
    } catch {
      /* storage unavailable; layout stays in-memory for this session */
    }
  }, [layout]);

  const toggleModule = useCallback((id: HudModuleId) => {
    setLayout((prev) => ({ ...prev, [id]: { ...prev[id], enabled: !prev[id].enabled } }));
  }, []);

  const closeModule = useCallback((id: HudModuleId) => {
    setLayout((prev) => ({ ...prev, [id]: { ...prev[id], enabled: false } }));
  }, []);

  const toggleCollapsed = useCallback((id: HudModuleId) => {
    setLayout((prev) => ({ ...prev, [id]: { ...prev[id], collapsed: !prev[id].collapsed } }));
  }, []);

  const togglePinned = useCallback((id: HudModuleId) => {
    setLayout((prev) => ({ ...prev, [id]: { ...prev[id], pinned: !prev[id].pinned } }));
  }, []);

  const moveZone = useCallback((id: HudModuleId) => {
    setLayout((prev) => ({ ...prev, [id]: { ...prev[id], zone: prev[id].zone === "left" ? "right" : "left" } }));
  }, []);

  return { layout, toggleModule, closeModule, toggleCollapsed, togglePinned, moveZone };
}
