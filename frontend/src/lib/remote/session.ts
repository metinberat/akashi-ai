// RemoteSessionClient: one live, self-healing session with AKASHI Core.
//
// Responsibilities (transport-independent):
// * handshake (device key or owner token, injected) → short-lived session
// * reliable requests: unique id + increasing seq; resent unchanged (same id/seq)
//   after timeouts and reconnects so Core can de-duplicate; retryable errors back off
// * realtime sends: fire-and-forget, dropped while offline (never queued stale)
// * heartbeat with RTT measurement; silence → reconnect
// * reconnect with exponential backoff + jitter; resume after the last processed
//   sseq; sleep/wake and network changes trigger an immediate attempt
// * a NEW session (expiry, Core restart) fails unanswered requests with
//   "outcome_unknown" instead of resending them: the new session cannot
//   de-duplicate, so resending could apply a change twice. Consumers re-sync.
// * revocation stops everything.

import { RemoteFailure, errorFrom, messageId, type ClientEnvelope, type ServerMessage, type Welcome } from "./protocol.ts";
import type { Transport, TransportFactory, TransportName } from "./transport.ts";

export type SessionState = "idle" | "connecting" | "online" | "reconnecting" | "revoked" | "unpaired" | "closed";

export type Timer = unknown;
export type ClientClock = {
  now(): number;
  wall(): number;
  setTimeout(fn: () => void, ms: number): Timer;
  clearTimeout(handle: Timer): void;
};

export const browserClientClock: ClientClock = {
  now: () => (typeof performance !== "undefined" ? performance.now() : Date.now()),
  wall: () => Date.now(),
  setTimeout: (fn, ms) => setTimeout(fn, ms),
  clearTimeout: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>),
};

export type SessionOptions = {
  handshake: () => Promise<Welcome>;
  transports: Array<{ name: TransportName; create: TransportFactory }>;
  clock?: ClientClock;
  random?: () => number;
  attemptTimeoutMs?: number;
  requestDeadlineMs?: number;
};

type Pending = {
  envelope: ClientEnvelope;
  resolve: (body: Record<string, unknown>) => void;
  reject: (error: RemoteFailure) => void;
  sentAt: number;
  attempts: number;
  deadline: number;
  timer: Timer | null;
  session: string;
  lastError?: RemoteFailure;
};

type Handler = (message: ServerMessage) => void;

export type SessionMetrics = {
  state: SessionState;
  transport: TransportName | null;
  sessionId: string | null;
  rttMs: { last: number | null; p50: number | null; p95: number | null };
  sent: number;
  received: number;
  retransmits: number;
  duplicatesAcked: number;
  reconnects: number;
  handshakes: number;
  pending: number;
  cursor: number;
  errors: Record<string, number>;
  offlineMs: number;
};

function percentile(values: number[], p: number): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
}

export class RemoteSessionClient {
  state: SessionState = "idle";
  welcome: Welcome | null = null;
  private transport: Transport | null = null;
  private transportIndex = 0;
  private wsFailures = 0;
  private seq = 0;
  private cursor = 0;
  private pending = new Map<string, Pending>();
  private handlers = new Map<string, Set<Handler>>();
  private listeners = new Set<(state: SessionState) => void>();
  private sessionListeners = new Set<(welcome: Welcome, resumed: boolean) => void>();
  private heartbeat: Timer | null = null;
  private reconnectTimer: Timer | null = null;
  private attempt = 0;
  private lastReceived = 0;
  private offlineSince: number | null = null;
  private stopped = false;
  private pings = new Map<string, number>();
  private rtts: number[] = [];
  private needHandshake = true;
  private connecting = false;
  readonly clock: ClientClock;
  private readonly random: () => number;
  private readonly metricsState = { sent: 0, received: 0, retransmits: 0, duplicatesAcked: 0, reconnects: 0, handshakes: 0, offlineMs: 0, errors: {} as Record<string, number> };

  constructor(private readonly options: SessionOptions) {
    this.clock = options.clock ?? browserClientClock;
    this.random = options.random ?? Math.random;
  }

  // Lifecycle ------------------------------------------------------------------------
  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(state: SessionState = "closed"): void {
    this.stopped = true;
    this.clearTimers();
    this.transport?.close();
    this.transport = null;
    this.failPending("stopped", "The remote session was closed.");
    this.setState(state);
  }

  /** Sleep/wake, network change or user action: try now instead of waiting for the backoff. */
  wake(): void {
    if (this.stopped || this.state === "revoked" || this.state === "unpaired") return;
    if (this.state === "online") {
      this.ping();
      return;
    }
    if (this.reconnectTimer !== null) this.clock.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.attempt = 0;
    void this.connect();
  }

