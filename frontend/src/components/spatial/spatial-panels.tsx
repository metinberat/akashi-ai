"use client";

import { useEffect, useState, useSyncExternalStore, type FormEvent } from "react";

import type { SpatialApi, SpatialFailure } from "@/lib/spatial/client";
import type { InteractionSnapshot } from "@/lib/spatial/gesture/interaction";
import type { PipelineMetrics } from "@/lib/spatial/gesture/pipeline";
import type { HandPose } from "@/lib/spatial/gesture/poses";
import type { TrackedHand } from "@/lib/spatial/gesture/tracker";
import { yawOf } from "@/lib/spatial/math";
import type { ProviderMetrics, ProviderStatus } from "@/lib/spatial/providers/types";
import type { ReplayFrame } from "@/lib/spatial/replay";
import type { Signal } from "@/lib/spatial/signal";
import type { Capabilities, FormProject, FormVersion, InterpretResult, SceneObject, SceneState, SessionInfo, SpatialEvent, SpatialRequest } from "@/lib/spatial/types";

export type HandsFrame = { hands: TrackedHand[]; poses: HandPose[]; interaction: InteractionSnapshot | null; metrics: PipelineMetrics | null };

const fmt = (value: number, digits = 2) => (Math.abs(value) < 1e-9 ? 0 : value).toFixed(digits);
const short = (sha: string) => `${sha.slice(0, 10)}…${sha.slice(-6)}`;

// ---------------------------------------------------------------------------------
// Library: FORM projects (read-only adapter), calibration fixture, uploads
// ---------------------------------------------------------------------------------
export function LibraryPanel({ api, capabilities, busy, onAdd, onUpload }: {
  api: SpatialApi;
  capabilities: Capabilities | null;
  busy: boolean;
  onAdd: (request: SpatialRequest, label: string) => void;
  onUpload: (file: File) => void;
}) {
  const [projects, setProjects] = useState<FormProject[]>([]);
  const [formState, setFormState] = useState<{ available: boolean; reason?: string } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [versions, setVersions] = useState<Record<string, FormVersion[]>>({});
  useEffect(() => {
    let alive = true;
    api.formProjects().then((value) => {
      if (!alive) return;
      setFormState({ available: value.available, reason: value.reason });
      setProjects(value.projects);
    }).catch(() => alive && setFormState({ available: false, reason: "FORM library request failed." }));
    return () => { alive = false; };
  }, [api]);
  async function toggle(project: FormProject) {
    setOpen(open === project.id ? null : project.id);
    if (!versions[project.id]) {
      const value = await api.formVersions(project.id).catch(() => ({ versions: [] as FormVersion[] }));
      setVersions((current) => ({ ...current, [project.id]: value.versions }));
    }
  }
  return <section className="spatial-panel spatial-library" aria-label="Spatial library">
    <header><span>LIBRARY</span><strong>Assets</strong></header>
    <div className="spatial-library-block">
      <p className="spatial-label">FORM CHARACTER STUDIO · READ-ONLY</p>
      {!formState ? <p className="spatial-muted">Checking FORM library…</p>
        : !formState.available ? <p className="spatial-muted" role="status">FORM unavailable: {formState.reason ?? "not found"}. Spatial Lab keeps working with fixtures and uploads.</p>
          : projects.length === 0 ? <p className="spatial-muted">No FORM projects yet.</p>
            : <ul className="spatial-form-projects">{projects.map((project) => <li key={project.id}>
              <button type="button" className="spatial-form-project" aria-expanded={open === project.id} onClick={() => void toggle(project)}>
                <strong>{project.name}</strong><small>{project.loadable_versions}/{project.versions} verified versions</small>
              </button>
              <div className="spatial-form-actions">
                <button type="button" disabled={busy || !project.latest_loadable} onClick={() => onAdd({ type: "scene.add_asset", form: { project_id: project.id, version: "latest" } }, `${project.name} latest`)}>Load latest</button>
                {project.best_version && <button type="button" disabled={busy} onClick={() => onAdd({ type: "scene.add_asset", form: { project_id: project.id, version: "best" } }, `${project.name} best`)}>Load best</button>}
              </div>
              {open === project.id && <ol className="spatial-form-versions">{(versions[project.id] ?? []).map((version) => <li key={version.id} data-loadable={version.loadable}>
                <span>{version.label}{version.is_best ? " · BEST" : ""}{version.experimental ? " · EXPERIMENTAL" : ""}</span>
                <small>{version.loadable ? (version.rigged ? "rigged · verified export" : "unrigged · verified") : version.reason}</small>
                <button type="button" disabled={busy || !version.loadable} onClick={() => onAdd({ type: "scene.add_asset", form: { project_id: project.id, version: version.id } }, `${project.name} ${version.label}`)}>Load</button>
              </li>)}</ol>}
            </li>)}</ul>}
    </div>
    <div className="spatial-library-block">
      <p className="spatial-label">CALIBRATION</p>
      <button type="button" className="spatial-wide-button" disabled={busy} onClick={() => onAdd({ type: "scene.add_asset", fixture: "calibration" }, "Calibration block")}>Add 1.70 m calibration block <small>SYNTHETIC</small></button>
    </div>
    <div className="spatial-library-block">
      <p className="spatial-label">GLB FILE</p>
      <label className="spatial-wide-button spatial-upload">Upload .glb (≤ 20 MiB)
        <input type="file" accept=".glb,model/gltf-binary" disabled={busy} onChange={(event) => { const file = event.target.files?.[0]; if (file) onUpload(file); event.target.value = ""; }} />
      </label>
      <p className="spatial-muted">Validated and normalised for display only; the file is never modified.{capabilities ? ` Max ${Math.round(capabilities.max_glb_bytes / 1048576)} MiB for FORM artifacts.` : ""}</p>
    </div>
  </section>;
}

