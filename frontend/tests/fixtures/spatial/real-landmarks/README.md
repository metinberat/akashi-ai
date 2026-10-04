# Real landmark regression set

Each file is a validated `akashi.spatial.hand-recording/1` recording captured by
Spatial Lab's own recorder while the live provider ran **real MediaPipe Hand
Landmarker** (`hand_landmarker.task`, float16/1, SHA-256 pinned in
`scripts/spatial-assets.mjs`) inside Chromium. The camera was Chromium's fake
device playing a still MediaPipe test photograph (Apache-2.0 assets from
`storage.googleapis.com/mediapipe-assets`, pinned in
`tests/spatial-e2e/fake_camera.py`). Coordinates are rounded to 5 decimals and
trimmed to 12 frames.

Scope: real model output on real hands, but **still images on cloud CPU**. These
fixtures say nothing about live motion, lighting, latency or the user's webcam.
Regenerate with `npm run test:spatial -- hand-tracking` and copy from
`tests/spatial-e2e/.artifacts/hand-tracking/`.
