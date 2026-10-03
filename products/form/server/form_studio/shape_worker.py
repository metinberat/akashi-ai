"""Fixed, isolated local SDK inference. Never download weights or execute asset code.

No vendor code is copied. The separately installed Hunyuan SDK/model retains its
own license. Outputs are quarantined from FORM expertise/training/datasets.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path


class ReferenceForegroundError(ValueError):
    """The foreground model has not established a usable character input."""


def apply_foreground(image, mask):
    """Reject partial estimates and trim feathered background before shape inference."""
    from PIL import Image

    binary = mask.convert("L").point(lambda value: 255 if value > 96 else 0)
    fraction = binary.histogram()[255] / (binary.width * binary.height)
    if not 0.15 < fraction < 0.96:
        raise ReferenceForegroundError("Provide a clean character crop or alpha mask.")
    result = image.copy()
    result.putalpha(binary.resize(image.size, Image.Resampling.NEAREST))
    return result.crop(result.getchannel("A").getbbox()), fraction


def prepare_reference(image):
    """Use an already cached local foreground model, never fetch a new weight."""
    import numpy as np
    from PIL import Image

    alpha = np.asarray(image.getchannel("A"))
    if (alpha < 32).any():
        return image, {"method": "supplied_alpha", "inference": False}
    checkpoint = Path.home() / ".u2net/u2net.onnx"
    if not checkpoint.is_file():
        raise ReferenceForegroundError(
            "No cached foreground model; supply clean alpha. No download attempted."
        )
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.intra_op_num_threads = 4
    session = ort.InferenceSession(
        str(checkpoint), sess_options=options, providers=["CPUExecutionProvider"]
    )
    rgb = np.asarray(image.convert("RGB").resize((320, 320)), dtype=np.float32) / 255.0
    rgb = (rgb - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array(
        [0.229, 0.224, 0.225], dtype=np.float32
    )
    inputs = np.transpose(rgb, (2, 0, 1))[None].astype(np.float32)
    mask = session.run(None, {session.get_inputs()[0].name: inputs})[0][0, 0]
    span = float(mask.max() - mask.min())
    if span < 1e-6:
        raise ReferenceForegroundError(
            "Local foreground model returned an ambiguous mask."
        )
    mask = ((mask - mask.min()) / span * 255).astype(np.uint8)
    fraction = float((mask > 96).mean())
    result, fraction = apply_foreground(image, Image.fromarray(mask))
    return result, {
        "method": "cached_u2net_onnx_cpu",
        "inference": True,
        "foreground_fraction": fraction,
        "model_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "scope": "learned foreground estimate, not anatomical or identity analysis",
    }


def run(args):
    import torch
    from PIL import Image, ImageOps
    from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline

    checkpoint, config = Path(args.checkpoint), Path(args.config)
    if (
        checkpoint.suffix != ".safetensors"
        or not checkpoint.is_file()
        or not config.is_file()
    ):
        raise ValueError(
            "Only operator-configured local safetensors/config are accepted."
        )
    if not torch.cuda.is_available():
        raise RuntimeError("Configured learned shape adapter needs local CUDA.")
    with Image.open(args.reference) as source:
        if source.width * source.height > 16000000:
            raise ValueError("Reference exceeds pixel budget.")
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail((768, 768))
    image, segmentation = prepare_reference(image)
    output = Path(args.output)
    if output.exists():
        raise ValueError("Shape inference cannot overwrite an existing artifact.")
    prepared = output.with_name(output.stem + "-reference.png")
    if prepared.exists():
        raise ValueError("Prepared reference cannot overwrite a prior artifact.")
    image.save(prepared, format="PNG")
    pipeline = Hunyuan3DDiTFlowMatchingPipeline.from_single_file(
        str(checkpoint),
        str(config),
        use_safetensors=True,
        device="cpu",
        dtype=torch.float16,
    )
    # The installed SDK revision exposes offload but omits its component registry.
    # Repair only this adapter instance; never edit vendor installation/source.
    if not hasattr(pipeline, "components"):
        pipeline.components = {
            "conditioner": pipeline.conditioner,
            "model": pipeline.model,
            "vae": pipeline.vae,
        }
    pipeline.enable_model_cpu_offload(device="cuda")
    # This SDK's sampling functions use .device rather than ._execution_device.
    # Set the input device without moving all components into VRAM at once.
    pipeline.device = torch.device("cuda:0")
    meshes = pipeline(
        image={"front": image},
        num_inference_steps=args.steps,
        octree_resolution=args.resolution,
        num_chunks=5000,
        guidance_scale=5.0,
        generator=torch.Generator(device="cpu").manual_seed(args.seed),
        enable_pbar=False,
    )
    mesh = meshes[0]
    if not len(mesh.vertices) or not len(mesh.faces):
        raise RuntimeError("Inference produced no geometry.")
    # Local presentation proposal, not recovered UV/texture truth. Visible front
    # colors are projected; unseen sides use a neutral inferred fallback.
    import numpy as np

    box = image.getchannel("A").getbbox() or (0, 0, image.width, image.height)
    crop = image.crop(box)
    pixels = np.asarray(crop)
    lower, upper = mesh.bounds
    normalized = (mesh.vertices - lower) / np.maximum(upper - lower, 1e-6)
    x = np.clip((normalized[:, 0] * (crop.width - 1)).astype(int), 0, crop.width - 1)
    y = np.clip(
        ((1 - normalized[:, 1]) * (crop.height - 1)).astype(int), 0, crop.height - 1
    )
    colors = pixels[y, x].copy()
    valid = colors[:, 3] > 96
    foreground = pixels[pixels[:, :, 3] > 96]
    fallback = (
        np.median(foreground, axis=0).astype(np.uint8)
        if len(foreground)
        else np.array([90, 90, 90, 255], dtype=np.uint8)
    )
    colors[~valid] = fallback
    colors[:, 3] = 255
    mesh.visual = __import__("trimesh").visual.ColorVisuals(mesh, vertex_colors=colors)
    mesh.metadata["form_training_allowed"] = False
    mesh.metadata["form_source_backend"] = "hunyuan3d2mv_local"
    mesh.export(str(output))
    if not output.is_file() or output.stat().st_size < 100:
        raise RuntimeError("No real export was created.")
    evidence = {
        "verified": True,
        "backend": "hunyuan3d2mv_local",
        "synthetic": True,
        "reference_sha256": hashlib.sha256(
            Path(args.reference).read_bytes()
        ).hexdigest(),
        "checkpoint": checkpoint.name,
        "checkpoint_bytes": checkpoint.stat().st_size,
        "config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "model_revision": checkpoint.parent.parent.name,
        "reference_preprocessing": segmentation,
        "steps": args.steps,
        "resolution": args.resolution,
        "seed": args.seed,
        "vertices": len(mesh.vertices),
        "faces": len(mesh.faces),
        "watertight": bool(mesh.is_watertight),
        "gpu": torch.cuda.get_device_name(0),
        "output_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "training_allowed": False,
        "expert_memory_allowed": False,
        "rig": "not_generated",
        "textures": "local_front_projected_vertex_colors; not recovered UV textures",
        "color_projection": {
            "axis": "x/y frontal assumption",
            "valid_samples": int(valid.sum()),
            "total": len(colors),
            "unseen_surface": "front projection or inferred median fallback; not observed source truth",
        },
        "scope": "single-view learned geometric proposal; hidden sides inferred, production topology and likeness unverified",
        "license": "Tencent Hunyuan 3D 2.0 Community License; territory/training/distribution restrictions apply",
    }
    Path(args.receipt).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {"verified": True, "vertices": len(mesh.vertices), "faces": len(mesh.faces)}
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("checkpoint", "config", "reference", "output", "receipt"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--steps", type=int, choices=(12, 30), default=12)
    parser.add_argument("--resolution", type=int, choices=(128, 192, 256), default=192)
    parser.add_argument("--seed", type=int, default=57)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        # Never print a provider config, private path or raw SDK exception.
        print(
            json.dumps({"verified": False, "error_category": type(exc).__name__}),
            flush=True,
        )
        if isinstance(exc, ReferenceForegroundError):
            Path(args.receipt).write_text(
                json.dumps(
                    {
                        "verified": False,
                        "error_category": "ReferenceForegroundError",
                        "reason": "Foreground estimate was partial/ambiguous. Supply a clean character crop or alpha mask; no shape accepted.",
                    }
                ),
                encoding="utf-8",
            )
        if os.getenv("FORM_SHAPE_TEST_DEBUG") == "1":
            import traceback

            traceback.print_exc()
        raise SystemExit(1)