// ---------------------------------------------------------------------------------
// Inspector: provenance, metadata, rig, clips, transform, version controls
// ---------------------------------------------------------------------------------
export function InspectorPanel({ object, measured, busy, onRequest, onRemove }: {
  object: SceneObject;
  measured: [number, number, number] | null;
  busy: boolean;
  onRequest: (request: SpatialRequest) => void;
  onRemove: (object: SceneObject) => void;
}) {
  const target = { id: object.id };
  const { asset, transform, display, animation } = object;
  const form = asset.form;
  const height = asset.normalization.size[1] * transform.scale;
  return <section className="spatial-panel spatial-inspector" aria-label="Object inspector">
    <header><span>INSPECTOR</span><strong title={object.label}>{object.label}</strong></header>
    <dl className="spatial-facts">
      <div><dt>Source</dt><dd>{asset.source === "form" ? "FORM" : asset.source === "fixture" ? "Synthetic fixture" : "Upload"}</dd></div>
      {form && <>
        <div><dt>Project</dt><dd>{form.project_name}</dd></div>
        <div><dt>Version</dt><dd>{form.version_label}{form.is_best_at_import ? " · best at import" : ""}{form.experimental ? " · experimental" : ""}</dd></div>
        <div><dt>Identity</dt><dd data-verified={form.identity_verified}>{form.identity_verified ? "SHA-256 matches FORM export record" : "not verified"}</dd></div>
      </>}
      <div><dt>SHA-256</dt><dd className="spatial-mono">{short(asset.sha256)}</dd></div>
      <div><dt>Geometry</dt><dd>{asset.triangles.toLocaleString()} triangles · {asset.bytes >= 1048576 ? `${(asset.bytes / 1048576).toFixed(2)} MiB` : `${Math.max(1, Math.round(asset.bytes / 1024))} KiB`}</dd></div>
      <div><dt>Rig</dt><dd>{asset.joints ? `${asset.joints} joints${asset.skinned ? " · skinned" : ""}` : "none"}</dd></div>
      <div><dt>Height</dt><dd>{fmt(height)} m{asset.normalization.flags.length ? ` · ${asset.normalization.flags.join(", ")}` : ""}</dd></div>
      {measured && <div><dt>Renderer</dt><dd className="spatial-mono">{measured.map((v) => fmt(v)).join(" × ")} m (measured)</dd></div>}
    </dl>
    <div className="spatial-control-group">
      <p className="spatial-label">TRANSFORM</p>
      <p className="spatial-mono spatial-transform">x {fmt(transform.position[0])} · y {fmt(transform.position[1])} · z {fmt(transform.position[2])} · yaw {fmt((yawOf(transform.rotation) * 180) / Math.PI, 0)}° · {fmt(transform.scale)}×</p>
      <div className="spatial-button-row">
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.transform", target, mode: "scale", factor: 1.25 })}>Bigger</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.transform", target, mode: "scale", factor: 0.8 })}>Smaller</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.transform", target, mode: "rotate", axis: "y", degrees: 45 })}>Turn 45°</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.transform", target, mode: "center" })}>Center</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.transform", target, mode: "reset" })}>Reset</button>
      </div>
    </div>
    <div className="spatial-control-group">
      <p className="spatial-label">DISPLAY</p>
      <div className="spatial-button-row">
        <button type="button" aria-pressed={display.skeleton} disabled={busy || !asset.joints} onClick={() => onRequest({ type: "object.display", target, skeleton: !display.skeleton })}>Rig</button>
        <button type="button" aria-pressed={display.form_hud} disabled={busy || !asset.form_hud_nodes} title={asset.form_hud_nodes ? "FORM character HUD geometry" : "This asset has no FORM HUD geometry"} onClick={() => onRequest({ type: "object.display", target, form_hud: !display.form_hud })}>FORM HUD</button>
        <button type="button" aria-pressed={display.bounds} disabled={busy} onClick={() => onRequest({ type: "object.display", target, bounds: !display.bounds })}>Bounds</button>
        <button type="button" aria-pressed={!object.visible} disabled={busy} onClick={() => onRequest({ type: "object.visibility", target, visible: !object.visible })}>{object.visible ? "Hide" : "Show"}</button>
      </div>
    </div>
    <div className="spatial-control-group">
      <p className="spatial-label">ANIMATION</p>
      {asset.clips.length === 0 ? <p className="spatial-muted">This asset has no animation clips.</p> : <ul className="spatial-clips">{asset.clips.map((clip) => {
        const active = animation.clip === clip.name;
        return <li key={clip.index}>
          <span>{clip.name}<small>{fmt(clip.duration, 1)} s</small></span>
          <button type="button" disabled={busy} aria-label={`${active && animation.playing ? "Pause" : "Play"} ${clip.name}`}
            onClick={() => onRequest(active && animation.playing ? { type: "animation.control", target, action: "pause" } : { type: "animation.control", target, action: "play", clip: clip.name })}>
            {active && animation.playing ? "Pause" : "Play"}
          </button>
        </li>;
      })}</ul>}
    </div>
    {form && form.version_kind === "production" && <div className="spatial-control-group">
      <p className="spatial-label">FORM VERSION</p>
      <div className="spatial-button-row">
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.version", target, version: "previous" })}>Previous</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.version", target, version: "next" })}>Next</button>
        <button type="button" disabled={busy} onClick={() => onRequest({ type: "object.version", target, version: "latest" })}>Latest</button>
      </div>
    </div>}
    <button type="button" className="spatial-danger" disabled={busy} onClick={() => onRemove(object)}>Remove from scene…</button>
  </section>;
}

