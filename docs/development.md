# Development and validation

All commands below start at the repository root on Windows PowerShell unless a
different platform is noted.

## Backend

Copy `backend/.env.example` to ignored `backend/.env`, generate a long
`AKASHI_API_TOKEN`, and select `AI_PROVIDER=ollama`, `mock`, or `gemini`.

```powershell
cd backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Ollama defaults to `127.0.0.1:11434`; ComfyUI defaults to
`127.0.0.1:8188`. Do not tunnel either service. For temporary remote mobile
testing, start a Cloudflare Quick Tunnel to FastAPI and enter the generated HTTPS
origin in AKASHI Connection Settings.

Research defaults to DuckDuckGo topic evidence because it requires no credential.
Use `RESEARCH_PROVIDER=searxng` with a private `SEARXNG_BASE_URL` when full web
search is required; Wikipedia remains an optional provider.

## Shared Web UI

```powershell
cd frontend
npm ci
npm run dev
```

Open `http://localhost:3100`. The backend CORS defaults allow both
`localhost:3100` and `127.0.0.1:3100` as well as the Capacitor and Electron
origins. Keep the frontend origin exact when overriding `AKASHI_CORS_ORIGINS`.

The backend URL and token are entered at runtime. A production static export is:

```powershell
npm run build
Test-Path .\out\index.html
```

## Android

For an HTTPS backend:

```powershell
cd frontend
npm run android:sync
$env:JAVA_HOME="$env:LOCALAPPDATA\AkashiAndroidJdk\jdk-21.0.12.1+1"
cd android
.\gradlew.bat assembleDebug
```

The debug APK is `frontend/android/app/build/outputs/apk/debug/app-debug.apk`.
For explicit LAN HTTP development only, set `AKASHI_MOBILE_DEV=1` while syncing.

## iOS (macOS/Xcode required)

```bash
cd frontend
npm ci
npm run ios:sync
npx cap open ios
```

Select an Apple Development Team and build the `App` scheme. Windows can sync and
validate the generated target but cannot compile or sign it.

## Windows Agent

Use a separate environment and the same long random agent token in the Agent and
Electron process environments:

```powershell
cd desktop\agent
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:AKASHI_AGENT_TOKEN='replace-with-at-least-32-random-characters'
.\.venv\Scripts\python.exe -m akashi_agent serve
```

Optional approved roots are semicolon-separated:

```powershell
$env:AKASHI_AGENT_ALLOWED_ROOTS="$HOME\Desktop;$HOME\Documents"
```

To pair for Mobile → Core → PC actions, create a code in the Devices panel, then:

```powershell
.\.venv\Scripts\python.exe -m akashi_agent pair --core-url https://your-fastapi.example --code ABC1234567
.\.venv\Scripts\python.exe -m akashi_agent run
```

Use `run --once` for one poll. `unpair` removes the encrypted local credential;
also revoke the device in AKASHI.

## Windows Desktop

Build the shared frontend first, then package Electron:

```powershell
cd frontend
npm run build
cd ..\desktop\app
npm ci
$env:AKASHI_AGENT_TOKEN='the-same-local-agent-token'
npm start
```

`npm run pack:win` produces an unpacked app; `npm run dist:win` creates the NSIS
installer. The Desktop backend token is entered in Connection Settings and
encrypted in the Electron user-data directory.

Desktop FULL VOICE uses the existing local Python 3.11 Whisper installation.
The default worker command is `py -3.11`; set `AKASHI_VOICE_PYTHON` to an
absolute Python `.exe` only when the launcher is unavailable. Install the voice
workers' dependencies into that interpreter, not the backend virtualenv:

```powershell
py -3.11 -m pip install -r desktop/app/voice/requirements.txt
```

That file pins `google-genai` to the version the always-on Gemini Live session
was verified against, which is a different major than the backend's pin. A cached
`tiny`, `base`, or `small` Whisper checkpoint is required. Microphone audio is
kept in memory, one recognition worker is allowed at a time, and no wake-word
or background recording is enabled. During a full voice session, detected
speech interrupts Electron TTS before the new utterance is transcribed.

