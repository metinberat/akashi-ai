# AKASHI Spatial Lab V1 — architecture

Spatial Lab is a camera-backed 3D workspace in which real 3D assets (primarily
FORM characters) are manipulated by hand gestures, natural language (typed or
spoken to AKASHI), UI controls and AKASHI tools — all through **one** validated
command path with one history.

**Honest scope.** V1 is *2.5D*: the camera image is a backdrop and hands move
objects on a plane at the object's own depth. There is no depth reconstruction,
occlusion, SLAM, world anchoring or physical hand/object contact. Measured
status per capability is in [the acceptance contract](acceptance/spatial-lab-v1.md).

## 1. Shape of the system

```text
 hand provider ─┐            ┌─ language (Spatial command bar, /chat, voice → /chat)
 (live camera / │            │
  recording /   │            │        UI controls, AKASHI tools (/tools, tasks)
  synthetic)    │            │               │
                ▼            ▼               ▼
   gesture pipeline     rule interpreter (+ optional model, JSON-validated)
   (frontend, per frame)          │
        │ intents                  │ requests
        ▼                          ▼
   gesture controller ──► ONE REQUEST CONTRACT (backend/app/spatial/requests.py)
   (lease, single commit)          │
                                   ▼
                     compiler: reference resolution, relative → absolute,
                     asset/FORM resolution, clip matching   (compiler.py)
                                   │  concrete commands
                                   ▼
                     lease / confirmation policy + dry run  (service.py)
                                   │
                                   ▼
                     pure reducer (domain.py) on ActionHistory (app/history)
                                   │  event: patches, digests, origin, request
                                   ▼
                     hash-chained JSONL log  ·  AKASHI event hub  ·  API snapshot
                                   │
                                   ▼
                     scene replica store (frontend) → three.js renderer
```

The **backend owns the scene**. The renderer draws `snapshot + explicit
transient previews` (only for objects currently held by a hand); there is no
second scene state. Gestures send *one* command when a manipulation ends, so
history stays meaningful (one undo step per grab).

## 2. Module map

| Path | Responsibility |
| --- | --- |
| `backend/app/history/` | **Reusable** action history: canonical digests, reversible verifiable patches, hash-chained crash-safe JSONL log, undo/redo, restore, deterministic replay verification. Domain-agnostic. |
| `backend/app/spatial/model.py` | Scene document schema, limits, factories. |
| `backend/app/spatial/domain.py` | Pure deterministic reducer (concrete commands only). |
| `backend/app/spatial/requests.py` | Public request contract (pydantic discriminated union) and `Origin`. |
| `backend/app/spatial/compiler.py` | Requests → concrete commands (references, relative ops, assets, clips, versions). |
| `backend/app/spatial/references.py` | Reference resolution with explicit `Clarification`. |
| `backend/app/spatial/language.py` | Rule interpreter (TR/EN) and optional model interpreter. |
| `backend/app/spatial/replies.py` | Deterministic TR/EN replies from what actually changed. |
| `backend/app/spatial/session.py` | Persistent sessions, leases, presence, corruption handling. |
| `backend/app/spatial/service.py` | The single submit path, confirmations, interpretation, metrics. |
| `backend/app/spatial/glb.py` | GLB validation, inspection, non-destructive normalisation. |
| `backend/app/spatial/assets.py` | Content-addressed asset registry (uploads, FORM, fixture). |
| `backend/app/spatial/form_library.py` | Read-only FORM library adapter (`form-library-read-1`). |
| `backend/app/spatial/tools.py`, `backend/app/live/actions/spatial.py`, `backend/app/api/spatial.py` | AKASHI integration: ToolRegistry tools, `/chat` live action, HTTP API. |
| `backend/app/spatial/contract.py` → `shared/contracts/spatial/` | Generated cross-language contract (request schema, replay fixture). |
| `frontend/src/lib/spatial/gesture/` | **Reusable** renderer-independent gesture engine (filters, tracker, poses, interaction, pipeline, synthetic hands). |
| `frontend/src/lib/spatial/providers/` | Input providers: live MediaPipe, recorded, scripted, mouse-simulated. |
| `frontend/src/lib/spatial/{client,scene-store,controller,replay,projection,calibration}.ts` | API client, replica store, gesture→command controller, replay reconstruction, shared camera rig, camera→viewport mapping. |
| `frontend/src/components/spatial/` | Product surface: `SpatialLab`, panels, three.js renderer, input runtime. |
| `desktop/app/security.cjs` | Video-only camera permission predicate. |

## 3. Scene document

