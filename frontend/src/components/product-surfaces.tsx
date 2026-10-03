/* eslint-disable @next/next/no-img-element -- authenticated runtime images cannot use the static Next image optimizer */
"use client";

import { useMemo, useState } from "react";

import { MemoryPanel } from "@/components/absolute-panels";
import { CallsPanel } from "@/components/calls-panel";
import { Icon, Presence } from "@/components/identity";
import type {
  AkashiTask,
  ConversationSummary,
  IntelligenceBrief,
  IntelligenceItem,
  MaintenanceItem,
  MemoryEntry,
  SystemHealth,
} from "@/lib/absolute-api";
import type { BackendConfig } from "@/lib/api";
import type {
  ClientKind,
  ClientPresentation,
  ProductMood,
  WorkspaceView,
} from "@/lib/platform";

export type IntelligenceFeed = {
  id: string;
  title: string;
  label: string;
  description: string;
  researchPrompt: string;
};

export const intelligenceFeeds: IntelligenceFeed[] = [
  {
    id: "akashi-watch",
    title: "AKASHI Watch",
    label: "CORE SIGNAL",
    description: "AKASHI'yi anlamlı biçimde geliştirebilecek doğrulanmış araç ve model hareketleri.",
    researchPrompt: "AKASHI için anlamlı olabilecek güncel model, agent, vision, voice, local inference ve ComfyUI gelişmelerini birincil kaynaklarla araştır. Hype ile ölçülebilir faydayı ayır.",
  },
  {
    id: "world",
    title: "World Brief",
    label: "GLOBAL",
    description: "Önemli gelişmeleri kaynak ve etki düzeyiyle tara.",
    researchPrompt: "Bugünün dünyadaki en önemli gelişmelerini güvenilir kaynaklarla araştır. Gürültüyü ele, etkisini ve belirsizlikleri kısa biçimde açıkla.",
  },
  {
    id: "technology",
    title: "Technology / AI",
    label: "SIGNAL",
    description: "AI, çipler, yazılım ve ürün hareketlerini izle.",
    researchPrompt: "Bugünün yapay zeka, çip, yazılım ve teknoloji ürünleri gelişmelerini araştır. Somut duyuruları söylentilerden ayır.",
  },
  {
    id: "screen",
    title: "Film / Series",
    label: "CULTURE",
    description: "Yeni yapımlar, gösterim tarihleri ve güçlü öneriler.",
    researchPrompt: "Film ve dizi dünyasındaki güncel önemli gelişmeleri araştır. Çıkış tarihlerini ve kaynak güvenilirliğini doğrula.",
  },
  {
    id: "gaming",
    title: "Gaming",
    label: "PLAY",
    description: "Oyun, donanım ve stüdyo gündemini derle.",
    researchPrompt: "Oyun dünyasındaki güncel önemli gelişmeleri araştır. Resmi duyurularla söylentileri açıkça ayır.",
  },
  {
    id: "economy",
    title: "Economy / Policy",
    label: "CONTEXT",
    description: "Ekonomi ve kamu kararlarını etkileriyle incele.",
    researchPrompt: "Bugünün ekonomi ve kamu politikası gelişmelerini güvenilir kaynaklarla araştır. Kararları, olası etkileri ve belirsizlikleri ayır.",
  },
  {
    id: "products",
    title: "Product Watch",
    label: "WATCHLIST",
    description: "Takip edilen ürünleri fiyat, çıkış ve değişim açısından izle.",
    researchPrompt: "Önemli yeni teknoloji ürünlerini ve özel sürümleri araştır. Fiyat, bulunabilirlik ve önceki nesle göre anlamlı değişimleri karşılaştır.",
  },
];

type FeedSurfaceProps = {
  pinnedFeedIds: Set<string>;
  connected: boolean;
  compact?: boolean;
  onOpen: (feed: IntelligenceFeed) => void;
  onTogglePin: (feed: IntelligenceFeed) => void;
};

