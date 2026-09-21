"use client";
/* eslint-disable @next/next/no-img-element -- Approved device captures are runtime data URLs. */
import { Markdown } from "./markdown";

function record(value: unknown): Record<string, unknown> { return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}; }
function metric(value: unknown, suffix = ""): string { return typeof value === "number" && Number.isFinite(value) ? `${Math.round(value * 10) / 10}${suffix}` : "—"; }
function safeDetail(key: string, value: unknown) {
  if (/token|password|secret|base64|credential|authorization/i.test(key)) return "[omitted]";
  return typeof value === "string" && value.length > 5000 ? `${value.slice(0, 5000)}…` : value;
}
export function ToolResult({ value }: { value: unknown }) {
  const outer = record(value), data = record(outer.data || outer);
  const cpu = record(data.cpu), memory = record(data.memory), gpu = record(data.gpu);
  const device = record(Array.isArray(gpu.devices) ? gpu.devices[0] : null);
  if (data.cpu && data.memory) return <div className="telemetry">
    <div className="list-meta"><span>{String(data.hostname || "DEVICE")}</span><span>CANLI ÖLÇÜM · ANLIK</span></div>
    <div className="telemetry-grid">
      <div><small>CPU</small><strong>{metric(cpu.usage_percent, "%")}</strong><span>{metric(cpu.logical_cores)} çekirdek</span></div>
      <div><small>GPU</small><strong>{metric(device.usage_percent, "%")}</strong><span>{gpu.available ? `${metric(device.temperature_c, "°C")} · ${String(device.name || "")}` : "Telemetri yok"}</span></div>
      <div><small>RAM</small><strong>{metric(memory.usage_percent, "%")}</strong><span>{typeof memory.total_bytes === "number" ? `${(memory.total_bytes / 2 ** 30).toFixed(1)} GB toplam` : "—"}</span></div>
    </div><div className="list-meta"><span>UPTIME {metric(typeof data.uptime_seconds === "number" ? data.uptime_seconds / 3600 : null, " h")}</span><span>{data.network_online ? "NETWORK UP" : "NETWORK UNKNOWN"}</span></div>
  </div>;
  if (data.media_type === "image/jpeg" && typeof data.base64 === "string" && data.base64.length < 2_000_000) return <img className="generated-image" src={`data:image/jpeg;base64,${data.base64}`} alt={data.source === "camera" ? "İstenen tek kare kamera görüntüsü" : "İstenen cihaz ekran görüntüsü"} />;
  if (typeof data.summary === "string") return <Markdown>{data.summary}</Markdown>;
  if (data.status === "offline") return <p className="panel-notice">Desktop agent çevrimdışı. Yerel agent servisini başlat.</p>;
  return <details><summary>Sonucu incele</summary><pre>{JSON.stringify(value, safeDetail, 2)}</pre></details>;
}

const actionFields: Record<string, Array<[string, string]>> = {
  application_status: [["application", "Uygulama: vscode, edge, chrome…"]], list_directory: [["path", "Onaylı kök içindeki klasör"]],
  find_file: [["root", "Onaylı arama kökü"], ["query", "Dosya adı parçası"]], file_metadata: [["path", "Dosya yolu"]],
  launch_application: [["application", "Uygulama: vscode, edge, chrome…"], ["url", "İsteğe bağlı HTTPS adresi"]],
  open_project: [["path", "Proje klasörü"]], reveal_file: [["path", "Dosya yolu"]], run_project_script: [["project", "Onaylı proje"], ["script", "Onaylı npm betiği"]],
};
export function ActionFields({ action, value, onChange }: { action: string; value: Record<string, unknown>; onChange: (next: Record<string, unknown>) => void }) {
  return <>{(actionFields[action] || []).map(([key, label]) => <label key={key}>{label}<input value={String(value[key] || "")} onChange={(event) => onChange({ ...value, [key]: event.target.value })} /></label>)}</>;
}
