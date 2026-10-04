# AKASHI Spatial Lab V1.5 — remote presence: local acceptance contract

Companion to [docs/remote-presence.md](../remote-presence.md) and the V1
contract [spatial-lab-v1.md](spatial-lab-v1.md) (whose camera/gesture items
remain LOCAL ACCEPTANCE REQUIRED; V1.5 does not change their status).
Vocabulary as in [AI_ENGINEERING_RULES.md](../../AI_ENGINEERING_RULES.md):
IMPLEMENTED · VALIDATED (say where) · BENCHMARKED (stated hardware + numbers) ·
LOCAL ACCEPTANCE REQUIRED. Nothing here is BENCHMARKED yet.

---

## 1. Status matrix

| Capability | IMPLEMENTED | VALIDATED (cloud) — evidence | LOCAL |
| --- | --- | --- | --- |
| Device identity in the device registry (presence role, grants, P-256 key) | yes | `test_remote_hub` (pairing, key handling, agent separation), `test_remote_api` | R1, R2 |
| Challenge handshake, single-use nonce, scope-bound signature | yes | `test_remote_hub`; WebCrypto signature from the browser verified by Core (`test_remote_contract`, shared fixture) | R1, R2 |
| Short-lived session credential, stale/idle/lifetime | yes | `test_remote_hub` (deterministic clock) | R10, R12 |
| Scopes per message, immediate grant change / revocation | yes | `test_remote_hub`, `test_remote_spatial`, `test_remote_api` (live WS closed 4403), E2E | R11 |
| Dedupe (id), ordering (seq), realtime latest-wins, clock-independent staleness | yes | `test_remote_hub`; network simulation | R3, R4, R13 |
| WebSocket + HTTP long-poll transports, resume, WS→HTTP fallback | yes | `test_remote_api` (both), `remote-client.test.mjs` (fallback, resume), E2E (WS) | R6, R15, R19 |
| Reconnect / resync after disconnect, sleep, Core restart | yes | network simulation (Core restart, sleeping device), E2E offline/online | R10, R13, R15 |
| Spatial remote commands with device provenance; "why did it move?" | yes | `test_remote_spatial`, E2E (touch drag → "Remote touch from E2E iPhone") | R5, R6 |
| Stale-write protection (`base_revision`) | yes | `test_remote_spatial`; simulation: 0 stale writes applied in all seeds | R4, R14 |
| Owner-bound leases, release on disconnect/demotion/revocation | yes | `test_remote_spatial` | R14 |
| Live previews to other viewers (never recorded), commit-before-release ordering | yes | `test_remote_spatial`, E2E ("held by", desktop label moves during drag) | R7 |
| Touch input through the shared gesture pipeline | yes | `remote-client.test.mjs` (drag, tap), E2E (mouse-driven pointer events in a touch-enabled phone context) | R7, R16 |
| On-device hand tracking on the remote device; no video leaves it | yes | E2E: fake camera + real MediaPipe in a simulated phone; traffic inspection (largest uplink message 1,163 B, total ≈ 5 KB) | R17 |
| Per-device hand anchors ("move it to my right hand") | yes | `test_remote_spatial` | R17 |
| Approvals center (spatial / tasks / autonomy), scope filter, audited decisions | yes | `test_remote_core`, `test_remote_api`, E2E (phone approves desktop removal) | R9 |
| Remote voice (transcript → Spatial or scope-limited chat) | yes | `test_remote_core`, `test_live_core` (computer actions unreachable remotely) | R8 |
| Capability registry and "which device can provide X?" | yes | `test_remote_core` (chat, tool, live update) | R16 |
| Hash-chained audit, fail-closed on tamper | yes | `test_remote_hub`, `test_remote_api`, E2E verify | R20 |
| Remote client UI (/remote) and owner Devices drawer | yes | E2E (desktop + iPhone-sized touch context, cloud Chromium) | R1–R19 |
| iOS/Android native camera permission declarations | yes | not executable in the cloud | R16 |

---

## 2. Cloud measurements (NOT benchmarks)

Cloud container: Linux x86-64, no GPU, headless Chromium, loopback network.
They prove behaviour, not user-network performance.

