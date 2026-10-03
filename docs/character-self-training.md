# Character self-training engine v1

This extends V3/V3.1. It does not replace Computer Agent V2, the workshop, Core,
voice, identity, images, Miss Minutes, or any client presentation.

## What actually learns

This is evidence-driven workflow/parameter learning, **not neural-network weight
training**. A typed portfolio competes on varied generated worlds. Independent
validation outcomes guide exploration, preserve method champions, produce scoped
skill candidates, and advance the curriculum. Failed trials remain retrievable.

The domain is in `backend/app/expertise/training`: contracts, recipes, synthetic
worlds, workflow compiler, reference evaluator, repository and controller. It
imports no FastAPI, Electron, model provider or desktop service. `host.py`,
`blender.py`, API routes and tools are replaceable AKASHI host adapters.

### Production recipes

Every newly ingested/cached character obtains a versioned recipe with geometry,
skeleton/rest/constraint, skin, surface-network and animation relationships.
Original observations, computed metrics, name-based anatomical inference and
proposed validation stages remain distinguishable. Historical author intent and
historical order of operations are **unknown**, not reconstructed facts.

Recipes are source-linked, additive and non-executable. A geometry/rest fingerprint
prevents renamed exports from manufacturing independent source support. Synthetic
and real source groups remain separate. Source finger patterns alter procedural
chain depth; observed influence limits inform the bounded method portfolio. No
source script or driver expression becomes an execution instruction.

### Practice and improvement

- Six families: defective normalization; corrupted binding; missing hand/finger
  rig; twist/foot/toe structures; missing unusual-proportion torso/head rig;
  layered surfaces. Seeds vary proportions, bone naming, tessellation and target
  weight falloff. These are labelled procedural segments, not anatomically realistic
  professional characters.
- Public synthetic region/parent/orientation labels and target geometry are available to the
  compiler. Exact reference joint positions/weights are not. Reconstruction uses
  target-geometry principal axes, not copied source skeleton coordinates.
- Typed methods normalize, estimate landmarks where supported, construct joints,
  bind spatially or by explicit synthetic regions, and optionally smooth. They
  reuse V3.1 operations. Raw retrieved text cannot choose code or shell execution.
- Every candidate starts from the same immutable input. Candidates are compared
  using reference weights, joint positions/hierarchy, isolated held-out LBS poses,
  normalization and protected geometry/material/UV/animation data. An operation
  completing does not imply its result passed.
- Best pointers advance only for a measured improvement with intact protected
  data/hierarchy/coverage. Earlier candidates and the initial/reference states
  remain content-addressed. Rejected candidates cannot poison the next attempt.
- Uncertainty-bounded selection uses previous independent trials and keeps the
  incumbent. A method needs at least three independent paired validation wins and
  posterior confidence >=0.65 to become a new champion. Prior champion versions
  remain immutable. Contradictory trials reduce current evidence confidence.
- Three independent validation successes in **every active recipe family** advance a level. This is mastery of a
  **synthetic family**, never a professional mastery claim.
  New runs skip already-supported trivial levels by default; `adaptive_start=false`
  permits an explicit benchmark replay. Different source-guided finger conventions
  cannot borrow one another's curriculum completion.

The evaluator is an isolated CPU linear-blend-skinning harness. It does not simulate
all Blender constraints, IK/FK, cloth, dual-quaternion behavior, facial expression
quality or artistic production standards. Actual Blender probes provide separate
application evidence, not automatic artistic certification.

### Evidence, skills and datasets

Attempts preserve input hash, available recipe/method evidence, selection rationale,
typed workflow, candidate hash, metrics, failure analysis, correction, prior best
and final target. Experiences enter existing expert memory. Promoted workflows
become **candidate** skills with synthetic provenance; no automatic activation or
promotion of manually validated expert knowledge occurs.

Partitioning is deterministic from the actual reference structure, not run names or
scores. Repeating a world adds no independent support. Train/validation rows guide
learning; locked test rows never guide selection, promotion or curriculum.
Validation is online selection evidence, **not a pristine final test set**. Cross-
generator and real-asset heldouts are still required for broad generalization.

Dataset exports retain both positive and negative paths, source recipe, immutable
input/result/best/reference hashes, versions, provenance and partition. Synthetic
records are excluded unless explicitly requested. Reference labels are identified
as analytic synthetic labels, not professional ground truth. Full input/best/reference
documents can be fetched separately by exercise. No model download, fine-tuning or
remote dataset upload is performed.

## Durability and compute