  private setState(state: SessionState): void {
    if (state === this.state) return;
    const now = this.clock.now();
    if (state === "online" && this.offlineSince !== null) {
      this.metricsState.offlineMs += now - this.offlineSince;
      this.offlineSince = null;
    } else if (state !== "online" && this.offlineSince === null && this.state === "online") {
      this.offlineSince = now;
    }
    this.state = state;
    for (const listener of this.listeners) listener(state);
  }

  onState(listener: (state: SessionState) => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** Fires for every (re)established session; resumed=false means state must be re-read. */
  onSession(listener: (welcome: Welcome, resumed: boolean) => void): () => void {
    this.sessionListeners.add(listener);
    return () => this.sessionListeners.delete(listener);
  }

  on(kind: string, handler: Handler): () => void {
    const set = this.handlers.get(kind) ?? new Set<Handler>();
    set.add(handler);
    this.handlers.set(kind, set);
    return () => set.delete(handler);
  }

  private async connect(): Promise<void> {
    if (this.stopped || this.connecting) return;
    this.connecting = true;
    this.setState(this.welcome ? "reconnecting" : "connecting");
    try {
      if (this.needHandshake || !this.welcome) {
        let welcome: Welcome;
        try {
          welcome = await this.options.handshake();
        } catch (error) {
          const failure = error instanceof RemoteFailure ? error : new RemoteFailure("network", String(error), undefined, true);
          this.count(failure.code);
          if (["device_unknown", "pairing_refused", "no_scopes"].includes(failure.code)) {
            this.stop(failure.code === "no_scopes" ? "revoked" : "unpaired");
            return;
          }
          this.scheduleReconnect();
          return;
        }
        const previous = this.welcome?.session_id;
        if (previous && previous !== welcome.session_id) {
          this.failPending("outcome_unknown", "The session was replaced before Core answered; re-check the scene.", previous);
        }
        this.welcome = welcome;
        this.needHandshake = false;
        this.cursor = 0;
        this.metricsState.handshakes += 1;
      }
      this.openTransport();
    } finally {
      this.connecting = false;
    }
  }

  private openTransport(): void {
    const welcome = this.welcome!;
    const choice = this.options.transports[Math.min(this.transportIndex, this.options.transports.length - 1)];
    this.transport?.close();
    const transport = choice.create({
      onOpen: ({ resumed }) => this.opened(transport, resumed),
      onMessage: (message) => { if (this.transport === transport) this.receive(message); },
      onClose: (code, reason) => { if (this.transport === transport) this.closed(code, reason); },
    });
    this.transport = transport;
    transport.open({ sessionId: welcome.session_id, token: welcome.session_token, resumeAfter: this.cursor > 0 ? this.cursor : null });
  }

  private opened(transport: Transport, resumed: boolean): void {
    if (this.transport !== transport) return;
    this.attempt = 0;
    if (transport.name === "websocket") this.wsFailures = 0;
    this.lastReceived = this.clock.now();
    this.setState("online");
    for (const listener of this.sessionListeners) listener(this.welcome!, resumed);
    // Resend everything unanswered in seq order; Core answers duplicates from its cache.
    // Requests made before any session existed were never sent and join this one.
    for (const entry of this.pending.values()) if (!entry.session) entry.session = this.welcome!.session_id;
    const unanswered = [...this.pending.values()].filter((p) => p.session === this.welcome?.session_id).sort((a, b) => a.envelope.seq - b.envelope.seq);
    if (unanswered.length) {
      this.metricsState.retransmits += unanswered.length;
      transport.send(unanswered.map((p) => p.envelope));
      for (const entry of unanswered) {
        entry.sentAt = this.clock.now();
        this.armAttempt(entry);
      }
    }
    this.scheduleHeartbeat();
  }

  private closed(code: number, reason: string): void {
    this.transport = null;
    this.clearHeartbeat();
    if (this.stopped) return;
    this.count(`close:${code}`);
    if (code === 4403 || reason === "session_revoked") {
      this.stop("revoked");
      return;
    }
    if (code === 4401) this.needHandshake = true;
    if (this.options.transports.length > 1 && this.options.transports[this.transportIndex]?.name === "websocket" && code !== 4401) {
      this.wsFailures += 1;
      if (this.wsFailures >= 2) this.transportIndex = Math.min(this.transportIndex + 1, this.options.transports.length - 1);
    }
    this.metricsState.reconnects += 1;
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.stopped || this.reconnectTimer !== null) return;
    this.setState(this.welcome ? "reconnecting" : "connecting");
    const base = Math.min(15_000, 500 * 2 ** this.attempt);
    const delay = base * (0.7 + this.random() * 0.6);
    this.attempt += 1;
    this.reconnectTimer = this.clock.setTimeout(() => {
      this.reconnectTimer = null;
      void this.connect();
    }, delay);
  }

