import { Capacitor } from "@capacitor/core";

export type ClientKind = "web" | "mobile" | "desktop";
export type ProductMood = "calm" | "hardcarry" | "best";
export type WorkspaceView =
  | "home"
  | "chat"
  | "create"
  | "research"
  | "memory"
  | "tasks"
  | "files"
  | "devices"
  | "autonomy"
  | "more";

export type ClientPresentation = {
  kind: ClientKind;
  primaryNavigation: WorkspaceView[];
  availableWorkspaces: WorkspaceView[];
  desktopBody: "primary" | "secondary" | "hidden";
  label: string;
};

const presentations: Record<ClientKind, ClientPresentation> = {
  web: {
    kind: "web",
    primaryNavigation: ["home", "chat", "create", "research", "memory", "files", "more"],
    availableWorkspaces: ["home", "chat", "create", "research", "memory", "tasks", "files", "more"],
    desktopBody: "hidden",
    label: "WEB",
  },
  mobile: {
    kind: "mobile",
    primaryNavigation: ["home", "chat", "create", "memory", "more"],
    availableWorkspaces: ["home", "chat", "create", "research", "memory", "tasks", "files", "devices", "more"],
    desktopBody: "secondary",
    label: "MOBILE",
  },
  desktop: {
    kind: "desktop",
    primaryNavigation: ["home", "chat", "create", "research", "tasks", "memory", "files", "devices"],
    availableWorkspaces: ["home", "chat", "create", "research", "tasks", "memory", "files", "devices", "autonomy", "more"],
    desktopBody: "primary",
    label: "DESKTOP",
  },
};

export function presentationForClient(kind: ClientKind): ClientPresentation {
  return presentations[kind];
}

export function detectClientKind(): ClientKind {
  if (typeof window !== "undefined" && window.akashiDesktop) return "desktop";
  if (typeof window !== "undefined" && window.akashiClientKind) return window.akashiClientKind;
  if (Capacitor.isNativePlatform()) return "mobile";
  return "web";
}

export function canPresentWorkspace(kind: ClientKind, workspace: WorkspaceView): boolean {
  return presentations[kind].availableWorkspaces.includes(workspace);
}

export function automaticMood(input: {
  connected: boolean;
  busy: boolean;
  intensive: boolean;
}): ProductMood {
  if (input.busy && input.intensive) return "hardcarry";
  if (input.connected) return "best";
  return "calm";
}
