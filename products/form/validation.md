# FORM local-first visual-quality validation — 2026-10-03

## Result and scope

The interrupted standalone validation was completed against actual packaged
Electron, its independent runtime and installed Blender 5.2. No AKASHI Core
process was required. New local appearance/reference methods and a separately
installed learned-shape channel were implemented and exercised.

**Professional character/reference fidelity remains PARTIAL.** A technically
verified export, polygon count, silhouette proxy or successful model invocation
does not prove professional artistic quality.

| Area | Status | Evidence and limit |
| --- | --- | --- |
| Standalone project workspace | WORKING | Packaged EXE created projects, invoked real production, saved state, exported and restored after relaunch. |
| Local core with providers disabled | WORKING | Actual numeric planning, reference measurement, two Blender versions and visual comparisons without model/API interpretation. |
| Rig / fingers / pose checks / animation / GLB | WORKING | Existing 57-joint rig retained, real Blender readback and export gates; not a complete professional IK/facial rig. |
| Character-linked HUD | WORKING | Real spatial geometry and animated flow/materials exported with the character, no API required. |
| Atelier appearance | WORKING technically; PARTIAL artistically | Shaped face sections, eyelids/eyes, scalp/locks, layered coat trim/materials. Visible anatomy is still segmented/stylized. |
| Reference pixel analysis | WORKING | Local alpha/uniform-background mask, palette/bounds; complex backgrounds abstain. Not anatomical/semantic reconstruction. |
| Appearance self-practice | WORKING for bounded proxies | Real versions, reference hash, evaluator version, losses, accepted/rejected attempts and preserved best. Professional perceptual learning remains FOUNDATION. |
| Local natural-language reasoning | WORKING | Installed Ollama qwen3:8b produced a validated design proposal; no cloud, tools or auto-build. Not vision. |
| Local learned shape | PARTIAL | Actual CUDA Hunyuan3D-2mv produced a watertight synthetic-reference GLB; no rig, production retopology or recovered UV textures. |
| Earlier AKASHI artwork reconstruction | FAILED visual acceptance | Mesh existed but was visually wrong; foreground model isolated only ~5.27% of the image. Corrected gate now rejects this reference before shape generation. |
| Complexity advisor | WORKING as a heuristic | Local work can continue; difficult reference/cinematic requests recommend optional specialist. No claimed quantitative artistic expertise. |
| Broader professional art evaluator / learned mesh-to-rig binding | FOUNDATION | Not implemented as a validated production-quality capability. |

No professional 3D character asset was supplied/analyzed. All 3D generation was
synthetic. A previously user-supplied, user-owned **2D** AKASHI artwork was also
tested locally. No model weight or professional asset was downloaded.

## Interrupted product validation and fixes

The old Compare selection retained an implicit second-version value and failed
to advance when a new real version arrived. Explicit per-project user selections
now remain stable; default A/B uses first/latest real renders. The full packaged
workflow was rerun, rather than treating an earlier interrupted report as proof.

A real pause before any accepted numeric candidate no longer creates an empty
DCC checkpoint. Observable production events now persist without exposing model
reasoning or system prompts. During visual QA a project-switch/polling race was
found: a stale response could overwrite the selected project's snapshot, leaving
a loaded 3D model hidden behind an empty state. Project generations, stale-load
guards and stronger visible-stage smoke assertions corrected it.

Starts/resumes share a product compute gate across production, rig training,
appearance practice and local shape. Tests verify resume cannot bypass that gate.
OS-owned runtime locking prevents duplicate product runtimes. Interrupted work
is explicitly paused/interrupted, not silently replayed.

## Actual packaged workflow

Latest full workflow, `.validation/app-smoke-report.json`:

- Project: `7aa39b045e3847d385d030f732fc640d`.
- First production: `production-35195e1875134f0f9c86e947d608778a`.
- Eleven actual DCC stages: stage, build, source hash, inspection, features,
  render, export, front, back, flow, export readback.
- Two immutable versions, explicit best selection, comparison, two completed
  training exercises, pause/resume, export and persistence after closing/relaunch.