  // Heartbeat ------------------------------------------------------------------------
  private scheduleHeartbeat(): void {
    this.clearHeartbeat();
    const interval = this.welcome?.heartbeat_ms ?? 5000;
    this.heartbeat = this.clock.setTimeout(() => {
      this.heartbeat = null;
      if (this.state !== "online") return;
      const silent = this.clock.now() - this.lastReceived;
      if (silent > (this.welcome?.stale_after_ms ?? 12_000)) {
        // The connection is dead even if the socket did not say so (sleep, Wi-Fi switch).
        const transport = this.transport;
        this.transport = null;
        transport?.close();
        this.closed(1006, "silent");
        return;
      }
      this.ping();
      this.scheduleHeartbeat();
    }, interval);
  }

  private clearHeartbeat(): void {
    if (this.heartbeat !== null) this.clock.clearTimeout(this.heartbeat);
    this.heartbeat = null;
  }

  private clearTimers(): void {
    this.clearHeartbeat();
    if (this.reconnectTimer !== null) this.clock.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    for (const entry of this.pending.values()) if (entry.timer !== null) this.clock.clearTimeout(entry.timer);
  }

  ping(): void {
    const envelope = this.envelope("ping", { ack: this.cursor });
    this.pings.set(envelope.id, this.clock.now());
    if (this.pings.size > 32) this.pings.delete(this.pings.keys().next().value as string);
    this.transmit([envelope]);
  }

  // Sending --------------------------------------------------------------------------
  private envelope(kind: string, body: Record<string, unknown>): ClientEnvelope {
    this.seq += 1;
    return { v: 1, id: messageId(this.random), seq: this.seq, t: this.clock.wall(), kind, body };
  }

  private transmit(envelopes: ClientEnvelope[]): boolean {
    if (this.state !== "online" || !this.transport) return false;
    for (const envelope of envelopes) {
      const entry = this.pending.get(envelope.id);
      if (entry && !entry.session) entry.session = this.welcome?.session_id ?? "";
    }
    const sent = this.transport.send(envelopes);
    if (sent) this.metricsState.sent += envelopes.length;
    return sent;
  }

  /** Reliable request: resolves with the ack body, rejects with RemoteFailure. */
  request(kind: string, body: Record<string, unknown> = {}, options: { deadlineMs?: number } = {}): Promise<Record<string, unknown>> {
    const envelope = this.envelope(kind, body);
    return new Promise((resolve, reject) => {
      const entry: Pending = {
        envelope, resolve, reject, sentAt: this.clock.now(), attempts: 1, timer: null, session: "",  // bound when first sent
        deadline: this.clock.now() + (options.deadlineMs ?? this.options.requestDeadlineMs ?? 15_000),
      };
      this.pending.set(envelope.id, entry);
      this.transmit([envelope]);
      this.armAttempt(entry);  // also enforces the deadline while offline
    });
  }

  private armAttempt(entry: Pending): void {
    if (entry.timer !== null) this.clock.clearTimeout(entry.timer);
    const backoff = (this.options.attemptTimeoutMs ?? 2500) * Math.min(4, 2 ** (entry.attempts - 1));
    const wait = Math.max(1, Math.min(backoff, entry.deadline - this.clock.now()));  // the deadline is never overshot
    entry.timer = this.clock.setTimeout(() => {
      entry.timer = null;
      if (!this.pending.has(entry.envelope.id)) return;
      if (this.clock.now() >= entry.deadline) {
        this.settle(entry.envelope.id, entry.lastError ?? new RemoteFailure("timeout", "Core did not answer in time.", undefined, true));
        return;
      }
      if (this.state === "online" && entry.session === this.welcome?.session_id) {
        entry.attempts += 1;
        this.metricsState.retransmits += 1;
        this.transmit([entry.envelope]);  // same id + seq: never applied twice
      }
      this.armAttempt(entry);
    }, wait);
  }

