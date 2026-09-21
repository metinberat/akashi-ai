/* eslint-disable @next/next/no-img-element -- backend-provided authenticated image URL */
"use client";

import { useState } from "react";
import { Icon } from "./identity";
import { Markdown } from "./markdown";
import { publicSourceUrl, type CenterStageEntity } from "@/lib/desktop-stage";
import { observeDesktop } from "@/lib/desktop-activity";

export function DesktopResult({ entity, onPrompt, onClose }: { entity: CenterStageEntity; onPrompt: (prompt: string) => void; onClose: () => void }) {
  const [index, setIndex] = useState(0);
  const [details, setDetails] = useState(false);
  const [error, setError] = useState("");
  const source = entity.sources[index];
  const url = source && publicSourceUrl(source.url);
  const selected = source?.title || entity.title;
  const host = url ? new URL(url).hostname : "AKASHI RESEARCH";
  async function openSource() {
    if (!url) return;
    try {
      const opened = await window.akashiDesktop?.shell.openExternal(url);
      if (!opened) throw new Error("open_failed");
      observeDesktop(`Tarayıcıya gönderildi · ${host}`);
    } catch { setError("Kaynak açılamadı. Bağlantıyı ve masaüstü köprüsünü kontrol et."); }
  }
  return <section className="research-result-card" data-stage={entity.type} aria-label="Araştırma sonucu">
    <header><span><i />{entity.type.toUpperCase()} RESULT</span><div className="result-pagination"><button type="button" aria-label="Önceki kaynak" disabled={index === 0} onClick={() => setIndex(index - 1)}>‹</button><small>{entity.sources.length ? index + 1 : 0} / {entity.sources.length}</small><button type="button" aria-label="Sonraki kaynak" disabled={index >= entity.sources.length - 1} onClick={() => setIndex(index + 1)}>›</button><button type="button" aria-label="Sonucu kapat" onClick={onClose}>×</button></div></header>
    <div className={`research-result-media ${entity.image ? "" : "no-source-image"}`}>
      {entity.image ? <img src={entity.image} alt={entity.title} /> : <><Icon name={entity.type === "video" ? "stream" : "research"} /><span>{host}</span><small>{entity.type === "video" ? "SOURCE PREVIEW · VİDEO KESİTİ YOK" : "DOĞRULANMIŞ GÖRSEL SAĞLANMADI"}</small></>}
    </div>
    <div className="research-result-body"><span className="research-result-badge standalone">{entity.sources.length} SOURCES · {entity.type.toUpperCase()}</span><h2>{selected}</h2><p className="result-topic">{entity.title}</p><div className="research-result-summary"><Markdown>{source?.snippet || entity.subtitle}</Markdown></div>
      {details && <div className="result-evidence"><h3>FINDINGS / SOURCE CONTEXT</h3><Markdown>{entity.subtitle}</Markdown>{entity.metadata.map(item => <p key={item.label}><small>{item.label}</small>{item.value}</p>)}<p className="result-source-url">{url}</p></div>}
    </div>
    <div className="research-result-actions"><button type="button" disabled={!source} onClick={() => onPrompt(`Kaynak temelli araştırmayı sürdür. Bu sonucu seçiyorum: ${selected}. Kaynak: ${url || "yok"}. ${entity.title} bağlamında kaynakları kullanarak devam et.`)}><Icon name="target" />Bu mu?</button><button type="button" disabled={!source} onClick={() => onPrompt(`${selected} için alternatifleri kaynaklarıyla karşılaştır. Önceki araştırma: ${entity.title}. Referans: ${url || "yok"}.`)}><Icon name="research" />Karşılaştır</button><button type="button" aria-expanded={details} onClick={() => setDetails(!details)}><Icon name="files" />Detaylar</button></div>
    <button type="button" className="result-open-source" disabled={!url} onClick={() => void openSource()}>Kaynağı aç <span>↗</span></button>{error && <p role="alert">{error}</p>}
  </section>;
}
