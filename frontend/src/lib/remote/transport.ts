// Transports for akashi.remote/1. Both carry the same envelopes; the session
// client above them does not care which one is in use.
//
// * WebSocketTransport — full duplex; credentials go in the first frame, never the URL.
// * HttpTransport      — batched POST for uplink, long-poll GET (cursor) for downlink.
//                        Used where WebSocket is unavailable: the desktop IPC bridge
//                        (CSP connect-src 'self'), strict proxies, some tunnels.

import type { ClientEnvelope, ServerMessage } from "./protocol.ts";

export type TransportName = "websocket" | "http";

export type TransportAuth = { sessionId: string; token: string; resumeAfter: number | null };

export type TransportEvents = {
  onOpen(info: { resumed: boolean; body: Record<string, unknown> }): void;
  onMessage(message: ServerMessage): void;
  /** code 4401 = credential rejected, 4403 = revoked/forbidden, other = network. */
  onClose(code: number, reason: string): void;
};

export interface Transport {
  readonly name: TransportName;
  open(auth: TransportAuth): void;
  send(envelopes: ClientEnvelope[]): boolean;
  close(): void;
}

export type TransportFactory = (events: TransportEvents) => Transport;

type SocketLike = {
  readyState: number;
  send(data: string): void;
  close(code?: number): void;
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number; reason: string }) => void) | null;
  onerror: ((event: unknown) => void) | null;
};

export function websocketUrl(coreUrl: string): string {
  const url = new URL("/remote/ws", coreUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

export class WebSocketTransport implements Transport {
  readonly name = "websocket" as const;
  private socket: SocketLike | null = null;
  private ready = false;
  private closed = false;

  constructor(private readonly coreUrl: string, private readonly events: TransportEvents,
              private readonly create: (url: string) => SocketLike = (url) => new WebSocket(url) as unknown as SocketLike) {}

  open(auth: TransportAuth): void {
    this.closed = false;
    const socket = this.create(websocketUrl(this.coreUrl));
    this.socket = socket;
    socket.onopen = () => {
      socket.send(JSON.stringify({ type: "auth", session_id: auth.sessionId, token: auth.token, resume_after: auth.resumeAfter }));
    };
    socket.onmessage = (event) => {
      let message: ServerMessage;
      try { message = JSON.parse(String(event.data)); } catch { return; }
      if (message.kind === "session.welcome") {
        this.ready = true;
        this.events.onOpen({ resumed: Boolean(message.body.resumed), body: message.body });
        return;
      }
      this.events.onMessage(message);
    };
    socket.onclose = (event) => {
      const wasReady = this.ready;
      this.ready = false;
      if (this.socket === socket) this.socket = null;
      if (!this.closed) this.events.onClose(event.code || (wasReady ? 1006 : 1006), event.reason || "closed");
    };
    socket.onerror = () => { /* onclose follows */ };
  }

  send(envelopes: ClientEnvelope[]): boolean {
    if (!this.ready || !this.socket || this.socket.readyState !== 1) return false;
    for (const envelope of envelopes) this.socket.send(JSON.stringify(envelope));
    return true;
  }

  close(): void {
    this.closed = true;
    this.ready = false;
    try { this.socket?.close(1000); } catch { /* already closed */ }
    this.socket = null;
  }
}

export type HttpRequest = (path: string, init: { method: "GET" | "POST" | "DELETE"; body?: unknown; signal?: AbortSignal }) => Promise<{ status: number; json: unknown }>;

export class HttpTransport implements Transport {
  readonly name = "http" as const;
  private auth: TransportAuth | null = null;
  private cursor = 0;
  private open_ = false;
  private queue: ClientEnvelope[] = [];
  private flushing = false;
  private abort: AbortController | null = null;
  private generation = 0;

  constructor(private readonly request: HttpRequest, private readonly events: TransportEvents, private readonly waitSeconds = 20) {}

  open(auth: TransportAuth): void {
    this.auth = auth;
    this.cursor = auth.resumeAfter ?? 0;
    this.open_ = true;
    const generation = ++this.generation;
    this.events.onOpen({ resumed: auth.resumeAfter !== null, body: {} });
    void this.pollLoop(generation, auth.resumeAfter === null);
  }

  private fail(generation: number, status: number, payload: unknown): void {
    if (generation !== this.generation || !this.open_) return;
    this.open_ = false;
    const code = typeof payload === "object" && payload && "code" in payload ? String((payload as { code: unknown }).code) : "";
    this.events.onClose(status === 401 ? (code === "session_revoked" ? 4403 : 4401) : 1006, code || `http ${status}`);
  }

  private async pollLoop(generation: number, fresh: boolean): Promise<void> {
    let first = fresh;
    while (this.open_ && generation === this.generation && this.auth) {
      this.abort = new AbortController();
      try {
        const wait = first ? 0 : this.waitSeconds;
        first = false;
        const response = await this.request(`/remote/sessions/${encodeURIComponent(this.auth.sessionId)}/poll?after=${this.cursor}&wait=${wait}`,
          { method: "GET", signal: this.abort.signal });
        if (generation !== this.generation) return;
        if (response.status !== 200) return this.fail(generation, response.status, response.json);
        const body = response.json as { messages: ServerMessage[]; resync: boolean; state: string };
        if (body.resync) this.events.onMessage({ v: 1, kind: "resync_required", body: { reason: "resume window passed" } });
        for (const message of body.messages) {
          if (typeof message.sseq === "number" && message.sseq <= this.cursor) continue;
          if (typeof message.sseq === "number") this.cursor = message.sseq;
          this.events.onMessage(message);
        }
        if (body.state === "closed") return this.fail(generation, 401, { code: "session_expired" });
      } catch {
        if (generation !== this.generation || !this.open_) return;
        return this.fail(generation, 0, null);
      }
    }
  }

  send(envelopes: ClientEnvelope[]): boolean {
    if (!this.open_) return false;
    this.queue.push(...envelopes);
    void this.flush();
    return true;
  }

  /** One POST in flight at a time keeps uplink order (reordering would only cost rejections). */
  private async flush(): Promise<void> {
    if (this.flushing || !this.auth) return;
    this.flushing = true;
    const generation = this.generation;
    try {
      while (this.queue.length && this.open_ && generation === this.generation) {
        const batch = this.queue.splice(0, 32);
        try {
          const response = await this.request(`/remote/sessions/${encodeURIComponent(this.auth.sessionId)}/messages`,
            { method: "POST", body: { messages: batch } });
          if (response.status !== 200) {
            this.fail(generation, response.status, response.json);
            return;
          }
          for (const message of (response.json as { responses: ServerMessage[] }).responses) this.events.onMessage(message);
        } catch {
          this.fail(generation, 0, null);
          return;
        }
      }
    } finally {
      this.flushing = false;
    }
  }

  close(): void {
    this.open_ = false;
    this.generation += 1;
    this.queue = [];
    this.abort?.abort();
  }
}
