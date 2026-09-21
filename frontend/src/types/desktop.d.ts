export {};

declare global {
  type DesktopBackendConfig = {
    baseUrl: string;
    tokenStored: boolean;
    coreMode?: "local" | "remote";
  };

  type DesktopProviderConfig = {
    aiProvider: "" | "ollama" | "gemini" | "mock";
    geminiKeyStored: boolean;
    geminiModel: string;
  };

  type DesktopBody =
    | { kind: "none" }
    | { kind: "text"; value: string }
    | { kind: "base64"; value: string }
    | {
        kind: "form";
        entries: Array<
          | { kind: "text"; name: string; value: string }
          | { kind: "file"; name: string; value: string; filename: string; type: string }
        >;
      };

  type DesktopRuntimeComponent = {
    state: "STARTING" | "READY" | "DEGRADED" | "OFFLINE" | "RECOVERING" | "FAILED";
    detail: string;
    pid: number | null;
    owned: boolean;
    restartCount: number;
  };

  type DesktopRuntimeStatus = {
    overall: DesktopRuntimeComponent["state"];
    coreMode: "local" | "remote";
    updatedAt: string;
    components: Record<"core" | "agent" | "ollama" | "comfyui" | "voice", DesktopRuntimeComponent>;
  };

  /** One JSON-line event from the desktop Gemini Live fast voice path (voice/live.py). */
  type DesktopVoiceLiveEvent =
    | { event: "ready" }
    | { event: "state"; state: "connecting" | "listening" | "thinking" | "speaking" | "interrupted" | "idle"; resumed?: boolean }
    | { event: "transcript"; role: "user" | "assistant"; text: string; final: boolean }
    | { event: "tool"; name: string; status: "start" | "done" | "error"; detail?: string }
    | { event: "latency"; label: string; ms: number }
    | { event: "error"; message: string; transient?: boolean };

  interface Window {
    /** Optional host presentation hint. It gates UI only; backend authorization remains authoritative. */
    akashiClientKind?: "web" | "mobile" | "desktop";
    akashiDesktop?: {
      platform: string;
      config: {
        load(): Promise<DesktopBackendConfig>;
        save(value: { baseUrl: string; token?: string; coreMode?: "local" | "remote" }): Promise<DesktopBackendConfig>;
      };
      provider: {
        load(): Promise<DesktopProviderConfig>;
        save(value: { aiProvider?: string; geminiApiKey?: string; geminiModel?: string }): Promise<DesktopProviderConfig>;
      };
      windowControls: {
        minimize(): Promise<boolean>;
        maximize(): Promise<boolean>;
        close(): Promise<boolean>;
        isMaximized(): Promise<boolean>;
        onState(callback: (value: { maximized: boolean }) => void): () => void;
      };
      runtime?: {
        status(): Promise<DesktopRuntimeStatus | null>;
        whenReady(): Promise<DesktopRuntimeStatus | null>;
        recover(component: "core" | "agent"): Promise<DesktopRuntimeStatus>;
        onState(callback: (value: DesktopRuntimeStatus) => void): () => void;
      };
      api: {
        fetch(request: {
          path: string;
          method: string;
          headers: Record<string, string>;
          body: DesktopBody;
          authenticated: boolean;
        }): Promise<{
          status: number;
          statusText: string;
          headers: Record<string, string>;
          body: string;
        }>;
      };
      agent: {
        status(): Promise<Record<string, unknown>>;
        execute(
          action: string,
          arguments_: Record<string, unknown>,
          approved: boolean,
        ): Promise<Record<string, unknown>>;
      };
      voice: {
        status(): Promise<Record<string, unknown>>;
        listen(options: { language: "auto" | "tr" | "en"; model: "tiny" | "base" | "small"; bargeIn?: boolean }): Promise<{ transcript: string; language: string; engine: string; device: string }>;
        stop(): Promise<boolean>;
        onState(callback: (value: { state: "listening" | "speech_started" | "transcribing"; detectedAtMs?: number }) => void): () => void;
        live: {
          available(): Promise<boolean>;
          start(options?: { language?: "auto" | "tr" | "en" }): Promise<{ started: boolean; alreadyRunning?: boolean }>;
          stop(): Promise<boolean>;
          interrupt(): Promise<boolean>;
          sendText(text: string): Promise<boolean>;
          onEvent(callback: (value: DesktopVoiceLiveEvent) => void): () => void;
        };
      };
      shell: {
        showDataFolder(): Promise<boolean>;
        openExternal(url: string): Promise<boolean>;
      };
    };
  }
}
