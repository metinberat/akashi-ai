import type { HudActivityEvent } from "./desktop-types";

export function observeDesktop(label: string, actor: HudActivityEvent["actor"] = "AKASHI") {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent("akashi:observation", { detail: {
    id: crypto.randomUUID(), actor, label: label.slice(0, 200),
    timestamp: new Date().toISOString(),
  } }));
}

export type CoreObservation = { id: number; timestamp: string; type: string; data: Record<string, unknown> };
const states: Record<string, string> = {
  planning: "Araştırma planı hazırlanıyor", searching: "Kaynaklar aranıyor", reading: "Kaynaklar toplandı",
  synthesizing: "Bulgular birleştiriliyor", completed: "Tamamlandı", failed: "Başarısız", cancelled: "Durduruldu",
  queued: "Sırada", running: "Çalışıyor", waiting_confirmation: "Onay bekleniyor",
};
export function observableLabel(event: CoreObservation): string | null {
  if (event.type === "research.progress") {
    const state = String(event.data.state || "");
    const count = typeof event.data.source_count === "number" ? ` · ${event.data.source_count} kaynak` : "";
    if (event.data.source_count === 0 && (state === "reading" || state === "completed")) return "Araştırma · Kaynak bulunamadı";
    return states[state] ? `${states[state]}${count}` : null;
  }
  if (event.type.startsWith("live.action.")) {
    const action = typeof event.data.action === "string" ? event.data.action.replaceAll("_", " ") : "Desktop eylemi";
    const phase = event.type.split(".").at(-1)!;
    return `${action} · ${phase === "started" ? "Başladı" : states[phase] || phase}`;
  }
  if (event.type.startsWith("task.")) return `Görev · ${states[String(event.data.status)] || event.type.split(".").at(-1)}`;
  return null;
}
