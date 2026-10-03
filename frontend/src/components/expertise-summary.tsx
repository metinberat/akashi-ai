"use client";

import { useEffect, useState } from "react";
import { getCharacterExpertise, queryCharacterKnowledge, listCharacterImprovements, createCharacterImprovement, runCharacterImprovement, cancelCharacterImprovement,
  getCharacterVersions, rollbackCharacterImprovement, type CharacterImprovement, type CharacterVersion, type CharacterSummary, type CharacterKnowledge } from "@/lib/absolute-api";
import type { BackendConfig } from "@/lib/api";

export function ExpertiseSummary({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [knowledge, setKnowledge] = useState<CharacterKnowledge[]>([]);
  const [query, setQuery] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [improvements, setImprovements] = useState<CharacterImprovement[]>([]);
  const [versions, setVersions] = useState<Record<string, CharacterVersion[]>>({});
  const [activeJob, setActiveJob] = useState("");
  useEffect(() => {
    if (!connected) return;
    let active = true;
    const timer = window.setTimeout(() => {
      void getCharacterExpertise(config).then((data) => { if (active) setCharacters(data.characters); })
        .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Expertise unavailable."); });
      void listCharacterImprovements(config).then((data) => { if (active) setImprovements(data.workshops); })
        .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Workshop unavailable."); });
    }, 0);
    return () => { active = false; window.clearTimeout(timer); };
  }, [config, connected]);

  async function search() {
    setBusy(true); setError("");
    try { setKnowledge((await queryCharacterKnowledge(config, query)).knowledge); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Knowledge unavailable."); }
    finally { setBusy(false); }
  }
  async function improve(assetId: string, existing?: CharacterImprovement) {
    setError(""); setActiveJob(existing?.id || "creating");
    try {
      const job = existing || await createCharacterImprovement(config, assetId);
      setActiveJob(job.id);
      setImprovements((items) => [job, ...items.filter((item) => item.id !== job.id)]);
      const updated = await runCharacterImprovement(config, job.id);
      setImprovements((items) => [updated, ...items.filter((item) => item.id !== updated.id)]);
      const result = await getCharacterVersions(config, updated.id);
      setVersions((items) => ({ ...items, [updated.id]: result.versions }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Improvement failed. Best checkpoint retained."); }
    finally { setActiveJob(""); }
  }
  async function cancel(job: CharacterImprovement) {
    try {
      const updated = await cancelCharacterImprovement(config, job.id);
      setImprovements((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed."); }
  }
  async function rollback(job: CharacterImprovement) {
    try {
      const updated = await rollbackCharacterImprovement(config, job.id, job.baseline_version);
      setImprovements((items) => items.map((item) => item.id === updated.id ? updated : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Rollback failed."); }
  }
  return <section className="expertise-summary" aria-label="Character expertise">
    <span className="eyebrow">EXPERT MEMORY / CHARACTER WORKSHOP V3.1</span>
    {!connected ? <p>Core çevrimdışı.</p> : <>
      {characters.length === 0 ? <p>Henüz karakter kaynağı eklenmedi. Gerçek asset analizi bekleniyor.</p> : <ul>{characters.map((item) => <li key={item.id}><strong>{item.name}</strong><span>{item.synthetic ? "SYNTHETIC" : "SOURCE ASSET"} · {item.joint_count} joints · {item.mesh_count} meshes</span><button disabled={!!activeJob} onClick={() => void improve(item.id)}>Ölç / iyileştir</button></li>)}</ul>}
      {improvements.slice(0, 6).map((job) => {
        const best = versions[job.id]?.find((version) => version.id === job.best_version);
        return <article key={job.id}><small>{job.synthetic ? "SYNTHETIC" : "SOURCE"} · {job.status.toUpperCase()} · {job.attempts}/{job.max_attempts} bounded attempts</small>
          <p>{best ? `Sayısal skor: ${best.evaluation.score.toFixed(3)} · ${best.evaluation.deformation.available ? "Poz kanıtı mevcut" : "Deformasyon testi yok"}` : "Checkpoint kayıtlı. Kaynak değişmez; en iyi sürüm korunur."}</p>
          <small>Sayısal test kapsamı. Sanatsal/profesyonel kalite onayı değildir.</small>
          {!["completed", "cancelled"].includes(job.status) && <button disabled={!!activeJob} onClick={() => void improve(job.asset_id, job)}>Checkpoint’ten devam</button>}
          {(job.status === "running" || activeJob === job.id) && <button onClick={() => void cancel(job)}>Durdur</button>}
          {job.best_version !== job.baseline_version && <button disabled={!!activeJob} onClick={() => void rollback(job)}>Kaynak sürüme dön</button>}
        </article>;
      })}
      <form onSubmit={(event) => { event.preventDefault(); void search(); }}><input aria-label="Character knowledge query" placeholder="Forearm twist, skin weights…" value={query} onChange={(event) => setQuery(event.target.value)} maxLength={500} /><button disabled={busy || query.trim().length < 2}>Bilgiyi getir</button></form>
      {knowledge.map((item) => <article key={item.id}><small>{item.kind.toUpperCase()} · {item.validation} · {item.provenance.synthetic ? "SYNTHETIC" : "SOURCE"}</small><p>{item.statement}</p></article>)}
    </>}
    {error && <p className="absolute-error">{error}</p>}
  </section>;
}