| Measurement | Value | Scope |
| --- | --- | --- |
| Device handshake (challenge + signed session) | ≈ 12–18 ms | loopback HTTP, 8 runs |
| `spatial.command` round trip (validated, fsync'd history, fan-out) | p50 3.6 ms, p95 4.2–5.3 ms | loopback WebSocket, 100 commands paced at ~15/s |
| Preview fan-out device → second device | p50 0.9 ms, p95 ≈ 1.0–1.2 ms | loopback, 150 previews at 30 Hz |
| WebSocket resume (new socket, same session) | ≈ 4 ms (8 runs); **one unexplained 10 s outlier** in the first of 9 runs | loopback; see R10/R15 |
| Network simulation, 3 devices, 30 s, 8 % loss + 8 % duplication + 4–120 ms random latency (seeds 1–3) | per seed: 245–281 messages lost, 235–270 duplicated, 41–64 duplicates answered from cache, 155–182 stale writes refused, 109–120 out-of-order refused, 99–133 retransmits; **0 double applications, 0 stale writes applied, all replicas converge, replay verifies** | deterministic simulation, not a network |
| Core restart mid-run (seed 7) | every device re-handshakes (6 handshakes total) and re-syncs by events (digest-verified); converged | simulation |
| Phone with camera hand tracking (fake camera) | 14 uplink messages in ~10 s, largest 1,163 B, total ≈ 4.9 KB; kinds: auth, subscribe, approvals.list, capabilities.update, presence, ping | Chromium fake camera, still photo, SwiftShader |

---

## 3. Preconditions for local runs

Record once per run in §6: PC (CPU/GPU, Windows build), Core commit, phone
model + iOS version, Mac model + macOS/browser, network (router, Wi-Fi band,
same LAN or via VPN/tunnel), how Core is reached (address, TLS terminator).

Reachability (choose one; none is mandatory to the design):

* LAN HTTPS reverse proxy in front of Core (e.g. Caddy with a local CA whose
  root is trusted on the iPhone/Mac), or
* a VPN (e.g. WireGuard/Tailscale) address, or
* any HTTPS tunnel.

Set `AKASHI_REMOTE_ENDPOINTS` to the addresses devices use and add the UI
origin to `AKASHI_CORS_ORIGINS` when the remote client is opened in a browser.
On iPhone, prefer the Capacitor app build (secure context, native speech,
camera permission strings) — plain-HTTP pages cannot use WebCrypto, the camera
or the microphone.

---

## 4. Local acceptance tests

**(target)** = proposed threshold; LOCAL ACCEPTANCE REQUIRED to confirm or
replace with a measured value (commit the measurement in §6 with the change).

### A. Automated suites on Windows

| ID | Command | Pass |
| --- | --- | --- |
| A.1 | `cd backend; .\.venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass (includes 6 remote test modules) |
| A.2 | `.\.venv\Scripts\python.exe -m app.remote.contract; .\.venv\Scripts\python.exe -m app.spatial.contract` | exit 0 |
| A.3 | `cd ..\frontend; npx tsc --noEmit; npm run lint; npm run test:api` | all pass |
| A.4 | `npm run build; npm run test:e2e; npm run test:spatial` | all pass (test:spatial includes `remote-presence.spec.ts`) |

### R. Remote presence on real devices

| ID | Procedure | Pass |
| --- | --- | --- |
| R1 Pairing / connection | Pair iPhone (app), iPhone (Safari over HTTPS), Mac (Safari/Chrome) 10× each from Spatial Lab → Devices | 10/10 succeed; device shows "Connected"; handshake (debug) ≤ 500 ms p95 on LAN (target) |
| R2 Authentication rejection | wrong code; expired code (wait for TTL); reused code; revoked device reconnect; unpaired device; API token used as a session token (curl) | 100 % refused with a clear message; refusals appear in `GET /remote/audit` |
| R3 Duplicate handling | With iOS Network Link Conditioner (lossy profile) or a proxy that duplicates requests, perform 50 actions | each action recorded once (history message ids unique per device); `replay/verify` true |
| R4 Out-of-order / stale | Two devices edit the same object for 5 min (rotate/scale/move, absolute and relative) | 0 backward moves observed; conflicting device sees "scene changed" and the current state; `replay/verify` true |
| R5 Scene convergence | Desktop + iPhone + Mac edit for 10 min, then stop | all debug panels show the same revision and digest within 1 s of the last change (target) |
| R6 Remote command latency | Film desktop + phone at 240 fps; tap "⟳ 15°" on the phone | median tap → desktop change ≤ 150 ms on LAN Wi-Fi (target); record p95 |
| R7 Remote gesture latency | Same filming; drag with one finger; measure phone finger stop → desktop object stop | median ≤ 120 ms (target); the phone's own view follows the finger with no network wait |
| R8 Voice latency | Say "rotate it ninety degrees" on the phone (app, native STT) | end of speech → reply spoken ≤ 2.5 s median (target; STT engine dependent); with Ollama/Gemini off it still works via rules |
| R9 Approval round trip | Desktop: "delete it" → phone shows approval → Approve | approval visible on phone ≤ 1 s; applied on desktop ≤ 1 s after tap (targets); audit shows device + session |
| R10 Expiration / sleep | Lock the phone 2 min (session expires) and 30 min, unlock | reconnected and current within 5 s without user action (target); no duplicate changes |
| R11 Revocation and scope change | Revoke from Devices; separately untick "Change the scene" | phone shows revoked / controls disabled ≤ 1 s (target); a held object is released immediately |
| R12 Sustained session | 60 min connected, mixed idle/use, screen on | 0 unexpected disconnects without network cause; note reconnect count, battery %, phone temperature |
| R13 Packet loss recovery | Network Link Conditioner "Very Bad Network" / 10 % loss, 5 min of use | no stuck UI; every action ends applied or with a message; converges after the profile is removed (R5 check) |
| R14 Multi-device consistency | iPhone holds an object while Mac and desktop try to move it | others get "held by iPhone"; after release all see the same transform |
| R15 Network change | Wi-Fi → cellular (VPN/tunnel) → Wi-Fi while connected | reconnect ≤ 10 s each switch (target); measure the resume time and record any outlier (the cloud showed one unexplained 10 s resume) |
| R16 Mobile permissions | First camera / microphone use in the app and in Safari; deny once | prompts appear with the AKASHI text; denial shows `camera: denied` on the desktop Devices panel; everything else keeps working |
| R17 On-device hand tracking | Phone "Hands" mode, 2 min | debug shows on-device tracking; desktop shows the phone's hand anchors; a proxy/inspector shows no message > 4 KB and no image data from the phone; record phone fps / inference ms / temperature |
| R18 PC under load | R6/R7 while Ollama generates and Blender renders on the RTX 4080 SUPER | latency within +50 ms of R6/R7 (target) |
| R19 Packaged desktop | Electron packaged app as owner | Devices button shows realtime online; invite, grants, revoke, approvals all work through IPC |
| R20 Audit integrity | After a day of use, Devices → Verify audit trail | verified |

---

## 5. Exit criteria for "Remote presence V1.5 accepted"

* A.1–A.4 pass on Windows.
* R1–R20 each have a recorded measurement; every **(target)** met or replaced
  by a measured value with a reason.
* No double application, stale write or unauthorized action observed in any test.
* §1 updated; rows move to BENCHMARKED only with §6 entries.

---

## 6. Results (fill in locally)

| Date | Commit | Devices / network | Test ID | Measured | Pass? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

---

## 7. Handoff order for local Codex

1. Branch `claude/remote-spatial-presence-v1-5` (never `main`). Read
   `AI_ENGINEERING_RULES.md`, `docs/remote-presence.md`, this file.
2. A.1–A.4 on Windows; fix Windows-only breakage without weakening tests.
3. Set up HTTPS reachability (§3), then R1, R2.
4. R5, R6, R7 with filming (latency numbers), R9, R11.
5. R10, R12, R13, R15 (network behaviour), R3, R4, R14.
6. R16, R17 on the iPhone app build; R8 voice.
7. R18 under GPU load, R19 packaged desktop, R20.
8. Record everything in §6 in the same commit as any change it justifies.

Do not: let a device send state, add a computer-control scope, accept remote
provenance from callers, persist session credentials, stream raw camera/mic data
by default, or make a commercial tunnel or cloud speech service mandatory.
