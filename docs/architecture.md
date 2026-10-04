# AKASHI ABSOLUTE architecture

## System shape

```text
Shared Next.js UI
├─ Web
├─ Capacitor Android
├─ Capacitor iOS
└─ Electron Windows Desktop
        │
        ▼
FastAPI AKASHI Core
├─ Conversation brain + intent + persona
├─ Memory V2 (session compression + explicit durable memory)
├─ Model profile router (FAST / QUALITY / REASONING / VISION)
├─ Research providers + synthesis
├─ Typed tool registry
├─ Persistent task engine
├─ Validated uploaded files
├─ Device pairing/action relay
├─ Spatial Lab scene service (one command path, action history, FORM read-only)
├─ Remote presence hub (paired devices, scoped sessions, approvals center)
└─ Authenticated SSE event stream
        │
        ├─ Ollama / Gemini
        ├─ ComfyUI (loopback only)
        ├─ Wikipedia or configured SearXNG
        └─ Paired Windows Agent
```

AI orchestration stays in the backend. Mobile and desktop clients select stable
capabilities and API resources; they do not contain provider credentials or
provider-specific logic.

The single exception is the desktop always-on voice worker
(`desktop/app/voice/live.py`), which holds a Gemini key in Windows DPAPI storage
and streams audio straight to Gemini Live. Anything beyond casual conversation
is delegated back to Core through `/chat`, so tools, research, memory and
persona remain backend-owned.

## Core services

`app/core/absolute.py` is the composition root, not a business-logic God class.
It wires focused services together and exposes the conversation entry point.
The existing `AkashiBrain` still owns intent, prompt context, response formatting,
and short-term conversation writes.

Memory V2 keeps the existing `data/memory.json` conversation schema. When a
session exceeds its configured raw-history window, older turns are compressed
into a bounded transcript summary. Durable memories live separately in ignored
`data/long_term_memory.json`, require explicit writes, reject secret-like values,
and use lexical relevance retrieval behind a replaceable store interface.

Research performs real provider queries, multi-query expansion in Deep mode,
URL deduplication, source extraction, and optional REASONING-profile synthesis.
If synthesis is unavailable, the real source metadata and extracts remain usable;
citations are never fabricated.

Tools have stable names, descriptions, input/result schemas, and `safe`,
`confirm`, or `restricted` risk levels. Tasks execute explicit tool steps in the
background, persist state, wait for approval when required, survive inspection,
and mark interrupted work honestly after a backend restart.

Uploaded files are stored by generated IDs under one private directory. The
initial extractor supports text, Markdown, JSON, CSV/TSV, and common source-code
formats. A file can be attached to a normal chat request through `file_ids`.

## Device flow

```text
Mobile/Web/Desktop UI
  → authenticated FastAPI device action
  → per-device queue
  ← Windows Agent polls with its own device identity
  → validates and executes one named local action
  → posts structured result
  → UI reads result / receives an SSE progress event
```

Pairing codes are short-lived and one-time. Device bearer tokens are returned
only during pairing, stored with Windows DPAPI by the Agent, and persisted by
Core only as salted PBKDF2 hashes.

## Client adapters

Android and iOS use Capacitor secure storage, native STT, and native TTS. The
Windows Electron shell uses an isolated preload bridge. Its FastAPI token is
encrypted with Electron `safeStorage`/Windows DPAPI in the main process; backend
requests are proxied over constrained IPC so the saved token is not returned to
the renderer.

The Electron shell loads the same static export over the privileged
`akashi://app` protocol with context isolation, renderer sandboxing, Node.js
disabled, navigation blocked, and a restrictive Content Security Policy.

## Spatial Lab and the action-history foundation

`app/history` is a domain-agnostic action history: commands become events with
reversible, verifiable patches and state digests in a hash-chained, crash-safe
JSONL log; undo/redo are events; replay re-executes the log and must reproduce
every digest. Spatial Lab (`app/spatial`) is its first domain: gesture, language,
UI and tool inputs all become one request contract, are compiled to concrete
commands (reference resolution, relative → absolute, FORM version selection) and
applied by a pure reducer. The backend owns the scene; clients draw a replica
plus transient previews for objects held by a hand. FORM data is read through a
read-only adapter (`form-library-read-1`) and is never written. Hand tracking
(MediaPipe, local WASM and model) runs in the client; only commands and
ephemeral hand anchors reach Core. Details: [spatial-lab.md](spatial-lab.md).

## Remote presence

`app/remote` turns other devices into scoped, authenticated parts of AKASHI:
device keys and single-use challenge handshakes on top of the existing device
registry, short-lived sessions, an ordered/idempotent message hub over WebSocket
or HTTP long-poll, a live capability registry and a hash-chained audit trail.
Spatial Lab is the first consumer (remote touch/gesture/voice/UI as ordinary
requests with device provenance, live previews, presence per device); the
approvals center (`app/approvals`) lets an authorized device decide pending
approvals. Core stays authoritative; devices never send state and keep camera
and microphone processing local. Details: [remote-presence.md](remote-presence.md).
