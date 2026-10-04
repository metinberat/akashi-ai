/* eslint-disable @next/next/no-img-element -- authenticated image blobs are runtime-only */
"use client";

import type { CSSProperties, DragEvent, ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Icon, Presence } from "@/components/identity";
import { HudZone, ModuleInventory, type HudModuleData } from "@/components/hud-modules";
import { Markdown } from "@/components/markdown";
import { CharacterScene } from "./character-scene";
import { DesktopResult } from "./desktop-result";
import { ActivityInstrument, AgentDock, SystemInstrument } from "./desktop-instruments";
import { useDesktopActivity } from "@/lib/use-desktop-activity";
import type { AkashiTask } from "@/lib/absolute-api";
import type { BackendConfig } from "@/lib/api";
import type { CenterStageEntity } from "@/lib/desktop-stage";
import type { DesktopMessage } from "@/lib/desktop-types";
import { computeEnergy } from "@/lib/energy-engine";
import { useHudLayout } from "@/lib/hud-modules";
import type { ProductMood, WorkspaceView } from "@/lib/platform";
import { useDesktopTelemetry } from "@/lib/telemetry";
import type { VoiceState } from "@/lib/voice";

export type { DesktopMessage } from "@/lib/desktop-types";

type Props = {
  activeView: WorkspaceView;
  mood: ProductMood;
  voiceState: VoiceState;
  voiceLabel: string;
  nativeVoiceAvailable: boolean;
  fullVoiceActive: boolean;
  connected: boolean;
  connectionLabel: string;
  desktopRuntime: DesktopRuntimeStatus | null;
  config: BackendConfig;
  messages: DesktopMessage[];
  isSending: boolean;
  workspaceActivity: string;
  tasks: AkashiTask[];
  stageEntity: CenterStageEntity | null;
  recentImages: string[];
  workspaceContent: ReactNode;
  commandStrip: ReactNode;
  settingsOverlay: ReactNode;
  onNavigate: (view: WorkspaceView) => void;
  onQuickMode: (view: WorkspaceView, mode?: "fast" | "quality" | "edit") => void;
  onMoodPreference: (mood: "auto" | ProductMood) => void;
  onMicrophone: () => void;
  onChooseFile: () => void;
  onDropFile: (file: File) => void;
  onRetry: (text: string, mode: "chat" | "fast" | "quality" | "edit") => void;
  onStagePrompt: (prompt: string) => void;
  onSettings: () => void;
};

const navItems: Array<{ view: WorkspaceView; icon: "mic" | "chat" | "create" | "research" | "tasks" | "memory" | "files" | "devices" | "spatial"; label: string }> = [
  { view: "home", icon: "mic", label: "Core" },
  { view: "chat", icon: "chat", label: "Sohbet" },
  { view: "create", icon: "create", label: "Oluştur" },
  { view: "spatial", icon: "spatial", label: "Spatial Lab" },
  { view: "research", icon: "research", label: "Araştır" },
  { view: "tasks", icon: "tasks", label: "Görevler" },
  { view: "memory", icon: "memory", label: "Hafıza" },
  { view: "files", icon: "files", label: "Dosyalar" },
  { view: "devices", icon: "devices", label: "Cihazlar" },
];

const quickActions: Array<{ label: string; view: WorkspaceView; icon: "chat" | "create" | "research"; mode?: "fast" | "edit" }> = [
  { label: "Sohbet", view: "chat", icon: "chat" },
  { label: "Görsel Oluştur", view: "create", icon: "create", mode: "fast" },
  { label: "Araştır", view: "research", icon: "research" },
  { label: "Düzenle", view: "create", icon: "create", mode: "edit" },
];

function useWindowControls() {
  const [maximized, setMaximized] = useState(false);
  useEffect(() => {
    const controls = window.akashiDesktop?.windowControls;
    if (!controls) return;
    let active = true;
    void controls.isMaximized().then((value) => { if (active) setMaximized(value); }).catch(() => undefined);
    const unsubscribe = controls.onState((value) => setMaximized(value.maximized));
    return () => { active = false; unsubscribe(); };
  }, []);
  const controls = window.akashiDesktop?.windowControls;
  return {
    available: Boolean(controls),
    maximized,
    minimize: () => void controls?.minimize(),
    maximize: () => void controls?.maximize().then(setMaximized),
    close: () => void controls?.close(),
  };
}

