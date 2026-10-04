"use client";

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";

import { deviceSession } from "@/lib/remote/device";
import type { StoredIdentity } from "@/lib/remote/identity";
import { RemoteFailure, type Approval, type CapabilityReport } from "@/lib/remote/protocol";
import { attachLifecycle } from "@/lib/remote/session";
import { RemoteSpatial } from "@/lib/remote/spatial";
import { availableEngine, ENGINE_NOTES, listenOnce, speak } from "@/lib/remote/voice-input";
import { DEFAULT_CALIBRATION } from "@/lib/spatial/calibration";
import { DEFAULT_RIG, PerspectiveProjector } from "@/lib/spatial/projection";
import { SpatialSceneStore } from "@/lib/spatial/scene-store";
import { createSignal } from "@/lib/spatial/signal";
import type { ProviderStatus } from "@/lib/spatial/providers/types";
import type { SceneObject, SpatialRequest } from "@/lib/spatial/types";

import type { HandsFrame } from "../spatial/spatial-panels";
import { SpatialRenderer } from "../spatial/spatial-renderer";
import { SpatialInputRuntime, type InputMode } from "../spatial/spatial-runtime";
import { ApprovalList, HistoryList, RemoteDebug, RosterList, type Reply } from "./remote-panels";

function detectCapabilities(): CapabilityReport[] {
  if (typeof window === "undefined") return [];
  const media = Boolean(navigator.mediaDevices?.getUserMedia) && window.isSecureContext;
  const touch = navigator.maxTouchPoints > 0;
  const engine = availableEngine();
  const list: CapabilityReport[] = [
    { name: "display", state: "available", detail: { width: window.screen?.width, height: window.screen?.height } },
    { name: "approval_surface", state: "available" },
    { name: "touch", state: touch ? "available" : "unavailable" },
    { name: "pointer", state: window.matchMedia?.("(pointer: fine)").matches ? "available" : "unavailable" },
    { name: "keyboard", state: "available" },
    { name: "camera", state: media ? "available" : "unavailable", detail: { processing: "on-device" } },
    { name: "microphone", state: media ? "available" : "unavailable", detail: { audio_to_core: false } },
    { name: "hand_tracking", state: media && typeof WebAssembly !== "undefined" ? "available" : "unavailable", detail: { engine: "mediapipe-hand-landmarker", on_device: true } },
    { name: "gesture", state: "available", detail: { on_device: true } },
    { name: "voice_input", state: engine === "none" ? "unavailable" : "available", detail: { engine, note: ENGINE_NOTES[engine] } },
    { name: "speech_output", state: "speechSynthesis" in window ? "available" : "unavailable" },
    { name: "orientation", state: "DeviceOrientationEvent" in window ? "available" : "unavailable" },
    { name: "notifications", state: "Notification" in window ? "available" : "unavailable" },
  ];
  return list;
}