MISS MINUTES state lives under `backend/data/private/`, separate from user
memory. Its interval jobs are durable but disabled by default. Enable them with
`MISS_MINUTES_ENABLED=true` only on a single scheduler process; source text is
untrusted data and cannot authorize tools or maintenance actions.

## Manual feature checks

- Memory: open Memory, save a non-secret preference, search it, attach a related
  prompt, edit/delete through the API or delete in the panel.
- Research: open Research, select NORMAL or DEEP, run a query, inspect real URLs
  and synthesis state.
- Tasks: enqueue `research.web` or `memory.search`; confirm state/progress. A
  `memory.create` task must stop at `waiting_for_approval` until approved.
- Files: upload a supported text/code file, choose **Sohbette kullan**, then ask a
  question in Chat.
- Voice: on Android/iOS, tap the microphone and speak Turkish or English. On
  Desktop, start **Voice session** and verify listen → transcribe → Core → TTS,
  then speak during playback to verify barge-in.
- PC telemetry: run the Agent, open Devices in Desktop, and choose **Bu PC'nin
  durumunu al**.
- Remote PC: pair the relay, send `get_system_status`; for launch/project/screenshot
  actions tick the explicit confirmation box and inspect the returned result.
- Spatial Lab: follow [the local acceptance contract](acceptance/spatial-lab-v1.md)
  (camera, gestures, FORM, replay); record results in its §6.

## Remote presence (iPhone, Mac, another laptop)

Devices reach Core over HTTPS; choose any reverse proxy, VPN or tunnel (none is
built in or required). For a LAN setup, run Core on a LAN-reachable address
behind a TLS reverse proxy whose certificate the devices trust, then:

```powershell
$env:AKASHI_REMOTE_ENDPOINTS="https://akashi.lan:8443"        # advertised to paired devices
$env:AKASHI_CORS_ORIGINS="...,https://<origin serving the UI>"  # when using the browser client
```

The packaged desktop starts Core on `127.0.0.1` with CORS limited to
`akashi://app`. Put a TLS reverse proxy on the same PC in front of it and allow
the remote client's origin explicitly (validated; never `*`):

```powershell
$env:AKASHI_REMOTE_ORIGINS="capacitor://localhost,https://<origin serving /remote>"
```

In Spatial Lab open **Devices → Create pairing code**. On the device open the
remote client (`/remote` in the browser, or the AKASHI app → More → Remote
presence), enter the Core address and the code. Follow
[the acceptance contract](acceptance/remote-spatial-presence-v1-5.md) for
physical checks.

## Spatial Lab assets

Hand tracking runs fully offline from files the frontend serves itself:

```powershell
cd frontend
npm run spatial:assets   # MediaPipe WASM from node_modules + pinned model (SHA-256 checked); network once
npm run build            # prebuild verifies the assets (--offline) and fails if missing
```

Optional settings in `backend/.env`: `SPATIAL_DIR`, `AKASHI_FORM_DATA_DIR`
(defaults to FORM's userData under `%APPDATA%`), `AKASHI_SPATIAL_INTERPRETER`
(`auto` = rules then the FAST model; `rules` = never call a model).

## Automated validation

```powershell
cd backend
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m app.spatial.contract   # exit 1 if shared/contracts/spatial is stale
.\.venv\Scripts\python.exe -m app.remote.contract    # exit 1 if shared/contracts/remote is stale

cd ..\frontend
npx tsc --noEmit
npm run lint
npm run test:api
npm run test:e2e
npm run build
npm run test:spatial   # real Core + real MediaPipe via Chromium's fake camera
npm run android:sync
npm run ios:sync

cd ..\desktop\agent
$env:PYTHONPATH=(Get-Location).Path
..\..\backend\.venv\Scripts\python.exe -m unittest discover -s tests -v
```
