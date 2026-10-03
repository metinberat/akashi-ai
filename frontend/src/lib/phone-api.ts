import { apiFetch, type BackendConfig } from "./api.ts";

export type PhoneCallState =
  | "ringing"
  | "answered"
  | "connected"
  | "caller_speaking"
  | "assistant_speaking"
  | "ended"
  | "failed";

export type PhoneTranscriptEntry = {
  role: "caller" | "assistant";
  content: string;
  final: boolean;
  timestamp: string;
};

export type PhoneCall = {
  id: string;
  direction: "inbound" | "outbound";
  caller_number: string;
  callee_number?: string | null;
  state: PhoneCallState;
  started_at: string;
  answered_at?: string | null;
  connected_at?: string | null;
  ended_at?: string | null;
  duration_seconds: number;
  transcript: PhoneTranscriptEntry[];
  result?: string | null;
  error?: string | null;
};

export type PhoneStatus = {
  enabled: boolean;
  configured: boolean;
  outbound_enabled: boolean;
  outbound_configured: boolean;
  agent_name: string;
  sip_provider: "verimor";
  codecs: string[];
  sms: "disabled";
};

async function json<T>(response: Response): Promise<T> {
  return await response.json() as T;
}

export async function getPhoneStatus(config: BackendConfig, signal?: AbortSignal): Promise<PhoneStatus> {
  return json<PhoneStatus>(await apiFetch(config, "/phone/status", { signal }));
}

export async function getPhoneCalls(config: BackendConfig, signal?: AbortSignal): Promise<PhoneCall[]> {
  const payload = await json<{ calls: PhoneCall[] }>(
    await apiFetch(config, "/phone/calls?limit=12", { signal }),
  );
  return Array.isArray(payload.calls) ? payload.calls : [];
}

export async function hangUpPhoneCall(config: BackendConfig, callId: string): Promise<PhoneCall> {
  return json<PhoneCall>(await apiFetch(
    config,
    `/phone/calls/${encodeURIComponent(callId)}/hangup`,
    { method: "POST" },
  ));
}