function describe(error: unknown): string {
  if (error instanceof RemoteFailure) {
    const known: Record<string, string> = {
      forbidden: "This device is not permitted to do that. The owner can change its permissions on the desktop.",
      stale_state: "The scene changed while you were looking. It is up to date now; try again.",
      object_busy: "Someone is holding that object right now.",
      outcome_unknown: "The connection was replaced before AKASHI answered. The scene was re-read; check it before retrying.",
      rate_limited: "Too many requests. Slow down a little.",
      timeout: "AKASHI did not answer in time.",
    };
    const question = typeof error.details?.question === "string" ? error.details.question : null;
    return question ?? known[error.code] ?? error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

/** Mutable values read by long-lived objects (session handshake, input modality) outside render. */
class Holder<T> {
  constructor(private value: T) {}
  get(): T { return this.value; }
  set(value: T): void { this.value = value; }
}

const STATE_LABEL: Record<string, string> = {
  idle: "Starting", connecting: "Connecting", online: "Connected", reconnecting: "Reconnecting", revoked: "Revoked", unpaired: "Not paired", closed: "Closed",
};

export default function RemoteSessionView({ identity, onUnpair }: { identity: StoredIdentity; onUnpair: () => void }) {
  const [capabilities, setCapabilities] = useState(detectCapabilities);
  const [capabilityHolder] = useState(() => new Holder<CapabilityReport[]>([]));
  const [client] = useState(() => deviceSession({
    identity,
    capabilities: () => capabilityHolder.get(),
    client: { app: "akashi-remote", platform: typeof navigator !== "undefined" ? navigator.platform : "unknown",
      shell: typeof window !== "undefined" && "Capacitor" in window ? "capacitor" : "browser" },
  }));
  const [store] = useState(() => new SpatialSceneStore());
  const [projector] = useState(() => new PerspectiveProjector(DEFAULT_RIG, 16 / 9));
  const [handsSignal] = useState(() => createSignal<HandsFrame>({ hands: [], poses: [], interaction: null, metrics: null }));
  const [modeHolder] = useState(() => new Holder<InputMode>("off"));
  const [spatial] = useState(() => new RemoteSpatial(client, store, {
    create: true, modality: () => (modeHolder.get() === "touch" ? "touch" : modeHolder.get() === "simulated" ? "pointer" : "gesture"),
  }));
  const [providerStatus, setProviderStatus] = useState<ProviderStatus>({ state: "idle" });
  const [mode, setMode] = useState<InputMode>("off");
  const [notice, setNotice] = useState<string | null>(null);
  const [runtime] = useState(() => new SpatialInputRuntime(store, spatial.port(), projector, handsSignal, {
    onStatus: (status, _label, next) => { setProviderStatus(status); setMode(next); },
    onHover: () => undefined,
    onNotice: setNotice,
    onError: (failure) => setNotice(failure.message),
    onCalibration: () => undefined,
  }));
  const stageRef = useRef<HTMLDivElement>(null);
  const hostRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const rendererRef = useRef<SpatialRenderer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reply, setReply] = useState<Reply | null>(null);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [sheet, setSheet] = useState<"none" | "approvals" | "history" | "devices" | "debug">("none");
  const [aspect, setAspect] = useState(16 / 9);
  const [engine] = useState(availableEngine);

  const clientState = useSyncExternalStore(useCallback((listener: () => void) => client.onState(listener), [client]), () => client.state, () => "idle");
  const storeVersion = useSyncExternalStore(useCallback((listener: () => void) => store.subscribe(listener), [store]), () => store.version, () => 0);
  const spatialVersion = useSyncExternalStore(useCallback((listener: () => void) => spatial.subscribeTo(listener), [spatial]), () => spatial.version, () => 0);
  const view = useMemo(() => (storeVersion >= 0 ? store.view() : null), [store, storeVersion]);
  const snapshot = useMemo(() => (storeVersion >= 0 ? store.current : null), [store, storeVersion]);
  const remote = useMemo(() => (spatialVersion >= 0 ? { leases: spatial.leases, roster: spatial.roster, history: spatial.history,
    presence: [...spatial.presence.values()], syncing: spatial.syncing, failure: spatial.failure, mode: spatial.lastSyncMode, resyncs: spatial.resyncs } : null),
  [spatial, spatialVersion]);
  const scopes = clientState === "online" || client.welcome ? client.scopes : [];
  const can = (scope: string) => scopes.includes(scope);
  const coreUrl = identity.credential.coreUrl;

  // Session lifecycle: connect, survive sleep/wake and network changes.
  useEffect(() => {
    capabilityHolder.set(capabilities);
    if (client.state === "online") void client.request("capabilities.update", { capabilities }).catch(() => undefined);
  }, [client, capabilities, capabilityHolder]);
  useEffect(() => {
    const stopSpatial = spatial.start();
    client.start();
    const detach = attachLifecycle(client);
    const offApprovals = client.on("approvals.changed", (message) => setApprovals(message.body.approvals as Approval[]));
    const offSession = client.onSession(() => {
      if (client.can("approvals.spatial") || client.can("approvals.general")) {
        void client.request("approvals.list").then((body) => setApprovals(body.approvals as Approval[])).catch(() => undefined);
      }
    });
    return () => { offApprovals(); offSession(); detach(); stopSpatial(); client.stop(); };
  }, [client, spatial]);
  useEffect(() => () => runtime.dispose(), [runtime]);
  useEffect(() => { runtime.configure({ sessionId: snapshot?.session.id ?? null }); }, [runtime, snapshot?.session.id]);
  useEffect(() => { modeHolder.set(mode); }, [mode, modeHolder]);

  // Renderer: the same three.js view as the desktop, fed from the synchronized replica.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;
    const loadAsset = async (assetId: string) => {
      const welcome = client.welcome;
      if (!welcome) throw new Error("Not connected");
      const response = await fetch(`${coreUrl}/remote/sessions/${encodeURIComponent(welcome.session_id)}/assets/${encodeURIComponent(assetId)}`,
        { headers: { Authorization: `Bearer ${welcome.session_token}` }, cache: "force-cache" });
      if (!response.ok) throw new Error(`Asset unavailable (${response.status})`);
      return response.arrayBuffer();
    };
    const renderer = new SpatialRenderer(host, DEFAULT_RIG, loadAsset, () => undefined, (value) => { projector.setAspect(value); setAspect(value); });
    rendererRef.current = renderer;
    runtime.attachRenderer(renderer);
    return () => { runtime.attachRenderer(null); renderer.dispose(); rendererRef.current = null; };
  }, [client, coreUrl, projector, runtime]);
  useEffect(() => { rendererRef.current?.sync(view, null); }, [view]);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    const observer = new ResizeObserver(() => {
      const rect = stage.getBoundingClientRect();
      runtime.configure({ viewport: { width: rect.width || 390, height: rect.height || 600 } });
    });
    observer.observe(stage);
    return () => observer.disconnect();
  }, [runtime]);

  // Input -------------------------------------------------------------------------------
  const setCapability = useCallback((name: CapabilityReport["name"], state: CapabilityReport["state"]) => {
    setCapabilities((current) => current.map((item) => (item.name === name ? { ...item, state } : item)));
  }, []);
  const startInput = useCallback(async (next: InputMode) => {
    setNotice(null);
    // Calibration: touch and pointer map the screen directly (no mirror); a selfie camera is mirrored.
    runtime.configure({ calibration: next === "camera" ? DEFAULT_CALIBRATION : { ...DEFAULT_CALIBRATION, mirror: false } });
    await runtime.start(next, { video: videoRef.current, stage: stageRef.current, delegate: "GPU" });
    const cameraState = next === "camera" ? (runtime.providerId ? "active" : "denied") : "available";
    if (capabilities.find((c) => c.name === "camera")?.state !== "unavailable") {
      setCapability("camera", cameraState);
      setCapability("hand_tracking", next === "camera" && runtime.providerId ? "active" : "available");
    }
  }, [capabilities, runtime, setCapability]);
  useEffect(() => {
    if (clientState !== "online" || mode !== "off" || !snapshot) return;
    const timer = window.setTimeout(() => void startInput(navigator.maxTouchPoints > 0 ? "touch" : "simulated"), 0);
    return () => window.clearTimeout(timer);
  }, [clientState, mode, snapshot, startInput]);

  // Actions ------------------------------------------------------------------------------
  const act = useCallback(async (work: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try { await work(); } catch (failure) { setError(describe(failure)); } finally { setBusy(false); }
  }, []);
  const command = useCallback((request: SpatialRequest) => act(async () => {
    const result = await spatial.command(request, "ui");
    if (result.status === "confirmation_required" && result.token) setReply({ reply: result.question ?? "Confirm?", confirmation: { token: result.token, question: result.question ?? "Confirm?" } });
  }), [act, spatial]);
  const say = useCallback((value: string, voice: boolean, transcriptEngine?: string) => act(async () => {
    const body = voice
      ? await client.request("voice.utterance", { text: value, language: "auto", engine: transcriptEngine ?? engine })
      : await spatial.interpret(value, "language");
    const spatialPart = (voice ? body.spatial : body) as Record<string, unknown> | undefined;
    const next: Reply = { reply: String(body.reply ?? ""), route: typeof body.route === "string" ? body.route : undefined,
      confirmation: (spatialPart?.confirmation as Reply["confirmation"]) ?? undefined, query: spatialPart?.query as string | undefined };
    setReply(next);
    if (voice && next.reply) speak(next.reply);
  }), [act, client, engine, spatial]);
  const listen = useCallback(async () => {
    setListening(true);
    setError(null);
    try {
      const heard = await listenOnce("auto");
      setText(heard.text);
      await say(heard.text, true, heard.engine);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
      if (failure instanceof Error && /denied/iu.test(failure.message)) setCapability("microphone", "denied");
    } finally {
      setListening(false);
    }
  }, [say, setCapability]);
  const decide = useCallback((approval: Approval, approve: boolean) => act(async () => {
    await client.request("approval.decide", { approval_id: approval.id, approve });
    setApprovals((current) => current.filter((item) => item.id !== approval.id));
  }), [act, client]);
  const confirm = useCallback((token: string, accept: boolean) => act(async () => {
    await spatial.confirm(token, accept);
    setReply(null);
  }), [act, spatial]);

  const selected: SceneObject | null = view && view.selection.length ? view.objects[view.selection[0]] ?? null : null;
  const labels = useMemo(() => {
    if (!view || !aspect) return [];
    return view.order.map((id) => view.objects[id]).filter((o) => o.visible).map((o) => {
      const height = o.asset.normalization.size[1] * o.transform.scale;
      const at = projector.project([o.transform.position[0], o.transform.position[1] + height + 0.06, o.transform.position[2]]);
      const chest = projector.project([o.transform.position[0], o.transform.position[1] + height * 0.6, o.transform.position[2]]);
      const holder = remote?.leases.find((lease) => lease.object_id === o.id)?.holder;
      return at && chest ? { id: o.id, label: o.label, x: at.x, y: at.y, chest, selected: view.selection.includes(o.id), holder: holder?.device_name ?? null } : null;
    }).filter(Boolean) as Array<{ id: string; label: string; x: number; y: number; chest: { x: number; y: number }; selected: boolean; holder: string | null }>;
  }, [view, projector, aspect, remote]);
  const anchors = useMemo(() => (!aspect ? [] : remote?.presence ?? []).flatMap((entry) => Object.entries(entry.anchors).map(([hand, anchor]) => {
    const at = projector.project(anchor.position);
    return at ? { key: `${entry.session}-${hand}`, name: entry.device.name, hand: hand === "right_hand" ? "R" : "L", x: at.x, y: at.y } : null;
  }).filter(Boolean)) as Array<{ key: string; name: string; hand: string; x: number; y: number }>, [remote, projector, aspect]);

  if (clientState === "revoked" || clientState === "unpaired") {
    return <main className="remote-app remote-ended" aria-label="Device not authorized">
      <header><span>AKASHI · REMOTE PRESENCE</span><h1>{clientState === "revoked" ? "This device was revoked" : "This device is no longer paired"}</h1></header>
      <p className="remote-muted">{clientState === "revoked" ? "The owner revoked this device or removed all of its permissions. It can no longer see or change anything."
        : "AKASHI Core does not know this device any more. Pair it again with a new code."}</p>
      <button type="button" className="remote-primary" onClick={onUnpair}>Forget and pair again</button>
    </main>;
  }

  const holdingOther = selected ? remote?.leases.find((lease) => lease.object_id === selected.id && lease.holder?.session !== client.welcome?.session_id) : null;
  return <main className="remote-app" data-state={clientState} data-input={mode} aria-label="AKASHI remote">
    <header className="remote-top">
      <div><span className="remote-brand">AKASHI · {identity.credential.deviceName}</span>
        <strong className="remote-connection" data-state={clientState} role="status">{STATE_LABEL[clientState] ?? clientState}</strong></div>
      <nav className="remote-tabs" aria-label="Remote panels">
        <button type="button" aria-pressed={sheet === "approvals"} onClick={() => setSheet(sheet === "approvals" ? "none" : "approvals")} disabled={!can("approvals.spatial") && !can("approvals.general")}>
          Approvals{approvals.length ? <b className="remote-badge">{approvals.length}</b> : null}</button>
        <button type="button" aria-pressed={sheet === "history"} onClick={() => setSheet(sheet === "history" ? "none" : "history")}>History</button>
        <button type="button" aria-pressed={sheet === "devices"} onClick={() => setSheet(sheet === "devices" ? "none" : "devices")}>Devices</button>
        <button type="button" aria-pressed={sheet === "debug"} onClick={() => setSheet(sheet === "debug" ? "none" : "debug")}>Debug</button>
      </nav>
    </header>

    <section ref={stageRef} className="remote-stage" aria-label="Scene" data-syncing={remote?.syncing ?? false}>
      <video ref={videoRef} className="spatial-video remote-video" data-mirror="true" muted playsInline aria-hidden="true" />
      <div ref={hostRef} className="remote-canvas-host" data-testid="remote-viewport" />
      {labels.map((item) => <span key={item.id} className="spatial-object-label remote-label" data-object={item.id} data-selected={item.selected}
        data-anchor={`${item.chest.x.toFixed(4)},${item.chest.y.toFixed(4)}`}
        style={{ left: `${item.x * 100}%`, top: `${item.y * 100}%` }}>{item.label}{item.holder ? <small>held by {item.holder}</small> : null}</span>)}
      {anchors.map((anchor) => <i key={anchor.key} className="remote-anchor" style={{ left: `${anchor.x * 100}%`, top: `${anchor.y * 100}%` }} title={`${anchor.name} ${anchor.hand}`}><b>{anchor.hand}</b><small>{anchor.name}</small></i>)}
      {clientState !== "online" && <p className="remote-overlay" role="status">{clientState === "reconnecting" ? "Connection lost — reconnecting. Nothing you do is lost or applied twice." : "Connecting to AKASHI…"}</p>}
      {remote?.failure && <p className="remote-overlay" role="alert">{remote.failure.message}</p>}
      {providerStatus.state === "error" && <p className="remote-overlay" role="alert">{providerStatus.message}</p>}
      <div className="remote-input-modes" role="group" aria-label="Input">
        <button type="button" aria-pressed={mode === "touch"} onClick={() => void startInput("touch")} disabled={!can("spatial.control")}>Touch</button>
        <button type="button" aria-pressed={mode === "simulated"} onClick={() => void startInput("simulated")} disabled={!can("spatial.control")}>Pointer</button>
        <button type="button" aria-pressed={mode === "camera"} disabled={!can("spatial.control") || capabilities.find((c) => c.name === "camera")?.state === "unavailable"}
          onClick={() => void startInput(mode === "camera" ? "touch" : "camera")} title="Hand tracking runs on this device; video never leaves it">{mode === "camera" ? "Stop hands" : "Hands"}</button>
      </div>
    </section>

    {notice && <p className="remote-notice" role="status">{notice}</p>}
    {error && <p className="remote-error" role="alert">{error}</p>}

    <section className="remote-selected" aria-label="Selected object">
      {selected ? <>
        <header><strong>{selected.label}</strong>{selected.asset.form?.version_label ? <small>FORM {selected.asset.form.version_label}</small> : null}
          {holdingOther ? <small className="remote-held">held by {holdingOther.holder?.device_name ?? "another input"}</small> : null}</header>
        <p className="remote-muted">x {selected.transform.position[0].toFixed(2)} · y {selected.transform.position[1].toFixed(2)} · scale {selected.transform.scale.toFixed(2)}</p>
        <div className="remote-actions" role="group" aria-label="Object actions">
          <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.transform", target: { id: selected.id }, mode: "rotate", degrees: -15 })}>⟲ 15°</button>
          <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.transform", target: { id: selected.id }, mode: "rotate", degrees: 15 })}>⟳ 15°</button>
          <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.transform", target: { id: selected.id }, mode: "scale", factor: 1 / 1.15 })}>Smaller</button>
          <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.transform", target: { id: selected.id }, mode: "scale", factor: 1.15 })}>Bigger</button>
          <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.transform", target: { id: selected.id }, mode: "center" })}>Center</button>
          {selected.asset.form_hud_nodes > 0 && <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "object.display", target: { id: selected.id }, form_hud: !selected.display.form_hud })}>{selected.display.form_hud ? "Hide FORM HUD" : "Show FORM HUD"}</button>}
          {selected.asset.clips.length > 0 && <button type="button" disabled={busy || !can("spatial.control")} onClick={() => void command({ type: "animation.control", target: { id: selected.id }, action: selected.animation.playing ? "pause" : "play" })}>{selected.animation.playing ? "Pause" : "Play"}</button>}
        </div>
      </> : <p className="remote-muted">{view?.order.length ? "Tap an object to select it, drag to move it, use two fingers to scale and turn." : "The scene is empty. Ask AKASHI to load your latest FORM character."}</p>}
      <div className="remote-actions" role="group" aria-label="Scene">
        <button type="button" disabled={busy || !snapshot?.session.can_undo || !can("spatial.control")} onClick={() => void command({ type: "history.undo" })}>Undo</button>
        <button type="button" disabled={busy || !snapshot?.session.can_redo || !can("spatial.control")} onClick={() => void command({ type: "history.redo" })}>Redo</button>
        <button type="button" disabled={busy || !view || !can("spatial.control")} onClick={() => void command({ type: "view.set", hud_visible: !(view?.view.hud_visible ?? true) })}>{view?.view.hud_visible === false ? "Show HUD" : "Hide HUD"}</button>
        <button type="button" disabled={busy || !view || !can("spatial.control")} onClick={() => void command({ type: "view.set", vfx_visible: !(view?.view.vfx_visible ?? true) })}>{view?.view.vfx_visible === false ? "VFX on" : "VFX off"}</button>
      </div>
    </section>

    <form className="remote-command" onSubmit={(event) => { event.preventDefault(); if (text.trim()) { void say(text.trim(), false); setText(""); } }}>
      <input aria-label="Instruction for AKASHI" placeholder="Rotate this character · Load the latest FORM version" value={text} onChange={(e) => setText(e.target.value)} disabled={!can("spatial.control")} />
      <button type="submit" disabled={busy || !text.trim() || !can("spatial.control")}>Send</button>
      {engine !== "none" && can("voice.spatial") && <button type="button" className="remote-mic" aria-pressed={listening} disabled={busy || listening} onClick={() => void listen()} title={ENGINE_NOTES[engine]}>{listening ? "Listening…" : "🎙"}</button>}
    </form>
    {reply && <div className="remote-reply" role="status"><p>{reply.reply}</p>
      {reply.confirmation && <div className="remote-actions"><button type="button" className="remote-danger" onClick={() => void confirm(reply.confirmation!.token, true)}>Confirm</button><button type="button" onClick={() => void confirm(reply.confirmation!.token, false)}>Cancel</button></div>}</div>}

    {sheet === "approvals" && <ApprovalList approvals={approvals} busy={busy} onDecide={(approval, approve) => void decide(approval, approve)} />}
    {sheet === "history" && <HistoryList events={remote?.history ?? []} me={client.welcome?.session_id ?? null} />}
    {sheet === "devices" && <RosterList roster={remote?.roster ?? []} me={client.welcome?.session_id ?? null} capabilities={capabilities} scopes={scopes} credential={identity.credential} onUnpair={onUnpair} />}
    {sheet === "debug" && <RemoteDebug client={client} revision={snapshot?.session.revision ?? null} digest={snapshot?.session.digest ?? null} syncMode={remote?.mode ?? null} resyncs={remote?.resyncs ?? 0} />}
  </main>;
}
