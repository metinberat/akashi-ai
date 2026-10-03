"""Bounded, hash-checked staging for typed character JSON, not a general file stream."""
import hashlib
import json
from pathlib import Path

MAX_PATCH_BYTES = 32*1024*1024


def stage_patch(paths, arguments, kind="weights"):
    output = paths.resolve(str(arguments.get("output") or ""), must_exist=False)
    paths.resolve(str(output.parent))
    if output.suffix.casefold() != ".json" or output.exists():
        raise ValueError("Character patch staging needs a NEW approved JSON artifact.")
    count, index = arguments.get("chunk_count"), arguments.get("chunk_index")
    digest, chunk = arguments.get("sha256"), arguments.get("chunk")
    if type(count) is not int or not 1 <= count <= 1500 or type(index) is not int or not 0 <= index < count:
        raise ValueError("Invalid character patch chunk bounds.")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError("Invalid patch SHA-256.")
    if not isinstance(chunk, str) or len(chunk.encode("utf-8")) > 24000:
        raise ValueError("Character patch chunk exceeds the transport budget.")
    # Identifier is derived, never caller-controlled as a staging path.
    identity = hashlib.sha256((str(output)+digest).encode()).hexdigest()[:24]
    intended_staging = output.parent/('.akashi-character-'+identity)
    staging = paths.resolve(str(intended_staging), must_exist=False)
    if staging != intended_staging:
        raise PermissionError("Character staging directory cannot redirect through a link.")
    staging.mkdir(exist_ok=True)

    def checked_child(name):
        intended = staging/name
        resolved = paths.resolve(str(intended), must_exist=False)
        if resolved != intended or intended.is_symlink() or (intended.exists() and intended.stat().st_nlink > 1):
            raise PermissionError("Character staging files cannot redirect through links.")
        return resolved

    manifest = checked_child("manifest.json")
    value = {"output": str(output), "sha256": digest, "chunks": count}
    if manifest.exists():
        if json.loads(manifest.read_text()) != value:
            raise ValueError("Character staging identity mismatch.")
    else:
        with manifest.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(value))
    part = checked_child("part-%04d" % index)
    content = chunk.encode("utf-8")
    if part.exists() and part.read_bytes() != content:
        raise ValueError("Chunk replay differs from the original bytes.")
    parts = [checked_child("part-%04d" % i) for i in range(count)]
    if sum(p.stat().st_size for p in parts if p.exists()) + (0 if part.exists() else len(content)) > MAX_PATCH_BYTES:
        raise ValueError("Character patch exceeds 32 MiB.")
    if not part.exists():
        with part.open("xb") as stream:
            stream.write(content)
    if not all(p.is_file() for p in parts):
        return {"verified": True, "complete": False, "received_chunk": index}
    payload = b"".join(p.read_bytes() for p in parts)
    if hashlib.sha256(payload).hexdigest() != digest:
        raise ValueError("Assembled character patch hash mismatch.")
    decoded = json.loads(payload)
    if kind == "production":
        from .production_contract import validate_production
        validate_production(decoded)
    elif kind == "character":
        from .character_document import validate_document
        validate_document(decoded, construction=True)
    elif (not isinstance(decoded, dict) or decoded.get("schema_version") != 1 or not isinstance(decoded.get("patches"), list)
        or set(decoded)-{"schema_version", "version_id", "synthetic", "patches", "quality_scope", "source_digest"}):
        raise ValueError("Assembled data is not a character weight patch.")
    # Exclusive creation: staging never overwrites an existing asset/configuration.
    with output.open("xb") as stream:
        stream.write(payload)
    for p in parts:
        p.unlink()
    manifest.unlink()
    staging.rmdir()
    return {"verified": True, "complete": True, "sha256": digest, "bytes": len(payload), "output": str(output)}
