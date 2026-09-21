import { useEffect, useState } from "react";

export type Telemetry = {
  cpu: number | null;
  ramPercent: number | null;
  ramUsed: number | null;
  ramTotal: number | null;
  disk: number | null;
  uptime: number | null;
  network: boolean | null;
  gpuName: string | null;
  gpu: number | null;
  temperature: number | null;
  vramUsed: number | null;
  vramTotal: number | null;
};

function finite(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function parseTelemetry(payload: unknown): Telemetry | null {
  if (!payload || typeof payload !== "object") return null;
  const root = payload as { ok?: boolean; data?: Record<string, unknown> };
  if (!root.ok || !root.data) return null;
  const cpu = root.data.cpu as Record<string, unknown> | undefined;
  const memory = root.data.memory as Record<string, unknown> | undefined;
  const disk = root.data.disk as Record<string, unknown> | undefined;
  const gpuRoot = root.data.gpu as { devices?: Array<Record<string, unknown>> } | undefined;
  const gpu = gpuRoot?.devices?.[0];
  const total = finite(memory?.total_bytes);
  const available = finite(memory?.available_bytes);
  const used = total !== null && available !== null ? total - available : null;
  return {
    cpu: finite(cpu?.usage_percent),
    ramPercent: total && used !== null ? (used / total) * 100 : null,
    ramUsed: used,
    ramTotal: total,
    disk: finite(disk?.usage_percent),
    uptime: finite(root.data.uptime_seconds),
    network: typeof root.data.network_online === "boolean" ? root.data.network_online : null,
    gpuName: typeof gpu?.name === "string" ? gpu.name : null,
    gpu: finite(gpu?.usage_percent),
    temperature: finite(gpu?.temperature_c),
    vramUsed: finite(gpu?.memory_used_mb),
    vramTotal: finite(gpu?.memory_total_mb),
  };
}

export function metric(value: number | null, suffix = "%") {
  return value === null ? "—" : `${Math.round(value)}${suffix}`;
}

export function memoryGB(value: number | null) {
  return value === null ? "—" : `${(value / 1024 ** 3).toFixed(1)} GB`;
}

export function uptimeLabel(seconds: number | null) {
  if (seconds === null) return "—";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

/** Polls the local Windows Agent directly (no device pairing) for this machine's own telemetry. */
export function useDesktopTelemetry(enabled: boolean) {
  const [telemetry, setTelemetry] = useState<Telemetry | null>(null);
  useEffect(() => {
    if (!enabled || !window.akashiDesktop?.agent) return;
    let active = true;
    const refresh = async () => {
      if (document.hidden) return;
      try {
        const result = await window.akashiDesktop!.agent.execute("get_system_status", {}, false);
        if (active) setTelemetry(parseTelemetry(result));
      } catch {
        if (active) setTelemetry(null);
      }
    };
    const visibility = () => { if (!document.hidden) void refresh(); };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 10_000);
    document.addEventListener("visibilitychange", visibility);
    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [enabled]);
  return enabled ? telemetry : null;
}