// ---------------------------------------------------------------------------------
// Command bar: natural language → validated scene actions
// ---------------------------------------------------------------------------------
export function CommandBar({ busy, result, failure, onSubmit, onCandidate, onConfirm }: {
  busy: boolean;
  result: InterpretResult | null;
  failure: SpatialFailure | null;
  onSubmit: (text: string) => void;
  onCandidate: (label: string) => void;
  onConfirm: (token: string, accept: boolean) => void;
}) {
  const [text, setText] = useState("");
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!text.trim()) return;
    onSubmit(text.trim());
    setText("");
  }
  return <div className="spatial-command">
    {(result || failure) && <div className="spatial-reply" role="status" data-kind={failure ? "error" : result?.clarification ? "clarify" : result?.confirmation ? "confirm" : result?.understood === false ? "unknown" : "ok"}>
      <p>{failure ? failure.message : result?.reply}</p>
      {result?.interpretation && <small>{result.interpretation.source === "rules" ? "LOCAL RULES" : result.interpretation.source.toUpperCase()} · {result.interpretation.rule}</small>}
      {result?.clarification?.candidates.length ? <div className="spatial-button-row">{result.clarification.candidates.map((c) => <button type="button" key={c.id} onClick={() => onCandidate(c.label)}>{c.label}{c.position ? ` · ${c.position}` : ""}</button>)}</div> : null}
      {result?.confirmation && <div className="spatial-button-row">
        <button type="button" className="spatial-danger" onClick={() => onConfirm(result.confirmation!.token, true)}>Confirm</button>
        <button type="button" onClick={() => onConfirm(result.confirmation!.token, false)}>Cancel</button>
      </div>}
    </div>}
    <form onSubmit={submit}>
      <input aria-label="Spatial command" value={text} onChange={(event) => setText(event.target.value)} placeholder="“Make it bigger”, “iskeleti göster”, “load the latest FORM version”…" maxLength={500} disabled={busy} />
      <button type="submit" disabled={busy || !text.trim()}>Send</button>
    </form>
  </div>;
}

