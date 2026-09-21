import type { CSSProperties } from "react";

export type IconName = "home" | "chat" | "create" | "research" | "tasks" | "memory" | "files" | "devices" | "more" | "activity" | "settings" | "plus" | "image" | "mic" | "stop" | "arrow" | "volume" | "grid" | "pin" | "chevron" | "pulse" | "target" | "stream" | "network" | "minimize" | "maximize" | "restore" | "close" | "autonomy";
const paths: Record<IconName, string> = {
  home: "M4 11 12 4l8 7v9h-6v-6h-4v6H4v-9Z",
  chat: "M5 4h14v12H9l-4 4V4Z M9 8h6 M9 12h4",
  create: "M4 20h16 M6 16 16 6l2 2L8 18H6v-2Z M14 5l2-2 5 5-2 2",
  research: "M20 20l-5-5 M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Z",
  tasks: "M9 5h11 M9 12h11 M9 19h11 M3 5l1 1 2-2 M3 12l1 1 2-2 M3 19h2",
  memory: "M12 3 21 12 12 21 3 12 12 3Z M12 8l4 4-4 4-4-4 4-4Z",
  files: "M5 3h9l5 5v13H5V3Z M14 3v6h5 M8 13h8 M8 17h5",
  devices: "M3 4h18v13H3V4Z M8 21h8 M12 17v4",
  more: "M5 12h.01 M12 12h.01 M19 12h.01",
  activity: "M3 12h4l2-6 4 12 2-6h6",
  settings: "M4 7h16 M4 17h16 M8 4v6 M16 14v6",
  plus: "M12 5v14 M5 12h14",
  image: "M3 3h18v18H3V3Z M3 17l6-6 4 4 3-3 5 5 M16 7h.01",
  mic: "M9 5a3 3 0 0 1 6 0v7a3 3 0 0 1-6 0V5Z M5 10v2a7 7 0 0 0 14 0v-2 M12 19v3 M9 22h6",
  stop: "M6 6h12v12H6V6Z", arrow: "M12 20V4 M5 11l7-7 7 7",
  volume: "M3 9h4l5-4v14l-5-4H3V9Z M16 8a6 6 0 0 1 0 8 M19 5a10 10 0 0 1 0 14",
  grid: "M4 4h7v7H4V4Z M13 4h7v7h-7V4Z M4 13h7v7H4v-7Z M13 13h7v7h-7v-7Z",
  pin: "M12 2c-3.3 0-6 2.7-6 6 0 4.5 6 11 6 11s6-6.5 6-11c0-3.3-2.7-6-6-6Z M12 11.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  chevron: "M6 9l6 6 6-6",
  pulse: "M2 12h4l2 6 4-15 3 9 2-6h5",
  target: "M12 2v4 M12 18v4 M2 12h4 M18 12h4 M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6Z",
  stream: "M3 6h18 M3 12h12 M3 18h8",
  network: "M3 9a13 13 0 0 1 18 0 M6.5 12.5a8 8 0 0 1 11 0 M10 16a3 3 0 0 1 4 0 M12 20h.01",
  minimize: "M5 12h14",
  maximize: "M5 5h14v14H5V5Z",
  restore: "M8 4h12v12h-4 M4 8h12v12H4V8Z",
  close: "M6 6l12 12 M18 6 6 18",
  autonomy: "M12 2 20 7v10l-8 5-8-5V7Z M12 7v10 M8.5 9l7 6 M15.5 9l-7 6",
};
export function Icon({ name }: { name: IconName }) {
  return <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name]} /></svg>;
}

export function Presence({ state = "idle", compact = false }: { state?: string; compact?: boolean }) {
  return <span className={`presence ${compact ? "compact" : ""}`} data-state={state} aria-hidden="true">
    <svg viewBox="0 0 80 80" fill="none"><path d="M40 9 68 65H12L40 9Z" stroke="currentColor" strokeWidth="1.3"/><path d="M40 27 59 65M40 27 21 65M26 49h28M4 49h15M61 49h15" stroke="currentColor" strokeWidth="1"/><path className="presence-scan" d="M26 40h28" stroke="currentColor" strokeWidth="2"/></svg>
  </span>;
}

export const visuallyHidden: CSSProperties = { position: "absolute", width: 1, height: 1, overflow: "hidden", clipPath: "inset(50%)" };
