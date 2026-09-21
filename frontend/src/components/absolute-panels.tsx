"use client";

import { ChangeEvent, FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  approveTask,
  cancelTask,
  createMemory,
  createPairingCode,
  createTask,
  deleteFile,
  deleteMemory,
  getDeviceAction,
  listDevices,
  listFiles,
  listMemories,
  listTasks,
  queueDeviceAction,
  runResearch,
  uploadFile,
  updateMemory,
  revokeDevice,
  getResearchProgress,
  type AkashiTask,
  type DeviceAction,
  type MemoryEntry,
  type PairedDevice,
  type ResearchResult,
  type UploadedFile,
} from "@/lib/absolute-api";
import { isDesktopRuntime, type BackendConfig } from "@/lib/api";
import { Markdown } from "./markdown";
import { Presence } from "./identity";
import { ActionFields, ToolResult } from "./tool-result";

type PanelProps = {
  config: BackendConfig;
  connected: boolean;
};

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "İstek tamamlanamadı.";
}

function PanelIntro({ eyebrow, title, children }: { eyebrow: string; title: string; children: React.ReactNode }) {
  return (
    <header className="panel-intro">
      <p className="eyebrow">{eyebrow}</p>
      <h3>{title}</h3>
      <p>{children}</p>
    </header>
  );
}

function ConnectionGate({ connected }: { connected: boolean }) {
  if (connected) return null;
  return <p className="panel-notice">Bu alan için önce FastAPI bağlantısını Ayarlar&apos;dan doğrula.</p>;
}

export function MemoryPanel({ config, connected }: PanelProps) {
  const [items, setItems] = useState<MemoryEntry[]>([]);
  const [query, setQuery] = useState("");
  const [content, setContent] = useState("");
  const [category, setCategory] = useState("preference");
  const [tags, setTags] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editContent, setEditContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!connected) return;
    setError("");
    try {
      setItems(await listMemories(config, query));
    } catch (value) {
      setError(errorText(value));
    }
  }, [config, connected, query]);

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initial);
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!content.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      await createMemory(config, {
        content,
        category,
        tags: tags.split(",").map((item) => item.trim()).filter(Boolean),
      });
      setContent("");
      setTags("");
      await load();
    } catch (value) {
      setError(errorText(value));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="absolute-panel">
      <PanelIntro eyebrow="MEMORY V2" title="Uzun süreli hafıza">
        Yalnızca kalıcı ve yararlı bilgileri sakla. Mesaj geçmişi ayrı tutulur; anahtar ve parola benzeri değerler reddedilir.
      </PanelIntro>
      <ConnectionGate connected={connected} />
      <div className="panel-grid two-column">
        <form className="absolute-card panel-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="memory-content">Yeni hafıza</label>
          <textarea id="memory-content" value={content} onChange={(event) => setContent(event.target.value)} placeholder="Örn. Teknik açıklamaları kısa ve doğrudan tercih ediyorum." rows={5} />
          <div className="field-row">
            <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Hafıza kategorisi">
              <option value="preference">Tercih</option>
              <option value="user">Kullanıcı bilgisi</option>
              <option value="project">Proje</option>
              <option value="decision">Karar</option>
              <option value="fact">Bilgi</option>
            </select>
            <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="etiket, virgülle" />
          </div>
          <button type="submit" disabled={!connected || busy || !content.trim()}>{busy ? "Kaydediliyor…" : "Hafızaya kaydet"}</button>
        </form>
        <section className="absolute-card">
          <div className="card-heading">
            <strong>Kayıtlar</strong>
            <input className="compact-input" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Hafızada ara" />
          </div>
          <div className="panel-list">
            {items.length === 0 && <p className="empty-state">Henüz eşleşen kalıcı hafıza yok.</p>}
            {items.map((item) => (
              <article className="list-item" key={item.id}>
                <div className="list-meta"><span>{item.category.toUpperCase()}</span><span>{item.tags.join(" · ")}</span></div>
                {editingId === item.id ? <div className="panel-form"><textarea aria-label="Hafızayı düzenle" value={editContent} onChange={(event) => setEditContent(event.target.value)} /><div className="inline-actions"><button type="button" className="text-button" onClick={() => void updateMemory(config, item.id, editContent).then(() => { setEditingId(null); return load(); }).catch((value) => setError(errorText(value)))}>Kaydet</button><button type="button" className="text-button" onClick={() => setEditingId(null)}>Vazgeç</button></div></div> : <p>{item.content}</p>}
                <div className="list-meta"><span>{item.source}</span><time dateTime={item.updated_at}>{new Date(item.updated_at).toLocaleDateString()}</time></div>
                <button className="text-button" type="button" onClick={() => { setEditingId(item.id); setEditContent(item.content); }}>Düzenle</button>{" · "}
                <button className="text-button danger" type="button" onClick={() => void deleteMemory(config, item.id).then(load).catch((value) => setError(errorText(value)))}>Sil</button>
              </article>
            ))}
          </div>
        </section>
      </div>
      {error && <p className="panel-error">{error}</p>}
    </div>
  );
}

