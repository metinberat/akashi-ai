"use client";

import { useCallback, useEffect, useState } from "react";
import { Icon } from "@/components/identity";
import { cancelAutonomyTask, listAutonomyTasks, resumeAutonomyTask, type AutonomyTask } from "@/lib/absolute-api";
import type { BackendConfig } from "@/lib/api";
import { ExpertiseSummary } from "@/components/expertise-summary";

export function AutonomyHub({ config, connected }: { config: BackendConfig; connected: boolean }) {
  const [tasks, setTasks] = useState<AutonomyTask[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const refresh = useCallback(async () => {
    if (!connected) return;
    try { setTasks(await listAutonomyTasks(config)); setError(""); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Autonomy state unavailable."); }
  }, [config, connected]);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 4000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [refresh]);

  async function act(task: AutonomyTask, operation: "resume" | "cancel") {
    setBusy(task.id);
    try {
      if (operation === "resume") await resumeAutonomyTask(config, task.id, task.status === "waiting_for_approval" ? true : undefined);
      else await cancelAutonomyTask(config, task.id);
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Task action failed."); }
    finally { setBusy(""); }
  }

  return (
    <div className="absolute-panel autonomy-hub">
      <div className="panel-intro">
        <span className="eyebrow">AUTONOMY / OPERATOR V2</span>
        <h3>Uzun görevler. Doğrulanmış sonuçlar.</h3>
        <p>Goal graph, uygulamalar arası yürütme, recovery checkpoint’leri ve gerçek artifact kanıtı.</p>
      </div>
      {error && <div className="absolute-error">{error}</div>}
      {!connected ? <div className="autonomy-empty"><Icon name="autonomy" /><strong>Core çevrimdışı.</strong><span>Görev durumu Core yeniden bağlandığında yüklenecek.</span></div>
      : tasks.length === 0 ? <div className="autonomy-empty"><Icon name="autonomy" /><strong>Aktif veya geçmiş otonom görev yok.</strong><span>Uzun bir hedef verdiğinde plan ve doğrulama burada görünür.</span></div>
      : <div className="autonomy-task-list">{tasks.map((task) => {
        const complete = task.subgoals.filter((step) => step.status === "completed").length;
        const resumable = ["failed", "paused_recovery", "waiting_for_approval"].includes(task.status);
        return <article className="autonomy-task" key={task.id}>
          <header><div><span>{task.status.toUpperCase()}</span><strong>{task.title}</strong></div><small>{complete} / {task.subgoals.length} · PLAN R{task.plan_revision} · REPLAN {task.replans}</small></header>
          <div className="autonomy-steps">{task.subgoals.map((step) => <div key={step.id} data-state={step.status}><i /><span><b>{step.title}</b><small>{step.channel.toUpperCase()} · {step.status} · attempt {step.attempts}</small></span></div>)}</div>
          {(task.summary || task.error) && <p>{task.summary || task.error}</p>}
          <footer>
            {resumable && <button disabled={busy === task.id} onClick={() => void act(task, "resume")}>{task.status === "waiting_for_approval" ? "Görev kapsamını onayla" : "Checkpoint’ten devam et"}</button>}
            {!['completed', 'failed', 'cancelled'].includes(task.status) && <button disabled={busy === task.id} onClick={() => void act(task, "cancel")}>Durdur</button>}
          </footer>
        </article>;
      })}</div>}
      <ExpertiseSummary config={config} connected={connected} />
    </div>
  );
}
