// Mirrors of the backend Spatial Lab contract (backend/app/spatial). The backend
// owns the scene; these types describe what it returns and accepts.
// shared/contracts/spatial/ holds the generated schema checked by both test suites.

export type Vec3 = [number, number, number];
export type Quat = [number, number, number, number];

export type Transform = { position: Vec3; rotation: Quat; scale: number };

export type AssetClip = { index: number; name: string; duration: number; kind?: "skeletal" | "hud_morph" | "morph" | "node" };

export type FormProvenance = {
  project_id: string;
  project_name: string;
  version_id: string;
  version_label: string;
  version_index: number | null;
  version_kind: "production" | "shape";
  created_at: string | null;
  is_best_at_import: boolean;
  rigged: boolean;
  experimental: boolean;
  recorded_sha256: string;
  identity_verified: boolean;
};

export type Normalization = {
  scale: number;
  offset: Vec3;
  native_size: Vec3;
  size: Vec3;
  pivot: string;
  up_axis: string;
  flags: string[];
  scope: string;
};

export type AssetSummary = {
  asset_id: string;
  sha256: string;
  format: "glb";
  source: "form" | "upload" | "fixture";
  label: string;
  bytes: number;
  clips: AssetClip[];
  joints: number;
  skinned: boolean;
  form_hud_nodes: number;
  triangles: number;
  normalization: Normalization;
  form: FormProvenance | null;
  inspector: string;
};

export type SceneObject = {
  id: string;
  label: string;
  asset: AssetSummary;
  transform: Transform;
  visible: boolean;
  display: { skeleton: boolean; form_hud: boolean; bounds: boolean };
  animation: { clip: string | null; playing: boolean; speed: number };
};

export type SceneState = {
  schema: "akashi.spatial.scene/1";
  objects: Record<string, SceneObject>;
  order: string[];
  selection: string[];
  view: { hud_visible: boolean; vfx_visible: boolean; inspector: string | null };
};

export type Lease = { id: string; object_id: string; origin: string; expires_in: number };

export type SessionInfo = {
  id: string;
  label: string;
  revision: number;
  digest: string;
  can_undo: boolean;
  can_redo: boolean;
  leases: Lease[];
  pending_confirmations: Array<{ token: string; question: string; expires_in: number }>;
  presence_fresh: boolean;
  recovered_torn_tail: boolean;
};

export type Snapshot = { session: SessionInfo; state: SceneState };

export type OriginKind = "gesture" | "language" | "ui" | "tool" | "replay" | "system" | "remote";
export type Origin = { kind: OriginKind; provider: string; interaction_id?: string; input?: Record<string, unknown> };

export type Patch =
  | { op: "add"; path: Array<string | number>; after: unknown }
  | { op: "remove"; path: Array<string | number>; before: unknown }
  | { op: "replace"; path: Array<string | number>; before: unknown; after: unknown };

export type SpatialEvent = {
  schema: "akashi.action-event/1";
  seq: number;
  id: string;
  at: string;
  kind: "command" | "undo" | "redo";
  origin: Origin;
  request: Record<string, unknown> | null;
  command: { type: string } & Record<string, unknown>;
  category: string;
  undoable: boolean;
  targets: string[];
  summary: string;
  undoes: number | null;
  redoes: number | null;
  patches: Patch[];
  digest_before: string;
  digest_after: string;
  prev_hash: string;
  hash: string;
};

export type ObjectRef =
  | { id: string }
  | { ref: "selected" | "deictic" | "only" | "last_touched" | "last_moved" | "leftmost" | "rightmost" | "largest" | "smallest" | "form" | "latest_version" }
  | { ref: "label"; label: string }
  | { ref: "nearest_anchor"; anchor: "left_hand" | "right_hand" };

export type SpatialRequest =
  | { type: "scene.add_asset"; asset_id?: string; form?: { project_id?: string; version: string }; fixture?: "calibration"; label?: string; position?: Vec3 }
  | { type: "scene.remove"; target: ObjectRef }
  | { type: "selection.select"; target?: ObjectRef }
  | { type: "view.inspect"; target?: ObjectRef }
  | { type: "object.transform"; target: ObjectRef; mode: "set"; transform: Transform; lease_id?: string }
  | { type: "object.transform"; target: ObjectRef; mode: "translate"; delta: Vec3 }
  | { type: "object.transform"; target: ObjectRef; mode: "rotate"; axis?: "x" | "y" | "z"; degrees: number }
  | { type: "object.transform"; target: ObjectRef; mode: "scale"; factor: number }
  | { type: "object.transform"; target: ObjectRef; mode: "reset" | "center" }
  | { type: "object.transform"; target: ObjectRef; mode: "to_anchor"; anchor: "left_hand" | "right_hand" }
  | { type: "object.visibility"; target: ObjectRef; visible: boolean }
  | { type: "object.display"; target: ObjectRef; skeleton?: boolean; form_hud?: boolean; bounds?: boolean }
  | { type: "animation.control"; target: ObjectRef; action: "play" | "pause" | "stop"; clip?: string; speed?: number }
  | { type: "object.version"; target: ObjectRef; version: string }
  | { type: "object.rename"; target: ObjectRef; label: string }
  | { type: "view.set"; hud_visible?: boolean; vfx_visible?: boolean }
  | { type: "history.undo" }
  | { type: "history.redo" };

export type Limits = {
  max_objects: number;
  position_min: Vec3;
  position_max: Vec3;
  scale_min: number;
  scale_max: number;
  label_max: number;
  animation_speed_min: number;
  animation_speed_max: number;
  max_selection: number;
};

export type Capabilities = {
  schema: string;
  limits: Limits;
  request_types: string[];
  presence_ttl_seconds: number;
  max_glb_bytes: number;
  form: { available: boolean; reason: string | null; contract: string; configured: boolean; code?: string };
  interpreters: string[];
  scope: { spatial_model: string; validation: string };
};

export type CommandResult = {
  status: "applied" | "noop" | "confirmation_required" | "declined";
  events?: SpatialEvent[];
  notes?: string[];
  targets?: string[];
  revision?: number;
  token?: string;
  question?: string;
  snapshot: Snapshot;
};

export type InterpretResult = {
  understood: boolean;
  reply: string;
  interpretation?: { source: string; rule: string; language: string; requests: SpatialRequest[] };
  results: Array<Omit<CommandResult, "snapshot">>;
  clarification?: { code: string; question: string; candidates: Array<{ id: string; label: string; why: string; position?: string }> };
  rejected?: { code: string; message: string };
  confirmation?: { token: string; question: string };
  snapshot?: Snapshot;
};

export type FormProject = {
  id: string;
  name: string;
  created_at: string | null;
  updated_at: string | null;
  best_version: string | null;
  versions: number;
  loadable_versions: number;
  latest_loadable: string | null;
};

export type FormVersion = {
  id: string;
  kind: "production" | "shape";
  index: number | null;
  label: string;
  status: string;
  created_at: string | null;
  loadable: boolean;
  reason: string | null;
  sha256: string | null;
  rigged: boolean;
  experimental: boolean;
  is_best: boolean;
};