- ZIP download: **3,029,414 bytes**, HTTP 200.
- Renderer JavaScript errors: **0**.
- Production status: `completed_partial`, deliberately not artistic certification.

This used `dist/win-unpacked/FORM Character Studio.exe` with its packaged engine
resources, not a repository web page pretending to be an application. The NSIS
installer was built; a system-wide installer acceptance was not performed.

## Provider-disabled production / appearance

The local test explicitly blanks reasoning/vision provider selection, sets
`FORM_EXTERNAL_MODELS_ENABLED=false`, disables model interpretation and uses
our own synthetic Blender front render as reference. It performs actual
production and records feature/readback gates before scoring images. The
driver has a separate `FORM_TEST_SOURCE_DATA` setting so it can validate the
correct current packaged project's artifacts instead of an obsolete data root.

Final core-only driver execution passed as a complete run:
`.validation/local-core-report.json`, project
`797793e298fa4f09a85008042f942aba`, both real versions with 57 joints,
providers disabled, no shape/model requested, reopened best-state persistence.
Measured losses were **0.04545233445693273 → 0.02341429527469584**. This is a
different reference/render instance from the earlier example below, not an
additional claim of identity or artistic quality.

The earlier fully exercised appearance project
`2d9f51987c5a4f04a8cfddd38e599fe7` has two 57-joint real Blender trials:

| Trial | Image proxy loss |
| --- | --- |
| Original deliberately wrong cloth palette | 0.045088272147094585 |
| Local reference-palette adaptation | 0.008733911154615095 |

The lower-loss state and previous version are both retained. Evidence is
retrievable through the shared knowledge store; Partner retrieval was corrected
to use that actual store, not only the narrower asset-knowledge query. The score
combines silhouette IoU and palette distance and is explicitly **not** a face,
identity, anatomy or professional-quality metric. Low-confidence synthetic
experience is not automatically promoted to validated expert truth.

## Installed local reasoning and GPU shape

`.validation/local-reasoning-report.json`: the existing local qwen3:8b generated
a strict typed atelier design with cloud disabled. It did not execute tools,
build automatically or claim to have seen the image.

`.validation/local-quality-report.json`: actual separately installed SDK,
locally cached safetensors and CUDA on **RTX 4080 SUPER** generated **50,104
vertices / 100,396 faces**, watertight, from a clean synthetic reference.
Inference was rerun after the foreground safety changes. Draft used 12 steps /
192 resolution; isolated CPU offload kept the large cached model usable locally.
The adapter fixes a missing component-registry/device issue only on its pipeline
instance; installed vendor source was not modified or copied.

Actual GLB geometry was loaded in packaged FORM. Vertex colors are a local front
projection with inferred unseen-surface fallback. No rig, animation, production
topology, reliable appearance reconstruction or UV texture recovery is claimed.

