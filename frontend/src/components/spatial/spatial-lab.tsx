"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import type { BackendConfig } from "@/lib/api";
import { ownerSession } from "@/lib/remote/owner";
import { RemoteSpatial } from "@/lib/remote/spatial";
import { DEFAULT_CALIBRATION, type CameraCalibration } from "@/lib/spatial/calibration";
import { spatialApi, spatialFailure, type SpatialFailure } from "@/lib/spatial/client";
import { DEFAULT_RIG, PerspectiveProjector } from "@/lib/spatial/projection";
import { listCameras } from "@/lib/spatial/providers/mediapipe";
import type { ProviderMetrics, ProviderStatus } from "@/lib/spatial/providers/types";
import { reconstruct, type ReplayFrame } from "@/lib/spatial/replay";
import { SpatialSceneStore } from "@/lib/spatial/scene-store";
import { createSignal } from "@/lib/spatial/signal";
import type { Capabilities, InterpretResult, SceneObject, SceneState, SpatialEvent, SpatialRequest } from "@/lib/spatial/types";

import { CommandBar, DebugPanel, InspectorPanel, LibraryPanel, ReplayPanel, sceneSummaryLine, type HandsFrame } from "./spatial-panels";
import { SpatialRenderer, type RendererStats } from "./spatial-renderer";
import { SpatialInputRuntime, type InputMode } from "./spatial-runtime";
import { RemotePresencePanel } from "../remote/presence-panel";

const SESSION_KEY = "akashi-spatial-session";
const CALIBRATION_KEY = "akashi-spatial-calibration";
const DELEGATE_KEY = "akashi-spatial-delegate";
const UI_ORIGIN = { kind: "ui" as const, provider: "spatial-lab-ui" };

function readStorage<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? { ...fallback, ...JSON.parse(raw) } : fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: unknown): void {
  try { localStorage.setItem(key, typeof value === "string" ? value : JSON.stringify(value)); } catch { /* per-viewer convenience only */ }
}

function HandOverlay({ signal, enabled }: { signal: ReturnType<typeof createSignal<HandsFrame>>; enabled: boolean }) {
  const frame = useSyncExternalStore(signal.subscribe, signal.get, signal.get);
  if (!enabled) return null;
  return <div className="spatial-hands" aria-hidden="true">{frame.hands.filter((h) => h.state === "tracking" || h.state === "coasting").map((hand) => {
    const pose = frame.poses.find((p) => p.hand === hand.id);
    const state = pose?.pinch ? "pinch" : pose?.grab ? "grab" : "open";
    return <i key={hand.id} className="spatial-hand-cursor" data-state={state} data-coasting={hand.state === "coasting"}
      style={{ left: `${hand.features.pointer.x * 100}%`, top: `${hand.features.pointer.y * 100}%` }}><b>{hand.handedness === "Right" ? "R" : "L"}</b></i>;
  })}</div>;
}

function ProvenanceLine({ api, sessionId, objectId, revision }: { api: ReturnType<typeof spatialApi>; sessionId: string; objectId: string; revision: number }) {
  const [line, setLine] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.provenance(sessionId, objectId).then((record) => {
      const last = record.changes[0];
      if (alive) setLine(last ? `Last change #${last.seq}: ${last.origin.en}` : "Unchanged since it was added.");
    }).catch(() => { if (alive) setLine(null); });
    return () => { alive = false; };
  }, [api, sessionId, objectId, revision]);
  return line ? <p className="spatial-muted spatial-provenance" data-testid="provenance">{line}</p> : null;
}

const NO_STATE = () => () => undefined;