export function FeedSurface({
  pinnedFeedIds,
  connected,
  compact = false,
  onOpen,
  onTogglePin,
}: FeedSurfaceProps) {
  const ordered = useMemo(
    () => [...intelligenceFeeds].sort((left, right) => Number(pinnedFeedIds.has(right.id)) - Number(pinnedFeedIds.has(left.id))),
    [pinnedFeedIds],
  );
  return (
    <div className={`feed-grid ${compact ? "compact" : ""}`}>
      {ordered.map((feed) => {
        const pinned = pinnedFeedIds.has(feed.id);
        return (
          <article className="feed-card" data-pinned={pinned} key={feed.id}>
            <button className="feed-open" type="button" onClick={() => onOpen(feed)}>
              <span className="feed-label">{feed.label}</span>
              <strong>{feed.title}</strong>
              {!compact && <p>{feed.description}</p>}
              <span className="feed-action">Kaynakları tara <span aria-hidden="true">↗</span></span>
            </button>
            <button
              className="feed-pin"
              type="button"
              disabled={!connected}
              aria-pressed={pinned}
              aria-label={`${feed.title} akışını ${pinned ? "sabitlemeden kaldır" : "sabitle"}`}
              onClick={() => onTogglePin(feed)}
            >
              {pinned ? "PINNED" : "PIN"}
            </button>
          </article>
        );
      })}
    </div>
  );
}

type DashboardProps = {
  clientKind: ClientKind;
  mood: ProductMood;
  connected: boolean;
  connectionLabel: string;
  systemHealth: SystemHealth | null;
  conversations: ConversationSummary[];
  tasks: AkashiTask[];
  recentImages: string[];
  pinnedFeedIds: Set<string>;
  intelligence: IntelligenceItem[];
  latestBrief: IntelligenceBrief | null;
  intelligenceBusy: boolean;
  onNavigate: (view: WorkspaceView) => void;
  onResume: (conversation: ConversationSummary) => void;
  onPrompt: (prompt: string) => void;
  onOpenFeed: (feed: IntelligenceFeed) => void;
  onTogglePin: (feed: IntelligenceFeed) => void;
  onRefreshIntelligence: () => void;
  onResearchIntelligence: (item: IntelligenceItem) => void;
  onIntelligenceStatus: (item: IntelligenceItem, status: IntelligenceItem["status"]) => void;
};