```jsonc
{
  "schema": "akashi.spatial.scene/1",
  "objects": { "obj-<12 hex>": {
      "id": "...", "label": "Hero Prototype V03",
      "asset": { "asset_id": "<sha256>", "source": "form|upload|fixture", "clips": [{ "index", "name", "duration", "kind" }],
                 "joints": 57, "form_hud_nodes": 3, "normalization": { "scale", "offset", "size", "flags" },
                 "form": { "project_id", "version_id", "version_label": "V03", "identity_verified": true, ... } },
      "transform": { "position": [x, y, z], "rotation": [x, y, z, w], "scale": 1.0 },
      "visible": true,
      "display": { "skeleton": false, "form_hud": true, "bounds": false },
      "animation": { "clip": null, "playing": false, "speed": 1.0 } } },
  "order": ["obj-..."],
  "selection": ["obj-..."],
  "view": { "hud_visible": true, "vfx_visible": true, "inspector": null }
}
```

Conventions: glTF/three.js axes (+Y up, camera looks along −Z), metres,
quaternions `[x, y, z, w]` with a canonical sign, all floats quantised to 1e-6
so digests are platform-stable. Limits (bounded workspace, scale 0.1–10, 12
objects) come from `GET /spatial/capabilities` and are enforced by the reducer.

"HUD" means two different things and V1 keeps them apart:
`view.hud_visible` is Spatial Lab's overlay (labels, status), while
`display.form_hud` toggles FORM's own HUD geometry (`hud-ring-*` nodes) inside a
character. "Hide the HUD" → overlay; "hide its HUD" → FORM geometry.

## 4. One command path

Public request types (`shared/contracts/spatial/requests.schema.json`):
`scene.add_asset`, `scene.remove`, `selection.select`, `view.inspect`,
`object.transform` (`set`/`translate`/`rotate`/`scale`/`reset`/`center`/`to_anchor`),
`object.visibility`, `object.display`, `animation.control`, `object.version`,
`object.rename`, `view.set`, `history.undo`, `history.redo`.

