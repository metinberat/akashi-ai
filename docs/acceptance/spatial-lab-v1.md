# AKASHI Spatial Lab V1 — local acceptance contract

This is the version-controlled acceptance contract for Spatial Lab V1. It
separates what was **implemented**, what was **validated in the cloud**, and what
must still be **accepted on the physical Windows machine** (real webcam, real
GPU, real FORM + Blender, packaged Electron). Architecture:
[docs/spatial-lab.md](../spatial-lab.md). Vocabulary:
[AI_ENGINEERING_RULES.md](../../AI_ENGINEERING_RULES.md).

| Term | Meaning here |
| --- | --- |
| IMPLEMENTED | Code exists and is wired into the product path. |
| VALIDATED (cloud) | An automated test exercised it in the cloud container (Linux, no GPU, no webcam, headless Chromium). |
| BENCHMARKED | A number was measured **on the target hardware** under a stated protocol. Nothing in V1 is benchmarked yet. |
| LOCAL ACCEPTANCE REQUIRED | Needs the physical machine. Numbers below are proposed targets until the first local run replaces them with measurements. |

V1 is **2.5D**: the camera image is a backdrop; hands move objects on a plane at
the object's own depth. No depth, occlusion, SLAM, anchoring or contact physics
is claimed or tested.

---

## 1. Status matrix

| Capability | IMPLEMENTED | VALIDATED (cloud) — evidence | LOCAL ACCEPTANCE |
| --- | --- | --- | --- |
| Unified command path (gesture, language, UI, tools → one contract → one history) | yes | `test_spatial_domain`, `test_spatial_api`, `spatial-lab.spec.ts` (real Core) | §4.I |
| Undo / redo as events, mixed origins | yes | `test_history`, `test_spatial_domain`, E2E undo after drag | §4.I |
| Hash-chained log, torn-tail recovery, corruption refusal (423) | yes | `test_history`, `test_spatial_api` | §4.I restart |
| Deterministic replay (backend re-execution + frontend patch replay) | yes | `verify_replay`, `spatial-client.test.mjs` on the generated fixture, E2E Replay panel | §4.I |
| Leases, dry-run, confirmation for removal | yes | `test_spatial_api`, E2E confirmed removal | — |
| GLB validation / normalisation / clip classification | yes | `test_spatial_assets` (11) incl. real FORM export | §4.J corpus |
| FORM read-only library, V01 numbering, SHA-256 identity | yes | contract test with FORM's real `Projects`; E2E Library | §4.H with real Blender 5.2 + FORM app |
| Real FORM export rendering (57 joints, HUD rings, skeletal clip, HUD energy) | yes | `spatial-lab.spec.ts` "real FORM export renders…" (fixture built with PyPI `bpy` 5.0.1, not the Blender 5.2 binary) | §4.H |
| Gesture engine (filters, hysteresis, tracker, interaction) | yes | `spatial-gesture.test.mjs` (16, synthetic), `spatial-real-landmarks.test.mjs` (7, real MediaPipe landmarks from photos) | §4.D feel and tuning |
| MediaPipe live provider (getUserMedia → HandLandmarker VIDEO) | yes | `hand-tracking.spec.ts` (7 runs): Chromium fake camera fed with MediaPipe's own hand photographs, GPU (SwiftShader) and CPU delegates | §4.B, §4.G with a real webcam |
| Pinch on real hands | yes | **not validated**: no real photo shows a pinch; synthetic only | §4.D |
| Calibration (mirror, cover crop, gain, offset), cursor alignment | yes | round-trip unit tests | §4.E |
| Handedness swap default (`swapHandedness: true`) | yes | **unsettled**: still photos do not determine mirroring of a live selfie camera | §4.E.3 |
| Language (TR/EN rules, references, clarification) | yes | `test_spatial_domain`, `test_spatial_api` (/chat routing), E2E | §4.K |
| Optional model interpreter (FAST profile, schema-validated) | yes | `test_spatial_domain` (parser rejects unknown ids/removals) — no real model ran in the cloud | §4.K.4 |
| Desktop camera permission (video only, `akashi://app` main frame) and CSP `'wasm-unsafe-eval'` | yes | `desktop/app/tests/security.test.cjs` | §4.G packaged app |
| Recording / deterministic replay of real hand sessions | yes | client tests + real recordings from the fake camera | §4.L |

