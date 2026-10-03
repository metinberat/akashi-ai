# Headless character production v1

This extends the existing V3/V3.1 expertise, workshop and self-training systems. It
does **not** claim professional character reconstruction from a single image.
No professional asset was provided or downloaded during development.

## Actual scope

**Working local procedural path:** typed design → seeded segmented quad-loft
humanoid → 57-joint skeleton → normalized spatial weights → fingers/toes/face
details → skinned clothes/accessories/hair → real UV loops → generated texture
tiles → optional chest-bound spatial HUD rings → immutable candidates → measured
defect correction → new Blender scene → saved-file reopen/readback → actual pose,
morph and camera tests → multi-view renders → animated, textured GLB → bounded
export validation/re-ingestion → source observations and technical experience.

**Partial:** whole-character visual quality, seamless retopology, collision-free
clothing, reference likeness, professional face/IK controls and target-engine
acceptance. The procedural body has separate intersecting shells. Cap fans are
triangles, not all-quad topology. Hair is tapered mesh strands, not a groom.
`JawOpen`/`Smile` are basic morph proposals, not certified facial deformation.
FK clips are demonstrations, not a production control rig. HUD rings are real
skinned mesh effects with morph/emission animation, not application HUD or PNGs.
Material animation and procedural shader nodes are not guaranteed to survive
glTF; the `.blend` is the complete presentation artifact.

**Supplied-asset mode:** ingested `.blend` source hash must match. A NEW presentation
copy can be lit/rendered/exported. Geometry, joints, skins, animation and assigned
materials are compared after reopen. Unassigned orphan datablocks can be purged
by Blender saving; original source bytes stay unchanged. This mode does not
silently replace a supplied professional character with the procedural generator.
Existing protected V3.1 workshops remain the separate rig/weight-edit path.

## Domain boundary

`app/expertise/production` owns contracts, authoring, evaluation, immutable trial
storage, numeric practice, reference adapter and host orchestration. It reuses
the existing expertise SQLite store/document pool, recipe memory, training method
versions, RAG, skills and experience records. Generic Core registers only typed
tools/router and the replaceable host. DCC-specific work stays in the fixed
Windows Agent Blender adapter. No new UI, model downloads or parallel voice brain.

The reference adapter uses the existing ModelRouter. `use_models=false` by default.
Image input is bounded and memory-only; durable state contains its SHA-256 and a
strict design proposal, never base64 pixels. Unknown/back anatomy remains unknown.
Explicit design overrides inferred design. Mock is rejected as reference
intelligence. Missing/invalid provider results are `unavailable`, not fabricated
vision. Colors have normalized channel bounds in both schemas and process guards.

## Technical evaluation and learning

Numeric gates measure face degeneracy, nonmanifold/boundary defects, normalization,
quad ratio and radial chord approximation. Garment clearance is explicitly a
**declared construction clearance**, not a collision certification. Baseline
radial=8/clearance=.006 fails; correction increases radial samples and clearance.
Only a passing lower-loss candidate becomes the immutable numeric best.

Blender verification reopens the saved scene and compares actual joint positions,
hierarchy, faces, vertices, weights and UV loops with the accepted canonical
document. Five joint probes × three angles × actual meshes test finite deformation
and sampled edge strain/collapse. Facial and HUD morph displacements are measured;
HUD chest motion is observed. Front/three-quarter/back camera framing is sampled.
These are technical quality gates, **not** perceptual/anatomical expert scoring.

Full-character practice varies height, head/shoulder proportions, build, hair,
clothes and effects. Existing independently promoted weighting parameters can be
adapted as bounded priors, with source method/evidence retained. Production method
support is deduplicated by actual geometry/rest fingerprints, not run count.
Three independent supporting worlds can publish compact computed RAG evidence
and **candidate**, never auto-active, skills. This is scoped synthetic evidence;
no artist/professional authority or universal causal principle is inferred.
Actual DCC completion separately persists application evidence and a technical
experience, then ingests saved source observations into existing expertise memory.
No neural model training was performed.

## State, ownership and recovery