The model is off by default and separately installed. Its
[upstream license](https://huggingface.co/tencent/Hunyuan3D-2/raw/main/LICENSE)
includes territorial, training and distribution restrictions. Output hashes
are persisted in a separate SQLite quarantine table, surviving bounded job-history
pruning. Known outputs cannot enter asset ingestion/recipes/RAG/self-training or
training dataset exports. Tests exercise rejection, rename and history pruning.
This safeguard is not a guarantee against deliberately transformed/laundered data.

## Failed reference experiment — retained honestly

`.validation/art-reference-report.json` records an actual local attempt using
the user's earlier 2D artwork. Thirty steps / 256 resolution generated **178,102
vertices / 356,244 faces**. Technical export was real; visual inspection showed
a poor head/body/background-like result, **not a convincing character**.

Cached U²-Net selected only **0.052685546875** foreground fraction. It must not be
treated as a valid full-character mask. The corrected preparation rejects small
or ambiguous estimates, thresholds/trim-valid masks, never downloads missing
weights, and requests a clean crop/alpha. `.validation/foreground-guard-report.json`
proves the actual cached ONNX model now rejects this input before generation.
Old output stays inspectable with a failed-attempt warning; it is not accepted
as a production state or inserted into learning.

This failure makes clean/multiview input, foreground verification, reference-derived
retopology and binding to the existing rig the meaningful next frontier—not merely
increasing polygon counts.

## Packaged visual evidence

`.validation/quality-ui-report.json`: actual packaged app, real saved artifacts,
0 renderer errors, tested **1920×1080** and **3440×1440**. Smoke checks require the
viewer to remain visible across polling and disable nonexistent skeleton controls.

- `quality-1920.png`: actual rigged atelier Blender output.
- `quality-compare-3440.png`: actual original/adapted rendered versions.
- `quality-learning-3440.png`: real practice attempts, best loss and learning state.
- `local-shape-1920.png`: real experimental synthetic-reference shape GLB.
- `art-reference-1920.png`, `art-reference-3440.png`: real **failed visual**
  artwork reconstruction retained for diagnosis; not marketing previews.

These are Electron renderer viewport screenshots, not entire physical-monitor
captures. Screenshots were visually inspected; the initial false-positive loaded
but hidden viewer was fixed rather than accepted based on test exit codes.

## Automated regressions / builds

| Check | Actual result |
| --- | --- |
| Backend full suite | 168/168; latest 59.081 s |
| FORM product/local-quality suite | 35/35; latest 3.883 s |
| Windows Agent suite | 24/24; latest 0.193 s |
| AKASHI Electron security/supervisor | 9/9 |
| FORM Electron security | 3/3 |
| Shared frontend API | 22/22 |
| Browser/UI suite | 13/13; latest 31.2 s |
| TypeScript | `npx tsc --noEmit` passed |
| ESLint | passed |
| FORM JavaScript syntax / Ruff | passed |
| Next production/static build | passed, Next 16.3.8, four static pages |
| FORM production bundle / Windows NSIS | passed |
| Real packaged workflow / visual smoke | passed; visual quality separately limited above |
| `git diff --check` | passed; existing CRLF warnings only |
| Production npm audit | 0 advisories |
| Full dev-inclusive npm audit | 8 high entries in builder's transitive HTTP cache chain; unresolved |

The dev advisory chain roots in `http-cache-semantics@4.2.0`; the current registry
still reports 4.2.0 as latest. A force downgrade of the packager was not used as
an unverified fix. This remains a build-tool security limitation, despite zero
production dependency findings. Focused key/private-key pattern scan found no
matches in FORM server, UI, main process and built static files. This is not a
comprehensive security certification or a full audit of the unrelated dirty tree.

TestClient/httpx and Node experimental transform warnings remain; no test failure
was hidden. Web/mobile presentation was not changed by this stage. Android/iOS
were not rebuilt or physically validated; no iOS compilation on Windows is claimed.

## Important implementation files

- Product: `server/form_studio/{engine,projects,api,runtime,partner,appearance_lab,local_shape,shape_worker}.py`.
- Independent Electron/UI: `desktop/{main,security}.cjs`, `web/{app,viewer}.js`,
  `web/index.html`, `web/style.css`, package/build configuration and tests.
- Shared engine: `backend/app/expertise/production/{appearance,visual,reference,geometry,contracts,host,repository}.py`.
- Fixed DCC: `desktop/agent/akashi_agent/{blender_production,production_contract}.py`.
- Configuration/docs: `.env.example`, `server/requirements*.txt`, this report and README.

## Remaining acceptance / limitations

The artistically convincing reference-faithful character objective is not finished.
The procedural rig is stronger than the appearance; learned shape does not yet
attach to that rig or solve professional mesh/UV/material/hair/cloth/facial quality.
Real professional assets and held-out multiview/deformation evaluation are absent.
Appearance practice does not fine-tune a neural model or validate broad artistic
expertise. The optional specialist port is extensible, but only existing Ollama/
Gemini adapters and the configured local shape SDK are implemented here.

Runtime prerequisites remain installed Python/Blender; optional SDK/weights remain
operator-managed. The Windows installer is unsigned/default icon. Export is an
artifact bundle, not a full project-library backup/migration system. Untrusted
Blender files still need an OS isolation strategy for stronger adversarial safety.
Long professional production acceptance belongs to the user's later supplied
real assets, not to synthetic fixtures presented as professional proof.