// ---------------------------------------------------------------------------------
// Replay / history timeline
// ---------------------------------------------------------------------------------
const ORIGIN_LABEL: Record<string, string> = { gesture: "GESTURE", language: "LANGUAGE", ui: "UI", tool: "TOOL", replay: "REPLAY", system: "SYSTEM", remote: "REMOTE" };

export function ReplayPanel({ frames, index, verified, error, onIndex, onVerify, onClose }: {
  frames: ReplayFrame[];
  index: number;
  verified: { verified: boolean; matches_live_state: boolean; final_digest: string } | null;
  error: string | null;
  onIndex: (index: number) => void;
  onVerify: () => void;
  onClose: () => void;
}) {
  const frame = frames[index];
  const event: SpatialEvent | null = frame?.event ?? null;
  return <section className="spatial-panel spatial-replay" aria-label="Replay timeline">
    <header><span>REPLAY · READ-ONLY</span><strong>{frames.length ? `Step ${index} / ${frames.length - 1}` : "No history"}</strong><button type="button" onClick={onClose} aria-label="Close replay">×</button></header>
    {error && <p className="spatial-error" role="alert">{error}</p>}
    {frames.length > 0 && <>
      <input type="range" aria-label="Replay position" min={0} max={frames.length - 1} value={index} onChange={(e) => onIndex(Number(e.target.value))} />
      <div className="spatial-button-row">
        <button type="button" disabled={index === 0} onClick={() => onIndex(index - 1)}>◀ Step</button>
        <button type="button" disabled={index >= frames.length - 1} onClick={() => onIndex(index + 1)}>Step ▶</button>
        <button type="button" onClick={onVerify}>Verify determinism</button>
      </div>
      {event ? <dl className="spatial-facts">
        <div><dt>Action</dt><dd>{event.kind === "command" ? event.command.type : event.kind.toUpperCase()} — {event.summary}</dd></div>
        <div><dt>Input</dt><dd><span className="spatial-origin" data-origin={event.origin.kind}>{ORIGIN_LABEL[event.origin.kind] ?? event.origin.kind}</span> {event.origin.provider}</dd></div>
        {typeof event.origin.input?.text === "string" && <div><dt>Said</dt><dd>“{event.origin.input.text}”</dd></div>}
        {typeof event.origin.input?.gesture === "string" && <div><dt>Gesture</dt><dd>{String(event.origin.input.gesture)} · {String(event.origin.input.duration_ms ?? "?")} ms · {String(event.origin.input.ended_by ?? "")}</dd></div>}
        <div><dt>Targets</dt><dd>{event.targets.join(", ") || "scene"}</dd></div>
        <div><dt>Before</dt><dd className="spatial-mono">{event.digest_before.slice(7, 19)}</dd></div>
        <div><dt>After</dt><dd className="spatial-mono">{event.digest_after.slice(7, 19)}</dd></div>
        {event.undoes && <div><dt>Undoes</dt><dd>event {event.undoes}</dd></div>}
        {event.redoes && <div><dt>Redoes</dt><dd>event {event.redoes}</dd></div>}
      </dl> : <p className="spatial-muted">Initial empty scene.</p>}
      {verified && <p className={verified.verified && verified.matches_live_state ? "spatial-ok" : "spatial-error"} role="status">
        {verified.verified && verified.matches_live_state ? `Re-executed every command: identical state (${verified.final_digest.slice(7, 19)}).` : "Replay diverged from the live state."}
      </p>}
    </>}
  </section>;
}