SQLite `production_jobs`, `production_trials` and a fenced single-worker lease
share the existing expertise database. Trial documents are content-addressed and
immutable. Workers renew ownership at phase commits. Outputs are new UUID-named
files under Agent-approved roots; no overwrite of source/best artifacts.

Each external effect records `inflight` BEFORE execution and a `done` receipt
AFTER verified completion. Pause/cancel are honored at safe phase boundaries;
they do not forcibly kill a DCC halfway through saving. Resume skips done effects.
An ambiguous effect or worker expiry becomes `paused_recovery`; it is not blindly
replayed. Explicit reconciliation reopens and compares the owned saved character,
preserves its `.blend`, and gives remaining renders/exports new paths. Unknown or
changed source state fails closed. Restart does not auto-resume production.
Graceful Core shutdown requests a boundary pause and waits for its owned worker.

`numeric_ready` means only computed authoring passed. `completed_partial` means
technical DCC/readback/render/export passed, with artistic/reference requirements
still listed. Dispatch never means completed. The host is replaceable for a
future independent service; current DCC host expects approved Windows paths.

## API / orchestration

All routes require existing Core bearer authentication:

- `POST /expertise/production` — persist explicit build objective.
- `GET /expertise/production`, `GET /{id}` — actual jobs/trials/events.
- `POST /{id}/numeric?steps=6` — bounded local authoring/correction slice.
- `POST /{id}/start` or `/resume` — explicit background DCC dispatch (202).
- `POST /{id}/pause`, `/cancel` — safe phase-boundary control.
- `POST /{id}/reconcile` — explicit saved-effect readback, never blind retry.
- `GET /{id}/best` — accepted canonical numeric state.
- `GET /lessons` — scoped computed method evidence.
- `POST /practice?count=3&seed=57` — bounded varied full-character numeric practice.
- `GET /{id}/dataset?include_synthetic=true` — provenance/input/knowledge/decision/
  method/quality/correction target/world-group records. Synthetic excluded by default.

Example body for create:

```json
{
  "brief": "Build a synthetic stylized humanoid with a coat and character-linked rings",
  "design": {"height": 1.8, "clothing": "coat", "hair": "short", "hud": true},
  "max_candidates": 3,
  "output_directory": "C:/YOUR/APPROVED/CHARACTER/OUTPUT"
}
```

Without an output directory, numeric-only operation works without Blender/Agent.
For supplied sources add `source_asset_id` and matching approved `source_project`.
First ingest through the existing fixed Blender inspection adapter so original
application SHA-256 is retained. Direct FBX parsing and automatic imports of
untrusted application scripts are not enabled.

Core tools: `character.build`, `character.production_status`,
`character.practice_production`, `character.production_control`.
Status is SAFE. Build/practice/state-changing control require explicit CONFIRM.
All execution remains typed, authenticated, bounded, `shell=False`, fixed script,
`--disable-autoexec`, approved roots, no model-generated Python/MEL/shell.

## Export / ingestion

Agent verifies GLB headers/chunks, embedded resources, buffer ranges, accessor
layouts, dense and sparse morph correspondence, ordered sparse indices and
mesh/node/skin/animation references. Backend parser version `interchange-1.1`
decodes bounded sparse overlays, surface vertex attributes and morph deltas.
Missing external buffers remain unavailable; no network fetch. The original
binary remains the provenance source. Raw `morph_target_deltas` are object-local
deltas, not mislabeled absolute shape-key positions.

## Reproducible validation

Run from `backend` with its existing virtualenv:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_character_production tests.test_expertise_sparse
.\.venv\Scripts\python.exe -m tests.physical_character_production_smoke
```

Optional `--reference PATH_TO_OUR_GENERATED_PNG` exercises real configured vision
→ strict proposed design → local build/render/export/re-ingestion. Never supply
private/professional media to a provider without the appropriate user choice.
`physical_production_source_smoke` tests an explicitly generated source copy;
`physical_production_resume_smoke` reconciles an interrupted owned test job without
rebuilding its already saved character. These harnesses own only isolated test
Agent processes and never stop unrelated user services.

The dedicated 3D product UI, human quality review, professional asset transfer,
learned/neural reconstruction, seamless anatomy and production facial/cloth/IK
systems remain future work, not quietly declared completed.