function CoreVisual({ energy, voiceState, voiceLabel, onMicrophone, disabled }: { energy: number; voiceState: VoiceState; voiceLabel: string; onMicrophone: () => void; disabled: boolean }) {
  return <section className="desktop-core-stage" data-voice={voiceState} aria-label={`AKASHI Core · ${voiceLabel}`}>
    <div className="character-fallback" aria-hidden="true"><img className="core-character" src="./desktop/akashi-core-wide.png" alt="" draggable={false} /></div>
    <CharacterScene energy={energy} voiceState={voiceState} />
    <div className="core-manifesto"><i /><h2 lang="ja">照見</h2><p>SEE<br />UNDERSTAND<br />CREATE<br />BEYOND.</p><i /><p>NOT JUST<br />ANSWERS.<br />A HIGHER<br />TOMORROW.</p></div>
    <div className="core-brand-accent" aria-hidden="true"><span>HUMAN</span><i>×</i><span>AI</span><small>A BRIGHTER<br />TOMORROW.</small></div>
    <div className="voice-focus">
      <div className="voice-wave" aria-hidden="true">{Array.from({ length: 37 }, (_, index) => <i key={index} style={{ "--bar": index, "--wave-height": Math.max(3, 29 - Math.abs(index - 18) * 1.15 + (index % 3) * 5) } as CSSProperties} />)}</div>
      <button className="core-microphone" type="button" onClick={onMicrophone} disabled={disabled} aria-label="AKASHI ile konuş"><Icon name={voiceState === "listening" ? "stop" : "mic"} /></button>
      <div className="core-state-copy"><span>AKASHI / {voiceState.toUpperCase()}</span><strong>{voiceLabel}</strong><p>{disabled ? "Voice için Core bağlantısını kontrol et." : voiceState === "idle" ? "Konuşmak için mikrofonu etkinleştir." : voiceState === "listening" ? "Dinliyorum." : voiceState === "speaking" ? "Yanıt aktarılıyor." : "LIVE Core işlemi yürütüyor."}</p></div>
    </div>
  </section>;
}

function QuickActionsCard({ onQuickMode }: { onQuickMode: Props["onQuickMode"] }) {
  return <section className="quick-actions-card">
    <header><span><i /> AKASHI QUICK ACTIONS</span></header>
    <div className="quick-actions-grid">
      {quickActions.map((item) => <button type="button" key={item.label} onClick={() => onQuickMode(item.view, item.mode)}><Icon name={item.icon} /><span>{item.label}</span></button>)}
    </div>
  </section>;
}