export default function SpatialLab({ config, connected, shell }: { config: BackendConfig; connected: boolean; shell: "desktop" | "web" }) {
  const api = useMemo(() => spatialApi(config), [config]);
  const store = useMemo(() => new SpatialSceneStore(), []);
  const handsSignal = useMemo(() => createSignal<HandsFrame>({ hands: [], poses: [], interaction: null, metrics: null }), []);
  const subscribe = useCallback((listener: () => void) => store.subscribe(listener), [store]);
  const version = useSyncExternalStore(subscribe, () => store.version, () => 0);
  const view = useMemo(() => (version >= 0 ? store.view() : null), [store, version]);
  const snapshot = useMemo(() => (version >= 0 ? store.current : null), [store, version]);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [sessionError, setSessionError] = useState<SpatialFailure | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [failure, setFailure] = useState<SpatialFailure | null>(null);
  const [reply, setReply] = useState<InterpretResult | null>(null);
  const [mode, setMode] = useState<InputMode>("off");
  const [providerStatus, setProviderStatus] = useState<ProviderStatus>({ state: "idle" });
  const [providerMetrics, setProviderMetrics] = useState<ProviderMetrics | null>(null);
  const [cameras, setCameras] = useState<Array<{ deviceId: string; label: string }>>([]);
  const [deviceId, setDeviceId] = useState<string>("");
  const [calibration, setCalibration] = useState<CameraCalibration>(() => readStorage(CALIBRATION_KEY, DEFAULT_CALIBRATION));
  const [debug, setDebug] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [replay, setReplay] = useState<{ frames: ReplayFrame[]; index: number; error: string | null; verified: { verified: boolean; matches_live_state: boolean; final_digest: string } | null } | null>(null);
  const [recentEvents, setRecentEvents] = useState<SpatialEvent[]>([]);
  const [rendererStats, setRendererStats] = useState<RendererStats | null>(null);
  const [measured, setMeasured] = useState<[number, number, number] | null>(null);
  const [serverMetrics, setServerMetrics] = useState<{ submit_ms: { count: number; p50: number | null; p95: number | null } } | null>(null);
  const [assetErrors, setAssetErrors] = useState<Record<string, string>>({});
  const [aspect, setAspect] = useState(16 / 9);
  const [recording, setRecording] = useState<number | null>(null);
  const [recordedFrames, setRecordedFrames] = useState<number | null>(null);
  const [providerLabel, setProviderLabel] = useState("none");
  // GPU vs CPU inference matters under GPU contention (local models, Blender); tuned locally.
  const [delegate, setDelegate] = useState<"GPU" | "CPU">(() => readStorage(DELEGATE_KEY, { value: "GPU" as "GPU" | "CPU" }).value);

  const stageRef = useRef<HTMLDivElement>(null);
  const canvasHostRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const rendererRef = useRef<SpatialRenderer | null>(null);
  const [projector] = useState(() => new PerspectiveProjector(DEFAULT_RIG, 16 / 9));
  const [runtime] = useState(() => new SpatialInputRuntime(store, api, projector, handsSignal, {
    onStatus: (status, label, nextMode) => { setProviderStatus(status); setProviderLabel(label); setMode(nextMode); },
    onHover: setHover,
    onNotice: setNotice,
    onError: setFailure,
    onCalibration: setCalibration,
  }));
  const sessionId = snapshot?.session.id ?? null;
  // Owner realtime presence: live previews and hands of remote devices, approvals, roster.
  // Commands keep using the HTTP API; this channel only adds push and preview streaming.
  const owner = useMemo(() => {
    if (!connected || !sessionId) return null;
    const client = ownerSession(config, shell === "desktop" ? "AKASHI Desktop" : "AKASHI Web",
      () => [{ name: "display", state: "available" }, { name: "approval_surface", state: "available" }, { name: "keyboard", state: "available" }]);
    return { client, spatial: new RemoteSpatial(client, store, { sessionId }) };
  }, [config, connected, sessionId, shell, store]);
  const [presenceOpen, setPresenceOpen] = useState(false);
  useEffect(() => {
    if (!owner) return;
    const stop = owner.spatial.start();
    owner.client.start();
    const port = owner.spatial.port();
    runtime.setPreviewSink((session, leaseId, objectId, transform) => port.preview(session, leaseId, objectId, transform));
    return () => { runtime.setPreviewSink(null); stop(); owner.client.stop(); };
  }, [owner, runtime]);
  const ownerState = useSyncExternalStore(useCallback((listener: () => void) => owner ? owner.client.onState(listener) : NO_STATE(), [owner]),
    () => owner?.client.state ?? "idle", () => "idle");
  const ownerVersion = useSyncExternalStore(useCallback((listener: () => void) => owner ? owner.spatial.subscribeTo(listener) : NO_STATE(), [owner]),
    () => owner?.spatial.version ?? 0, () => 0);
  const presence = useMemo(() => (ownerVersion >= 0 && owner ? { leases: owner.spatial.leases, roster: owner.spatial.roster, anchors: [...owner.spatial.presence.values()] } : null),
    [owner, ownerVersion]);
  useEffect(() => { runtime.configure({ calibration }); }, [runtime, calibration]);
  useEffect(() => { runtime.configure({ capabilities }); }, [runtime, capabilities]);
  useEffect(() => { runtime.configure({ sessionId }); }, [runtime, sessionId]);
  useEffect(() => () => runtime.dispose(), [runtime]);

  // Calibration persists per viewer (local convenience only).
  useEffect(() => { writeStorage(CALIBRATION_KEY, calibration); }, [calibration]);

  // Session: resume the last one, otherwise create; corrupted history fails closed.
  const openSession = useCallback(async (fresh: boolean) => {
    setSessionError(null);
    try {
      const caps = await api.capabilities();
      setCapabilities(caps);
      let saved: string | null = null;
      try { saved = fresh ? null : localStorage.getItem(SESSION_KEY); } catch { saved = null; }
      if (saved) {
        try {
          const existing = await api.getSession(saved);
          if (existing.changed) {
            store.apply({ session: existing.session, state: existing.state });
            return;
          }
        } catch (error) {
          const f = spatialFailure(error);
          if (f.code === "session_corrupted") { setSessionError(f); return; }
        }
      }
      const created = await api.createSession(shell === "desktop" ? "Desktop Spatial Lab" : "Web Spatial Lab");
      writeStorage(SESSION_KEY, created.session.id);
      store.apply(created);
    } catch (error) {
      setSessionError(spatialFailure(error));
    }
  }, [api, shell, store]);

  useEffect(() => {
    if (!connected) return;
    const timer = window.setTimeout(() => void openSession(false), 0);
    return () => window.clearTimeout(timer);
  }, [connected, openSession]);

  // Poll for changes from other origins (voice, /chat, tools). Cheap when unchanged.
  // While the owner realtime channel is online, changes are pushed instead.
  useEffect(() => {
    if (!connected || !snapshot?.session.id || replay || ownerState === "online") return;
    const id = snapshot.session.id;
    let alive = true;
    const timer = window.setInterval(async () => {
      if (document.hidden) return;
      try {
        const next = await api.getSession(id, store.revision);
        if (!alive) return;
        if (next.changed) store.apply({ session: next.session, state: next.state });
        else store.applySession(next.session);
      } catch { /* transient; the next poll retries */ }
    }, 1000);
    return () => { alive = false; window.clearInterval(timer); };
  }, [api, connected, ownerState, replay, snapshot?.session.id, store]);

  // Renderer lifecycle.
  useEffect(() => {
    const host = canvasHostRef.current;
    if (!host) return;
    const renderer = new SpatialRenderer(host, DEFAULT_RIG, (assetId) => api.assetContent(assetId),
      (assetId, state) => setAssetErrors((current) => {
        if (state.state === "error") return { ...current, [assetId]: state.detail ?? "GLB failed to load" };
        if (!(assetId in current)) return current;
        const next = { ...current };
        delete next[assetId];
        return next;
      }),
      (value) => { projector.setAspect(value); setAspect(value); });
    rendererRef.current = renderer;
    runtime.attachRenderer(renderer);
    const stats = window.setInterval(() => {
      setRendererStats(renderer.stats());
      setRecordedFrames(runtime.recordedFrames);
      const selectedId = store.view()?.selection[0];
      const size = selectedId ? renderer.measuredSize(selectedId) : null;
      setMeasured(size ? [size.x, size.y, size.z] : null);
    }, 500);
    return () => { window.clearInterval(stats); runtime.attachRenderer(null); renderer.dispose(); rendererRef.current = null; };
  }, [api, projector, runtime, store]);

  const displayed = replay ? replay.frames[replay.index]?.state ?? null : view;
  useEffect(() => { rendererRef.current?.sync(displayed, replay ? null : hover); }, [displayed, hover, replay]);

  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(() => {
      const rect = stage.getBoundingClientRect();
      runtime.configure({ viewport: { width: rect.width || 1280, height: rect.height || 720 } });
    });
    observer.observe(stage);
    return () => observer.disconnect();
  }, [runtime]);

  // Debug metrics (low frequency, only while the drawer is open).
  useEffect(() => {
    if (!debug || !snapshot?.session.id) return;
    const id = snapshot.session.id;
    const tick = async () => {
      setProviderMetrics(runtime.providerMetrics());
      try {
        const [events, metrics] = await Promise.all([api.events(id, Math.max(0, store.revision - 20)), api.metrics()]);
        setRecentEvents(events.events);
        setServerMetrics(metrics);
      } catch { /* debug only */ }
    };
    const timer = window.setInterval(() => void tick(), 1000);
    return () => window.clearInterval(timer);
  }, [api, debug, runtime, snapshot?.session.id, store]);

  // Input providers ------------------------------------------------------------------
  const startInput = useCallback(async (next: InputMode, recordingFile?: File) => {
    setFailure(null);
    await runtime.start(next, { video: videoRef.current, stage: stageRef.current, deviceId, recording: recordingFile, delegate });
    if (next === "camera" && runtime.providerId) setCameras(await listCameras().catch(() => []));
  }, [delegate, deviceId, runtime]);
  useEffect(() => { writeStorage(DELEGATE_KEY, { value: delegate }); }, [delegate]);
  useEffect(() => { runtime.configure({ paused: Boolean(replay) }); }, [runtime, replay]);

  // Commands --------------------------------------------------------------------------
  const run = useCallback(async (work: () => Promise<{ snapshot?: { session: NonNullable<typeof snapshot>["session"]; state: SceneState } } | void>) => {
    setBusy(true);
    setFailure(null);
    try {
      const result = await work();
      if (result && result.snapshot) store.apply(result.snapshot);
    } catch (error) {
      const f = spatialFailure(error);
      setFailure(f);
      if (f.kind === "clarification") setReply({ understood: true, reply: f.question ?? f.message, results: [], clarification: { code: f.code, question: f.question ?? f.message, candidates: f.candidates ?? [] } });
    } finally {
      setBusy(false);
    }
  }, [store]);

  const request = useCallback((value: SpatialRequest, confirmed = false) => {
    const id = sessionId;
    if (!id) return;
    void run(async () => {
      const result = await api.command(id, value, UI_ORIGIN, confirmed);
      for (const note of result.notes ?? []) setNotice(note);
      return result;
    });
  }, [api, run, sessionId]);

  const say = useCallback((text: string) => {
    const id = sessionId;
    if (!id) return;
    void run(async () => {
      const result = await api.interpret(id, text);
      setReply(result);
      return result;
    });
  }, [api, run, sessionId]);

  const confirm = useCallback((token: string, accept: boolean) => {
    const id = sessionId;
    if (!id) return;
    void run(async () => {
      const result = await api.confirm(id, token, accept);
      setReply(null);
      setNotice(accept ? "Confirmed." : "Cancelled; nothing changed.");
      return result;
    });
  }, [api, run, sessionId]);

  const openReplay = useCallback(async () => {
    const id = sessionId;
    if (!id) return;
    await runtime.start("off", {});
    try {
      const page = await api.events(id, 0);
      const frames = reconstruct(page.initial_state!, page.events);
      setReplay({ frames, index: frames.length - 1, error: null, verified: null });
    } catch (error) {
      setReplay({ frames: [], index: 0, error: error instanceof Error ? error.message : "Replay unavailable", verified: null });
    }
  }, [api, runtime, sessionId]);

  const selected: SceneObject | null = view && view.selection.length ? view.objects[view.selection[0]] ?? null : null;
  const labels = useMemo(() => {
    if (!displayed || !displayed.view.hud_visible || !aspect) return [];
    return displayed.order.map((id) => displayed.objects[id]).filter((o) => o.visible).map((o) => {
      const height = o.asset.normalization.size[1] * o.transform.scale;
      const at = projector.project([o.transform.position[0], o.transform.position[1] + height + 0.06, o.transform.position[2]]);
      const chest = projector.project([o.transform.position[0], o.transform.position[1] + height * 0.6, o.transform.position[2]]);
      const holder = presence?.leases.find((lease) => lease.object_id === o.id && lease.holder?.kind === "device")?.holder?.device_name ?? null;
      return at && chest ? { id: o.id, label: o.label, x: at.x, y: at.y, chest, selected: displayed.selection.includes(o.id), form: o.asset.form?.version_label ?? null, holder } : null;
    }).filter(Boolean) as Array<{ id: string; label: string; x: number; y: number; chest: { x: number; y: number }; selected: boolean; form: string | null; holder: string | null }>;
  }, [displayed, projector, aspect, presence]);
  const remoteAnchors = useMemo(() => (!aspect || !presence ? [] : presence.anchors.flatMap((entry) => Object.entries(entry.anchors).map(([hand, anchor]) => {
    const at = projector.project(anchor.position);
    return at ? { key: `${entry.session}-${hand}`, name: entry.device.name, hand: hand === "right_hand" ? "R" : "L", x: at.x, y: at.y } : null;
  }))).filter(Boolean) as Array<{ key: string; name: string; hand: string; x: number; y: number }>, [presence, projector, aspect]);
  const remoteDevices = presence?.roster.filter((entry) => entry.device.kind === "device") ?? [];

  const session = snapshot?.session ?? null;
  const cameraOn = mode === "camera" && providerStatus.state === "running";
  const inputLabel = mode === "camera" ? "CAMERA" : mode === "simulated" ? "SIMULATED HANDS" : mode === "recorded" ? "RECORDED HANDS" : "NO HAND INPUT";

  if (!connected) {
    return <section className="spatial-lab" data-shell={shell}><div className="spatial-offline"><p className="spatial-label">SPATIAL LAB</p><h3>AKASHI Core is offline.</h3><p>The scene, history and FORM integration live in Core. Connect to Core to open Spatial Lab.</p></div></section>;
  }

  return <section className="spatial-lab" data-shell={shell} data-input={mode} aria-label="Spatial Lab">
    <div ref={stageRef} className="spatial-stage" data-camera={cameraOn} data-replay={Boolean(replay)}>
      <video ref={videoRef} className="spatial-video" data-mirror={calibration.mirror} muted playsInline aria-hidden="true" />
      <div ref={canvasHostRef} className="spatial-canvas-host" data-testid="spatial-viewport" />
      {labels.map((item) => <span key={item.id} className="spatial-object-label" data-object={item.id} data-anchor={`${item.chest.x.toFixed(4)},${item.chest.y.toFixed(4)}`} data-selected={item.selected} style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%` }}>{item.label}{item.form ? <small>{item.form}</small> : null}{item.holder ? <small className="spatial-held">held by {item.holder}</small> : null}</span>)}
      {remoteAnchors.map((anchor) => <i key={anchor.key} className="remote-anchor" data-remote-anchor={anchor.name} style={{ left: `${anchor.x * 100}%`, top: `${anchor.y * 100}%` }}><b>{anchor.hand}</b><small>{anchor.name}</small></i>)}
      <HandOverlay signal={handsSignal} enabled={mode !== "off" && !replay} />
      <header className="spatial-topbar">
        <div className="spatial-title"><span>SPATIAL LAB · V1</span><strong>{sceneSummaryLine(view)}</strong><small title={capabilities?.scope.spatial_model}>Camera-backed 2.5D · no depth, occlusion or world anchoring</small></div>
        <div className="spatial-input-controls" role="group" aria-label="Hand input">
          <span className="spatial-input-state" data-state={providerStatus.state}>{inputLabel}{providerStatus.state === "starting" ? ` · ${providerStatus.detail}` : ""}</span>
          <button type="button" aria-pressed={mode === "camera"} disabled={Boolean(replay)} onClick={() => void startInput(mode === "camera" ? "off" : "camera")}>{mode === "camera" ? "Stop camera" : "Camera"}</button>
          <button type="button" aria-pressed={mode === "simulated"} disabled={Boolean(replay)} onClick={() => void startInput(mode === "simulated" ? "off" : "simulated")} title="Mouse-driven synthetic hand: hold the button to pinch, press 2 for a mirrored second hand">Simulate</button>
          <label className="spatial-file-button" title="Replay a recorded hand session">Recording<input type="file" accept="application/json,.json" onChange={(e) => { const file = e.target.files?.[0]; if (file) void startInput("recorded", file); e.target.value = ""; }} /></label>
          {cameras.length > 1 && <select aria-label="Camera device" value={deviceId} onChange={(e) => setDeviceId(e.target.value)}>{cameras.map((c) => <option key={c.deviceId} value={c.deviceId}>{c.label}</option>)}</select>}
          <button type="button" aria-pressed={presenceOpen} onClick={() => setPresenceOpen(!presenceOpen)} data-realtime={ownerState}
            title="Remote devices: invite, permissions, approvals">Devices{remoteDevices.length ? ` · ${remoteDevices.length}` : ""}</button>
          <button type="button" aria-pressed={debug} onClick={() => setDebug(!debug)}>Debug</button>
        </div>
      </header>
      {providerStatus.state === "error" && <p className="spatial-banner" role="alert">{providerStatus.message} The scene remains usable with commands and controls.</p>}
      {sessionError && <div className="spatial-banner" role="alert">
        <p>{sessionError.code === "session_corrupted" ? sessionError.message : `Spatial Lab could not open: ${sessionError.message}`}</p>
        <button type="button" onClick={() => void openSession(true)}>Start a new session</button>
      </div>}
      {Object.entries(assetErrors).map(([asset, message]) => <p key={asset} className="spatial-banner" role="alert">Asset {asset.slice(0, 10)} could not be rendered: {message}</p>)}
      {notice && <p className="spatial-notice" role="status" onAnimationEnd={() => setNotice(null)}>{notice}</p>}
      {session?.pending_confirmations.length ? <div className="spatial-banner" role="alert">
        <p>{session.pending_confirmations[0].question}</p>
        <div className="spatial-button-row"><button type="button" className="spatial-danger" onClick={() => confirm(session.pending_confirmations[0].token, true)}>Confirm</button><button type="button" onClick={() => confirm(session.pending_confirmations[0].token, false)}>Cancel</button></div>
      </div> : null}
    </div>

    <aside className="spatial-side spatial-side-left">
      <LibraryPanel api={api} capabilities={capabilities} busy={busy || !session} onAdd={(value) => request(value)} onUpload={(file) => {
        const id = sessionId;
        if (!id) return;
        void run(async () => {
          const asset = await api.uploadAsset(file);
          return api.command(id, { type: "scene.add_asset", asset_id: asset.asset_id }, UI_ORIGIN);
        });
      }} />
      {mode !== "off" && <section className="spatial-panel spatial-calibration" aria-label="Camera calibration">
        <header><span>CALIBRATION</span><strong>Hand → scene</strong></header>
        <label><input type="checkbox" checked={calibration.mirror} onChange={(e) => setCalibration({ ...calibration, mirror: e.target.checked })} /> Mirror (selfie view)</label>
        <label><input type="checkbox" checked={calibration.swapHandedness} onChange={(e) => setCalibration({ ...calibration, swapHandedness: e.target.checked })} /> Swap camera handedness labels</label>
        <label>Reach gain {calibration.gain.toFixed(2)}<input type="range" min={0.8} max={1.8} step={0.05} value={calibration.gain} onChange={(e) => setCalibration({ ...calibration, gain: Number(e.target.value) })} /></label>
        <label>Inference <select aria-label="Inference delegate" value={delegate} onChange={(e) => setDelegate(e.target.value as "GPU" | "CPU")}><option value="GPU">GPU (WebGL)</option><option value="CPU">CPU (WASM)</option></select><small className="spatial-muted">applies on next camera start</small></label>
        <div className="spatial-button-row">
          {recording === null ? <button type="button" onClick={() => { runtime.startRecording(); setRecording(Date.now()); }}>Record hands</button>
            : <button type="button" onClick={() => {
              setRecording(null);
              const data = runtime.stopRecording();
              if (!data) return;
              const url = URL.createObjectURL(new Blob([JSON.stringify(data)], { type: "application/json" }));
              const link = document.createElement("a");
              link.href = url;
              link.download = `akashi-hands-${new Date().toISOString().replace(/[:.]/gu, "-")}.json`;
              link.click();
              window.setTimeout(() => URL.revokeObjectURL(url), 5000);
            }}>Stop & save recording</button>}
          {recording !== null && <small className="spatial-muted" data-recorded-frames={recordedFrames ?? 0}>{recordedFrames ?? 0} frames</small>}
        </div>
      </section>}
    </aside>

    <aside className="spatial-side spatial-side-right">
      {presenceOpen && <RemotePresencePanel config={config} client={owner?.client ?? null} onClose={() => setPresenceOpen(false)} />}
      {selected && sessionId && !replay && <ProvenanceLine api={api} sessionId={sessionId} objectId={selected.id} revision={session?.revision ?? 0} />}
      {replay ? <ReplayPanel frames={replay.frames} index={replay.index} verified={replay.verified} error={replay.error}
        onIndex={(index) => setReplay({ ...replay, index: Math.max(0, Math.min(index, replay.frames.length - 1)) })}
        onVerify={() => { const id = sessionId; if (id) void api.verifyReplay(id).then((verified) => setReplay((current) => current && { ...current, verified })).catch((error) => setFailure(spatialFailure(error))); }}
        onClose={() => setReplay(null)} />
        : selected ? <InspectorPanel object={selected} busy={busy} measured={measured}
          onRequest={(value) => request(value)} onRemove={(object) => { if (window.confirm(`Remove ${object.label} from the scene? You can undo this.`)) request({ type: "scene.remove", target: { id: object.id } }, true); }} />
          : <section className="spatial-panel spatial-empty-inspector"><header><span>INSPECTOR</span><strong>Nothing selected</strong></header><p className="spatial-muted">Pinch an object (or tap it in the list) to select it. Commands like “select the one on the left” also work.</p>
            {view && view.order.length > 0 && <ul className="spatial-object-list">{view.order.map((id) => <li key={id}><button type="button" onClick={() => request({ type: "selection.select", target: { id } })}>{view.objects[id].label}</button></li>)}</ul>}</section>}
      {debug && <DebugPanel signal={handsSignal} provider={providerLabel} providerStatus={providerStatus} providerMetrics={providerMetrics} session={session} renderer={rendererStats} serverMetrics={serverMetrics} events={recentEvents} />}
    </aside>

    <footer className="spatial-dock">
      <div className="spatial-history" role="group" aria-label="History">
        <button type="button" disabled={busy || !session?.can_undo || Boolean(replay)} onClick={() => request({ type: "history.undo" })}>Undo</button>
        <button type="button" disabled={busy || !session?.can_redo || Boolean(replay)} onClick={() => request({ type: "history.redo" })}>Redo</button>
        <button type="button" aria-pressed={Boolean(replay)} disabled={!session} onClick={() => (replay ? setReplay(null) : void openReplay())}>{replay ? "Exit replay" : "Replay"}</button>
        <button type="button" aria-pressed={view?.view.hud_visible === false} disabled={busy || !view || Boolean(replay)} onClick={() => request({ type: "view.set", hud_visible: !(view?.view.hud_visible ?? true) })}>{view?.view.hud_visible === false ? "Show HUD" : "Hide HUD"}</button>
        <button type="button" aria-pressed={view?.view.vfx_visible === false} disabled={busy || !view || Boolean(replay)} onClick={() => request({ type: "view.set", vfx_visible: !(view?.view.vfx_visible ?? true) })}>{view?.view.vfx_visible === false ? "VFX on" : "VFX off"}</button>
      </div>
      <CommandBar busy={busy || !session || Boolean(replay)} result={reply} failure={failure} onSubmit={say} onCandidate={(label) => say(`select ${label}`)} onConfirm={confirm} />
    </footer>
  </section>;
}