export function HomeDashboard(props: DashboardProps) {
  const latestConversation = props.conversations[0];
  const activeTask = props.tasks.find((task) => ["queued", "running", "waiting_confirmation"].includes(task.status));
  const desktop = props.systemHealth?.desktop_agent;
  const date = new Intl.DateTimeFormat("tr-TR", { weekday: "long", day: "numeric", month: "long" }).format(new Date());
  return (
    <div className="product-surface home-dashboard">
      <section className="command-hero">
        <div className="command-copy">
          <p className="eyebrow">AKASHI / {props.clientKind.toUpperCase()} / {date.toUpperCase()}</p>
          <h3>Kontrol sende.<br /><span>Gürültü dışarıda.</span></h3>
          <p>Konuş, üret veya bir konuyu kanıtlarla çöz. AKASHI hazır olan sistemi gösterir; olmayanı uydurmaz.</p>
          <div className="hero-actions">
            <button type="button" onClick={() => props.onNavigate("chat")}><Icon name="chat" /> AKASHI&apos;ye yaz</button>
            <button type="button" onClick={() => props.onNavigate("create")}><Icon name="create" /> Görsel üret</button>
          </div>
        </div>
        <div className="command-presence">
          <Presence state={props.mood === "hardcarry" ? "thinking" : "idle"} />
          <span>{props.mood === "hardcarry" ? "HARDCARRY" : props.mood === "best" ? "BEST OF BEST" : "CALM"}</span>
          <strong>{props.connectionLabel}</strong>
        </div>
      </section>

      <section className="dashboard-grid">
        <article className="dashboard-card briefing-card">
          <div className="card-kicker"><span>DAILY INTELLIGENCE</span><span>{props.latestBrief ? `${props.latestBrief.item_count} SIGNAL` : "ON DEMAND"}</span></div>
          <h4>{props.latestBrief?.item_count ? "Doğrulanmış sinyal hazır." : "Bugünün sinyalini çıkar."}</h4>
          <p>{props.latestBrief?.item_count ? `${Object.keys(props.latestBrief.groups).length} kategoride gerçek kaynak kaydı.` : "Kaynak taraması çalıştırılmadan haber özeti gösterilmez."}</p>
          <button type="button" disabled={props.intelligenceBusy || !props.connected} onClick={props.onRefreshIntelligence}>{props.intelligenceBusy ? "Kaynaklar taranıyor…" : "Keşif döngüsünü çalıştır ↗"}</button>
        </article>

        <article className="dashboard-card continue-card">
          <div className="card-kicker"><span>CONTINUE</span><span>{latestConversation ? `${latestConversation.message_count} MSG` : "NEW"}</span></div>
          {latestConversation ? <>
            <h4>{latestConversation.title || "İsimsiz oturum"}</h4>
            <p>{latestConversation.excerpt}</p>
            <button type="button" onClick={() => props.onResume(latestConversation)}>Oturumu sürdür ↗</button>
          </> : <>
            <h4>İlk oturumu başlat.</h4>
            <p>Karar, plan, analiz veya doğrudan bir soru.</p>
            <button type="button" onClick={() => props.onPrompt("Bugün çözmem gereken en önemli konuyu netleştir.")}>Yeni oturum ↗</button>
          </>}
        </article>

        <article className="dashboard-card activity-card">
          <div className="card-kicker"><span>ACTIVE WORK</span><span>{activeTask ? activeTask.status.toUpperCase() : "CLEAR"}</span></div>
          {activeTask ? <>
            <h4>{activeTask.title}</h4>
            <p>{activeTask.steps.filter((step) => step.status === "completed").length} / {activeTask.steps.length} adım tamamlandı.</p>
            <button type="button" onClick={() => props.onNavigate("tasks")}>Detayı aç ↗</button>
          </> : <>
            <h4>Aktif görev yok.</h4>
            <p>Sistem yeni bir talimat için hazır.</p>
            <button type="button" onClick={() => props.onNavigate("chat")}>AKASHI&apos;yi aç ↗</button>
          </>}
        </article>

        <article className="dashboard-card device-status-card">
          <div className="card-kicker"><span>LINKED DESKTOP</span><span>{desktop?.status?.replaceAll("_", " ").toUpperCase() ?? "UNKNOWN"}</span></div>
          <h4>{desktop?.online ? `${desktop.online} desktop çevrimiçi.` : "Desktop bağlı değil."}</h4>
          <p>{props.clientKind === "desktop" ? "Yerel gövde yetenekleri Devices alanında." : "Mobil deneyim desktop bağlantısı olmadan da tam işlevlidir."}</p>
          {props.clientKind !== "web" && <button type="button" onClick={() => props.onNavigate("devices")}>Bağlantıyı incele ↗</button>}
        </article>
      </section>

      {props.recentImages.length > 0 && (
        <section className="recent-creation-strip">
          <div><p className="eyebrow">RECENT CREATION</p><h4>Son görsel çalışma</h4></div>
          <img src={props.recentImages[0]} alt="Son AKASHI görsel çıktısı" />
          <button type="button" onClick={() => props.onNavigate("create")}>Create&apos;te aç ↗</button>
        </section>
      )}

      <section className="feed-section">
        <div className="section-heading"><div><p className="eyebrow">PINNED INTELLIGENCE</p><h4>Yaşayan akışlar</h4></div><span>Kaynaklar yalnızca açıldığında taranır.</span></div>
        <FeedSurface
          compact
          connected={props.connected}
          pinnedFeedIds={props.pinnedFeedIds}
          onOpen={props.onOpenFeed}
          onTogglePin={props.onTogglePin}
        />
      </section>

      <section className="intelligence-watch" aria-label="AKASHI Watch">
        <div className="section-heading"><div><p className="eyebrow">MISS MINUTES / AKASHI WATCH</p><h4>Üretime dokunmayan gelişim radarı</h4></div><span>{props.intelligence.length} kayıt</span></div>
        {props.intelligence.length === 0 ? <div className="premium-empty"><Presence compact /><strong>Doğrulanmış gelişme yok.</strong><p>Keşif çalıştırılmadan içerik üretilmez.</p></div> : <div className="intelligence-list">{props.intelligence.slice(0, 4).map((item) => <article key={item.id}>
          <div className="list-meta"><span>{item.category.toUpperCase()}</span><span>{item.priority.replaceAll("_", " ").toUpperCase()}</span></div>
          <strong>{item.title}</strong>
          <p>{item.why_it_matters}</p>
          <div className="intelligence-actions">
            <span>{item.affected_subsystem.replaceAll("_", " ").toUpperCase()} · {item.confidence.toUpperCase()}</span>
            <button type="button" onClick={() => props.onIntelligenceStatus(item, "dismissed")}>DISMISS</button>
            <button type="button" onClick={() => props.onIntelligenceStatus(item, "watching")}>WATCH</button>
            <button type="button" onClick={() => props.onResearchIntelligence(item)}>RESEARCH MORE</button>
            <button type="button" onClick={() => props.onIntelligenceStatus(item, "approved_for_test")}>APPROVE TEST</button>
            <button type="button" onClick={() => props.onIntelligenceStatus(item, "approved_for_maintenance")}>ADD TO MAINTENANCE</button>
          </div>
        </article>)}</div>}
      </section>
    </div>
  );
}

