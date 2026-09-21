# AKASHİ AI shared frontend and native shells

The existing Next.js chat/image interface is exported once and used by Web,
Android, and iOS through Capacitor. FastAPI remains the only AI/image gateway.
Android and iOS include native speech recognition, text-to-speech, and secure
local storage for the personal access token (Android KeyStore / iOS Keychain).

## Local web development

Run the frontend, then open `http://localhost:3100`. Open Connection Settings
(gear) and enter the FastAPI URL and personal token. Development mode offers
`http://localhost:8000` as a local fallback.
fallback. Production/Android builds have no embedded backend URL.

```powershell
npm install
npm run dev
```

The backend runs separately from `../backend` with Uvicorn. Set a long random
`AKASHI_API_TOKEN` in the ignored `backend/.env` before using `/chat` or `/image/*`.
`/health` stays public; `/auth/check` tests the bearer token without invoking AI.
For a browser deployment, add its exact origin to `AKASHI_CORS_ORIGINS` on the backend.
Web development retains its token only for the current browser session. Native
mobile builds store the URL and token with the secure-storage plugin.

## Static export and Capacitor

`npm run build` writes the static app to `out/`; `npm run start` previews that
directory. Capacitor reads `out/` via `capacitor.config.ts`. Android lives in
`android/`, iOS lives in `ios/`, and both consume the same frontend bundle.
Use `npm run mobile:sync` to build and synchronize both platforms, or
`npm run android:sync` / `npm run ios:sync` for one platform. Backend addresses
are changed in the app without rebuilding.

For LAN HTTP testing only, build a debug APK with the explicit development flag,
then enter the PC's reachable `http://LAN-IP:8000` address in the Android settings.
Do not use this flag for a release build:

```powershell
$env:AKASHI_MOBILE_DEV = "1"
npm run android:sync
Remove-Item Env:AKASHI_MOBILE_DEV
```

`AKASHI_ANDROID_DEV=1` remains supported as a compatibility alias for the
existing Android workflow. Normal Android and iOS builds require HTTPS. The
iOS Debug target has only the narrow `NSAllowsLocalNetworking` ATS exception;
Release has none. Set `AKASHI_MOBILE_DEV=1` during `ios:sync` to allow an HTTP
LAN URL in the JavaScript client, or use the HTTPS tunnel flow below.

Normal builds accept only HTTPS addresses at runtime. A temporary Cloudflare
Quick Tunnel needs no account. On this machine, start FastAPI from `backend/`
with `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`.
In another PowerShell window, run
`& "$env:LOCALAPPDATA\AkashiTools\cloudflared.exe" tunnel --url http://127.0.0.1:8000`.
Enter the generated HTTPS URL and the token from ignored `backend/.env` in
Connection Settings. Never tunnel Ollama or ComfyUI. Quick Tunnel
addresses expire/change and are for testing, not reliable production. The
backend PC must keep FastAPI, Ollama, and ComfyUI running for chat/images.

Image URLs returned by FastAPI are relative. The shared client fetches images
through FastAPI with the bearer header, then displays local blobs; tokens never
enter image URLs. EDIT uses the platform file/photo picker and uploads to the
existing `/image/edit` endpoint. Native speech recognition defaults to the
device language (Turkish where installed/supported); TTS chooses Turkish for
Turkish text when available.

## iOS development (macOS required)

The iOS target uses bundle identifier `com.akashiai.app`, display name
`AKASHİ AI`, iOS 15+, and Swift Package Manager. Microphone, speech-recognition,
and photo-library descriptions are in the Release and Debug property lists;
permissions are requested only when the user starts voice input or opens the
photo picker. Debug also includes the local-network explanation required for
explicit LAN testing.

On a Mac with Xcode and Node.js installed:

```bash
cd frontend
npm ci
npm run ios:sync
npx cap open ios
```

In Xcode, select the `App` target, choose your Apple development team under
Signing & Capabilities, select an iPhone/simulator, and run. A command-line
simulator build can be checked with:

```bash
xcodebuild -project ios/App/App.xcodeproj -scheme App \
  -configuration Debug -sdk iphonesimulator \
  -destination 'platform=iOS Simulator,name=iPhone 16' build
```

Use an HTTPS FastAPI URL at runtime. The backend CORS defaults include the iOS
Capacitor origin `capacitor://localhost` as well as the existing web/Android
origins.

Building an APK or AAB requires a local JDK and Android SDK/Android Studio.
Building or signing iOS requires macOS and Xcode; Windows can generate and sync
the project but cannot compile or sign it.
On this machine Gradle 8.14.3 requires the installed Temurin 21 JDK rather than
Android Studio's Java 25 JBR; set `JAVA_HOME` for the build process only.
The current Android application ID `com.akashiai.app` is provisional; finalize
it before distributing a release. Keep signing keys outside Git.
