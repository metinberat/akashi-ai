# Character Workshop V3.1

This is an executable, non-destructive improvement domain, not an assertion of
professional character-production expertise. No real professional character asset
was supplied or downloaded. All validation assets are explicitly synthetic.

## Boundary and execution

`backend/app/expertise/workshop/` contains typed proposals, bind-space geometry,
quality evaluation, a closed controller, immutable version storage and evidence
aggregation. It imports neither Electron nor model providers. Expertise/storage
and objective-safety checks are injected through ports. `blender_workflow.py` and
`tools.py` are host adapters. Core changes are composition and lifecycle only.

Existing V3 ingestion, canonical structures, source hashes, expert memory and RAG
are reused. Existing Windows Agent approval, approved roots, discovered Blender,
fixed scripts, subprocess argument arrays and `--disable-autoexec` are reused.

The bounded loop is:

1. Retrieve scoped numeric expertise and previous improvement evidence.
2. Analyze the actual target; generate typed repair/construction proposals.
3. Apply a proposal to a deep copy of the **best** version, never the source.
4. Measure integrity, bind proximity, weight variation and train/held-out poses.
5. Reject regressions; atomically retain an accepted document and best pointer.
6. Try alternative strengths/strategies; persist successes **and** failures.
7. Optionally materialize to a NEW Blender file through the Windows Agent.
8. Reopen the saved file, verify exact weights and test actual modifier geometry.
9. If application evidence rejects quality, invalidate the branch, restore the
   source baseline and queue bounded correction alternatives. The exact failed
   document cannot be accepted again for the same source digest.
10. `refine-blender` closes the application loop: run numeric proposals, apply,
    verify, and replan/retest actual quality rejection under one explicit approval,
    up to three application cycles within the original attempt budget. Budget
    exhaustion returns `needs_review`, never a fabricated verified result.

An Agent transport error means application verification is unavailable. It does
not falsely disprove a numerical result. Unverified artifacts are never reported
as accepted application results.

## Operations and quality

- Normalize weights; prune bounded influences; adjacency-based weight smoothing.
- Target-geometry bone-segment distance binding, with bounded influence count.
- Explicit target-landmark joint construction/alignment for declared shared-bind
  coordinates. Existing animation, bind matrices and constraints block rest edits
  unless a proper retarget/bind application adapter is available.
- Geometry, UVs, materials, modifiers, morph metadata, objects and animations are
  protected. Existing joints and meaningful skin coverage cannot disappear.
- CPU probes apply single-joint rotations inherited by descendants using linear
  blend skinning. Fixed train and held-out bending/twist probes test edge strain,
  surface-area distortion, collapsed edges/faces and evidence coverage.
- Per-pose regression gates prevent a better average score hiding a local defect.
- Blender probes read actual evaluated meshes, including the modifier stack.
  Saved weight readback is performed inside Blender, not truncated through chat.

Pose testing is unavailable when coordinate correspondence is unknown. In
particular, generic glTF local transforms are not guessed into a common bind
space. Weight integrity can still be tested, but no deformation-quality claim is
made. The numerical loss is not an artistic score or a professional certificate.

## Persistence, recovery and learning

SQLite WAL tables coexist with V3 in `EXPERTISE_DB`. Source binaries are not copied
into each version. Candidate documents are content-addressed and deduplicated;
versions/attempts are append-only. Best-pointer changes and checkpoints are atomic.
An expiring 120-second lease fences duplicate workers. Backend loss never triggers
silent re-execution; expired work is `paused_recovery` and requires explicit resume.
Graceful shutdown/cancellation stops at a bounded operation/checkpoint boundary.
Evaluator revision changes require a new run; historical evidence is not rewritten.

Experience includes goal, target/source digest, retrieved knowledge, decision
basis, proposal, parent version, observed metrics, decision, actual application
evidence, correction and current best. Repeated attempts on the same source hash
count as **one** independent source. A structural fingerprint also groups renamed
or metadata-only re-exports, preventing artificial evidence/dataset inflation.
Synthetic/real evidence stays separate.
Three independent positive sources can strengthen a scoped numeric strategy;
they do not create universal rigging truth. Failed application candidates are
negative evidence; transport failures are not technical quality labels.