Additive SQLite/WAL tables share the existing expertise database. Large source blobs
are not duplicated per attempt; document bodies are content-addressed in the V3.1
document pool. Candidate/cursor/best commits are atomic; exercise completion and its
experience-learning record share one transaction, so a failed write can resume
without repeating committed candidates or silently losing the lesson. A run lease and a database-
wide numeric compute lease fence duplicate workers across Core processes.

Runs are explicit, capped at 128 exercises with 2–8 candidates; each numeric slice
is capped at 32 exercises/300 seconds. Pause/cancel are checked between bounded
candidates. Restart never silently resumes work. Expired workers appear as
`paused_recovery`; old worker results cannot write after ownership changes. Changed
generator/trainer/recipe/evaluator versions require a new run. Graceful shutdown
requests pause and waits for the numeric boundary rather than cancelling a thread
and claiming it stopped.

## Rich source and Blender boundary

Existing JSON/OBJ/self-contained GLTF/GLB ingestion remains. The new authenticated
`ingest-blender` path inspects an approved local `.blend`, retrieves hash-checked
canonical JSON in bounded chunks, and ingests it through the same service. The
original binary stays at its approved source location; its SHA-256 is preserved
alongside the extraction hash. No external professional asset is downloaded.

Blender extraction now includes constraint/modifier parameters, loop UV coordinates,
bounded shape-key deltas, shader sockets/links/packed-image references, animation
handles/modifiers/slots, active actions/NLA metadata, and object/shape-key/material
driver descriptions. Driver expressions remain source data. Large meshes retain
counts/relations when detailed geometry exceeds the 200k-vertex budget. UV/shape data
are separately bounded; extraction over 32 MiB drops whole per-vertex datasets with
explicit unavailable markers, never truncates index correspondence silently.

