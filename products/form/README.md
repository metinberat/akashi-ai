# FORM Character Studio

Independent, local-first character workspace. It starts its own loopback runtime,
project library and expert store; it does **not** start AKASHI Core, its Agent
HTTP server, scheduler, phone service or voice service. AKASHI's existing engine
integration is retained. Shared expertise/DCC library source is packaged from
this monorepo, not duplicated into a second intelligence implementation.

## Launch

From this directory:

```powershell
npm ci
npm start
```

Or run `dist/win-unpacked/FORM Character Studio.exe`, or the generated NSIS
installer. An installed Python 3.11+ environment with `server/requirements.txt`
and installed Blender are required. The development runtime uses the repository
backend virtual environment. A packaged first launch asks for a compatible
`python.exe`; `FORM_PYTHON` can configure it explicitly. No interpreter, Blender,
Ollama or model weights are included in the installer or automatically installed.

Settings can be placed in `form.env` in Electron's userData directory under
`%APPDATA%` (a `FORM_DATA_DIR` override selects an explicit directory).
See `.env.example`. Keep this private file outside application resources/source
control. Environment values override file settings. Projects, `expert.sqlite3`,
knowledge, evidence, renders and exports live under userData. Closing/reopening
preserves them; interrupted compute does not silently resume.

## Local core / optional intelligence

`FORM_EXTERNAL_MODELS_ENABLED=false` is the default. Disabling all providers does
not disable project production, numeric planning/evaluation, local reference
measurements, recipe/experience retrieval, rigging, rendering, HUD, export or
appearance practice. These are bounded technical methods, **not** a claim that
the deterministic path understands arbitrary artistic instructions.

Optional natural-language reasoning uses an already installed Ollama model:

```dotenv
FORM_REASONING_PROVIDER=ollama
FORM_REASONING_MODEL=qwen3:8b
FORM_OLLAMA_URL=http://127.0.0.1:11434
FORM_EXTERNAL_MODELS_ENABLED=false
```

The text model receives measured reference data, not fictitious vision input.
Reference alpha/uniform-background segmentation, palette, silhouette bounds and
complexity advice run locally. Complex backgrounds abstain from a character mask.
Model replies are strictly validated design proposals, never executable scripts
or automatic builds. The user reviews controls and explicitly builds a version.

Optional external vision is currently implemented through the existing Gemini
adapter behind a replaceable provider port. To choose that specialist, explicitly
enable external models and configure `FORM_VISION_PROVIDER`,
`FORM_VISION_MODEL`, `FORM_GEMINI_API_KEY`; its optional SDK dependencies are in
`server/requirements-cloud.txt`. Other vendor implementations are not
claimed to exist. An API is not necessary to continue the local workflow.

## Production and learning

New projects default to the `atelier` appearance profile: shaped head sections,
eyelids/irises/pupils, scalp and hair locks, coat lapels/trim and material response.
The legacy `classic` profile remains available. Both use the same 57-joint
anatomical skeleton, individual finger chains, weights and fixed Blender actions.
Character HUD consists of real rig-attached geometry and animated energy/material
effects, not an application overlay.

Production keeps immutable versions and verified receipts. Real Blender builds,
readback, pose tests, renders and GLB export gates are required. Status remains
`completed_partial`: technical validity does not certify artistic quality.
Pause/cancel use safe boundaries; restart recovery preserves ambiguous effect
intent and requires inspection/reconciliation before replay. Best-version pinning
is explicit. Export packages the selected verified artifacts and manifest, **not**
a complete portable backup of the entire project database.

Learning has two distinct intentional workflows:

- Existing rig/recipe self-training with synthetic exercises, evaluations,
  champions, failure memory and dataset export.
- Appearance practice: 1–3 actual Blender versions compared against a separable
  reference. Silhouette IoU/palette-distance proxies preserve the best comparable
  result and reject regressions. Accepted/rejected attempts, design, reference
  hash and evaluator version are persisted. Synthetic low-confidence observations
  enter retrieval; no result is promoted to universal professional expertise.

These mechanisms are evidence/parameter/workflow learning, **not neural model
fine-tuning**. The appearance proxy does not measure identity, anatomy, sculpting
quality, unseen surfaces or cinematic art direction.

## Experimental separately installed local learned shape

