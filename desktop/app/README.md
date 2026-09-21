# AKASHI ABSOLUTE Desktop

Electron reuses the same static Next.js bundle as Web, Android, and iOS. The
renderer is sandboxed with Node disabled. Backend settings are encrypted by
Electron `safeStorage` (Windows DPAPI) in the main process, and authenticated
requests pass through a narrow preload/IPC bridge so the persisted token is not
returned to the renderer.

Run the frontend production build first, then use `npm start`, `npm run pack:win`,
or `npm run dist:win` from this directory.

## Runtime ownership

- New Desktop installations default to `local` Core mode. Electron starts the
  packaged Core and loopback Windows Agent with encrypted, per-installation
  credentials. Mutable state is stored under Electron `userData`.
- `remote` mode connects to the configured HTTPS/VPS Core and never starts a
  local replacement. The loopback Windows Agent remains a supervised Desktop
  Body.
- Ollama and ComfyUI are detected only. Desktop never starts or stops them.
- Python 3.11 is currently an explicit runtime prerequisite. Override discovery
  only with an existing absolute executable through `AKASHI_RUNTIME_PYTHON`,
  `AKASHI_BACKEND_PYTHON`, or `AKASHI_AGENT_PYTHON`.

Runtime logs are bounded and credential-redacted at
`<userData>/logs/runtime.jsonl`. Core/Agent mutable data is never written into
ASAR or packaged resources.