  private settle(id: string, outcome: RemoteFailure | Record<string, unknown>): void {
    const entry = this.pending.get(id);
    if (!entry) return;
    this.pending.delete(id);
    if (entry.timer !== null) this.clock.clearTimeout(entry.timer);
    if (outcome instanceof RemoteFailure) {
      this.count(outcome.code);
      entry.reject(outcome);
    } else {
      entry.resolve(outcome);
    }
  }

  private failPending(code: string, message: string, session?: string): void {
    for (const [id, entry] of [...this.pending.entries()]) {
      if (session === undefined || entry.session === session) this.settle(id, new RemoteFailure(code, message));
    }
  }

  /** Realtime input (previews, presence, renewals): newest wins; nothing is queued while offline. */
  send(kind: string, body: Record<string, unknown>): boolean {
    return this.transmit([this.envelope(kind, body)]);
  }

  // Receiving ------------------------------------------------------------------------
  private receive(message: ServerMessage): void {
    this.lastReceived = this.clock.now();
    this.metricsState.received += 1;
    if (typeof message.sseq === "number" && message.sseq > this.cursor) this.cursor = message.sseq;
    if (message.kind === "ack" || message.kind === "error") {
      const started = message.re ? this.pings.get(message.re) : undefined;
      if (started !== undefined) {
        this.pings.delete(message.re!);
        this.rtts.push(this.clock.now() - started);
        if (this.rtts.length > 100) this.rtts.shift();
        return;
      }
      if (message.kind === "error") {
        const failure = errorFrom(message);
        if (failure.code.startsWith("session_")) {
          this.count(failure.code);
          if (failure.code === "session_revoked") return this.stop("revoked");
          this.needHandshake = true;
          const transport = this.transport;
          this.transport = null;
          transport?.close();
          this.closed(4401, failure.code);
          return;
        }
        if (failure.retryable && message.re && this.pending.has(message.re)) {
          this.count(failure.code);
          const entry = this.pending.get(message.re)!;
          entry.lastError = failure;
          if (this.clock.now() < entry.deadline) return;  // the attempt timer resends later
        }
        if (message.re) this.settle(message.re, failure);
        return;
      }
      if (message.duplicate) this.metricsState.duplicatesAcked += 1;
      if (message.re) this.settle(message.re, message.body);
      return;
    }
    if (message.kind === "revoked") {
      this.emit(message);
      this.stop("revoked");
      return;
    }
    if (message.kind === "session.closed") {
      const reason = String(message.body.reason ?? "");
      this.emit(message);
      if (reason === "revoked") return this.stop("revoked");
      this.needHandshake = true;
      return;
    }
    this.emit(message);
  }

  private emit(message: ServerMessage): void {
    for (const handler of this.handlers.get(message.kind) ?? []) handler(message);
    for (const handler of this.handlers.get("*") ?? []) handler(message);
  }

  private count(code: string): void {
    this.metricsState.errors[code] = (this.metricsState.errors[code] ?? 0) + 1;
  }

  // Introspection --------------------------------------------------------------------
  get scopes(): string[] {
    return this.welcome?.scopes ?? [];
  }

  can(scope: string): boolean {
    return this.scopes.includes(scope);
  }

  metrics(): SessionMetrics {
    const offline = this.offlineSince !== null ? this.clock.now() - this.offlineSince : 0;
    return {
      state: this.state, transport: this.transport?.name ?? null, sessionId: this.welcome?.session_id ?? null,
      rttMs: { last: this.rtts.at(-1) ?? null, p50: percentile(this.rtts, 0.5), p95: percentile(this.rtts, 0.95) },
      sent: this.metricsState.sent, received: this.metricsState.received, retransmits: this.metricsState.retransmits,
      duplicatesAcked: this.metricsState.duplicatesAcked, reconnects: this.metricsState.reconnects,
      handshakes: this.metricsState.handshakes, pending: this.pending.size, cursor: this.cursor,
      errors: { ...this.metricsState.errors }, offlineMs: this.metricsState.offlineMs + offline,
    };
  }
}

/** Wire sleep/wake and network changes to an immediate reconnect attempt. */
export function attachLifecycle(client: RemoteSessionClient, target: Window = window): () => void {
  const wake = () => { if (!target.document.hidden) client.wake(); };
  target.addEventListener("online", wake);
  target.addEventListener("pageshow", wake);
  target.addEventListener("focus", wake);
  target.document.addEventListener("visibilitychange", wake);
  return () => {
    target.removeEventListener("online", wake);
    target.removeEventListener("pageshow", wake);
    target.removeEventListener("focus", wake);
    target.document.removeEventListener("visibilitychange", wake);
  };
}
