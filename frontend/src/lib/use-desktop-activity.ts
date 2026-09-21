import { useEffect, useMemo, useRef, useState } from "react";
import { apiFetch, type BackendConfig } from "./api";
import { observableLabel, observeDesktop, type CoreObservation } from "./desktop-activity";
import type { DesktopMessage, HudActivityEvent } from "./desktop-types";

export function useDesktopActivity(config: BackendConfig, connected: boolean, messages: DesktopMessage[], voice: string, runtime: string, workspace: string) {
  const [events, setEvents] = useState<HudActivityEvent[]>([]);
  const seen = useRef(new Set<string>());
  useEffect(() => {
    const receive = (event: Event) => {
      const observation = (event as CustomEvent<HudActivityEvent>).detail;
      setEvents(current => [...current.slice(-79), observation]);
    };
    window.addEventListener("akashi:observation", receive);
    return () => window.removeEventListener("akashi:observation", receive);
  }, []);
  useEffect(() => {
    for (const message of messages) {
      if (seen.current.has(message.id)) continue;
      seen.current.add(message.id);
      observeDesktop(message.content.replace(/\s+/gu, " "), message.role === "user" ? "YOU" : "AKASHI");
    }
    if (seen.current.size > 500) seen.current = new Set(messages.map(message => message.id));
  }, [messages]);
  useEffect(() => { if (voice !== "idle") observeDesktop(`STATE · ${voice.toUpperCase()}`, "SYSTEM"); }, [voice]);
  useEffect(() => { if (runtime) observeDesktop(runtime, "SYSTEM"); }, [runtime]);
  useEffect(() => { if (workspace) observeDesktop(workspace); }, [workspace]);
  useEffect(() => {
    if (!connected) return;
    let stopped = false, cursor = 0, instance = "", timer: ReturnType<typeof setTimeout>;
    const controller = new AbortController();
    const poll = async () => {
      if (!document.hidden) {
        try {
          const response = await apiFetch(config, `/events/recent?after=${cursor}`, { signal: controller.signal });
          const value = await response.json() as { cursor: number; instance: string; events: CoreObservation[] };
          if (!stopped && Array.isArray(value.events)) {
            if (instance && instance !== value.instance) { cursor = 0; instance = value.instance; }
            else {
              instance = value.instance; cursor = value.cursor;
              const incoming = value.events.flatMap(event => {
                const label = observableLabel(event);
                return label ? [{ id: `${instance}:${event.id}`, timestamp: event.timestamp, actor: "AKASHI" as const, label }] : [];
              });
              if (incoming.length) setEvents(current => [...current, ...incoming.filter(event => !current.some(old => old.id === event.id))].slice(-80));
            }
          }
        } catch { /* Older/offline Core: local observations remain available. */ }
      }
      if (!stopped) timer = setTimeout(poll, 1400);
    };
    void poll();
    return () => { stopped = true; controller.abort(); clearTimeout(timer); };
  }, [config, connected]);
  return useMemo(() => [...events].sort((a, b) => Date.parse(a.timestamp) - Date.parse(b.timestamp)), [events]);
}