type CreateStudioProps = {
  mode: "fast" | "quality" | "edit";
  editProfile: "fast" | "quality";
  editStage: "uploading" | "preparing" | "editing" | "finalizing" | null;
  selectedImagePreview: string | null;
  recentImages: string[];
  busy: boolean;
  statusMessage?: { content: string; meta?: string };
  onMode: (mode: "fast" | "quality" | "edit") => void;
  onEditProfile: (profile: "fast" | "quality") => void;
  onPrompt: (prompt: string) => void;
  onChooseImage: () => void;
};

export function CreateStudio({ mode, editProfile, editStage, selectedImagePreview, recentImages, busy, statusMessage, onMode, onEditProfile, onPrompt, onChooseImage }: CreateStudioProps) {
  const stageImage = selectedImagePreview || recentImages[0];
  const editStageLabel = editStage ? {
    uploading: "UPLOADING",
    preparing: "PREPARING",
    editing: "EDITING",
    finalizing: "FINALIZING",
  }[editStage] : null;
  const templates = [
    "Titanium ve siyah yüzeylerde premium ürün çekimi",
    "Sinematik gece şehri, kontrollü kırmızı vurgular",
    "Minimal beyaz stüdyoda mühendislik prototipi",
  ];
  return (
    <div className="product-surface create-studio">
      <header className="product-intro"><p className="eyebrow">CREATE / IMAGE ENGINE</p><h3>Fikri yüzeye çıkar.</h3><p>FAST taslak için. QUALITY ayrıntı için. EDIT mevcut görüntüyü kontrollü biçimde değiştirmek için.</p></header>
      <div className="create-layout">
        <section className="creation-stage">
          {stageImage ? <img src={stageImage} alt={selectedImagePreview ? "Düzenlenecek görsel" : "Son üretilen görsel"} /> : <div className="empty-stage"><Presence /><span>IMAGE STAGE</span><p>Bir mod seç ve kompozisyonu tarif et.</p></div>}
          <div className="stage-status"><span>{mode === "edit" ? `EDIT ${editProfile.toUpperCase()}` : mode.toUpperCase()}</span><strong>{busy ? editStageLabel || "PROCESSING" : "READY"}</strong></div>
        </section>
        <aside className="create-controls">
          {(["fast", "quality", "edit"] as const).map((item) => <button key={item} type="button" disabled={busy} className={mode === item ? "active" : ""} onClick={() => onMode(item)}><span>{item === "fast" ? "01" : item === "quality" ? "02" : "03"}</span><strong>{item.toUpperCase()}</strong><small>{item === "fast" ? "Hızlı kompozisyon" : item === "quality" ? "Yüksek ayrıntı" : "Görselden görsele"}</small></button>)}
          {mode === "edit" && <div className="edit-profile-control" aria-label="Düzenleme kalitesi">
            <span>EDIT PROFILE</span>
            <div>{(["fast", "quality"] as const).map((profile) => <button type="button" disabled={busy} aria-pressed={editProfile === profile} className={editProfile === profile ? "active" : ""} onClick={() => onEditProfile(profile)} key={profile}>{profile.toUpperCase()}</button>)}</div>
            <small>{editProfile === "fast" ? "8 adım · renk, ışık ve atmosfer" : "40 adım · kaldırma ve karmaşık düzenleme"}</small>
          </div>}
          {mode === "edit" && <button className="image-picker-cta" type="button" disabled={busy} onClick={onChooseImage}><Icon name="image" /> Fotoğraflardan seç</button>}
        </aside>
      </div>
      <section className="prompt-library"><div className="section-heading"><div><p className="eyebrow">PROMPT STARTERS</p><h4>Başlangıç kompozisyonları</h4></div></div><div>{templates.map((template) => <button type="button" key={template} onClick={() => onPrompt(template)}>{template}<span>↗</span></button>)}</div></section>
      {statusMessage && <div className="create-status-message" role="status"><span>{statusMessage.meta || "CREATE"}</span><p>{statusMessage.content}</p></div>}
      {recentImages.length > 0 && <section className="creation-history"><div className="section-heading"><div><p className="eyebrow">THIS SESSION</p><h4>Son çıktılar</h4></div><span>{recentImages.length} çalışma</span></div><div>{recentImages.slice(0, 6).map((image, index) => <img src={image} alt={`AKASHI görsel çıktısı ${index + 1}`} key={`${image}-${index}`} />)}</div></section>}
    </div>
  );
}

