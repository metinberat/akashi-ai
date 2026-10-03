"""Opt-in validation using already configured local credentials; no secret output."""

import os
import subprocess
from pathlib import Path
from dotenv import dotenv_values

root = Path(__file__).resolve().parents[3]
values = dotenv_values(root / "backend" / ".env")
key = values.get("GEMINI_API_KEY") or values.get("AKASHI_GEMINI_API_KEY")
model = (
    values.get("AKASHI_MODEL_VISION_NAME")
    or values.get("GEMINI_MODEL")
    or values.get("GEMINI_MODEL_NAME")
)
if not key or not model:
    raise SystemExit("BLOCKED: Existing Gemini key/model is not configured.")
env = dict(os.environ)
env.update(
    FORM_GEMINI_API_KEY=key,
    FORM_VISION_PROVIDER="gemini",
    FORM_VISION_MODEL=model,
    FORM_REASONING_PROVIDER="gemini",
    FORM_REASONING_MODEL=model,
    FORM_TEST_AI="1",
)
result = subprocess.run(
    ["node", "tests/inspection-smoke.cjs"],
    cwd=root / "products" / "form",
    env=env,
    timeout=240,
    check=False,
)
raise SystemExit(result.returncode)
