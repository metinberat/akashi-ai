"""Bounded offline GLB container validation; not a generic file download endpoint."""

import hashlib
import json
import struct


def validate_references(value, binary_reader=None):
    """Validate actual buffer/mesh/skin/animation references, not only feature counts."""

    def index(key, number):
        if type(number) is not int or not 0 <= number < len(value.get(key, [])):
            raise ValueError("Invalid GLB " + key + " reference.")
        return value[key][number]

    if len(value.get("buffers", [])) > 1:
        raise ValueError("GLB must use one embedded buffer.")
    for view in value.get("bufferViews", []):
        buffer = index("buffers", view.get("buffer"))
        start, length = view.get("byteOffset", 0), view.get("byteLength")
        if (
            type(start) is not int
            or type(length) is not int
            or start < 0
            or length < 0
            or start + length > buffer["byteLength"]
        ):
            raise ValueError("GLB buffer view exceeds its buffer.")
    sizes = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
    components = {
        "SCALAR": 1,
        "VEC2": 2,
        "VEC3": 3,
        "VEC4": 4,
        "MAT2": 4,
        "MAT3": 9,
        "MAT4": 16,
    }
    for accessor in value.get("accessors", []):
        count, offset = accessor.get("count"), accessor.get("byteOffset", 0)
        component = sizes.get(accessor.get("componentType"), 0)
        width = component * components.get(accessor.get("type"), 0)
        if accessor.get("type") in {"MAT2", "MAT3", "MAT4"} and component:
            columns = int(accessor["type"][-1])
            width = columns * (((columns * component + 3) // 4) * 4)
        if (
            not width
            or type(count) is not int
            or not 0 <= count <= 2000000
            or type(offset) is not int
            or offset < 0
        ):
            raise ValueError("Invalid GLB accessor layout.")
        if "bufferView" in accessor:
            view = index("bufferViews", accessor["bufferView"])
            stride = view.get("byteStride", width)
            if (
                type(stride) is not int
                or stride < width
                or offset + (max(0, count - 1) * stride + width if count else 0)
                > view["byteLength"]
            ):
                raise ValueError("GLB accessor exceeds buffer view.")
        elif offset:
            raise ValueError("Zero-initialized accessor cannot have a base offset.")
        sparse = accessor.get("sparse")
        if sparse:
            number = sparse.get("count")
            if type(number) is not int or not 1 <= number <= count:
                raise ValueError("Invalid sparse accessor count.")
            parts = sparse.get("indices", {}), sparse.get("values", {})
            kind = parts[0].get("componentType")
            size = {5121: 1, 5123: 2, 5125: 4}.get(kind)
            if not size:
                raise ValueError("Invalid sparse index type.")
            for part, element in zip(parts, (size, width)):
                view = index("bufferViews", part.get("bufferView"))
                start = part.get("byteOffset", 0)
                if (
                    "byteStride" in view
                    or "target" in view
                    or type(start) is not int
                    or start < 0
                    or start + number * element > view["byteLength"]
                ):
                    raise ValueError("Sparse data exceeds its packed buffer view.")
            if binary_reader:
                view = index("bufferViews", parts[0]["bufferView"])
                start = view.get("byteOffset", 0) + parts[0].get("byteOffset", 0)
                raw = binary_reader(start, number * size)
                previous = -1
                for (position,) in struct.iter_unpack(
                    {5121: "<B", 5123: "<H", 5125: "<I"}[kind], raw
                ):
                    if not previous < position < count:
                        raise ValueError(
                            "Sparse indices must be ordered, unique and in range."
                        )
                    previous = position
    for image in value.get("images", []):
        if "uri" in image or "bufferView" not in image:
            raise ValueError("Export image must be embedded, not an external resource.")
        index("bufferViews", image["bufferView"])
    for mesh in value.get("meshes", []):
        if not mesh.get("primitives"):
            raise ValueError("GLB mesh has no primitives.")
        for primitive in mesh["primitives"]:
            if "POSITION" not in primitive.get("attributes", {}):
                raise ValueError("GLB primitive has no positions.")
            for attribute in primitive["attributes"].values():
                index("accessors", attribute)
            if "indices" in primitive:
                index("accessors", primitive["indices"])
            if "material" in primitive:
                index("materials", primitive["material"])
            for target in primitive.get("targets", []):
                for attribute in target.values():
                    index("accessors", attribute)
    for node in value.get("nodes", []):
        for field, key in (("mesh", "meshes"), ("skin", "skins")):
            if field in node:
                index(key, node[field])
        for child in node.get("children", []):
            index("nodes", child)
    for skin in value.get("skins", []):
        for joint in skin.get("joints", []):
            index("nodes", joint)
        if "inverseBindMatrices" in skin:
            index("accessors", skin["inverseBindMatrices"])
    for animation in value.get("animations", []):
        for sampler in animation.get("samplers", []):
            index("accessors", sampler.get("input"))
            index("accessors", sampler.get("output"))
        for channel in animation.get("channels", []):
            sampler = channel.get("sampler")
            if type(sampler) is not int or not 0 <= sampler < len(
                animation.get("samplers", [])
            ):
                raise ValueError("Invalid GLB animation sampler.")
            index("nodes", channel.get("target", {}).get("node"))


def inspect_export(paths, arguments):
    path = paths.resolve(str(arguments.get("project") or ""))
    if (
        path.suffix.casefold() != ".glb"
        or not path.is_file()
        or path.stat().st_size < 20
        or path.stat().st_size > 128 * 1024 * 1024
    ):
        raise ValueError("Expected bounded approved GLB.")
    with path.open("rb") as stream:
        magic, version, size = struct.unpack("<4sII", stream.read(12))
        if magic != b"glTF" or version != 2 or size != path.stat().st_size:
            raise ValueError("Invalid GLB header/size.")
        length, kind = struct.unpack("<I4s", stream.read(8))
        if kind != b"JSON" or not 0 < length <= 16 * 1024 * 1024:
            raise ValueError("Invalid GLB JSON bounds.")
        value = json.loads(stream.read(length))
        if value.get("asset", {}).get("version") != "2.0" or any(
            "uri" in b for b in value.get("buffers", [])
        ):
            raise ValueError("Export must be self-contained GLB.")
        binary = 0
        binary_offset = None
        while stream.tell() < size:
            length, kind = struct.unpack("<I4s", stream.read(8))
            if stream.tell() + length > size:
                raise ValueError("Truncated GLB chunk.")
            if kind == b"BIN\x00":
                if binary_offset is not None:
                    raise ValueError("Multiple GLB binary chunks.")
                binary_offset, binary = stream.tell(), length
            stream.seek(length, 1)
        if sum(b.get("byteLength", 0) for b in value.get("buffers", [])) > binary:
            raise ValueError("GLB buffer correspondence mismatch.")

        def read_binary(start, length):
            if binary_offset is None or start < 0 or start + length > binary:
                raise ValueError("Sparse index data exceeds binary chunk.")
            stream.seek(binary_offset + start)
            return stream.read(length)

        validate_references(value, read_binary)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "verified": bool(value.get("meshes")),
        "sha256": digest.hexdigest(),
        "bytes": size,
        "meshes": len(value.get("meshes", [])),
        "skins": len(value.get("skins", [])),
        "animations": len(value.get("animations", [])),
        "materials": len(value.get("materials", [])),
        "images": len(value.get("images", [])),
        "scope": "GLB container/buffer and feature presence; engine import/artistic quality not certified",
    }
