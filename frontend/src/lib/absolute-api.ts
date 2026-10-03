import { apiFetch, type BackendConfig } from "./api.ts";

export type MemoryEntry = {
  id: string;
  content: string;
  category: string;
  created_at: string;
  updated_at: string;
  source: string;
  confidence: number;
  tags: string[];
};

export type ConversationSummary = {
  session_id: string;
  title: string;
  excerpt: string;
  message_count: number;
  last_updated: string;
};

export type ConversationMessage = {
  role: "user" | "assistant";
  content: string;
  intent: string | null;
  timestamp: string;
};

export type ResearchSource = {
  title: string;
  url: string;
  snippet: string;
  provider: string;
  relevance: number;
};

export type ResearchResult = {
  question: string;
  mode: "normal" | "deep";
  provider: string;
  status: string;
  summary: string;
  synthesis_status: string;
  findings: Array<{ title: string; finding: string; source_url: string }>;
  sources: ResearchSource[];
};

export type TaskStep = {
  id: string;
  tool: string;
  risk: "safe" | "confirm" | "restricted";
  status: string;
  result: unknown;
  error: string | null;
};

export type AkashiTask = {
  id: string;
  title: string;
  status: string;
  progress: number;
  approved: boolean;
  steps: TaskStep[];
  result: unknown;
  error: string | null;
  created_at: string;
};

export type UploadedFile = {
  id: string;
  name: string;
  extension: string;
  content_type: string;
  size: number;
  sha256: string;
  created_at: string;
  text_length: number;
};

export type PairedDevice = {
  id: string;
  name: string;
  device_type: string;
  capabilities: string[];
  created_at: string;
  last_seen: string;
  revoked: boolean;
  online: boolean;
};

export type DeviceAction = {
  id: string;
  device_id: string;
  action: string;
  risk: string;
  status: string;
  result: unknown;
  error: string | null;
};

export type IntelligenceSource = {
  url: string;
  title: string;
  provider: string;
  publication_date: string | null;
};

export type IntelligenceItem = {
  id: string;
  discovered_at: string;
  title: string;
  category: string;
  sources: IntelligenceSource[];
  publication_date: string | null;
  summary: string;
  why_it_matters: string;
  akashi_relevance: "direct" | "adjacent" | "general";
  affected_subsystem: string;
  maturity: string;
  risk: string;
  migration_effort: string;
  expected_benefit: string;
  confidence: string;
  priority: "critical" | "important" | "daily_brief" | "background";
  status: "new" | "reviewed" | "dismissed" | "watching" | "approved_for_test" | "approved_for_maintenance";
};

export type IntelligenceBrief = {
  id: string;
  title: string;
  status: string;
  created_at: string;
  item_count: number;
  groups: Record<string, IntelligenceItem[]>;
  empty_reason: string | null;
};

export type MaintenanceItem = {
  id: string;
  intelligence_id: string;
  title: string;
  status: string;
  approval: string;
  created_at: string;
  notes: string;
};

export type VoiceSession = {
  id: string;
  session_id: string;
  interaction_id: string | null;
  state: "idle" | "listening" | "transcribing" | "thinking" | "acting" | "speaking" | "interrupted" | "error";
  language: "auto" | "tr" | "en";
  generation: number;
};

export type AutonomySubgoal = {
  id: string; title: string; channel: string; status: string; attempts: number;
  acceptance: string; evaluation?: string; error?: string | null;
};

export type AutonomyTask = {
  id: string; title: string; goal: string; status: string; plan_revision: number; replans: number;
  subgoals: AutonomySubgoal[];
  artifacts: Array<{ kind: string; value: string; verified: boolean }>;
  summary?: string; error?: string | null; updated_at: string;
};

async function jsonRequest<T>(
  config: BackendConfig,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await apiFetch(config, path, init);
  return (await response.json()) as T;
}

function jsonInit(method: string, body?: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json; charset=utf-8" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  };
}

export async function listMemories(config: BackendConfig, query = "", category = "") {
  const parameters = new URLSearchParams();
  if (query) parameters.set("query", query);
  if (category) parameters.set("category", category);
  const suffix = parameters.size ? `?${parameters.toString()}` : "";
  return (await jsonRequest<{ memories: MemoryEntry[] }>(config, `/memory${suffix}`)).memories;
}

export async function listConversations(config: BackendConfig, limit = 30) {
  return (await jsonRequest<{ conversations: ConversationSummary[] }>(
    config,
    `/memory/conversations?limit=${Math.max(1, Math.min(limit, 100))}`,
  )).conversations;
}

export function getConversation(config: BackendConfig, sessionId: string) {
  return jsonRequest<{
    session_id: string;
    messages: ConversationMessage[];
    summary: string | null;
  }>(config, `/memory/conversations/${encodeURIComponent(sessionId)}`);
}

