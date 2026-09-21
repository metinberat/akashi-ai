"""Run the practical EDIT acceptance set against a local AKASHI backend.

Generated fixtures and outputs are written to the OS temporary directory, never
to repository data or source control.
"""

import argparse
import json
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict

import httpx

from app.core.config import get_settings


SOURCE_PROMPT = (
    "Photorealistic editorial photograph of one person wearing a bright blue jacket "
    "seated at a wooden table with a red ceramic cup. A large window clearly shows a "
    "blue daytime sky. A clear simple circular logo sign is mounted on the wall. "
    "Balanced daylight, all requested elements visible, square composition."
)
EDIT_PROMPTS = [
    "Arka planı siyah yap.",
    "Masadaki bardağı kaldır.",
    "Kıyafeti beyaz yap.",
    "Gökyüzünü gece yap.",
    "Logoyu kaldır.",
]


def parse_server_timing(value: str) -> Dict[str, float]:
    result: Dict[str, float] = {}
    for part in value.split(","):
        fields = [field.strip() for field in part.split(";")]
        if not fields or len(fields) < 2 or not fields[1].startswith("dur="):
            continue
        try:
            result[fields[0]] = float(fields[1][4:])
        except ValueError:
            continue
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--profile", choices=["fast", "quality"])
    parser.add_argument("--prompt", action="append")
    args = parser.parse_args()
    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.api_token}"} if settings.api_token else {}
    root = Path(tempfile.gettempdir()) / f"akashi-edit-benchmark-{int(time.time())}"
    root.mkdir(parents=True, exist_ok=False)
    records = []

    with httpx.Client(base_url="http://127.0.0.1:8000", headers=headers, timeout=360.0) as client:
        if args.source:
            source_file = args.source.resolve()
            if not source_file.is_file():
                raise FileNotFoundError(source_file)
        else:
            generation_started = time.perf_counter()
            generated = client.post("/image/fast-test", json={"prompt": SOURCE_PROMPT})
            generated.raise_for_status()
            source_path = generated.json()["images"][0]
            source_response = client.get(source_path)
            source_response.raise_for_status()
            source_file = root / "source.png"
            source_file.write_bytes(source_response.content)
            records.append({
                "kind": "source_generation",
                "wall_ms": round((time.perf_counter() - generation_started) * 1000, 1),
                "result_transfer_ms": round(source_response.elapsed.total_seconds() * 1000, 1),
                "bytes": len(source_response.content),
                "output": str(source_file),
            })

        prompts = args.prompt or EDIT_PROMPTS
        cases = (
            [(args.profile, prompt) for prompt in prompts]
            if args.profile else
            [("fast", prompt) for prompt in prompts] + [("quality", prompts[0])]
        )
        for index, (profile, prompt) in enumerate(cases, start=1):
            request_id = str(uuid.uuid4())
            started = time.perf_counter()
            with source_file.open("rb") as source:
                response = client.post(
                    "/image/edit",
                    data={"prompt": prompt, "profile": profile, "request_id": request_id},
                    files={"image": (source_file.name, source, "image/png")},
                )
            wall_ms = (time.perf_counter() - started) * 1000
            response.raise_for_status()
            timing = parse_server_timing(response.headers.get("server-timing", ""))
            result_path = response.json()["images"][0]
            transfer_started = time.perf_counter()
            image_response = client.get(result_path)
            image_response.raise_for_status()
            transfer_ms = (time.perf_counter() - transfer_started) * 1000
            output_file = root / f"{index:02d}-{profile}.png"
            output_file.write_bytes(image_response.content)
            records.append({
                "kind": "edit",
                "profile": profile,
                "prompt": prompt,
                "request_wall_ms": round(wall_ms, 1),
                "transport_and_response_ms": round(max(0.0, wall_ms - timing.get("api_total", wall_ms)), 1),
                "server_timing_ms": timing,
                "result_transfer_ms": round(transfer_ms, 1),
                "result_server_timing_ms": parse_server_timing(image_response.headers.get("server-timing", "")),
                "bytes": len(image_response.content),
                "output": str(output_file),
            })

    print(json.dumps({"output_directory": str(root), "records": records}, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