function ChatPanel({ messages, busy, onRetry, onPrompt, onClose }: { messages: DesktopMessage[]; busy: boolean; onRetry: Props["onRetry"]; onPrompt: Props["onStagePrompt"]; onClose: () => void }) {
  const transcript = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  useEffect(() => { if (following.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight; }, [messages, busy]);
  const startingPoints = ["Bugünün kritik gelişmelerini araştır.", "Bir kararı seçenekler ve risklerle analiz et.", "Bu sistemdeki en net sonraki adımı belirle."];
  return <section className="desktop-workspace-panel desktop-chat-panel" aria-label="Sohbet geçmişi"><header><div><span>CHAT / SECONDARY CHANNEL</span><h2>Conversation</h2></div><button type="button" onClick={onClose} aria-label="Sohbeti kapat">×</button></header><div className="desktop-transcript" ref={transcript} aria-live="polite" onScroll={() => { const el = transcript.current!; following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 36; }}>{messages.length === 0 ? <div className="desktop-empty"><Presence /><strong>Komut kanalı hazır.</strong><p>Yaz veya mikrofonu kullan. Voice, Desktop&apos;ın ana etkileşimidir.</p><div className="desktop-empty-actions">{startingPoints.map((prompt, index) => <button type="button" key={prompt} onClick={() => onPrompt(prompt)}><span>0{index + 1}</span>{prompt}<i>↗</i></button>)}</div></div> : messages.map((message) => <article key={message.id} data-role={message.role}><span>{message.role === "assistant" ? "AKASHI" : "YOU"}{message.meta ? ` / ${message.meta}` : ""}</span>{message.role === "assistant" ? <Markdown>{message.content}</Markdown> : <p>{message.content}</p>}{message.imageUrl && <img src={message.imageUrl} alt="AKASHI görsel çıktısı" />}{message.retry && <button type="button" onClick={() => onRetry(message.retry!.text, message.retry!.mode)}>Yeniden dene</button>}</article>)}{busy && <article data-role="assistant"><span>AKASHI / PROCESSING</span><div className="desktop-processing"><i /><i /><i /></div></article>}</div></section>;
}

export function DesktopCommandCenter(props: Props) {
  const [dragging, setDragging] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);
  const [navCollapsed, setNavCollapsed] = useState(false);
  const [dismissedResultId, setDismissedResultId] = useState<string | null>(null);
  const agentReady = Boolean(props.desktopRuntime?.components.agent.state === "READY");
  const telemetry = useDesktopTelemetry(agentReady);
  const hud = useHudLayout();
  const windowControls = useWindowControls();
  const [inventoryOpen, setInventoryOpen] = useState(false);
  const [agentsOpen, setAgentsOpen] = useState(false);
  const latestUser = useMemo(() => [...props.messages].reverse().find((message) => message.role === "user"), [props.messages]);
  const latestAssistant = useMemo(() => [...props.messages].reverse().find((message) => message.role === "assistant"), [props.messages]);
  const coreState = props.desktopRuntime?.components.core.state;
  const agentState = props.desktopRuntime?.components.agent.state;
  const activeView = props.activeView;
  const onNavigate = props.onNavigate;
  const visionRequested = /(?:ekranıma|ekrana|kameradan|camera|screen).*(?:bak|gör|anali)/iu.test(latestUser?.content || "") && latestAssistant?.meta?.includes("LIVE");
  const visionMessage = visionRequested && latestAssistant ? latestAssistant : null;
  const tasksIntensive = props.tasks.some((task) => task.status === "running");
  const energy = computeEnergy(props.mood, {
    voiceActive: props.voiceState !== "idle",
    busy: props.isSending,
    intensive: props.fullVoiceActive || tasksIntensive,
  });
  const events = useDesktopActivity(props.config, props.connected, props.messages, props.voiceState, coreState && agentState ? `CORE ${coreState} · BODY ${agentState}` : "", props.workspaceActivity);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      if (inventoryOpen) setInventoryOpen(false);
      else if (agentsOpen) setAgentsOpen(false);
      else if (activeView !== "home") onNavigate("home");
    };
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, [inventoryOpen, agentsOpen, activeView, onNavigate]);
  useEffect(() => {
    const visibility = () => setPageVisible(!document.hidden);
    visibility();
    document.addEventListener("visibilitychange", visibility);
    return () => {
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);

  const stage = props.activeView === "home" ? "core" : "workspace";
  const researchResult = props.stageEntity && props.stageEntity.contextId !== dismissedResultId ? props.stageEntity : null;

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) props.onDropFile(file);
  }


  const hudData: HudModuleData = {
    config: props.config,
    connected: props.connected,
    connectionLabel: props.connectionLabel,
    telemetry,
    agentReady,
    desktopRuntime: props.desktopRuntime,
    messages: props.messages,
    tasks: props.tasks,
    recentImages: props.recentImages,
    stageEntity: props.stageEntity,
    visionMessage,
    events,
    voiceState: props.voiceState,
    voiceLabel: props.voiceLabel,
    fullVoiceActive: props.fullVoiceActive,
  };

  const style = { "--ak-energy": energy } as CSSProperties;
  return <main className="desktop-command-center" data-interface="absolute" data-mood={props.mood} data-stage={stage} data-view={activeView} data-voice={props.voiceState} data-voice-session={props.fullVoiceActive ? "active" : "idle"} data-visible={pageVisible ? "true" : "false"} data-nav={navCollapsed ? "collapsed" : "open"} style={style}>
    <header className="desktop-titlebar">
      <button type="button" className="titlebar-collapse" onClick={() => setNavCollapsed((collapsed) => !collapsed)} aria-pressed={navCollapsed} aria-label={navCollapsed ? "Gezinme rayını göster" : "Gezinme rayını gizle"}><Icon name="chevron" /></button>
      <button type="button" className="desktop-brand" onClick={() => props.onNavigate("home")}><Presence compact /><span><strong>A.K.A.S.H.I</strong><small>ABSOLUTE INTELLIGENCE</small></span></button>
      <div className="desktop-title-copy"><span>VOICE // ACTION // VISUAL INTELLIGENCE</span><small>CONTROLLED LOCAL RUNTIME</small></div>
      <div className="desktop-title-status"><span className={`status-dot ${props.connected ? "online" : "offline"}`} /><strong>{props.connectionLabel}</strong><small>{props.desktopRuntime?.coreMode.toUpperCase() || "CORE"}</small></div>
      <ModuleInventory open={inventoryOpen} onToggleOpen={() => setInventoryOpen((open) => !open)} layout={hud.layout} toggleModule={hud.toggleModule} togglePinned={hud.togglePinned} moveZone={hud.moveZone} />
      <button type="button" className="desktop-settings" onClick={props.onSettings} aria-label="Ayarlar"><Icon name="settings" /></button>
      {windowControls.available && <div className="desktop-window-controls">
        <button type="button" onClick={windowControls.minimize} aria-label="Küçült"><Icon name="minimize" /></button>
        <button type="button" onClick={windowControls.maximize} aria-label={windowControls.maximized ? "Eski boyuta getir" : "Büyüt"}><Icon name={windowControls.maximized ? "restore" : "maximize"} /></button>
        <button type="button" className="window-close" onClick={windowControls.close} aria-label="Kapat"><Icon name="close" /></button>
      </div>}
    </header>

    <nav className="desktop-nav-rail" aria-label="Ana gezinme">
      <div className="nav-rail-items">
        {navItems.map((item) => <button type="button" key={item.view} className={activeView === item.view ? "active" : ""} onClick={() => props.onNavigate(item.view)} aria-label={item.label} title={item.label}><Icon name={item.icon} /></button>)}
      </div>
      <div className="nav-rail-footer">
        <button type="button" className={agentsOpen ? "active" : ""} onClick={() => setAgentsOpen(!agentsOpen)} aria-expanded={agentsOpen} aria-label="Agent Dock" title="Agent Dock / Autonomy Hub"><Icon name="autonomy" /></button>
      </div>
    </nav>

    <section className="desktop-center-stage">
      {/* Spatial Lab owns the stage (and the GPU); the Core scene is not rendered behind it. */}
      {activeView !== "spatial" && <CoreVisual energy={energy} voiceState={props.voiceState} voiceLabel={props.voiceLabel} onMicrophone={props.onMicrophone} disabled={!props.nativeVoiceAvailable || !props.connected} />}
      {researchResult && activeView === "home" && <DesktopResult key={researchResult.contextId} entity={researchResult} onPrompt={props.onStagePrompt} onClose={() => setDismissedResultId(researchResult.contextId)} />}
      {agentsOpen && <AgentDock runtime={props.desktopRuntime} tasks={props.tasks} connected={props.connected} onNavigate={view => { setAgentsOpen(false); props.onNavigate(view); }} onClose={() => setAgentsOpen(false)} />}
      {activeView === "spatial" ? <section className="desktop-spatial-stage" aria-label="Spatial Lab workspace">{props.workspaceContent}</section> : stage === "workspace" && (props.activeView === "chat" ? <ChatPanel messages={props.messages} busy={props.isSending} onRetry={props.onRetry} onPrompt={props.onStagePrompt} onClose={() => props.onNavigate("home")} /> : <section className={`desktop-workspace-panel desktop-${props.activeView}-panel`}><header><div><span>WORKSPACE / {props.activeView.toUpperCase()}</span><h2>{props.activeView}</h2></div><button type="button" onClick={() => props.onNavigate("home")} aria-label="Çalışma alanını kapat">×</button></header><div className="desktop-workspace-scroll">{props.workspaceContent}</div></section>)}
      <SystemInstrument telemetry={telemetry} ready={agentReady} />
      {inventoryOpen && <div className="diagnostics-drawer"><HudZone zone="left" layout={hud.layout} data={hudData} onCollapse={hud.toggleCollapsed} onPin={hud.togglePinned} onMove={hud.moveZone} onClose={hud.closeModule} /><HudZone zone="right" layout={hud.layout} data={hudData} onCollapse={hud.toggleCollapsed} onPin={hud.togglePinned} onMove={hud.moveZone} onClose={hud.closeModule} /></div>}
      <div className={`desktop-command-strip ${props.activeView === "chat" ? "expanded" : ""}`}>{props.commandStrip}</div>
    </section>

    <aside className="desktop-right-rail">
      <ActivityInstrument events={events} connected={props.connected} />
      <section className={`desktop-file-drop ${dragging ? "dragging" : ""}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={drop}><header>FILE DROP</header><button type="button" onClick={props.onChooseFile}><Icon name="files" /><strong>Dosyayı buraya bırak</strong><span>veya güvenli seçim yap</span><small>Images · Text · Code · Data</small></button></section>
      {props.tasks.some((task) => ["queued", "running", "waiting_confirmation"].includes(task.status)) && <section className="desktop-command-queue"><header>COMMAND QUEUE</header>{props.tasks.filter((task) => ["queued", "running", "waiting_confirmation"].includes(task.status)).slice(0, 2).map((task) => <article key={task.id}><span>{task.status.toUpperCase()}</span><strong>{task.title}</strong><small>{task.steps.filter((step) => step.status === "completed").length} / {task.steps.length} STEP</small></article>)}</section>}
      <QuickActionsCard onQuickMode={props.onQuickMode} />
    </aside>

    <div className="desktop-ambient-selector" aria-label="Ambient HUD state">{(["calm", "best", "hardcarry"] as const).map((value) => <button type="button" key={value} className={props.mood === value ? "active" : ""} onClick={() => props.onMoodPreference(value)}>{value === "best" ? "BEST OF BEST" : value.toUpperCase()}</button>)}</div>
    {props.settingsOverlay}
  </main>;
}
