export type DesktopMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  meta?: string;
  imageUrl?: string;
  retry?: { text: string; mode: "chat" | "fast" | "quality" | "edit" };
};

export type HudActivityEvent = {
  id: string;
  timestamp: string;
  actor: "YOU" | "AKASHI" | "SYSTEM";
  label: string;
};