type MemoryHubProps = {
  config: BackendConfig;
  connected: boolean;
  conversations: ConversationSummary[];
  pinnedFeeds: MemoryEntry[];
  pinnedFeedIds: Set<string>;
  onResume: (conversation: ConversationSummary) => void;
  onOpenFeed: (feed: IntelligenceFeed) => void;
  onTogglePin: (feed: IntelligenceFeed) => void;
};

export function MemoryHub(props: MemoryHubProps) {
  const [section, setSection] = useState<"conversations" | "saved" | "feeds" | "threads">("conversations");
  const ongoing = props.conversations.filter((item) => item.message_count >= 4);
  return (
    <div className="memory-hub">
      <header className="product-intro"><p className="eyebrow">MEMORY / CONTINUITY</p><h3>Bağlam, kontrol altında.</h3><p>Oturumlar, kalıcı bilgiler ve takip edilen konular birbirine karıştırılmadan yönetilir.</p></header>
      <nav className="product-tabs" aria-label="Memory bölümleri">
        {(["conversations", "saved", "feeds", "threads"] as const).map((item) => <button type="button" className={section === item ? "active" : ""} onClick={() => setSection(item)} key={item}>{item === "conversations" ? "Conversations" : item === "saved" ? "Saved Memory" : item === "feeds" ? "Pinned Feeds" : "Ongoing Threads"}</button>)}
      </nav>
      {section === "saved" ? <MemoryPanel config={props.config} connected={props.connected} /> : section === "feeds" ? <section className="product-section"><div className="section-heading"><div><p className="eyebrow">INTELLIGENCE STREAMS</p><h4>{props.pinnedFeeds.length} sabit akış</h4></div></div><FeedSurface connected={props.connected} pinnedFeedIds={props.pinnedFeedIds} onOpen={props.onOpenFeed} onTogglePin={props.onTogglePin} /></section> : <section className="conversation-library">
        {(section === "threads" ? ongoing : props.conversations).length === 0 ? <div className="premium-empty"><Presence compact /><strong>{section === "threads" ? "Devam eden tematik oturum yok." : "Henüz özel oturum yok."}</strong><p>AKASHI yalnızca gerçek konuşmaları burada gösterir.</p></div> : (section === "threads" ? ongoing : props.conversations).map((conversation) => <button type="button" key={conversation.session_id} onClick={() => props.onResume(conversation)}><span className="conversation-time">{conversation.last_updated ? new Date(conversation.last_updated).toLocaleDateString() : "—"}</span><strong>{conversation.title || "İsimsiz oturum"}</strong><p>{conversation.excerpt}</p><small>{conversation.message_count} kayıtlı mesaj <span>Devam et ↗</span></small></button>)}
      </section>}
    </div>
  );
}

type MorePanelProps = {
  config: BackendConfig;
  presentation: ClientPresentation;
  moodPreference: "auto" | ProductMood;
  connected: boolean;
  systemHealth: SystemHealth | null;
  maintenance?: MaintenanceItem[];
  onMoodPreference: (value: "auto" | ProductMood) => void;
  onNavigate: (view: WorkspaceView) => void;
  onSettings: () => void;
};