RAG exposes these computed experiences as untrusted, provenance-linked evidence.
It cannot execute prose, approve tools or promote itself to validated professional
knowledge. Dataset exports retain positive/negative labels, policy/evaluator
revision and source-hash split groups. Synthetic records are excluded by default;
labels explicitly are measured policy preferences, not artistic ground truth.
Actual application rejection overrides a numeric-positive dataset label. Transport
failure remains `unverified`, not a negative technical label; it does not block
rollback to an otherwise accepted numeric checkpoint.

## API and Core tools

All routes require the existing Bearer token:

- `POST /expertise/workshops`: `asset_id`, optional objective/proposals, 1–16 attempts.
- `GET /expertise/workshops`, `GET /expertise/workshops/{id}`.
- `POST /expertise/workshops/{id}/run?steps=2`: bounded work; explicit resume.
- `POST /expertise/workshops/{id}/cancel`.
- `GET /expertise/workshops/{id}/versions`, `GET /expertise/versions/{version_id}`.
- `POST /expertise/workshops/{id}/rollback`: accepted `version_id` of this job only.
- `GET /expertise/workshops/{id}/weight-patch`.
- `POST /expertise/workshops/{id}/materialize-blender`: explicit approved absolute
  Windows `project` and `output_directory`; outputs are new uniquely named files.
- `POST /expertise/workshops/{id}/refine-blender`: same explicit paths plus optional
  `max_cycles` (1–3). Automatically correct/retest actual application rejection;
  ambiguous transport failure is not blindly retried.
- `GET /expertise/workshops/evidence`, `GET /expertise/workshops/dataset`.

Registered Core tools: `character.improve` (CONFIRM),
`character.improvement_status` (SAFE), `character.materialize_blender` (CONFIRM),
`character.refine_blender` (CONFIRM).
They work through the existing ToolRegistry/TaskEngine approval boundary.

Autonomy Hub has a compact measure/improve, resume, cancel and source-rollback
surface. Agent Dock now links to that already-existing workspace. Desktop's main
presentation, general Web/Mobile navigation, voice, Identity and Miss Minutes are
not redesigned or replaced.

## Bounds and honest limitations

- Detailed canonical data retains V3's 200,000-vertex budget.
- CPU spatial rebinding: 20,000 vertices per mesh, at most 128 eligible joints.
  Larger targets need an accelerated/specialist binding adapter; ordinary weight
  normalization/pruning does not falsely advertise that adapter exists.
- CPU deformation probes: up to eight active joints and 4,096 distributed surface
  edges. Sampling and missing evidence are explicit. This is not all-pose coverage.
- Blender application patches: 32 MiB, 200,000 vertices, complete bone palette,
  exact geometry fingerprint, no arbitrary Python. Large patches use 24,000-byte
  hash-checked chunks through the same approved typed action. General file-read,
  text-write and paired-action limits are not loosened.
- Staging refuses symlink/junction redirection and hard-linked internal files;
  writes are exclusive and cannot overwrite existing source artifacts.
- Interrupted patch transfers may leave clearly named staging/artifact files in
  the explicitly approved output directory; they are not accepted outputs.
- Actual topology-changing modifier correspondence is refused rather than guessed.
- Landmark-created/rest-edited rigs are canonical variants. The weight-only Blender
  adapter deliberately refuses them; a fixed rig/retarget adapter is still needed.
- No automatic anatomical landmark detector, master facial/IK rig construction,
  volume-conservation solver, visual aesthetics grader or learned rigging model is
  claimed. Rendering evidence exists, but visual quality is not model-certified.

The first user-supplied real asset should establish format, rest/bind conventions,
success criteria and reference poses. Ingest it before attempting production edits.

## Reproducible local checks

