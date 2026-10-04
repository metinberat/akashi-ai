// Client side of the akashi.remote/1 protocol (see backend/app/remote/protocol.py).
//
// Client → Core: { v, id, seq, t, kind, body }  (id = idempotency key, seq = per-session order)
// Core → client: pushed { v, sseq, kind, body } or replies { v, kind: "ack"|"error", re, seq, body }.
// sseq is monotonic but not contiguous; scene state never depends on it.

export const PROTOCOL = "akashi.remote/1";
export const MAX_MESSAGE_BYTES = 64 * 1024;

export type ClientEnvelope = { v: 1; id: string; seq: number; t: number; kind: string; body: Record<string, unknown> };

export type ServerMessage = {
  v: 1;
  kind: string;
  body: Record<string, unknown>;
  sseq?: number;
  re?: string;
  seq?: number;
  duplicate?: boolean;
};

export type ErrorBody = { code: string; message: string; retryable: boolean; details?: Record<string, unknown> };

export class RemoteFailure extends Error {
  constructor(readonly code: string, message: string, readonly details?: Record<string, unknown>, readonly retryable = false, readonly status?: number) {
    super(message);
    this.name = "RemoteFailure";
  }
}

export type Welcome = {
  session_id: string;
  session_token: string;
  kind: "device" | "owner";
  device: { id: string; name: string; device_type: string; kind: string };
  scopes: string[];
  protocol: string;
  server_time_ms: number;
  heartbeat_ms: number;
  stale_after_ms: number;
  idle_timeout_ms: number;
  max_lifetime_ms: number;
  endpoints: string[];
  limits: { max_message_bytes: number; max_batch: number };
};

export type CapabilityName =
  | "camera" | "microphone" | "touch" | "pointer" | "keyboard" | "hand_tracking" | "gesture" | "orientation"
  | "display" | "speech_output" | "voice_input" | "notifications" | "approval_surface";

export type CapabilityReport = { name: CapabilityName; state: "available" | "active" | "unavailable" | "denied"; detail?: Record<string, unknown> };

export const SCOPE_LABELS: Record<string, { en: string; tr: string }> = {
  "spatial.view": { en: "See the scene", tr: "Sahneyi görme" },
  "spatial.control": { en: "Change the scene", tr: "Sahneyi değiştirme" },
  "spatial.presence": { en: "Share hand positions", tr: "El konumlarını paylaşma" },
  "voice.spatial": { en: "Voice scene commands", tr: "Sesli sahne komutları" },
  "assistant.chat": { en: "Talk to AKASHI (scene-bounded)", tr: "AKASHI ile konuşma (sahne sınırlı)" },
  "approvals.spatial": { en: "Approve scene confirmations", tr: "Sahne onaylarını verme" },
  "approvals.general": { en: "Approve all AKASHI requests", tr: "Tüm AKASHI onaylarını verme" },
};

export type Approval = {
  id: string;
  source: string;
  scope: "spatial" | "general";
  title: string;
  reason: string;
  action: string;
  risk: string;
  requested_by: { en?: string; tr?: string; device?: { name?: string } } & Record<string, unknown>;
  expires_in: number | null;
  details: Record<string, unknown>;
};

export function errorFrom(message: ServerMessage): RemoteFailure {
  const body = message.body as Partial<ErrorBody>;
  return new RemoteFailure(String(body.code ?? "error"), String(body.message ?? "Request failed"), body.details, Boolean(body.retryable));
}

const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";

/** URL-safe random id (idempotency key). */
export function messageId(random: () => number = Math.random): string {
  let id = "";
  for (let i = 0; i < 20; i += 1) id += ALPHABET[Math.floor(random() * ALPHABET.length)];
  return id;
}
