import { CharacterViewer } from "./viewer.js";
const $ = (id) => document.getElementById(id);
const state = {
  project: null,
  snapshot: null,
  selected: null,
  renderKind: "render",
  view: "render",
  viewer: null,
  model: null,
  shapeID: null,
  dirty: false,
  loading: false,
  generation: 0,
  compareSelections: {},
};
const el = (tag, text, className) => {
  const n = document.createElement(tag);
  if (text !== undefined) n.textContent = text;
  if (className) n.className = className;
  return n;
};
function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
async function api(path, method = "GET", body) {
  const response = await fetch("/api/" + path, {
    method,
    headers:
      body instanceof FormData ? {} : { "Content-Type": "application/json" },
    body: body
      ? body instanceof FormData
        ? body
        : JSON.stringify(body)
      : undefined,
  });
  let value;
  try {
    value = await response.json();
  } catch {
    throw new Error("Engine response unavailable");
  }
  if (!response.ok)
    throw new Error(
      typeof value.detail === "string"
        ? value.detail
        : "Input was rejected. Check production controls.",
    );
  return value;
}
async function guarded(fn) {
  try {
    return await fn();
  } catch (error) {
    notice(error.message, true);
  }
}
function fileURL(file, download = false) {
  return `/api/projects/${state.project}/files/${file.id}${download ? "?download=true" : ""}`;
}
async function projectList() {
  const projects = await api("projects");
  $("projects").replaceChildren();
  for (const p of projects) {
    const button = el(
      "button",
      undefined,
      "project-item" + (p.id === state.project ? " selected" : ""),
    );
    button.append(
      el("span", p.name),
      el("small", new Date(p.updated_at).toLocaleDateString() + " · LOCAL"),
    );
    button.dataset.project = p.id;
    button.onclick = () => guarded(() => openProject(p.id));
    $("projects").append(button);
  }
  return projects;
}
async function openProject(id) {
  const generation = ++state.generation;
  state.project = id;
  state.compareSelections = {};
  state.selected = null;
  state.model = null;
  state.shapeID = null;
  state.renderKind = "render";
  state.dirty = false;
  state.loading = false;
  localStorage.setItem("form-project", id);
  await refresh();
  if (generation !== state.generation) return;
  await projectList();
  notice("Project restored. Nothing resumes without your instruction.");
}
function current() {
  return (
    state.snapshot?.runs.find((r) => r.id === state.selected) ||
    state.snapshot?.runs.at(-1)
  );
}
function artifact(kind, run = current()) {
  return state.snapshot?.files.find(
    (f) => f.kind === kind && f.run_id === run?.id,
  );
}
function renderMessages() {
  const box = $("messages");
  box.replaceChildren();
  for (const m of state.snapshot.messages) {
    const n = el("div", undefined, "message " + m.role);
    n.append(
      el(
        "span",
        m.role === "assistant"
          ? "FORM / DESIGN PROPOSAL"
          : m.role === "user"
            ? "YOU"
            : "ENGINE / OBSERVABLE EVENT",
      ),
      el("p", m.text),
    );
    box.append(n);
  }
  if (!box.children.length)
    box.append(
      el(
        "p",
        "Describe what matters. The model proposes a supported design; production requires an explicit build.",
        "muted",
      ),
    );
  box.scrollTop = box.scrollHeight;
}
function renderControls() {
  const d = state.snapshot.project.design || {};
  if (!state.dirty) {
    $("build-type").value = d.build || "balanced";
    $("clothing").value = d.clothing || "coat";
    $("hair").value = d.hair || "short";
    $("height").value = d.height || 1.8;
    $("appearance").value = d.appearance || "classic";
    $("hud").checked = !!d.hud;
    $("facial").checked = d.facial !== false;
  }
  const run = current(),
    terminal = ["completed_partial", "cancelled"];
  const active = run && !terminal.includes(run.status);
  $("build").disabled = false;
  $("export").disabled = !state.snapshot.runs.some(
    (r) => r.status === "completed_partial",
  );
  $("pause").disabled = !active;
  $("cancel").disabled = !active;
  $("resume").disabled =
    !run ||
    !["planned", "paused", "paused_recovery"].includes(run.status) ||
    !!run.inflight;
  $("reconcile").disabled =
    !run || run.status !== "paused_recovery" || !run.inflight;
  $("run-state").textContent = run
    ? run.status.toUpperCase().replaceAll("_", " ") +
      " · " +
      run.steps.length +
      " RECEIPTS"
    : "No production started";
}
function renderVersions() {
  const box = $("versions");
  box.replaceChildren();
  if (!state.snapshot.runs.length) {
    box.append(
      el(
        "p",
        "Every attempt stays inspectable. A new version never overwrites your best.",
        "muted",
      ),
    );
    return;
  }
  for (const [i, run] of state.snapshot.runs.entries()) {
    const button = el(
      "button",
      undefined,
      "version" + (run.id === current()?.id ? " selected" : ""),
    );
    const image = artifact("render", run);
    if (image) {
      const img = el("img");
      img.src = fileURL(image);
      img.alt = "Version " + (i + 1) + " render";
      button.append(img);
    } else button.append(el("div", "Actual production pending", "placeholder"));
    button.append(
      el(
        "span",
        `V${String(i + 1).padStart(2, "0")} ${state.snapshot.project.best_run === run.id ? " / BEST" : ""}`,
      ),
      el("small", run.status.replaceAll("_", " ")),
    );
    button.onclick = () => {
      state.selected = run.id;
      state.model = null;
      state.shapeID = null;
      state.renderKind = "render";
      render();
    };
    box.append(button);
  }
}
function renderReferences() {
  const box = $("references");
  box.replaceChildren();
  for (const f of state.snapshot.files.filter((f) =>
    ["reference", "source"].includes(f.kind),
  )) {
    const row = el("div", undefined, "reference");
    if (f.kind === "reference") {
      const img = el("img");
      img.src = fileURL(f);
      img.alt = f.label;
      row.append(img);
    } else row.append(el("b", "↳"));
    row.append(el("span", f.label));
    box.append(row);
  }
  if (!box.children.length)
    box.append(
      el(
        "p",
        "Add a reference image or a supplied character asset. No source is downloaded automatically.",
        "muted",
      ),
    );
  const reference = state.snapshot.files.filter(f => f.kind === "reference").at(-1);
  if (reference) {
    const generate = el("button", "Local learned shape / experimental");
    generate.disabled = !state.snapshot.local_shape?.configured || state.snapshot.local_shape.busy;
    generate.title = "Requires separately configured local SDK and license acceptance. No rig/textures. Outputs excluded from learning.";
    generate.onclick = () => guarded(async () => {
      await api(`projects/${state.project}/shape`, "POST", {reference_id: reference.id, quality: "quality"});
      await refresh();
      notice("Local GPU shape proposal started. No external API; not a production-ready rigged character.");
    });
    box.append(generate);
  }
  for (const job of state.snapshot.project.shape_jobs || []) {
    const label = el("p", `LOCAL SHAPE · ${job.status.replaceAll("_", " ")} · excluded from training`, "fine");
    box.append(label);
    if (job.reason) box.append(el("p", job.reason, "fine"));
    if (job.reference_preview) {
      const preview = el("img");
      preview.src = fileURL({id:job.reference_preview});
      preview.alt = "Actual local foreground estimate; not recovered anatomy";
      preview.className = "reference-mask";
      box.append(preview);
    }
    if (job.output) {
      const show = el("button", "Inspect actual shape in 3D");
      show.onclick = () => { state.shapeID = job.output; state.view = "3d"; state.model = null; showView(); renderInspector(); };
      const download = el("a", "Export shape ↗");
      download.href = fileURL({id:job.output}, true);
      download.download = "";
      box.append(show, download);
    }
  }
}
function renderInspector() {
  const box = $("inspector");
  box.replaceChildren();
  if (state.shapeID) {
    const job = state.snapshot.project.shape_jobs.find(j => j.output === state.shapeID);
    const evidence = job?.evidence;
    box.append(el("span", "LOCAL LEARNED SHAPE / EXPERIMENTAL", "eyebrow"),
      el("h3", "A geometric proposal, not a finished character."),
      el("p", `${evidence?.vertices ?? "—"} vertices · ${evidence?.faces ?? "—"} faces · rig NOT GENERATED.`),
      el("p", "Front-projected color is a local presentation estimate. Unseen surfaces and anatomical fidelity are unverified."),
      el("p", "This separate model lineage is excluded from FORM expertise/training/datasets because of its license."));
    if ((evidence?.reference_preprocessing?.foreground_fraction ?? 1) < 0.15)
      box.append(el("p", "Earlier output used a partial foreground estimate. This is a failed visual attempt, not an accepted character; repeat with a clean crop/alpha."));
    return;
  }
  const run = current();
  if (run) {
    box.append(
      el("span", "VERSION / " + run.status.toUpperCase(), "eyebrow"),
      el("h3", "Evidence before confidence."),
    );
    const features = run.features || {};
    const grid = el("div", undefined, "metric-grid");
    for (const [label, value] of [
      ["Meshes", features.meshes ?? "—"],
      ["Joints", features.joints ?? "—"],
      ["Numeric loss", run.best?.evaluation?.loss?.toFixed(4) ?? "—"],
      ["Visual fidelity", "Unmeasured"],
    ]) {
      const cell = el("div");
      cell.append(el("b", String(value)), el("span", label));
      grid.append(cell);
    }
    box.append(
      grid,
      el(
        "p",
        "Only measured technical results are accepted. A technical pass is not professional character quality.",
      ),
    );
    const visual = state.snapshot.project.visual_evaluations?.filter(v => v.run_id === run.id).at(-1);
    if (visual) box.append(el("p", visual.loss == null ? "Image comparison unavailable: ambiguous foreground." :
      `Measured image proxy: ${visual.loss.toFixed(4)} · silhouette IoU ${(visual.silhouette_iou * 100).toFixed(1)}%. Not a likeness/artist-quality score.`));
    for (const step of run.steps)
      box.append(el("div", "✓ " + step.replaceAll("_", " "), "evidence-step"));
    if (run.events?.length) {
      const history = el("details");
      history.append(el("summary", "Execution history / observable events"));
      for (const event of run.events.slice(-20)) {
        const label =
          event.kind === "candidate_evaluated"
            ? `Candidate ${event.accepted ? "accepted" : "rejected"} · loss ${event.loss.toFixed(4)}`
            : event.step || event.status;
        history.append(
          el(
            "p",
            `${new Date(event.at).toLocaleTimeString()} · ${label.replaceAll("_", " ")}`,
          ),
        );
      }
      box.append(history);
    }
    if (run.inflight)
      box.append(
        el(
          "div",
          "→ " + run.inflight.replaceAll("_", " ") + " · in progress",
          "evidence-step",
        ),
      );
    if (run.recovery_reason) box.append(el("p", run.recovery_reason));
    if (run.remaining.length)
      box.append(
        el("h3", "Still unproven"),
        el("p", run.remaining.join(" · ")),
      );
    box.append(el("h3", "Candidate comparison"));
    for (const [i, t] of run.trials.entries())
      box.append(
        el(
          "p",
          `Attempt ${i + 1} · loss ${t.evaluation?.loss?.toFixed(4) ?? "—"} · ${t.evaluation?.passed ? "technical gates passed" : "rejected"} · radial ${t.method.radial}`,
        ),
      );
    if (run.status === "completed_partial") {
      const best = el("button", "Keep as project best");
      best.onclick = () =>
        guarded(async () => {
          await api(`projects/${state.project}/best`, "PUT", {
            run_id: run.id,
          });
          await refresh();
          notice("Best version pinned. Other attempts remain intact.");
        });
      box.append(best);
      for (const kind of ["glb", "blend", "render", "front", "back", "flow"]) {
        const f = artifact(kind, run);
        if (!f) continue;
        const button = el(
          "button",
          kind === "glb"
            ? "Download GLB"
            : kind === "blend"
              ? "Download Blender"
              : kind.toUpperCase(),
        );
        button.onclick = () => {
          if (["glb", "blend"].includes(kind)) {
            const a = el("a");
            a.href = fileURL(f, true);
            a.download = "";
            a.click();
          } else {
            state.view = "render";
            state.renderKind = kind;
            $("render-image").src = fileURL(f);
            showView();
          }
        };
        box.append(button);
      }
    }
  }
  for (const asset of state.snapshot.assets) {
    box.append(
      el("h3", asset.name),
      el(
        "p",
        `Provenance: ${asset.source.synthetic ? "SYNTHETIC" : "SUPPLIED ASSET"} · ${asset.id}`,
      ),
      el(
        "p",
        `${asset.analysis.observed.mesh_count} meshes · ${asset.analysis.observed.joint_count} joints · ${asset.analysis.observed.material_count} materials · ${asset.analysis.observed.morph_targets} morph targets`,
      ),
      el(
        "p",
        `Rig: ${asset.analysis.observed.has_rig ? "observed" : "absent"} · Skin: ${asset.analysis.observed.has_skin ? "observed" : "absent"} · Animation: ${asset.analysis.observed.has_animation ? "observed" : "absent"}`,
      ),
      el(
        "p",
        "Missing information: " +
          (asset.analysis.unavailable.join(" · ") ||
            "See source-specific analysis scope."),
      ),
    );
    if (asset.source.source_name?.endsWith(".json")) {
      const button = el(
        "button",
        "Create protected presentation copy (.blend source required)",
      );
      button.onclick = () => guarded(() => build(asset.id));
      box.append(button);
    }
  }
  if (!run && !state.snapshot.assets.length)
    box.append(
      el(
        "p",
        "Production trials, imported structures and verified export receipts appear here.",
      ),
    );
}
function showView() {
  for (const id of [
    "render-image",
    "viewer",
    "compare",
    "learning",
    "empty",
    "caption",
    "viewer-controls",
  ])
    $(id).hidden = true;
  document
    .querySelectorAll("[data-view]")
    .forEach((b) =>
      b.classList.toggle("selected", b.dataset.view === state.view),
    );
  if (state.view === "learning") {
    $("learning").hidden = false;
    return;
  }
  if (state.view === "compare") {
    $("compare").hidden = false;
    return;
  }
  const run = current(),
    file = state.view === "3d" && state.shapeID
      ? state.snapshot.files.find(f => f.id === state.shapeID)
      : artifact(state.view === "3d" ? "glb" : state.renderKind, run);
  if (!file) {
    $("empty").hidden = false;
    if (state.project) {
      $("empty").querySelector("h2").textContent = run
        ? "The engine is doing the real work."
        : "Define the character. Build with evidence.";
      $("empty").querySelector("p").textContent = run
        ? `Current state: ${run.status.replaceAll("_", " ")}. ${run.inflight ? "Working on " + run.inflight : "Verified receipts: " + run.steps.length}. No preview is fabricated while work is pending.`
        : "Add a reference, describe the result, then review the production controls. Every render and 3D preview will come from a real saved artifact.";
      $("start-project").hidden = true;
    }
    return;
  }
  if (state.view === "3d") {
    $("viewer").hidden = false;
    $("viewer-controls").hidden = false;
    loadModel(file);
  } else {
    $("render-image").hidden = false;
    if (!$("render-image").src.endsWith(fileURL(file)))
      $("render-image").src = fileURL(file);
  }
  $("caption").hidden = false;
  $("version-caption").textContent =
    (state.shapeID ? "LOCAL SHAPE / NO RIG" : run.id.slice(-8).toUpperCase()) +
    " / " +
    (state.view === "3d" ? "ORBIT · SCROLL · INSPECT" : "BLENDER RENDER");
}
async function loadModel(file) {
  if (state.model === file.id) return;
  const generation = state.generation, project = state.project;
  state.model = file.id;
  try {
    state.viewer ||= new CharacterViewer($("viewer"));
    const clips = await state.viewer.load(fileURL(file));
    if (generation !== state.generation || project !== state.project || state.model !== file.id) return;
    $("clips").replaceChildren(
      ...clips.map((c, i) => {
        const n = el("option", c);
        n.value = i;
        return n;
      }),
    );
    $("motion").disabled = !clips.length;
    $("skeleton").disabled = Number($("viewer").dataset.joints || 0) === 0;
    notice(
      state.shapeID ? "Real local shape loaded. No rig or animation is claimed; inspect the geometric proposal." : "Real GLB loaded. Orbit, inspect the skeleton or play the exported clips.",
    );
  } catch (e) {
    if (generation !== state.generation || project !== state.project) return;
    state.model = null;
    notice(e.message, true);
  }
}
function renderCompare() {
  const runs = state.snapshot.runs.filter((r) => artifact("render", r));
  for (const [id, image] of [
    ["compare-a", "compare-image-a"],
    ["compare-b", "compare-image-b"],
  ]) {
    const select = $(id),
      previous = state.compareSelections[id];
    select.replaceChildren(
      ...runs.map((r, i) => {
        const n = el("option", `Version ${i + 1} / ${r.id.slice(-6)}`);
        n.value = r.id;
        return n;
      }),
    );
    select.value = runs.some((r) => r.id === previous)
      ? previous
      : (id === "compare-a" ? runs[0]?.id : runs.at(-1)?.id) || "";
    const updateImage = () => {
      const r = runs.find((r) => r.id === select.value),
        f = artifact("render", r);
      $(image).src = f ? fileURL(f) : "";
    };
    select.onchange = () => {
      state.compareSelections[id] = select.value;
      updateImage();
    };
    updateImage();
  }
}
function render() {
  const p = state.snapshot.project;
  $("name").textContent = p.name;
  $("project-title").textContent = p.name + " / SAVED LOCALLY";
  const advisor = state.snapshot.capability_advisor;
  $("capability-advice").textContent = advisor?.optional_specialist_recommended
    ? "High-detail/reference matching: local work can continue. An optional specialist may improve maximum quality; professional likeness is not proven."
    : "LOCAL CORE · Real geometry, finger rig, spatial HUD and Blender output. Pixel analysis is not semantic reconstruction.";
  renderControls();
  renderVersions();
  renderReferences();
  renderInspector();
  renderCompare();
  showView();
}
async function refresh() {
  if (!state.project || state.loading) return;
  state.loading = true;
  const project = state.project, generation = state.generation;
  try {
    const snapshot = await api("projects/" + project);
    if (generation !== state.generation || project !== state.project) return;
    state.snapshot = snapshot;
    render();
    renderMessages();
    if (state.view === "learning") await learning();
  } finally {
    if (generation === state.generation) state.loading = false;
  }
}
async function learning() {
  const value = await api(`projects/${state.project}/learning`);
  const box = $("learning");
  box.replaceChildren(
    el("span", "DELIBERATE PRACTICE / REAL EVIDENCE", "eyebrow"),
    el("h2", "Expertise is earned, not animated."),
    el(
      "p",
      "Training generates synthetic exercises, compares methods, retains independent validation and remembers failures. It does not fine-tune a neural model or certify professional mastery.",
    ),
  );
  const controls = el("div", undefined, "training-controls");
  const count = el("select");
  for (const c of [2, 4, 8, 16]) {
    const n = el("option", c + " exercises");
    n.value = c;
    count.append(n);
  }
  controls.append(count);
  const start = el("button", "Train yourself ↗", "primary");
  start.onclick = () =>
    guarded(async () => {
      await api(`projects/${state.project}/training`, "POST", {
        max_exercises: Number(count.value),
        candidates_per_exercise: 3,
        seed: Math.floor(Math.random() * 1000000),
      });
      await refresh();
      notice("Intentional synthetic practice started.");
    });
  controls.append(start);
  const dataset = el("button", "Export learning evidence");
  dataset.onclick = () =>
    guarded(async () => {
      const file = await api(
        `projects/${state.project}/learning/export`,
        "POST",
      );
      const link = el("a");
      link.href = fileURL(file, true);
      link.download = "";
      link.click();
      notice(
        "Project-scoped evidence exported. Synthetic provenance remains explicit.",
      );
    });
  controls.append(dataset);
  for (const r of state.snapshot.training) {
    const label = el(
      "p",
      `${r.status.toUpperCase()} · ${r.completed_exercises}/${r.request.max_exercises} exercises · level ${r.level}`,
    );
    controls.append(label);
    for (const command of ["pause", "resume", "cancel"]) {
      const b = el("button", command);
      b.onclick = () =>
        guarded(async () => {
          await api(
            `projects/${state.project}/training/${r.id}/${command}`,
            "POST",
          );
          await refresh();
        });
      controls.append(b);
    }
  }
  box.append(
    controls,
    el(
      "p",
      `${value.attempts.length} retained attempts in this project · ${value.methods.length} best-known methods in the expert library · ${value.knowledge.length} retrieved evidence entries.`,
    ),
  );
  const refs = state.snapshot.files.filter(f => f.kind === "reference");
  const practice = el("button", "Practice appearance / real Blender trials");
  practice.disabled = !refs.length;
  practice.onclick = () => guarded(async () => {
    await api(`projects/${state.project}/visual/practice`, "POST", { reference_id: refs.at(-1).id, attempts: 2 });
    await refresh();
    notice("Bounded visual practice started. Real front renders are compared; regressions keep the prior best.");
  });
  box.append(practice, el("p", "Appearance training measures silhouette/palette proxies. Use comparable front-view references with transparent/uniform backgrounds. It does not prove professional fidelity.", "fine"));
  const lab = state.snapshot.project.visual_lab;
  if (lab) {
    box.append(el("p", `${lab.status.toUpperCase()} · ${lab.cursor}/${lab.candidates.length} visual trials · best proxy ${lab.best?.loss?.toFixed(4) ?? "unmeasured"}`));
    for (const command of ["pause", "resume", "cancel"]) {
      const b = el("button", command + " visual practice");
      b.onclick = () => guarded(async () => { await api(`projects/${state.project}/visual/${command}`, "POST"); await refresh(); });
      box.append(b);
    }
    for (const attempt of lab.attempts) box.append(el("p", `${attempt.accepted ? "KEPT" : "REJECTED"} · ${attempt.evaluation.run_id.slice(-6)} · ${attempt.decision}`));
  }
  for (const item of value.knowledge) {
    const n = el("div", undefined, "lesson");
    n.append(
      el(
        "span",
        `${item.kind} / ${item.metadata.synthetic ? "SYNTHETIC" : "SUPPLIED SOURCE"} / ${item.metadata.validation || "unvalidated"}`,
      ),
      el("h3", item.title),
      el(
        "p",
        item.kind === "computed_experience_evidence"
          ? "Measured synthetic comparison evidence; not universal production truth."
          : item.content.slice(0, 700),
      ),
      el("small", item.source),
    );
    box.append(n);
  }
  for (const a of value.attempts.slice(0, 10)) {
    const n = el("div", undefined, "lesson");
    n.append(
      el(
        "span",
        `${a.partition} / ${a.evaluation?.passed ? "PASSED" : "FAILED"}`,
      ),
      el(
        "p",
        `${a.context} · method ${a.method.id} · loss ${a.evaluation?.loss?.toFixed(5) ?? "unavailable"}`,
      ),
    );
    box.append(n);
  }
}
async function build(asset_id = null) {
  notice("Saving production design…");
  const d = {
    ...(state.snapshot.project.design || {}),
    build: $("build-type").value,
    clothing: $("clothing").value,
    hair: $("hair").value,
    height: Number($("height").value),
    appearance: $("appearance").value,
    hud: $("hud").checked,
    facial: $("facial").checked,
  };
  await api(`projects/${state.project}/design`, "PUT", d);
  state.dirty = false;
  const run = await api(`projects/${state.project}/build`, "POST", {
    asset_id,
  });
  state.selected = run.id;
  state.view = "render";
  await refresh();
  notice(
    "Real production dispatched. Pause stops at a safe operation boundary.",
  );
}
$("appearance").onchange = () => { state.dirty = true; };
for (const id of ["new-project", "start-project"])
  $(id).onclick = () => $("project-dialog").showModal();