From `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe tests\physical_character_workshop_smoke.py
```

The physical smoke creates a 1,040-vertex synthetic articulated Blender limb with
damaged skin, runs actual corrections, stages a large patch, writes/reopens a NEW
`.blend`, compares ten actual application probes, renders and verifies that the
original `.blend` hash is unchanged. Reports/artifacts live under ignored
`backend/data/private/v31-validation/<run-id>/`.
It starts a separate loopback Agent on an ephemeral port with a generated token,
proves unauthenticated access is rejected, and executes through the actual Core
`DesktopActionGateway` HTTP transport. It stops only that test-owned child.

Automated tests cover corrupted/unsupported inputs, coordinate spaces, protected
data, positive and negative variants, local per-pose regression, cancellation,
lease fencing/expiry, resume, rollback, scoped independent evidence, source
instruction inertness, approval, authenticated API, chunk tampering/replay and
browser checkpoint UI. Packaged Electron checks exercise V3.1 through secure IPC
and confirm best-version/weights persistence across a real Core process restart.
Refinement tests force an application-quality rejection, prove replanning/retesting
uses a different candidate, enforce the original attempt/cycle budgets, and show
ambiguous transport failure is not replayed. Those forced-failure cases are
deterministic integration fixtures, not a claim of artist-grade failure detection.

## Recorded validation — 2026-10-02

- Backend: **130 passed**; Windows Agent: **19 passed**.
- Frontend API/contracts: **22 passed**; browser/UI: **13 passed**.
- Electron security/runtime unit tests: **9 passed**.
- TypeScript, ESLint, Next.js production build and static export passed.
- Actual Blender **5.2.2 LTS**: 1,040 synthetic vertices, six attempts, two accepted
  and four rejected; CPU loss `0.732161 -> 0.058103` (lower is better).
- Ten actual Blender pose probes: mean log edge strain
  `0.084426 -> 0.006759`; no collapsed edges before/after. This is measured numeric
  deformation evidence, not a visual/artist quality grade.
- The 104,352-byte patch traversed five authenticated HTTP chunks. Saved weights
  were read back, geometry matched, and the original source SHA-256 was unchanged.
- NSIS installer built. Packaged Electron launched, exposed V3.1 over secure IPC,
  reused the single instance, recovered a killed Agent, preserved the best version
  and weights through an actual Core kill/restart, cleaned up owned children and
  relaunched successfully. Current backend/Agent resource hashes matched source.
- Static-bundle scan found no configured secret values; packaged resources contain
  no `.env` files. Private validation binaries/databases/reports remain ignored.
- Python dependency consistency and full frontend/Electron dependency audits passed
  (zero reported npm vulnerabilities).

The installer is **unsigned**, uses the existing default Electron icon, and still
requires the configured local Python/dependencies and Blender for local operations.
It is not a new self-contained runtime distribution. Android/iOS were not rebuilt;
no native configuration or default Web/Mobile presentation changed in this pass.
Human voice acceptance and long-horizon V2 acceptance were not repeated.

## Important implementation files

- Domain: `backend/app/expertise/workshop/{contracts,geometry,evaluation,operations,
  repository,service,application}.py`.
- Host adapters: `backend/app/expertise/{blender_workflow,tools,service,schema}.py`,
  `backend/app/api/expertise.py`, Core tool composition and shutdown.
- Fixed application bridge: `desktop/agent/akashi_agent/{blender_bridge,
  character_patch,actions,security}.py`; computer action-schema descriptions.
- Existing UI integration: `frontend/src/components/expertise-summary.tsx`,
  Agent Dock's Autonomy Hub link, and `frontend/src/lib/absolute-api.ts`.
- Tests: `backend/tests/test_character_workshop.py`, focused expertise API tests,
  `backend/tests/fixtures/{workshop_characters,create_workshop_blender}.py`,
  `backend/tests/physical_character_workshop_smoke.py`, Agent safety tests,
  frontend contract/browser tests and packaged-runtime restart tests.
