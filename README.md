# AKASHI ABSOLUTE — Pre-Astra

AKASHI is one shared AI interface for Web, Android, iOS, and Windows Desktop.
FastAPI is the central orchestration boundary: clients never connect directly to
Ollama, Gemini, ComfyUI, search providers, or the Windows Agent.

## Repository map

- `backend/` — FastAPI Core, providers, chat/images, Memory V2, research,
  tools, tasks, files, devices, and authenticated events.
- `frontend/` — statically exported Next.js interface shared by the browser and
  Capacitor Android/iOS shells.
- `desktop/app/` — hardened Electron shell for the same static interface.
- `desktop/agent/` — loopback-only Windows telemetry/action service and secure
  Core relay.
- `docs/` — architecture, development, and security details.

The established `/health`, `/chat`, and `/image/*` contracts remain available.
New system capabilities are additive under `/memory`, `/research`, `/tools`,
`/tasks`, `/files`, `/devices`, `/events`, and `/system`.

Start with [Development](docs/development.md), then review the
[Architecture](docs/architecture.md) and [Security model](docs/security.md).