$("close-dialog").onclick = () => $("project-dialog").close();
$("about").onclick = () => $("about-dialog").showModal();
$("close-about").onclick = () => $("about-dialog").close();
$("project-form").onsubmit = (e) => {
  e.preventDefault();
  guarded(async () => {
    const p = await api("projects", "POST", {
      name: $("project-name").value,
      brief: $("project-brief").value,
    });
    $("project-dialog").close();
    await openProject(p.id);
  });
};
$("message-form").onsubmit = (e) => {
  e.preventDefault();
  if (!state.project) {
    notice("Create or open a project first.", true);
    return;
  }
  $("send").disabled = true;
  guarded(async () => {
    await api(`projects/${state.project}/messages`, "POST", {
      text: $("message").value,
      use_models: $("use-model").checked,
    });
    $("message").value = "";
    state.dirty = false;
    await refresh();
    notice("Instruction and proposal evidence saved.");
  }).finally(() => ($("send").disabled = false));
};
document.querySelectorAll("[data-tab]").forEach(
  (b) =>
    (b.onclick = () => {
      document
        .querySelectorAll("[data-tab]")
        .forEach((x) => x.classList.toggle("selected", x === b));
      $("intent-tab").hidden = b.dataset.tab !== "intent";
      $("inspect-tab").hidden = b.dataset.tab !== "inspect";
    }),
);
document.querySelectorAll("[data-view]").forEach(
  (b) =>
    (b.onclick = () =>
      guarded(async () => {
        state.view = b.dataset.view;
        showView();
        if (state.project && state.view === "learning") await learning();
      })),
);
document.querySelectorAll(".design-grid input,.design-grid select").forEach(
  (n) =>
    (n.onchange = () => {
      state.dirty = true;
    }),
);
$("build").onclick = () => guarded(() => build());
for (const command of ["pause", "resume", "reconcile", "cancel"])
  $(command).onclick = () =>
    guarded(async () => {
      const run = current();
      await api(`projects/${state.project}/runs/${run.id}/${command}`, "POST");
      await refresh();
      notice(
        command === "pause"
          ? "Pause requested. The current DCC operation finishes safely."
          : "Command recorded: " + command,
      );
    });