An optional Hunyuan3D-2mv adapter uses locally cached safetensors, local YAML and
an operator-installed SDK/Python environment. No weights are downloaded. It is
isolated from the standard rigged production path and disabled by default.

Read the [upstream model license](https://huggingface.co/tencent/Hunyuan3D-2/raw/main/LICENSE)
before enabling it. It has territorial, distribution/notice and model-training
restrictions. No vendor source/model is copied into FORM's source or installer.
Generated outputs are quarantined from expert ingestion, RAG, recipes,
self-training and dataset exports; known hashes are rejected even after rename
or cross-project upload. This is not a legal certification or a way to detect
arbitrary transformed/re-authored outputs. A future permissively licensed adapter
can replace this channel without changing the standard engine.

```dotenv
FORM_LOCAL_SHAPE_ENABLED=true
FORM_SHAPE_LICENSE_ACCEPTED=true
FORM_SHAPE_PYTHON=C:/absolute/installed-shape-runtime/Scripts/python.exe
FORM_SHAPE_SDK=C:/absolute/installed-sdk
FORM_SHAPE_CHECKPOINT=C:/absolute/cached-model/model.fp16.safetensors
FORM_SHAPE_CONFIG=C:/absolute/cached-model/config.yaml
```

Only enable these after making your own license/use decision. The worker uses
CUDA and CPU offload, offline model settings, a fixed script, no shell, no API
credentials, bounded output and a 600-second timeout. It does not start/stop
Ollama or unrelated applications. A single product compute owner guards starts
and resumes across production, training, practice and shape inference.

Transparent references are accepted directly. Opaque references require an
already cached `%USERPROFILE%/.u2net/u2net.onnx`; missing or partial masks fail
honestly and request a clean crop/alpha instead of generating accepted geometry
from a head-only mask. Foreground processing is inspectable.

Output is an experimental unrigged GLB with local front-projected vertex colors.
Hidden surfaces are inferred; this is not recovered UV texturing, production
retopology or professional likeness. It does not replace the 57-joint pipeline.
The viewer disables skeleton/animation controls when the GLB has neither.

## Headless interfaces

`python -m form_studio.runtime` accepts operator runtime configuration, binds a
random loopback port and requires `FORM_RUNTIME_TOKEN` of at least 32 characters.
Set `PYTHONPATH` to this `server`, repository `backend`, and `desktop/agent`, plus
`FORM_DATA_DIR` and `FORM_WEB_DIR`. Electron normally owns this lifecycle and
keeps the token out of the renderer.

All `/api/` endpoints require the local token and origin/host checks. Main routes:

| Workflow | Route |
| --- | --- |
| Project library/state | `GET/POST /api/projects`, `GET /api/projects/{id}` |
| Reference/asset upload | `POST /api/projects/{id}/uploads` |
| Partner proposal/design | `POST .../messages`, `PUT .../design` |
| Production | `POST .../build`, `POST .../runs/{run}/{pause,cancel,resume,reconcile}` |
| Best/export/artifacts | `PUT .../best`, `POST .../export`, `GET .../files/{opaque_id}` |
| Rig training | `POST .../training`, `POST .../training/{run}/{pause,cancel,resume}` |
| Knowledge/evidence | `GET .../learning`, `POST .../learning/export` |
| Visual comparison/practice | `POST .../visual/assess`, `POST .../visual/practice`, `POST .../visual/{pause,cancel,resume}` |
| Local learned shape | `POST .../shape` |

Shape jobs are inspectable in the project snapshot; exit stops the owned worker.
There is not yet a dedicated shape cancel/resume API.

## Security and current quality limits

Electron sandbox/contextIsolation stay enabled, renderer Node stays disabled.
No generic shell, script execution or broad IPC is exposed. Paths are confined
to project roots with opaque file IDs. Uploads/output/resources are bounded;
external GLB texture fetches are forbidden. Blender auto-exec is disabled, but
Blender itself is not an OS sandbox: treat untrusted `.blend` files cautiously.

Procedural characters remain stylized and segmented. Seamless professional
anatomy, likeness, groomed hair, cloth simulation, production facial rigs,
retopology and learned-mesh binding are not complete. The installer is unsigned
and currently uses Electron's default application icon.

See [validation.md](validation.md) for real executions, failures and status.
