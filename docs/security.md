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

## Known boundaries

The JSON stores are appropriate for one personal Core process, not a horizontally
scaled deployment. Before multi-user/public production, migrate them to a
transactional database, add account-scoped authorization, request throttling,
audit retention, and a production job queue.