$("attach").onclick = () => {
  if (!state.project) {
    notice("Create or open a project first.", true);
    return;
  }
  $("upload").click();
};
$("upload").onchange = () =>
  guarded(async () => {
    const file = $("upload").files[0];
    if (!file) return;
    notice("Uploading and analyzing " + file.name + "…");
    const data = new FormData();
    data.append("file", file);
    data.append("synthetic", String($("synthetic").checked));
    await api(`projects/${state.project}/uploads`, "POST", data);
    $("upload").value = "";
    await refresh();
    notice("Input stored and connected to this project.");
  });
$("export").onclick = () =>
  guarded(async () => {
    notice("Packaging verified artifacts and hash manifest…");
    const file = await api(`projects/${state.project}/export`, "POST");
    const a = el("a");
    a.href = fileURL(file, true);
    a.download = "";
    a.click();
    notice(
      "Export bundle ready. Includes real artifacts and provenance manifest.",
    );
  });
$("wire").onclick = () => {
  if (state.viewer) {
    state.viewer.setWire(!state.viewer.wire);
    $("wire").classList.toggle("selected", state.viewer.wire);
  }
};
$("skeleton").onclick = () => {
  if (state.viewer) {
    const on = !$("skeleton").classList.contains("selected");
    state.viewer.setSkeleton(on);
    $("skeleton").classList.toggle("selected", on);
  }
};
$("motion").onclick = () => {
  if (state.viewer) {
    state.viewer.playing = !state.viewer.playing;
    state.viewer.play(Number($("clips").value));
    $("motion").textContent = state.viewer.playing
      ? "Pause animation"
      : "Play animation";
  }
};
$("clips").onchange = () => state.viewer?.play(Number($("clips").value));
await guarded(async () => {
  const health = await api("health");
  $("health").textContent = health.blender
    ? "LOCAL ENGINE / BLENDER READY"
    : "LOCAL ENGINE / BLENDER NOT FOUND";
  const projects = await projectList();
  const recent = localStorage.getItem("form-project");
  if (projects.some((p) => p.id === recent)) await openProject(recent);
  else if (projects.length) await openProject(projects[0].id);
});
setInterval(() => {
  if (!document.hidden && state.project) guarded(refresh);
}, 3000);
window.addEventListener("beforeunload", () => state.viewer?.dispose());
