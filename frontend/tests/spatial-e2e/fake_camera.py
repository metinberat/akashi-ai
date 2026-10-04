"""Build Chromium fake-camera videos from MediaPipe's own hand test photographs.

The photos are MediaPipe test assets (Apache-2.0, storage.googleapis.com/
mediapipe-assets), pinned by SHA-256. Each becomes a looping Y4M clip used with
--use-file-for-fake-video-capture. This exercises the real camera API, the real
MediaPipe runtime and model, and Spatial Lab's live provider on real hands —
but on STILL photographs, not a live webcam, real lighting or motion.

    python fake_camera.py <output dir>
"""

import hashlib
import sys
import urllib.request
from pathlib import Path

from PIL import Image

PHOTOS = {
    "fist": "43fa1cabf3f90d574accc9a56986e2ee48638ce59fc65af1846487f73bb2ef24",
    "victory": "84cb8853e3df614e0cb5c93a25e3e2f38ea5e4f92fd428ee7d867ed3479d5764",
    "pointing_up": "ecf8ca2611d08fa25948a4fc10710af9120e88243a54da6356bacea17ff3e36e",
    "thumb_up": "5d673c081ab13b8a1812269ff57047066f9c33c07db5f4178089e8cb3fdc0291",
    "right_hands": "4b5134daa4cb60465535239535f9f74c2842aba3aa5fd30bf04ef5678f93d87f",
    "left_hands": "240c082e80128ff1ca8a83ce645e2ba4d8bc30f0967b7991cf5fa375bab489e1",
}
WIDTH, HEIGHT, FPS, FRAMES = 640, 480, 15, 30


def fetch(name: str, digest: str, directory: Path) -> Path:
    path = directory / f"{name}.jpg"
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        data = urllib.request.urlopen(f"https://storage.googleapis.com/mediapipe-assets/{name}.jpg", timeout=30).read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise SystemExit(f"{name}.jpg does not match its pinned SHA-256; refusing to use it.")
        path.write_bytes(data)
    return path


def y4m(photo: Path, output: Path) -> None:
    image = Image.open(photo).convert("RGB")
    scale = min(WIDTH / image.width, HEIGHT / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), (238, 238, 236))
    canvas.paste(resized, ((WIDTH - resized.width) // 2, (HEIGHT - resized.height) // 2))
    y, cb, cr = canvas.convert("YCbCr").split()
    half = (WIDTH // 2, HEIGHT // 2)
    frame = b"FRAME\n" + y.tobytes() + cb.resize(half, Image.BOX).tobytes() + cr.resize(half, Image.BOX).tobytes()
    with output.open("wb") as stream:
        stream.write(f"YUV4MPEG2 W{WIDTH} H{HEIGHT} F{FPS}:1 Ip A1:1 C420jpeg\n".encode())
        for _ in range(FRAMES):
            stream.write(frame)


def main() -> None:
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True)
    for name, digest in PHOTOS.items():
        y4m(fetch(name, digest, directory), directory / f"{name}.y4m")
    print("ok")


if __name__ == "__main__":
    main()