export function createMemory(
  config: BackendConfig,
  value: { content: string; category: string; tags: string[] },
) {
  return jsonRequest<MemoryEntry>(config, "/memory", jsonInit("POST", value));
}

export async function deleteMemory(config: BackendConfig, id: string) {
  await apiFetch(config, `/memory/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function updateMemory(config: BackendConfig, id: string, content: string) {
  return jsonRequest<MemoryEntry>(config, `/memory/${encodeURIComponent(id)}`, jsonInit("PATCH", { content }));
}

export async function revokeDevice(config: BackendConfig, id: string) {
  await apiFetch(config, `/devices/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export function runResearch(
  config: BackendConfig,
  question: string,
  mode: "normal" | "deep",
  requestId?: string,
  signal?: AbortSignal,
) {
  return jsonRequest<ResearchResult>(
    config,
    "/research",
    { ...jsonInit("POST", { question, mode, ...(requestId ? { request_id: requestId } : {}) }), signal },
  );
}

export function getResearchProgress(config: BackendConfig, id: string) {
  return jsonRequest<{ state: string; source_count?: number }>(config, `/research/runs/${encodeURIComponent(id)}`);
}

export async function listTasks(config: BackendConfig) {
  return (await jsonRequest<{ tasks: AkashiTask[] }>(config, "/tasks")).tasks;
}

export function createTask(
  config: BackendConfig,
  value: {
    title: string;
    approved: boolean;
    steps: Array<{ tool: string; arguments: Record<string, unknown> }>;
  },
) {
  return jsonRequest<AkashiTask>(config, "/tasks", jsonInit("POST", value));
}

export function approveTask(config: BackendConfig, id: string) {
  return jsonRequest<AkashiTask>(config, `/tasks/${encodeURIComponent(id)}/approve`, { method: "POST" });
}

export function cancelTask(config: BackendConfig, id: string) {
  return jsonRequest<AkashiTask>(config, `/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export async function listFiles(config: BackendConfig) {
  return (await jsonRequest<{ files: UploadedFile[] }>(config, "/files")).files;
}

export function uploadFile(config: BackendConfig, file: File) {
  const body = new FormData();
  body.append("file", file);
  return jsonRequest<UploadedFile>(config, "/files", { method: "POST", body });
}

export async function deleteFile(config: BackendConfig, id: string) {
  await apiFetch(config, `/files/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function listDevices(config: BackendConfig) {
  return (await jsonRequest<{ devices: PairedDevice[] }>(config, "/devices")).devices;
}

export function createPairingCode(config: BackendConfig) {
  return jsonRequest<{ code: string; expires_at: string }>(config, "/devices/pairing-codes", { method: "POST" });
}

export function queueDeviceAction(
  config: BackendConfig,
  deviceId: string,
  action: string,
  args: Record<string, unknown>,
  approved: boolean,
) {
  return jsonRequest<DeviceAction>(
    config,
    `/devices/${encodeURIComponent(deviceId)}/actions`,
    jsonInit("POST", { action, arguments: args, approved }),
  );
}

export function getDeviceAction(config: BackendConfig, actionId: string) {
  return jsonRequest<DeviceAction>(config, `/devices/actions/${encodeURIComponent(actionId)}`);
}

export type ModelProfile = "fast" | "quality" | "reasoning" | "vision";
export type Capabilities = { models: Record<ModelProfile, { available: boolean; accepts_images: boolean; kind: string }> };
export function getCapabilities(config: BackendConfig) {
  return jsonRequest<Capabilities>(config, "/system/capabilities");
}

export type DependencyState = {
  status: string;
  detail: string;
  online?: number;
  paired?: number;
};

export type SystemHealth = {
  core: DependencyState;
  auth: DependencyState;
  model: DependencyState;
  ollama: DependencyState;
  images: DependencyState;
  research: DependencyState;
  desktop_agent: DependencyState;
};

export function getSystemHealth(config: BackendConfig) {
  return jsonRequest<SystemHealth>(config, "/system/health");
}

export function cancelLiveInteraction(config: BackendConfig, interactionId: string) {
  return jsonRequest<{ interaction_id: string; cancelled: boolean }>(
    config,
    `/live/interactions/${encodeURIComponent(interactionId)}/cancel`,
    { method: "POST" },
  );
}

export function listIntelligence(config: BackendConfig, limit = 40) {
  return jsonRequest<IntelligenceItem[]>(config, `/intelligence/items?limit=${Math.max(1, Math.min(limit, 100))}`);
}

export function discoverIntelligence(config: BackendConfig) {
  return jsonRequest<{ status: string; created: number; merged: number; failures: Array<{ source: string; error: string }>; items: IntelligenceItem[] }>(
    config,
    "/intelligence/discover",
    jsonInit("POST", { per_feed: 4 }),
  );
}

export function listIntelligenceBriefs(config: BackendConfig, limit = 10) {
  return jsonRequest<IntelligenceBrief[]>(config, `/intelligence/briefs?limit=${Math.max(1, Math.min(limit, 30))}`);
}

export function createIntelligenceBrief(config: BackendConfig) {
  return jsonRequest<IntelligenceBrief>(config, "/intelligence/briefs", { method: "POST" });
}

export function setIntelligenceStatus(config: BackendConfig, id: string, status: IntelligenceItem["status"]) {
  return jsonRequest<IntelligenceItem>(config, `/intelligence/items/${encodeURIComponent(id)}/status`, jsonInit("PATCH", { status }));
}

export function listMaintenance(config: BackendConfig) {
  return jsonRequest<MaintenanceItem[]>(config, "/intelligence/maintenance");
}

export function startVoiceSession(config: BackendConfig, sessionId: string, language: "auto" | "tr" | "en" = "auto") {
  return jsonRequest<VoiceSession>(config, "/voice/sessions", jsonInit("POST", { session_id: sessionId, language }));
}

export function updateVoiceSession(
  config: BackendConfig,
  id: string,
  value: Partial<Pick<VoiceSession, "interaction_id" | "state">> & {
    last_user_utterance?: string;
    last_assistant_utterance?: string;
    error?: string;
  },
) {
  return jsonRequest<VoiceSession>(config, `/voice/sessions/${encodeURIComponent(id)}`, jsonInit("PATCH", value));
}

export function interruptVoiceSession(config: BackendConfig, id: string) {
  return jsonRequest<VoiceSession>(config, `/voice/sessions/${encodeURIComponent(id)}/interrupt`, { method: "POST" });
}

export async function stopVoiceSession(config: BackendConfig, id: string) {
  await apiFetch(config, `/voice/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function listAutonomyTasks(config: BackendConfig) {
  return (await jsonRequest<{ tasks: AutonomyTask[] }>(config, "/autonomy/tasks?limit=30")).tasks;
}

export function resumeAutonomyTask(config: BackendConfig, id: string, approved?: boolean) {
  return jsonRequest<AutonomyTask>(config, `/autonomy/tasks/${encodeURIComponent(id)}/resume`, jsonInit("POST", approved === undefined ? {} : { approved }));
}

export function cancelAutonomyTask(config: BackendConfig, id: string) {
  return jsonRequest<AutonomyTask>(config, `/autonomy/tasks/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export type CharacterSummary = { id: string; name: string; synthetic: number; joint_count: number; mesh_count: number; parser: string; created_at: string };
export type CharacterKnowledge = { id: string; kind: string; topic: string; statement: string; validation: string; confidence: number; provenance: { synthetic: boolean; asset_id: string } };

export function getCharacterExpertise(config: BackendConfig) {
  return jsonRequest<{ characters: CharacterSummary[] }>(config, "/expertise/characters?limit=20");
}

export function queryCharacterKnowledge(config: BackendConfig, query: string) {
  return jsonRequest<{ knowledge: CharacterKnowledge[] }>(config, `/expertise/knowledge?query=${encodeURIComponent(query)}&limit=6`);
}

export type CharacterImprovement = { id: string; asset_id: string; status: string; attempts: number; max_attempts: number; synthetic: boolean; best_version: string; baseline_version: string };
export type CharacterVersion = { id: string; decision: { accepted: boolean; reasons: string[] }; evaluation: { score: number; scope: string; integrity: { defective_vertices: number }; deformation: { available: boolean } } };

export async function listCharacterImprovements(config: BackendConfig) {
  const value = await jsonRequest<{ workshops: CharacterImprovement[] }>(config, "/expertise/workshops");
  if (!Array.isArray(value.workshops)) throw new Error("Invalid workshop state returned by Core.");
  return value;
}

export function createCharacterImprovement(config: BackendConfig, assetId: string) {
  return jsonRequest<CharacterImprovement>(config, "/expertise/workshops", jsonInit("POST", { asset_id: assetId }));
}

export function runCharacterImprovement(config: BackendConfig, id: string) {
  return jsonRequest<CharacterImprovement>(config, `/expertise/workshops/${encodeURIComponent(id)}/run?steps=2`, { method: "POST" });
}

export function cancelCharacterImprovement(config: BackendConfig, id: string) {
  return jsonRequest<CharacterImprovement>(config, `/expertise/workshops/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

export function getCharacterVersions(config: BackendConfig, id: string) {
  return jsonRequest<{ versions: CharacterVersion[] }>(config, `/expertise/workshops/${encodeURIComponent(id)}/versions`);
}

export function rollbackCharacterImprovement(config: BackendConfig, id: string, versionId: string) {
  return jsonRequest<CharacterImprovement>(config, `/expertise/workshops/${encodeURIComponent(id)}/rollback`, jsonInit("POST", { version_id: versionId }));
}