type ResearchPanelProps = PanelProps & {
  initialQuestion?: string;
  onContinue?: (prompt: string) => void;
  onActivityChange?: (activity: string) => void;
  onResult?: (result: ResearchResult) => void;
};

export function ResearchPanel({ config, connected, initialQuestion = "", onContinue, onActivityChange, onResult }: ResearchPanelProps) {
  const [question, setQuestion] = useState(initialQuestion);
  const [mode, setMode] = useState<"normal" | "deep">("normal");
  const [state, setState] = useState("Hazır");
  const [stage, setStage] = useState("queued");
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => {
    if (progressTimer.current) clearInterval(progressTimer.current);
    onActivityChange?.("");
  }, [onActivityChange]);
  const [result, setResult] = useState<ResearchResult | null>(null);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || state === "Araştırılıyor") return;
    setState("Araştırılıyor");
    setError("");
    setResult(null);
    setStage("queued");
    onActivityChange?.("Researching");
    const requestId = crypto.randomUUID();
    progressTimer.current = setInterval(() => { void getResearchProgress(config, requestId).then((value) => setStage(value.state)).catch(() => undefined); }, 900);
    try {
      const completed = await runResearch(config, question, mode, requestId);
      setResult(completed);
      onResult?.(completed);
      setStage("completed");
      setState("Tamamlandı");
    } catch (value) {
      setError(errorText(value));
      setState("Başarısız");
    } finally {
      if (progressTimer.current) clearInterval(progressTimer.current);
      onActivityChange?.("");
    }
  }

  return (
    <div className="absolute-panel">
      <PanelIntro eyebrow="RESEARCH ENGINE" title="Kaynak destekli araştırma">
        Dış kanıt gerektiren bir soru gir. Kaynak çıkarımları, model sentezi ve eksik kanıt birbirinden ayrı tutulur.
      </PanelIntro>
      <ConnectionGate connected={connected} />
      <form className="absolute-card research-form" onSubmit={(event) => void submit(event)}>
        <textarea aria-label="Araştırma sorusu" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Araştırmak istediğin soruyu yaz…" rows={3} />
        <div className="field-row">
          <select value={mode} onChange={(event) => setMode(event.target.value as "normal" | "deep")} aria-label="Araştırma modu">
            <option value="normal">NORMAL</option>
            <option value="deep">DEEP</option>
          </select>
          <button type="submit" disabled={!connected || !question.trim() || state === "Araştırılıyor"}>Araştırmayı başlat</button>
          <span className="state-pill">{state}</span>
        </div>
      </form>
      <div className="research-stages" aria-label="Araştırma aşamaları">{["planning", "searching", "reading", "synthesizing", "completed"].map((step, i) => <span key={step} className={["planning", "searching", "reading", "synthesizing", "completed"].indexOf(stage) >= i ? "active" : ""}>{["PLAN", "SEARCH", "READ", "SYNTHESIZE", "COMPLETE"][i]}</span>)}</div>
      {state === "Araştırılıyor" && <div className="inline-actions"><Presence compact state="thinking" /><span className="state-pill">CORE / {stage.toUpperCase()}</span></div>}
      {error && <p className="panel-error" role="alert">{error}</p>}
      {result && (
        <section className="absolute-card research-results product-research-result">
          <div className="research-product-hero">
            <div className="research-stage-mark"><Presence state="idle" /><span>EVIDENCE STAGE</span></div>
            <div><p className="eyebrow">RESEARCH SPOTLIGHT</p><h3>{result.question}</h3><p>{result.findings[0]?.finding || "Kaynak sentezi tamamlandı."}</p><div className="inline-actions">{onContinue && <button className="secondary-button" type="button" onClick={() => onContinue(`${result.question}\n\nBu araştırmayı karar odaklı bir sonraki adıma dönüştür.`)}>AKASHI ile devam et ↗</button>}<span className="state-pill">{result.sources.length} SOURCE</span></div></div>
          </div>
          <div className="card-heading"><strong>{result.sources.length} kaynak</strong><span>{result.provider.toUpperCase()}</span></div>
          <p className="list-meta">{result.synthesis_status === "completed" ? "MODEL SYNTHESIS · KAYNAK DESTEKLİ" : "SOURCE EXTRACTS · MODEL SENTEZİ YOK"}</p>
          <Markdown>{result.summary}</Markdown>
          <div className="panel-list">
            {result.sources.map((source, index) => (
              <article className="list-item" key={source.url}>
                <div className="list-meta"><span>{source.provider.toUpperCase()}</span><span className="source-number">{index + 1}</span></div>
                <strong>{source.title}</strong>
                <p>{source.snippet || "Özet sağlanmadı; kaynağı doğrudan doğrula."}</p>
                <a href={source.url} target="_blank" rel="noreferrer" onClick={(event) => {
                  if (isDesktopRuntime()) {
                    event.preventDefault();
                    void window.akashiDesktop?.shell.openExternal(source.url);
                  }
                }}>Kaynağı aç</a>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

export function TasksPanel({ config, connected }: PanelProps) {
  const [items, setItems] = useState<AkashiTask[]>([]);
  const [title, setTitle] = useState("");
  const [tool, setTool] = useState("research.web");
  const [argumentsText, setArgumentsText] = useState('{"question":"","mode":"normal"}');
  const [busy, setBusy] = useState(false);
  const [approved, setApproved] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!connected) return;
    try { setItems(await listTasks(config)); } catch (value) { setError(errorText(value)); }
  }, [config, connected]);

  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    const timer = window.setInterval(() => void load(), 3000);
    return () => { window.clearTimeout(initial); window.clearInterval(timer); };
  }, [load]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const parsed = JSON.parse(argumentsText) as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Argümanlar bir JSON nesnesi olmalı.");
      await createTask(config, {
        title: title || `${tool} görevi`,
        approved,
        steps: [{ tool, arguments: parsed as Record<string, unknown> }],
      });
      setTitle("");
      await load();
    } catch (value) {
      setError(errorText(value));
    } finally { setBusy(false); }
  }

  return (
    <div className="absolute-panel">
      <PanelIntro eyebrow="AGENT TASKS" title="Kontrollü görev yürütme">
        Her adım kayıtlı bir aracı çağırır. Değişiklik yapan araçlar açık onay bekler; sınırsız otonom komut yürütülmez.
      </PanelIntro>
      <ConnectionGate connected={connected} />
      <div className="panel-grid two-column">
        <form className="absolute-card panel-form" onSubmit={(event) => void submit(event)}>
          <label htmlFor="task-title">Görev adı</label>
          <input id="task-title" value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Kaynak araştırması" />
          <label htmlFor="task-tool">Araç</label>
          <select id="task-tool" value={tool} onChange={(event) => {
            const next = event.target.value; setTool(next); setApproved(false);
            setArgumentsText(JSON.stringify(next === "research.web" ? { question: "", mode: "normal" } : next === "memory.search" ? { query: "" } : next === "memory.create" ? { content: "", category: "context" } : next === "files.read" ? { file_id: "" } : next === "devices.status" ? {} : { device_id: "", action: "get_system_status", arguments: {} }, null, 2));
          }}>
            <option value="research.web">research.web</option>
            <option value="memory.search">memory.search</option>
            <option value="memory.create">memory.create</option>
            <option value="files.read">files.read</option>
            <option value="devices.status">devices.status</option>
            <option value="devices.action">devices.action</option>
          </select>
          <ToolFields tool={tool} text={argumentsText} onChange={setArgumentsText} />
          <details><summary>Gelişmiş / JSON argümanları</summary><textarea aria-label="Görev JSON argümanları" value={argumentsText} onChange={(event) => setArgumentsText(event.target.value)} rows={6} spellCheck={false} /></details>
          <label className="check-line"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> Bu görevdeki CONFIRM işlemlerini onaylıyorum</label>
          <button type="submit" disabled={!connected || busy}>{busy ? "Kuyruğa alınıyor…" : "Görevi kuyruğa al"}</button>
        </form>
        <section className="absolute-card">
          <div className="card-heading"><strong>Görev akışı</strong><button className="text-button" type="button" onClick={() => void load()}>Yenile</button></div>
          <div className="panel-list">
            {items.length === 0 && <p className="empty-state">Henüz görev yok.</p>}
            {items.map((item) => (
              <article className="list-item" key={item.id}>
                <div className="list-meta"><span>{item.status.toUpperCase()}</span><span>{item.steps.filter((step) => step.status === "completed").length} / {item.steps.length} ADIM</span></div>
                <strong>{item.title}</strong>
                <ol className="step-list">{item.steps.map((step) => <li key={step.id} data-state={step.status}><strong>{step.tool}</strong><small>{step.status.toUpperCase()} · {step.risk.toUpperCase()}</small>{step.error && <p className="inline-error">{step.error}</p>}{step.result != null && <ToolResult value={step.result} />}</li>)}</ol>
                {item.error && <p className="inline-error">{item.error}</p>}
                <div className="inline-actions">
                  {item.status === "waiting_for_approval" && <button className="text-button" onClick={() => void approveTask(config, item.id).then(load).catch((value) => setError(errorText(value)))}>Onayla</button>}
                  {["queued", "planning", "running", "waiting_for_approval"].includes(item.status) && <button className="text-button danger" onClick={() => void cancelTask(config, item.id).then(load).catch((value) => setError(errorText(value)))}>İptal</button>}
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
      {error && <p className="panel-error">{error}</p>}
    </div>
  );
}

export function FilesPanel({
  config,
  connected,
  onUseInChat,
}: PanelProps & { onUseInChat: (file: UploadedFile) => void }) {
  const [items, setItems] = useState<UploadedFile[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const load = useCallback(async () => {
    if (!connected) return;
    try { setItems(await listFiles(config)); } catch (value) { setError(errorText(value)); }
  }, [config, connected]);
  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initial);
  }, [load]);

  async function selected(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setError("");
    try { await uploadFile(config, file); await load(); } catch (value) { setError(errorText(value)); }
    finally { setBusy(false); if (inputRef.current) inputRef.current.value = ""; }
  }

  return (
    <div className="absolute-panel">
      <PanelIntro eyebrow="FILE INTELLIGENCE" title="Doğrulanmış dosya bağlamı">
        Metin, Markdown, JSON, CSV ve kaynak kodu güvenli kimliklerle yüklenir. Sunucu istemciden dosya sistemi yolu kabul etmez.
      </PanelIntro>
      <ConnectionGate connected={connected} />
      <section className="absolute-card">
        <div className="card-heading">
          <strong>Dosyalar</strong>
          <label className={`upload-control ${busy ? "disabled" : ""}`}>Dosya yükle<input ref={inputRef} type="file" onChange={(event) => void selected(event)} disabled={!connected || busy} /></label>
        </div>
        <div className="panel-list">
          {items.length === 0 && <p className="empty-state">Henüz analiz edilebilir dosya yüklenmedi.</p>}
          {items.map((item) => (
            <article className="list-item file-item" key={item.id}>
              <div><strong>{item.name}</strong><p>{(item.size / 1024).toFixed(1)} KB · {item.text_length.toLocaleString()} karakter</p></div>
              <div className="inline-actions">
                <button className="text-button" onClick={() => onUseInChat(item)}>Sohbette kullan</button>
                <button className="text-button danger" onClick={() => void deleteFile(config, item.id).then(load).catch((value) => setError(errorText(value)))}>Sil</button>
              </div>
            </article>
          ))}
        </div>
      </section>
      {error && <p className="panel-error">{error}</p>}
    </div>
  );
}

const deviceActions = [
  "get_system_status",
  "list_processes",
  "application_status",
  "list_directory",
  "find_file",
  "file_metadata",
  "launch_application",
  "open_project",
  "reveal_file",
  "take_screenshot",
  "capture_camera_frame",
  "run_project_script",
];

export function DevicesPanel({ config, connected }: PanelProps) {
  const [devices, setDevices] = useState<PairedDevice[]>([]);
  const [deviceId, setDeviceId] = useState("");
  const [action, setAction] = useState("get_system_status");
  const [actionArgs, setActionArgs] = useState<Record<string, unknown>>({});
  const [dispatching, setDispatching] = useState(false);
  const [approved, setApproved] = useState(false);
  const [pairing, setPairing] = useState<{ code: string; expires_at: string } | null>(null);
  const [lastAction, setLastAction] = useState<DeviceAction | null>(null);
  const [localAgent, setLocalAgent] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (!connected) return;
    try {
      const next = await listDevices(config);
      setDevices(next);
      setDeviceId((current) => current || next.find((item) => !item.revoked)?.id || "");
    } catch (value) { setError(errorText(value)); }
  }, [config, connected]);
  useEffect(() => {
    const initial = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(initial);
  }, [load]);
  useEffect(() => {
    if (!lastAction || !["queued", "dispatched"].includes(lastAction.status)) return;
    const timer = window.setInterval(() => void getDeviceAction(config, lastAction.id).then(setLastAction).catch((value) => setError(errorText(value))), 2000);
    return () => window.clearInterval(timer);
  }, [config, lastAction]);

  const selectedDevice = useMemo(() => devices.find((item) => item.id === deviceId), [devices, deviceId]);
  const requiresApproval = !["get_system_status", "list_processes", "application_status", "list_directory", "find_file", "file_metadata"].includes(action);

  async function dispatch(event: FormEvent) {
    event.preventDefault();
    if (dispatching) return;
    setDispatching(true);
    setError("");
    try {
      const queued = await queueDeviceAction(config, deviceId, action, actionArgs, approved);
      setLastAction(queued);
    } catch (value) { setError(errorText(value)); }
    finally { setDispatching(false); }
  }

  return (
    <div className="absolute-panel">
      <PanelIntro eyebrow="PAIRED DEVICES" title="AKASHI cihaz köprüsü">
        Mobil ve Web istemcileri yalnızca Core ile konuşur. Windows Agent dış ağa açılmaz; onaylı, yapılandırılmış eylemleri Core üzerinden alır.
      </PanelIntro>
      <ConnectionGate connected={connected} />
      <div className="device-strip">
        {devices.length === 0 && <div className="device-card muted"><strong>DESKTOP</strong><span>Eşleşmiş cihaz yok</span></div>}
        {devices.map((device) => <button type="button" className={`device-card ${device.id === deviceId ? "selected" : ""}`} onClick={() => setDeviceId(device.id)} key={device.id}><span className={`status-dot ${device.online ? "online" : "offline"}`} /><strong>{device.name}</strong><small>{device.online ? "ONLINE" : "OFFLINE"}</small></button>)}
      </div>
      {selectedDevice && <div className="absolute-card" style={{ marginBottom: 24 }}><div className="card-heading"><strong>{selectedDevice.name}</strong><button className="text-button danger" disabled={selectedDevice.revoked} onClick={() => { if (window.confirm("Bu cihazın erişimini iptal et?")) void revokeDevice(config, selectedDevice.id).then(load).catch((value) => setError(errorText(value))); }}>Eşleşmeyi kaldır</button></div><div className="capability-tags">{selectedDevice.capabilities.map((item) => <span key={item}>{item.toUpperCase()}</span>)}</div><p className="list-meta">SON GÖRÜLME · {new Date(selectedDevice.last_seen).toLocaleString()}{selectedDevice.revoked ? " · REVOKED" : ""}</p></div>}
      <div className="panel-grid two-column">
        <section className="absolute-card">
          <div className="card-heading"><strong>Cihaz eşleştirme</strong><button className="text-button" type="button" disabled={!connected} onClick={() => void createPairingCode(config).then(setPairing).catch((value) => setError(errorText(value)))}>Kod oluştur</button></div>
          {pairing ? <div className="pairing-code"><strong>{pairing.code}</strong><span>Agent&apos;ta bu tek kullanımlık kodu gir. {new Date(pairing.expires_at).toLocaleTimeString()} tarihinde biter.</span></div> : <p className="empty-state">Kod yalnızca eşleştirme başlatıldığında üretilir.</p>}
          {isDesktopRuntime() && <button className="secondary-button" type="button" onClick={() => void window.akashiDesktop?.shell.showDataFolder()}>Desktop veri klasörünü aç</button>}
          {isDesktopRuntime() && (
            <div className="local-agent-block">
              <button className="secondary-button" type="button" onClick={() => void window.akashiDesktop?.agent.status().then(setLocalAgent).catch((value) => setError(errorText(value)))}>Yerel agent durumunu denetle</button>
              <button className="secondary-button" type="button" onClick={() => void window.akashiDesktop?.agent.execute("get_system_status", {}, false).then(setLocalAgent).catch((value) => setError(errorText(value)))}>Bu PC&apos;nin durumunu al</button>
              {localAgent && <ToolResult value={localAgent} />}
            </div>
          )}
        </section>
        <form className="absolute-card panel-form" onSubmit={(event) => void dispatch(event)}>
          <div className="card-heading"><strong>Yapılandırılmış eylem</strong><span>{selectedDevice?.online ? "DEVICE ONLINE" : "REMOTE DESKTOP REQUIRED"}</span></div>
          <select aria-label="Cihaz eylemi" value={action} onChange={(event) => { setAction(event.target.value); setActionArgs({}); setApproved(false); }}>
            {deviceActions.filter((item) => !selectedDevice || selectedDevice.capabilities.includes(item)).map((item) => <option key={item} value={item}>{item}</option>)}
          </select>
          <ActionFields action={action} value={actionArgs} onChange={setActionArgs} />
          {requiresApproval && <label className="check-line"><input type="checkbox" checked={approved} onChange={(event) => setApproved(event.target.checked)} /> Bu CONFIRM işlemini açıkça onaylıyorum</label>}
          <button type="submit" disabled={!connected || !selectedDevice?.online || dispatching || (requiresApproval && !approved)}>Eylemi gönder</button>
          {lastAction && <div className="action-result"><div className="list-meta"><span>{lastAction.action}</span><span>{lastAction.status}</span></div><button className="text-button" type="button" onClick={() => void getDeviceAction(config, lastAction.id).then(setLastAction).catch((value) => setError(errorText(value)))}>Sonucu yenile</button>{lastAction.result ? <ToolResult value={lastAction.result} /> : null}{lastAction.error && <p className="inline-error">{lastAction.error}</p>}</div>}
        </form>
      </div>
      {error && <p className="panel-error">{error}</p>}
    </div>
  );
}
function ToolFields({ tool, text, onChange }: { tool: string; text: string; onChange: (value: string) => void }) {
  let args: Record<string, unknown>;
  try { args = JSON.parse(text); if (!args || Array.isArray(args) || typeof args !== "object") return null; } catch { return null; }
  const fields = tool === "research.web" ? ["question"] : tool === "memory.search" ? ["query"] : tool === "memory.create" ? ["content", "category"] : tool === "files.read" ? ["file_id"] : tool === "devices.action" ? ["device_id", "action"] : [];
  const labels: Record<string, string> = { question: "Araştırma sorusu", query: "Aranacak bilgi", content: "Kalıcı bilgi", category: "Kategori", file_id: "Yüklenen dosya kimliği", device_id: "Cihaz kimliği", action: "Yapılandırılmış eylem" };
  return <>{fields.map((key) => <label key={key}>{labels[key]}<input value={String(args[key] || "")} onChange={(event) => onChange(JSON.stringify({ ...args, [key]: event.target.value }, null, 2))} /></label>)}</>;
}