export function MorePanel({ config, presentation, moodPreference, connected, systemHealth, maintenance = [], onMoodPreference, onNavigate, onSettings }: MorePanelProps) {
  const destinations: Array<{ view: WorkspaceView; title: string; detail: string; icon: "research" | "files" | "devices" | "tasks" }> = [
    { view: "research", title: "Research", detail: "Dış kanıt ve kaynak sentezi", icon: "research" },
    { view: "files", title: "Files", detail: "Belge bağlamı ve yüklemeler", icon: "files" },
    { view: "devices", title: "Linked Devices", detail: "Eşleşmiş desktop durumu", icon: "devices" },
    { view: "tasks", title: "Tasks", detail: "Gerçek yürütme adımları", icon: "tasks" },
  ];
  return <div className="product-surface more-panel">
    <header className="product-intro"><p className="eyebrow">PROFILE / SYSTEM</p><h3>AKASHI, bu cihazda.</h3><p>{presentation.label} istemcisi yalnızca bu yüzeye uygun yetenekleri öne çıkarır.</p></header>
    <section className="more-grid">{destinations.filter((item) => presentation.availableWorkspaces.includes(item.view)).map((item) => <button type="button" key={item.view} onClick={() => onNavigate(item.view)}><Icon name={item.icon} /><span><strong>{item.title}</strong><small>{item.detail}</small></span><span>↗</span></button>)}</section>
    <section className="profile-settings-card"><div><p className="eyebrow">VISUAL STATE</p><h4>Controlled intensity</h4><p>AUTO, işlem yüküne göre CALM / HARDCARRY / BEST OF BEST arasında geçer.</p></div><select aria-label="AKASHI görsel durumu" value={moodPreference} onChange={(event) => onMoodPreference(event.target.value as "auto" | ProductMood)}><option value="auto">AUTO</option><option value="calm">CALM</option><option value="hardcarry">HARDCARRY</option><option value="best">BEST OF BEST</option></select></section>
    <section className="profile-settings-card"><div><p className="eyebrow">CONNECTION</p><h4>{connected ? "Core connected" : "Core offline"}</h4><p>Model ve servis anahtarları istemcide tutulmaz.</p></div><button type="button" onClick={onSettings}>Backend ayarları</button></section>
    <section className="profile-settings-card"><div><p className="eyebrow">MAINTENANCE QUEUE</p><h4>{maintenance.length ? `${maintenance.length} onaylı inceleme` : "Kuyruk boş"}</h4><p>{maintenance[0]?.title || "Miss Minutes üretim kodunu kendiliğinden değiştirmez."}</p></div><span className="state-pill">MANUAL ONLY</span></section>
    <CallsPanel config={config} connected={connected} />
    {presentation.desktopBody !== "hidden" && <section className="linked-body-card"><div><span className={`status-dot ${systemHealth?.desktop_agent.online ? "online" : "offline"}`} /><p className="eyebrow">DESKTOP BODY</p></div><h4>{systemHealth?.desktop_agent.online ? `${systemHealth.desktop_agent.online} cihaz çevrimiçi` : "Bağlı desktop yok"}</h4><p>{presentation.desktopBody === "primary" ? "Yerel eylemler Devices alanında kullanılabilir." : "Desktop güçleri mobil ana deneyimden ayrı ve ikincil tutulur."}</p></section>}
  </div>;
}

type ActivityDrawerProps = {
  open: boolean;
  connected: boolean;
  busy: boolean;
  operation: string;
  voiceState: string;
  tasks: AkashiTask[];
  onClose: () => void;
};

export function ActivityDrawer({ open, connected, busy, operation, voiceState, tasks, onClose }: ActivityDrawerProps) {
  if (!open) return null;
  const active = tasks.filter((task) => ["queued", "running", "waiting_confirmation"].includes(task.status));
  return <aside className="activity-drawer" aria-label="AKASHI aktivitesi">
    <div className="activity-heading"><div><p className="eyebrow">LIVE ACTIVITY</p><h3>{busy ? operation : "System clear"}</h3></div><button type="button" onClick={onClose} aria-label="Aktivite panelini kapat">×</button></div>
    <div className="activity-status-line"><span className={`status-dot ${connected ? "online" : "offline"}`} /><span>CORE</span><strong>{connected ? "CONNECTED" : "OFFLINE"}</strong></div>
    <div className="activity-status-line"><Presence compact state={voiceState} /><span>VOICE</span><strong>{voiceState.toUpperCase()}</strong></div>
    <div className="activity-section"><p className="eyebrow">TASKS</p>{active.length === 0 ? <p className="empty-state">Aktif görev yok.</p> : active.map((task) => <article key={task.id}><strong>{task.title}</strong><span>{task.steps.filter((step) => step.status === "completed").length} / {task.steps.length} adım</span></article>)}</div>
  </aside>;
}
