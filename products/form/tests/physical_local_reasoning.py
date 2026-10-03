"""Short actual installed Ollama test. No cloud credentials or new model downloads."""

import asyncio
import json
import os
from pathlib import Path
from form_studio.engine import Engine


async def main():
    os.environ.update(
        FORM_EXTERNAL_MODELS_ENABLED="false",
        FORM_REASONING_PROVIDER="ollama",
        FORM_REASONING_MODEL="qwen3:8b",
        FORM_VISION_PROVIDER="",
    )
    root = Path(__file__).resolve().parents[1] / ".validation/local-reasoning"
    e = Engine(root)
    p = e.projects.create(
        "Synthetic local reasoning",
        "Stylized coat character, not professional likeness.",
    )
    reply, evidence = await e.propose(
        p["id"],
        "Propose a supported slender humanoid with a short hairstyle, a coat and local HUD rings. No production has started. Return a concise design proposal only.",
        True,
    )
    result = {
        "evidence": evidence,
        "reply": reply.model_dump(),
        "cloud_enabled": False,
        "model": "installed qwen3:8b",
        "automatic_execution": bool(e.production.worker),
    }
    assert not e.production.worker
    (root.parent / "local-reasoning-report.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "model_status": evidence["model_status"],
                "intent": reply.intent,
                "automatic_execution": False,
            }
        )
    )
    await e.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