Direct FBX import, Maya-native extraction, external GLTF resource resolution and
unbounded high-poly analysis are not added. Supply a `.blend` or supported canonical
export for now. Blender importer documentation was checked, but unsafe or untested
format support was not advertised: [Blender import API](https://docs.blender.org/api/5.2/bpy.ops.import_scene.html).

`stage_character`, `build_character`, `read_character_chunk` are narrow typed Agent
operations. Construction currently accepts only synthetic shared-bind data and
rejects unsupported constraints, transforms, morph targets and animations rather
than silently discarding them. The fixed bridge builds a NEW `.blend`, reopens it,
compares saved hierarchy/geometry/weights/UVs, runs actual modifier-space pose tests
and renders. Application evidence is stored separately. Failed/ambiguous operations
are not blindly replayed. No arbitrary Python or general file-stream endpoint is
exposed; approved roots, confirmation, loopback authentication, argument arrays,
bounded environment and `--disable-autoexec` remain.

## Headless use

All routes below require the existing Core bearer token. Use the configured Core
origin; never embed the token in a URL or source file.

1. Ingest via `POST /expertise/characters` or existing multipart
   `/expertise/characters/upload`. For `.blend`, call
   `POST /expertise/characters/ingest-blender` with absolute approved `project`,
   `output_directory` and `source` (`reference`, `category`, `synthetic`, optional
   version/license). Real assets use `asset_observation`/false; fixtures use
   `synthetic_fixture`/true. The extraction route does not upload the large binary.
2. Inspect `GET /expertise/recipes/{asset_id}` and `/expertise/recipes/patterns`.
3. `POST /expertise/training` with e.g.
   `{"source_asset_ids":["character-..."],"seed":151,"max_exercises":32,"candidates_per_exercise":8,"start_level":0,"max_level":5}`.
   Without sources, explicitly labelled procedural bootstrap practice is allowed.
4. `POST /expertise/training/{id}/start` (202) starts the bounded background run.
   Or use `/run?exercises=1&seconds=120` for a deterministic synchronous slice.
5. Inspect `GET /expertise/training/{id}`, `/exercises`, `/attempts`, and
   `/expertise/training/methods`. `/pause`, `/resume`, `/cancel` are explicit controls.
6. Fetch `/artifacts/{exercise_id}?version=best` (or input/reference).
7. `POST /training/{id}/export-blender` under `/expertise` with `exercise_id` and
   absolute approved `output_directory`. Inspect `/application-evidence` afterward.
8. Fetch `/dataset?include_synthetic=true` or `/dataset.jsonl?include_synthetic=true`.
   Optional `view=weights`, `view=joint_placement`, `view=preferences` yields bounded
   supervised or numerically ranked preference records. Vertex/weight correspondence
   remains exact; preferences are not invented from ties or attributed to artists.
9. `POST /expertise/training/apply-method` with target `asset_id` and immutable
   `method_version` creates a V3.1 workshop **proposal**, not a fabricated execution
   success. Synthetic segmented restrictions cannot be assumed on a real asset;
   spatial adaptation is labelled explicitly. Run/verify/refine that workshop
   through existing APIs. Missing real anatomy still requires explicit landmarks.

Core tools: `character.train_yourself` (confirm), `.training_status` (safe),
`.production_recipe` (safe), `.training_control` (confirm), `.apply_learned_method`
(confirm). They can be invoked via the existing authenticated tool/task APIs.
No dedicated UI is necessary; natural-language inference selecting these tools is
not a substitute for inspecting their returned status.

## Validation commands

From `backend`: `.venv/Scripts/python.exe -m unittest discover -s tests -p "test*.py" -q`.
Short physical test: `.venv/Scripts/python.exe -m tests.physical_character_training_smoke`.
It creates only local synthetic scenes and an isolated authenticated loopback Agent,
then stops its own child. Reports/artifacts go to ignored private validation storage.

Agent tests use the backend venv with `PYTHONPATH=desktop/agent`. Existing frontend
API/browser, types/lint/build and Electron security/runtime/package smoke remain
regression gates. No Android/iOS presentation changes require a rebuild.

## Recorded validation — 2026-10-03

- Backend: **149/149**, including source-injection isolation, paired evidence,
  family-scoped curriculum, expired-worker fencing, checkpoint resume, and atomic
  completion/experience recovery after an injected storage failure.
- Windows Agent: **22/22**; frontend API: **22/22**; browser/UI: **13/13**;
  Electron security/runtime unit tests: **9/9**. TypeScript, ESLint, Python
  compilation/dependency consistency, static production build and NSIS packaging
  passed. Source-runtime integration also exercised bounded crash-loop protection.
- The packaged executable was actually launched. Owned Core/Agent became ready,
  a second instance reused the stack, a deliberately killed Agent recovered,
  and actual Core restart preserved V2/V3.1/self-training checkpoints. Training
  did not automatically resume. Owned children stopped and relaunch recovered.
- Actual Blender validation: **4 exercises / 32 attempts**, **1,610 vertices and
  saved weights**, **5,520 UV loops**, **920 application pose measurements**.
  The saved NEW `.blend` was reopened, not merely assumed correct. Maximum numeric
  readback error was `2.36905e-7`; synthetic reference loss improved from
  `0.1548338` to numerical roundoff. This is analytic synthetic agreement, not an
  artist-quality score. Shape-key deltas, constraint parameters, shader links,
  animation handles and shape-key driver descriptions were reingested from an
  additional locally fabricated scene.
  Report: `backend/data/private/self-training-validation/e6999ee32d04/report.json`.
- New-domain obvious-secret scan, configured-secret checks against exported
  frontend bundles, and plaintext credential-file checks in packaged resources
  found no matches. This is a bounded diagnostic, not proof of universal security.
  Packaged domain/Blender bridge hashes matched source.
- `npm audit --omit=dev`: **0 findings** in frontend and desktop. Full developer
  dependency audits are **not clean**: frontend 5 high, desktop 8 high propagated
  findings, from two root advisories:
  [braces](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) and
  [http-cache-semantics](https://github.com/advisories/GHSA-ch52-4w7c-c8xp).
  Both advisories list no patched release at this check. Blind major toolchain
  downgrades were deliberately avoided; no audit suppression was added.
- The NSIS installer is **unsigned**, uses the existing default icon, and still
  requires the configured installed Python dependencies/Blender. Packaging does
  not create a self-contained Blender/Python distribution. Android/iOS native
  builds and human microphone acceptance were not performed in this milestone.

Important source entry points: `app/expertise/training/`,
`app/api/character_training.py`, `app/expertise/service.py`,
`app/expertise/store.py` (optional transaction participation),
`app/autonomy/skills.py` (candidate provenance), and narrow registrations in
`app/core/absolute.py`/`app/main.py`. Agent construction/extraction lives in
`desktop/agent/akashi_agent/character_document.py`, `character_patch.py`,
`blender_bridge.py` and the existing typed `actions.py` dispatcher.

## Honest remaining frontier

Ready: headless rich `.blend` inspection, recipes, varied numeric practice,
checkpointed attempts, paired method learning, synthetic skill candidates, datasets,
real saved Blender construction/readback/stress/render.

Partial: transfer to genuinely new professional anatomy, source-specific deformation
recreation, broader generator distributions and independent real-asset validation.

Foundation/unsupported practice: automatic facial/IK/FK production, topology design,
arbitrary shader recreation, learned geometry/weight neural models, Maya-native
execution. Observing these source structures does not mean they can yet be recreated.
The first real professional source and artist-quality acceptance are still external
requirements. No real professional character was analyzed in this milestone.
