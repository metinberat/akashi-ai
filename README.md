# AKASHI ABSOLUTE — Pre-Astra

AKASHI is one shared AI interface for Web, Android, iOS, and Windows Desktop.
FastAPI is the central orchestration boundary: clients never connect directly to
Ollama, Gemini, ComfyUI, search providers, or the Windows Agent.

One deliberate exception: the Windows Desktop always-on voice path opens a
Gemini Live native-audio session directly from the Electron shell, because
routing a bidirectional audio stream through Core would add the very latency the
path exists to remove. It still hands every tool, research, memory or system
request back to Core over `/chat`; only the conversational audio is direct.

## Repository map

- `backend/` — FastAPI Core, providers, chat/images, Memory V2, research,
  tools, tasks, files, devices, and authenticated events.
- `frontend/` — statically exported Next.js interface shared by the browser and
  Capacitor Android/iOS shells.
- `desktop/app/` — hardened Electron shell for the same static interface.
- `desktop/agent/` — loopback-only Windows telemetry/action service and secure
  Core relay.
- `docs/` — architecture, development, and security details.
- `shared/contracts/` — generated cross-language contracts (Spatial Lab requests
  and replay fixture).

The established `/health`, `/chat`, and `/image/*` contracts remain available.
New system capabilities are additive under `/memory`, `/research`, `/tools`,
`/tasks`, `/files`, `/devices`, `/events`, `/system`, and `/spatial`.

Start with [Development](docs/development.md), then review the
[Architecture](docs/architecture.md) and [Security model](docs/security.md).

Character expertise is a separate domain: [V3 ingestion](docs/character-expertise-v3.md)
and [V3.1 non-destructive Character Workshop](docs/character-workshop-v31.md).
The workshop applies typed modifications, compares measured variants, preserves
the best checkpoint and can verify saved Blender weights/deformation through the
controlled Windows Agent. Current physical validation uses synthetic assets only;
numerical tests are not professional or artistic quality certification.

**Spatial Lab V1** is a camera-backed 2.5D workspace where real 3D assets
(primarily FORM exports, read-only) are moved by hand gestures, natural language,
UI and AKASHI tools through one validated command path with undo/redo and
deterministic replay: [architecture](docs/spatial-lab.md) and
[local acceptance contract](docs/acceptance/spatial-lab-v1.md). Physical webcam,
GPU and packaged-desktop behaviour still require local acceptance.

AI agents working in this repository follow [AI_ENGINEERING_RULES.md](AI_ENGINEERING_RULES.md).