Targets are `{"id": ...}` or semantic refs: `selected`, `deictic` ("it/that
one": selection → only object → last touched), `only`, `last_touched`,
`last_moved`, `leftmost`, `rightmost`, `largest`, `smallest`, `form`,
`latest_version`, `label`, `nearest_anchor`. Ties or missing context raise a
clarification with candidates; nothing is guessed.

Policy in `service.py`:

* **Leases.** A grab takes a 4 s renewable lease (renewed every 1.5 s). While it
  is held, other origins get `409 object_busy`, and undo/redo wait. The commit
  carries the lease id; an expired lease is refused (the client snaps back).
* **Confirmation.** `scene.remove` requires confirmation from every origin; the
  language path returns a token bound to the current revision. Model-proposed
  removals are discarded outright.
* **Dry run.** All concrete commands of a request are validated before any is
  recorded, so a multi-command request never half-applies.

## 5. Events, undo, redo, replay

Every accepted change appends an `akashi.action-event/1` event:
`seq`, `kind` (`command|undo|redo`), `origin` (`kind`, `provider`, `input`),
`request` (what was asked), `command` (what ran), `category`, `targets`,
`patches` (before/after per path), `digest_before`, `digest_after`,
`undoes`/`redoes`, `prev_hash`, `hash`. This answers *what happened, what input
caused it, what the state was before and after, which object, from which
origin* — the replay requirement.

* Undo/redo are events (the log is append-only). Selection and the inspector are
  recorded but not undoable; everything else is.
* `restore` rebuilds a session from patches, checking every digest
  (storage corruption → `423`). `verify_replay` re-executes every command with
  today's reducer and requires identical patches and digests (determinism).
* The client's replay view reconstructs states from recorded patches and stops on
  any inconsistency; `POST /replay/verify` proves determinism server-side.
* A torn final line (crash before the fsync'd append returned) is dropped and
  reported; any other damage fails closed.

**Reuse.** `app/history` knows nothing about scenes. Another AKASHI domain
(task replay, computer-agent audit, FORM workflows) supplies a pure
`apply(state, command)` and `reconcile(state)` and gets the same log, undo/redo
and replay guarantees.

## 6. Gesture engine

`HandFrame` (any provider) → `HandTracker` → `PoseClassifier` →
`InteractionEngine` → intents, with metrics from `GesturePipeline`.

| Problem | Mechanism |
| --- | --- |
| Landmark jitter | One Euro filter per landmark coordinate (image and world). |
| Hand size / distance | Pinch and curl use ratios to hand length (world landmarks when available). |
| Threshold chatter | Hysteresis (enter < exit), enter/exit dwell, cooldown after release. |
| Entry noise | New tracks must settle (120 ms) before any pose. |
| Fist vs pinch | Pinch requires the index finger partly extended (`minIndexExtension`). |
| Pointing vs grab | Grab requires every finger curled (`maxExtension`) — found with real MediaPipe data. |
| Missed detections / occlusion | Tracks coast for `graceMs`; manipulation freezes at the last stable transform. |
| Long tracking loss | Ends as `tracking_lost` at the last stable transform (no jump, no revert). |
| Detector glitches | Raw jumps above `outlierJump` are held one frame and accepted only if confirmed. |
| Teleports | Jumps beyond `matchDistance` become a new track; the old one coasts. |
| Left/right label flips | Identity is spatial; handedness is a decaying vote. |
| Release drift | On release the transform from before the release dwell is committed. |
| Two-hand conflicts | One manipulation at a time; a second hand joins it (scale by distance, yaw by twist); either hand leaving re-anchors without a jump. |
| Accidental grabs | Holds must start over an object (projected screen rectangle); air pinches do nothing. |

Tunables live in `gesture/config.ts`; those marked LOCAL ACCEPTANCE REQUIRED
must be tuned on the physical webcam. Camera mapping (`calibration.ts`)
reproduces the CSS `object-fit` crop and mirror so cursors sit over the hands;
`swapHandedness` exists because MediaPipe labels assume a mirrored image.

## 7. Input providers

All providers implement `HandInputProvider` and emit `HandFrame`s:

* `MediaPipeHandProvider` — `getUserMedia` (video only) + MediaPipe Hand
  Landmarker in VIDEO mode, `requestVideoFrameCallback` loop, GPU delegate with
  CPU fallback (selectable), explicit error codes (`camera_denied`,
  `camera_busy`, `camera_unavailable`, `model_missing`, `runtime_unavailable`).
  WASM and model are served locally (`npm run spatial:assets`).
* `RecordedHandProvider` + `HandRecorder` — validated recordings
  (`akashi.spatial.hand-recording/1`) with source, delegate and calibration;
  corrupt recordings are rejected. Use **Record hands** in the calibration panel.
* `ScriptedHandProvider` / `PointerHandProvider` — synthetic hands; the pointer
  version follows the mouse (button = pinch, `2` = mirrored second hand) and
  drives the real pipeline without a camera.

## 8. Assets and FORM

* **Validation** (`glb.py`): container, every index reference, acyclic node tree,
  embedded resources only, no decoder-only extensions, bounded sizes, finite
  bounds. Unbound skinned geometry is flagged (rendered static).
* **Normalisation** is display-only: ground-centre pivot, rescale only outside
  0.2–3 m (`rescaled_tiny`, `rescaled_enormous`, `rescaled_unit_mismatch`),
  `pivot_recentered` and `orientation_suspect_z_up` flags. The renderer applies
  it as a parent node; the source file is never touched.
* **Clips** are classified: `skeletal`, `hud_morph` (FORM HUD energy shape keys
  on `hud-ring-*` meshes, looped when FORM HUD and VFX are on), `morph`, `node`.
* **FORM** (`form_library.py`): reads FORM's `studio_projects`, `studio_links`,
  `studio_files` and `production_jobs` read-only; numbers versions exactly like
  FORM (`V01…` in production-link order); loadable = FORM-verified export inside
  the project directory; `latest`/`best`/`previous`/`next`/`V03` selectors; each
  load verifies the file's SHA-256 against FORM's export record
  (`identity_verified`). Experimental local-shape outputs are listed as such.
  FORM is never required: when absent, Spatial Lab reports it and works with
  uploads and the calibration fixture. FORM never needs Spatial Lab.
* The contract test `backend/tests/test_spatial_assets.py` builds a library
  with FORM's real `Projects` class; a FORM schema change breaks it loudly.

### Real FORM fixture

`backend/tests/fixtures/form/form-atelier-hud-seed57.glb` is genuine FORM output
content (57 joints, 3 HUD rings, FK clip, HUD shape keys). Regenerate with
`backend/scripts/form_spatial_probe.py <dir> <blender>`; on Windows pass
`blender.exe`. Without a Blender binary, a shim around the PyPI `bpy` module
works:

```bash
python3.11 -m venv bpyenv && bpyenv/bin/pip install "bpy>=4.2,<5.3"
cat > blender-shim <<EOF
#!$(pwd)/bpyenv/bin/python
import runpy, sys
argv = sys.argv[1:]; rest = argv[argv.index("--"):] if "--" in argv else []
head = argv[:argv.index("--")] if "--" in argv else argv
script = head[head.index("--python") + 1]; blend = next((a for a in head if a.endswith(".blend")), None)
import bpy
bpy.ops.wm.open_mainfile(filepath=blend, load_ui=False, use_scripts=False) if blend else bpy.ops.wm.read_factory_settings(use_empty=False)
sys.argv = ["blender"] + rest; runpy.run_path(script, run_name="__main__")
EOF
chmod +x blender-shim && backend/.venv/bin/python backend/scripts/form_spatial_probe.py /tmp/form-probe ./blender-shim
```

## 9. AKASHI intelligence

* **Rules first, offline.** `RuleInterpreter` covers the product phrases in
  Turkish and English (move to hand, bigger/smaller, rotate N°, show/hide rig,
  FORM HUD, overlay HUD, VFX, play/pause clips, load/switch FORM versions,
  center/reset, nudge, select/inspect, rename, hide/show, undo/redo, remove).
* **Optional model** (`AKASHI_SPATIAL_INTERPRETER=auto`, default): only when
  rules fail, the FAST profile proposes `{"requests": [...]}`; anything not
  matching the schema, any unknown object id and any removal is discarded.
  Mock providers are never used. `rules` disables the model path.
* **Channels.** Spatial command bar → `POST /spatial/sessions/{id}/interpret`.
  AKASHI `/chat` (typed or desktop voice) → `spatial.scene` live action, which
  matches only while a Spatial Lab client is connected (heartbeat ≤ 45 s).
  Tools: `spatial.scene`, `spatial.command`, `spatial.interpret`,
  `spatial.form_library` (safe), `spatial.confirm` (confirm risk).
* **"Move it to my right hand."** The client posts hand anchors (projected on
  the z = 0 plane) at ≤ 4 Hz; anchors older than 2 s are ignored and the user
  is asked to show the hand.

## 10. HTTP API (authenticated)

| Method & path | Purpose |
| --- | --- |
| `GET /spatial/capabilities`, `GET /spatial/metrics` | Limits, request types, FORM status, scope; submit latency p50/p95. |
| `GET/POST /spatial/sessions`, `GET /spatial/sessions/{id}?since=&client=` | Sessions; cheap polling (`changed:false`). |
| `POST /spatial/sessions/{id}/commands` | `{request, origin, confirmed}` → result + snapshot. |
| `POST /spatial/sessions/{id}/confirmations/{token}` | Accept/decline a pending destructive change. |
| `POST /spatial/sessions/{id}/interpret` | Natural language → requests → results + reply. |
| `POST /spatial/sessions/{id}/leases`, `POST …/leases/{lease}/renew`, `DELETE …/leases/{lease}` | Gesture manipulation leases. |
| `POST /spatial/sessions/{id}/presence` | Hand anchors (ephemeral). |
| `GET /spatial/sessions/{id}/events?after=`, `GET …/states/{seq}`, `POST …/replay/verify` | History, reconstruction, determinism proof. |
| `GET/POST /spatial/assets`, `GET /spatial/assets/{id}`, `GET …/content` | Asset registry and bytes. |
| `GET /spatial/form/projects`, `GET /spatial/form/projects/{id}/versions` | Read-only FORM library. |

Errors carry `detail` plus `code`, `kind` and, for clarifications, `question`
and `candidates`.

## 11. Running and testing

```bash
# backend
cd backend && .venv/bin/python -m unittest discover -s tests
.venv/bin/python -m app.spatial.contract          # contract artifacts current?
# frontend
cd frontend && npm run spatial:assets              # once: WASM + pinned model
npm run test:api && npx tsc --noEmit && npm run lint && npm run build
npm run test:e2e                                    # existing UI suite
npm run test:spatial                                # real Core + real MediaPipe suite
```

Settings: `SPATIAL_DIR`, `AKASHI_FORM_DATA_DIR` (defaults to FORM's Electron
userData under `%APPDATA%`), `AKASHI_SPATIAL_INTERPRETER=auto|rules`.

## 12. Remote presence (V1.5)

Other devices (iPhone, Mac, another laptop) join a Spatial Lab session through
[remote presence](remote-presence.md): they render the authoritative scene, drive
it with touch, on-device camera hands, text and voice, see other devices' live
previews and decide approvals they are allowed to. Every remote change is an
ordinary request with `origin.kind = "remote"` and device/session/modality
provenance; `GET /spatial/sessions/{id}/objects/{obj}/provenance` (and "why did
it move?") explains any object's state. Requests carry `base_revision`; leases are
owner-bound and released when a device leaves. Acceptance:
[remote-spatial-presence-v1-5.md](acceptance/remote-spatial-presence-v1-5.md).

## 13. Extension points (not implemented)

* Depth / occlusion / anchoring: add `z` from a depth provider into
  `InteractionEngine` (it already works in world space) and a depth-aware
  projector; the scene document needs no change.
* WebXR: a new `HandInputProvider`; remote devices already work (§12).
* Richer gestures: add pose machines in `poses.ts` and intents in
  `interaction.ts`; commands stay the same.
* Other domains adopting `app/history`: implement a pure reducer, store logs
  next to the domain's data, expose `verify_replay` in that domain's API.