// ---------------------------------------------------------------------------------
// Developer / debug drawer (hidden by default)
// ---------------------------------------------------------------------------------
export function DebugPanel({ signal, provider, providerStatus, providerMetrics, session, renderer, serverMetrics, events }: {
  signal: Signal<HandsFrame>;
  provider: string;
  providerStatus: ProviderStatus;
  providerMetrics: ProviderMetrics | null;
  session: SessionInfo | null;
  renderer: { fps: number; frameMs: number; calls: number; triangles: number; continuous: boolean } | null;
  serverMetrics: { submit_ms: { count: number; p50: number | null; p95: number | null } } | null;
  events: SpatialEvent[];
}) {
  const frame = useSyncExternalStore(signal.subscribe, signal.get, signal.get);
  const m = frame.metrics;
  return <section className="spatial-panel spatial-debug" aria-label="Spatial debug">
    <header><span>DEBUG</span><strong>Instrumentation</strong></header>
    <dl className="spatial-facts spatial-mono">
      <div><dt>Provider</dt><dd>{provider} · {providerStatus.state}{providerStatus.state === "error" ? ` (${providerStatus.code})` : ""}</dd></div>
      {providerMetrics && <div><dt>Source</dt><dd>{fmt(providerMetrics.sourceFps, 1)} fps · delivered {fmt(providerMetrics.deliveredFps, 1)} · skipped {providerMetrics.skippedFrames}{providerMetrics.inferenceMs !== null ? ` · infer ${fmt(providerMetrics.inferenceMs, 1)} ms` : ""}{providerMetrics.delegate ? ` · ${providerMetrics.delegate}` : ""}</dd></div>}
      {providerMetrics?.resolution && <div><dt>Camera</dt><dd>{providerMetrics.resolution.width}×{providerMetrics.resolution.height}{providerMetrics.device ? ` · ${providerMetrics.device}` : ""}</dd></div>}
      {m && <div><dt>Pipeline</dt><dd>{fmt(m.fps, 1)} fps · gaps {m.gaps} · proc p95 {fmt(m.processingMs.p95, 2)} ms{m.inferenceMs.p95 !== null ? ` · infer p95 ${fmt(m.inferenceMs.p95, 1)} ms` : ""}</dd></div>}
      <div><dt>Interaction</dt><dd>{frame.interaction ? `${frame.interaction.mode}${frame.interaction.objectId ? ` · ${frame.interaction.objectId}` : ""}${frame.interaction.hover ? ` · hover ${frame.interaction.hover}` : ""}` : "—"}</dd></div>
      {frame.hands.map((hand) => {
        const pose = frame.poses.find((p) => p.hand === hand.id);
        return <div key={hand.id}><dt>Hand {hand.id}</dt><dd>{hand.handedness} ({fmt(hand.handednessConfidence)}) · {hand.state}{hand.degraded ? " · degraded" : ""} · score {fmt(hand.score)} · pinch {fmt(hand.features.pinchRatio)} · ext {fmt(hand.features.extension)} · {pose?.pinch ? "PINCH" : pose?.grab ? "GRAB" : "open"} · glitches {hand.glitches}</dd></div>;
      })}
      {renderer && <div><dt>Renderer</dt><dd>{renderer.fps} fps · {fmt(renderer.frameMs, 2)} ms · {renderer.calls} calls · {renderer.triangles.toLocaleString()} tris · {renderer.continuous ? "continuous" : "on demand"}</dd></div>}
      {serverMetrics && <div><dt>Core submit</dt><dd>p50 {serverMetrics.submit_ms.p50 ?? "—"} ms · p95 {serverMetrics.submit_ms.p95 ?? "—"} ms · n={serverMetrics.submit_ms.count}</dd></div>}
      {session && <div><dt>Session</dt><dd>{session.id} · rev {session.revision} · {session.digest.slice(7, 19)}{session.leases.length ? ` · lease ${session.leases[0].object_id}` : ""}</dd></div>}
    </dl>
    <ol className="spatial-event-stream">{events.slice(-8).reverse().map((event) => <li key={event.seq}><span className="spatial-origin" data-origin={event.origin.kind}>{ORIGIN_LABEL[event.origin.kind] ?? event.origin.kind}</span> #{event.seq} {event.kind === "command" ? event.command.type : event.kind}</li>)}</ol>
  </section>;
}

export function sceneSummaryLine(state: SceneState | null): string {
  if (!state) return "No scene";
  const count = state.order.length;
  return `${count} object${count === 1 ? "" : "s"}${state.selection.length ? ` · selected ${state.objects[state.selection[0]]?.label ?? ""}` : ""}`;
}