---

## 2. Cloud measurements (NOT benchmarks)

Measured in the cloud container (Linux x86-64, no GPU, headless Chromium with
SwiftShader, Python 3.11). They prove the paths run end to end; they say nothing
about user hardware.

| Measurement | Value | Scope |
| --- | --- | --- |
| MediaPipe inference, GPU delegate on SwiftShader (software GL) | median ≈ 747–775 ms/frame; first inference in a fresh browser ≈ 3.7 s (shader warm-up) | 640×480 fake camera, still photos |
| MediaPipe inference, CPU (WASM) delegate | median ≈ 89–91 ms/frame | same, `fist` photo |
| Expected hand count detected | 100 % of recorded frames, all 7 runs, in every suite run | still photos, 13–38 frames per run |
| Handedness score (median) | 0.95–0.999 | still photos |
| Gesture pipeline processing p95 | ≈ 0.6–1.0 ms/frame | synthetic and recorded frames, Node |
| Core submit latency (in-process, fsync'd log) | p50 0.98 ms, p95 1.22 ms, max 3.49 ms | 300 `object.transform` commands |
| Replay verification | 302 events re-executed and verified in 148 ms | same session |
| Real FORM GLB (57 joints, 3 HUD rings) | loads, renders, plays skeletal clip; zero page errors | headless Chromium |

Photo results (real MediaPipe output through the full live provider):
`fist` → grab, `thumb_up` → grab (a closed hand; reported, not an error),
`pointing_up` → no grab (regression for a real bug found here), `victory` → no
grab, `right_hands` / `left_hands` → two stable identities, no pose. No photo
produced a pinch.

---

## 3. Preconditions for a local run

Record these once at the top of the results table (§6):

* Windows version, CPU, GPU + driver, RAM, VRAM.
* Webcam model, chosen resolution and frame rate (debug panel → *Source*).
* Whether Ollama is running and which model is loaded; whether Blender is open.
* Build: git commit, `npm ls three @mediapipe/tasks-vision`, Electron version.

Setup (PowerShell, repository root):

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd ..\frontend
npm ci
npm run spatial:assets        # copies MediaPipe WASM, downloads the pinned model (SHA-256 checked)
npm run build
```

`npm run spatial:assets` needs network once; afterwards everything runs offline.
`npm run build` fails loudly (`--offline` check) if the assets are missing.

---

## 4. Local acceptance tests

Each test has an ID, a procedure, how to measure, and a pass criterion.
Criteria marked **(target)** are proposals: LOCAL ACCEPTANCE REQUIRED to confirm
or replace them, and the replacement must be committed here with the measurement
that justified it.

### A. Automated suites on the Windows machine

| ID | Command | Pass |
| --- | --- | --- |
| A.1 | `cd backend; .\.venv\Scripts\python.exe -m unittest discover -s tests -v` | all pass (on Linux two pre-existing `PureWindowsPath` tests fail; on Windows they must pass) |
| A.2 | `.\.venv\Scripts\python.exe -m app.spatial.contract` | exit code 0, no output (generated contract in `shared/contracts/spatial/` not stale) |
| A.3 | `cd ..\frontend; npx tsc --noEmit; npm run lint; npm run test:api` | all pass |
| A.4 | `npm run test:e2e` | all pass (existing UI suite) |
| A.5 | `npm run test:spatial` | 10 pass: 3 product flows + 7 live MediaPipe runs. Uses Playwright's Chromium; record the GPU-delegate inference median from `tests/spatial-e2e/.artifacts/hand-tracking/*.json` — on a real GPU it should be far below the cloud's ≈ 750 ms |
| A.6 | `cd ..\desktop\app; npm run test:security` | all pass |
| A.7 | `cd ..\..\products\form; npm test; $env:PYTHONPATH="server;..\..\backend;..\..\desktop\agent"; ..\..\backend\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"` | all pass (cloud: 3 + 35); FORM code is not modified by Spatial Lab |

### B. Camera and tracking performance (Debug panel → toggle **Debug**)

Run 60 s with one hand moving naturally in view, default resolution, GPU
delegate, nothing else heavy running. Read the debug panel at the end.

| ID | Metric (debug panel field) | Pass |
| --- | --- | --- |
| B.1 | *Source* fps | ≥ 25 fps (target; webcam-dependent) |
| B.2 | *Pipeline* fps (frames that reached the gesture engine) | ≥ 24 fps (target) |
| B.3 | *Pipeline* infer p95 | ≤ 25 ms on GPU delegate (target) |
| B.4 | *Pipeline* proc p95 (gesture engine) | ≤ 2 ms (cloud: ≈ 1 ms) |
| B.5 | *Pipeline* gaps (interval > 2× average) | ≤ 1 per 10 s (target) |
| B.6 | *Source* skipped | ≤ 5 % of delivered (target) |
| B.7 | *Renderer* fps while manipulating | ≥ 50 fps (target); idle scene renders on demand |
| B.8 | Delegate fallback: choose **CPU** in the delegate selector, restart camera | runs; record infer p95 |
| B.9 | GPU delegate failure path: if the GPU delegate fails to start, the provider falls back to CPU and the debug panel shows the CPU delegate | no crash, status message shown |

### C. Latency

| ID | Procedure | Pass |
| --- | --- | --- |
| C.1 | Motion-to-photon: film hand and screen together with a phone at 240 fps; pinch-drag, stop abruptly; count frames between hand stop and cursor/object stop (10 trials, median) | ≤ 120 ms median (target) |
| C.2 | Commit latency: debug panel *Core submit* p95 after 50 drags | ≤ 25 ms (target; cloud in-process ≈ 1.2 ms) |
| C.3 | Language round trip: type "make it bigger" → reply shown (rules interpreter, 10 trials) | ≤ 300 ms median (target) |

### D. Gesture feel and false activation

Protocol for every row: one object (calibration fixture) centred, user at
normal desk distance (≈ 50–80 cm), room lighting noted.

| ID | Procedure | Pass |
| --- | --- | --- |
| D.1 | Pinch select: 20 quick pinches over the object | ≥ 19 select, 0 moves (target) |
| D.2 | Pinch drag: 20 drags to a marked target | ≥ 19 commit exactly one `object.transform` each (Replay panel / events) |
| D.3 | Grab drag (fist): 20 drags | ≥ 19 succeed; 0 recorded as pinch |
| D.4 | Release precision: after D.2 drags, object rest position vs where the hand stopped | ≤ 3 % of viewport width drift on release (target) |
| D.5 | Idle false activation: 5 min of talking, typing and gesturing **without** intending to manipulate, hands frequently in view, recorded with **Record hands** | 0 committed commands (Replay panel); ≤ 1 pose start/min when the recording is replayed through `GesturePipeline` (target) |
| D.6 | Air pinch away from objects: 20 pinches over empty space | 0 commands |
| D.7 | Two-hand scale/rotate: pinch with both hands, spread then twist | scale follows distance; rotation direction matches the twist (if inverted, set `twoHand.rotationSign` and record it here) |
| D.8 | Pointing and victory signs held over the object for 5 s each | no grab, no pinch |
| D.9 | Tracking recovery (short): during a drag, pass the other hand in front for ≈ 0.2 s | manipulation continues, no jump |
| D.10 | Tracking loss (long): during a drag, drop the hand out of view for ≥ 1 s | manipulation ends as `tracking_lost`; object stays at the last stable transform (no jump, no revert) |
| D.11 | Fast swipe: drag quickly across the view | object follows; no "glitch rejected" freeze longer than one frame (debug *glitches*) |

Tuning: every gesture tunable marked LOCAL ACCEPTANCE REQUIRED in
`frontend/src/lib/spatial/gesture/config.ts` (filters, `outlierJump`,
`graceMs`, pinch, grab) may change only together with (1) a committed hand
recording that shows the problem (§4.L), (2) a regression test that replays it,
and (3) an update of this section with the new measured value.

### E. Calibration and camera mapping

| ID | Procedure | Pass |
| --- | --- | --- |
| E.1 | Mirror: move the right hand to the right | cursor moves right (selfie convention) |
| E.2 | Alignment: with **Debug** on, place the index fingertip on 5 points (centre + 4 corners at 15 % inset); compare cursor to fingertip in the camera image | ≤ 3 % of viewport diagonal error at each point (target) |
| E.3 | Handedness: raise only the right hand | debug panel labels it **Right**. If it says *Left*, set `swapHandedness: false` in calibration, re-test, and record the correct default here (currently `true`, unverified) |
| E.4 | Window resize and fullscreen with camera running | cursor stays aligned (E.2 at one point) |
| E.5 | Calibration persists across restart | same values after reopening Spatial Lab |

### F. Resource contention (GPU shared with Ollama and Blender)

| ID | Procedure | Pass |
| --- | --- | --- |
| F.1 | B.1–B.3 while Ollama generates continuously (loaded model noted) | Pipeline ≥ 20 fps; infer p95 ≤ 40 ms (target) |
| F.2 | B.1–B.3 while Blender renders (FORM build or a Cycles render) | Pipeline ≥ 15 fps; no camera stall > 1 s (target) |
| F.3 | VRAM: Task Manager / `nvidia-smi` before and after starting the camera | record the delta (no target yet: LOCAL ACCEPTANCE REQUIRED) |
| F.4 | Ollama answers still arrive while the camera runs | Chat reply arrives; no Spatial Lab error |

### G. Electron (packaged Windows app)

Build with `npm run pack:win` (desktop/app) after `npm run build` (frontend).

| ID | Procedure | Pass |
| --- | --- | --- |
| G.1 | First camera start | Windows camera privacy setting respected; app requests **video only**; no microphone request from Spatial Lab |
| G.2 | DevTools console during camera start | no CSP violations; WASM compiles (`'wasm-unsafe-eval'`); `.wasm` served by `akashi://` with a MIME type MediaPipe accepts (if it falls back to non-streaming compile, note it — not a failure) |
| G.3 | Offline: disconnect network, restart app, start camera | tracking works (WASM + model are local) |
| G.4 | Camera busy: open the camera in another app first | error `camera_busy` shown; switching to **Simulated** works |
| G.5 | Camera denied in Windows privacy settings | error `camera_denied`; rest of Spatial Lab usable |
| G.6 | Unplug webcam while running | provider stops with an error, scene unaffected, restart works after re-plug |
| G.7 | Multiple cameras | device selector lists them; switching works |
| G.8 | `AKASHI_FORM_DATA_DIR` and `AKASHI_SPATIAL_INTERPRETER` passed through by the runtime supervisor | Spatial Lab capabilities show the chosen FORM directory and interpreter |

### H. FORM end to end (real FORM, real Blender 5.2)

| ID | Procedure | Pass |
| --- | --- | --- |
| H.1 | In FORM, build and export a character (HUD on). Record SHA-256 of FORM's `expert.sqlite3` and the export GLB | — |
| H.2 | Spatial Lab → Library | project listed; versions numbered exactly as FORM shows them (V01…); export marked verified |
| H.3 | Load the latest version | object appears; inspector shows `identity_verified: true`, joints and clips matching FORM's export readback |
| H.4 | Language: "load the previous version", "switch to V01", "load the best version" | the right version each time; one undo step each |
| H.5 | Play animation, toggle FORM HUD and VFX | skeletal clip plays; HUD rings show energy animation only when HUD + VFX are on |
| H.6 | After H.2–H.5, re-hash the files from H.1 | unchanged (Spatial Lab never writes FORM data) |
| H.7 | Close AKASHI; FORM still builds and exports. Close FORM; Spatial Lab still loads uploads and the fixture and reports FORM as unavailable | both independent |
| H.8 | Replace the export file on disk with different bytes, then load it | refused (SHA-256 mismatch), nothing loaded |

### I. Command system correctness

| ID | Procedure | Pass |
| --- | --- | --- |
| I.1 | After any 10-minute mixed session (gesture + language + UI), Replay panel → **Verify** (`POST …/replay/verify`) | `verified: true` (100 %) |
| I.2 | Scripted mixed undo/redo: drag (gesture), "make it bigger" (language), rename (UI), undo ×3, redo ×2 | each undo restores the exact previous transform/label; redo reapplies; history shows origins |
| I.3 | Restart Core mid-session; reopen Spatial Lab | same scene, same history, undo still works |
| I.4 | Kill Core during a burst of commands; restart | log recovers (torn tail dropped at most one partial line); replay verifies |
| I.5 | Edit one byte inside the session log; restart | session refused with 423 (`SessionCorrupted`), never silently "repaired" |
| I.6 | Two clients (web + desktop) on the same session | both converge within one poll (≤ 1 s); a client cannot start a manipulation on an object leased by another (`object_busy`) |
| I.7 | Removal by language ("delete it") | confirmation required; declining changes nothing |

### J. Assets

| ID | Procedure | Pass |
| --- | --- | --- |
| J.1 | Load a local corpus: every FORM export available + ≥ 5 Blender-exported GLBs (skinned, unskinned, multi-mesh, Z-up source, centimetre units) | 100 % of valid files load; normalisation flags match the file (record any mismatch) |
| J.2 | Invalid corpus: truncated GLB, wrong magic, external `uri`, Draco/meshopt-required, > 20 MiB upload, cyclic node graph | 100 % rejected with a specific error; nothing added to the scene |
| J.3 | Heavy asset (largest FORM export) | B.7 still met, or the slowdown is recorded |

### K. Language and AKASHI

| ID | Procedure | Pass |
| --- | --- | --- |
| K.1 | TR and EN phrases from docs/spatial-lab.md §9 (≥ 25 phrases, both languages) | ≥ 95 % do the expected thing; 0 destructive guesses |
| K.2 | Two characters in scene: "make the character bigger" | clarification question listing both; nothing changes until answered |
| K.3 | References: "that one" (after pointing/selecting), "the selected character", "the object on the left", "the larger character", "my FORM character", "the latest version", "the one I just moved" | each resolves correctly or asks |
| K.4 | `AKASHI_SPATIAL_INTERPRETER=auto` with Ollama: an off-script phrase | either a valid validated request or an honest "not understood"; never a removal |
| K.5 | `AKASHI_SPATIAL_INTERPRETER=rules`, Ollama stopped | all K.1 rule phrases still work (cloud AI not required) |
| K.6 | Desktop voice: say "move it to my right hand" with the right hand visible | object moves to the hand anchor; with no visible hand, AKASHI asks to show it |
| K.7 | `/chat` more than 45 s after Spatial Lab was closed | spatial phrases are **not** captured by the spatial action (falls through to normal chat) |

### L. Real hand recordings (the bridge from local to automated)

1. Spatial Lab → **Debug** → **Record hands**, perform one scenario
   (pinch-drag, two-hand scale, idle talking, pointing, fast swipe), **Stop &
   save recording**.
2. Recordings contain landmarks, timestamps, resolution, delegate and
   calibration — **no images**. Still, review before committing.
3. Commit them under `frontend/tests/fixtures/spatial/real-landmarks/` with a
   README line (scenario, camera, lighting), and add an expectation to
   `frontend/tests/spatial-real-landmarks.test.mjs`.
4. Minimum set for V1 acceptance: one real pinch-drag, one real two-hand
   scale, one 60 s idle false-activation recording, one fast swipe.

---

## 5. Exit criteria for "Spatial Lab V1 accepted"

* A.1–A.6 pass on Windows.
* B, C, D, E, F, G, H, I, J, K: every row has a recorded measurement; every
  **(target)** either met, or replaced by a measured value with a written reason.
* E.3 settles the `swapHandedness` default.
* §4.L minimum recordings committed with passing regression tests.
* Status matrix (§1) updated: rows move to BENCHMARKED only with §6 entries.

---

## 6. Results (fill in locally)

| Date | Commit | Machine (CPU / GPU / webcam) | Test ID | Measured | Pass? | Notes |
| --- | --- | --- | --- | --- | --- | --- |
| | | | | | | |

---

## 7. Handoff order for local Codex

1. Check out `claude/spatial-lab-v1-current` (never work on `main`); read
   `AI_ENGINEERING_RULES.md`, then [docs/spatial-lab.md](../spatial-lab.md).
2. §3 setup, then §4.A. Fix Windows-only breakage first (paths, `cmd.exe`
   quoting, line endings) without weakening any test.
3. §4.E.3 (handedness) and §4.E.2 (alignment) before any gesture tuning: a
   wrong mapping makes every other gesture number meaningless.
4. §4.B and §4.F to establish the machine's baseline; record in §6.
5. §4.L recordings, then §4.D. Tune only through recordings + regression tests.
6. §4.G with the packaged app, §4.H with the real FORM app and Blender 5.2.
7. §4.I, §4.J, §4.K.
8. Update §1 and §6 in this file in the same commit as any code change they
   justify. Do not mark anything BENCHMARKED without a §6 row.

Do not: add a second scene state in the renderer, bypass the request contract
for "fast paths", write into FORM's data directory, relax the desktop camera
permission beyond video for `akashi://app`, or make a cloud model mandatory.
