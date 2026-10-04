# Security model

## Trust boundaries

FastAPI is the only externally reachable service. Ollama and ComfyUI remain on
loopback. A public HTTPS tunnel may point to FastAPI only. Personal data and AI
routes require `Authorization: Bearer <AKASHI_API_TOKEN>`; `/health` and the
single-use device pairing exchange are intentionally unauthenticated.

The Windows Agent is a separate local trust domain. Its supported launch command
binds only to `127.0.0.1`, and its API requires an independent token of at least
32 characters. A paired relay uses a distinct per-device credential.

## Local action policy

- `safe`: telemetry, selected process state, directory listing, filename search,
  and metadata inside configured roots.
- `confirm`: application/project launch, reveal, screenshot, and a locally
  registered npm script whose project path, script name, and `package.json`
  digest match the administrator-controlled registry.
- `restricted`: credential access, arbitrary shell/PowerShell, security-setting
  changes, destructive filesystem operations, privilege escalation, and
  persistence. No generic restricted endpoint exists.

Executables come from a discovered allowlist. Subprocesses receive argument
arrays with `shell=False`, timeouts, and bounded output. Project scripts are
disabled unless `AKASHI_AGENT_SCRIPT_REGISTRY` names an exact approved project,
script, and package digest; the action also verifies those values at execution.
Screenshots
are one-shot, explicit, size-bounded captures; no hidden/continuous capture is
implemented.

## Files and uploads

Backend uploads enforce byte limits and extension/type constraints. Storage
paths are generated server-side. Uploaded-file APIs accept IDs, never caller
filesystem paths. ComfyUI image view parameters reject filename/subfolder
traversal. The Windows Agent separately canonicalizes local paths and requires
them to be descendants of configured allowed roots.

## Secrets and storage

- Backend provider keys and the personal API token belong only in ignored
  `backend/.env` or the process environment.
- Android uses KeyStore-backed Capacitor secure storage; iOS uses Keychain.
- Electron encrypts connection settings in the main process using Windows DPAPI.
- The Windows Agent encrypts its pairing credential with current-user DPAPI.
- Long-term memory refuses common password/token/API-key/private-key patterns.
- Device and task runtime documents, uploaded files, captures, build output, and
  all `.env` files are ignored by Git.

Do not put secrets in `NEXT_PUBLIC_*`; those variables are compiled into the
shared client bundle. Rotate both the FastAPI token and paired-device identity if
a device is lost. Revoke the device in the Devices panel as well as deleting its
local credential.

## Spatial Lab (camera, WebAssembly, scene actions)

- **Camera permission (desktop).** Electron previously denied every renderer
  permission. It now grants exactly one: a `media` request whose media types are
  `["video"]` only, from the `akashi://app` **main frame**
  (`desktop/app/security.cjs` → `allowPermissionRequest`, tested in
  `tests/security.test.cjs`). Microphone, combined audio+video, screen capture,
  geolocation, notifications, clipboard and all other permissions stay denied.
  Voice capture continues to run in the separate Python workers.
- **Frames stay local.** Hand tracking runs MediaPipe Hand Landmarker inside the
  renderer. Camera frames are never uploaded; only landmark-derived hand anchors
  (two 3D points with a confidence, ≤ 4 Hz) are posted to Core while Spatial Lab
  is open, kept in memory for 2 s and never persisted.
- **CSP.** `script-src` adds `'wasm-unsafe-eval'`, which permits WebAssembly
  compilation only (needed by the local MediaPipe runtime). JavaScript `eval`
  remains forbidden. The WASM files and the model are served from the app
  origin; the model is fetched once by `npm run spatial:assets` and installed
  only if its SHA-256 matches the pinned value.
- **Scene-bounded actions.** `spatial.*` tools and the `spatial.scene` live
  action change only the Spatial Lab scene document. They cannot touch files,
  the desktop, the browser or the Windows Agent. Removing an object needs
  confirmation (UI dialog, `spatial.confirm` tool with `confirm` risk, or an
  explicit confirm token for language); model-proposed removals are discarded.
- **FORM data is read-only.** The FORM adapter opens `expert.sqlite3` with
  `mode=ro`, only serves GLBs inside the FORM project directory (no symlinks),
  and refuses a file whose SHA-256 differs from FORM's export record.
- **Uploaded GLBs** are bounded (20 MiB upload, 48 MiB inspection), fully
  validated (container, every index reference, node hierarchy acyclicity), may
  not reference external or data URIs, and may not require decoder extensions
  (Draco/meshopt/KTX2). They are stored content-addressed and never modified.
- **History integrity.** Session logs are hash-chained; edited, reordered or
  truncated logs fail closed (`423 session_corrupted`) instead of being repaired.
  Credential-like text in language commands is redacted before it is recorded.

## Known boundaries

The JSON stores are appropriate for one personal Core process, not a horizontally
scaled deployment. Before multi-user/public production, migrate them to a
transactional database, add account-scoped authorization, request throttling,
audit retention, and a production job queue.
