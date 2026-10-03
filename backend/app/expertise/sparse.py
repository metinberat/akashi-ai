"""Bounded glTF sparse overlay decoding; never fetch external buffers."""

import math
import struct


def apply_sparse(data, buffers, accessor, result):
    sparse = accessor.get("sparse")
    if not sparse:
        return result
    count = sparse.get("count")
    if type(count) is not int or not 1 <= count <= len(result):
        raise ValueError("Sparse count exceeds accessor.")
    component = {
        5120: ("b", 1),
        5121: ("B", 1),
        5122: ("h", 2),
        5123: ("H", 2),
        5125: ("I", 4),
        5126: ("f", 4),
    }[accessor["componentType"]]
    indices = sparse.get("indices", {})
    index_component = {5121: ("B", 1), 5123: ("H", 2), 5125: ("I", 4)}.get(
        indices.get("componentType")
    )
    if not index_component:
        raise ValueError("Invalid sparse index type.")
    dimensions = len(result[0]) if isinstance(result[0], list) else 1

    def unpack(part, descriptor, dimensions):
        reference = part.get("bufferView")
        views = data.get("bufferViews", [])
        if type(reference) is not int or not 0 <= reference < len(views):
            raise ValueError("Invalid sparse buffer view.")
        view = views[reference]
        if "byteStride" in view or "target" in view:
            raise ValueError("Sparse view must be tightly packed.")
        reference = view.get("buffer")
        if type(reference) is not int or not 0 <= reference < len(buffers):
            raise ValueError("Invalid sparse buffer.")
        buffer = buffers[reference]
        if not buffer:
            return None
        fmt, size = descriptor
        offset, length, local = (
            view.get("byteOffset", 0),
            view.get("byteLength"),
            part.get("byteOffset", 0),
        )
        if (
            any(type(v) is not int or v < 0 for v in (offset, length, local))
            or offset + length > len(buffer)
            or local + count * size * dimensions > length
            or (offset + local) % size
        ):
            raise ValueError("Sparse data outside buffer view.")
        return [
            list(
                struct.unpack_from(
                    "<" + fmt * dimensions,
                    buffer,
                    offset + local + i * size * dimensions,
                )
            )
            for i in range(count)
        ]

    positions = unpack(indices, index_component, 1)
    values = unpack(sparse.get("values", {}), component, dimensions)
    if positions is None or values is None:
        return []  # Actual buffer unavailable, not invented zero-valued data.
    previous = -1
    for (position,), row in zip(positions, values):
        if not previous < position < len(result):
            raise ValueError("Sparse indices must be increasing and in range.")
        previous = position
        if any(not math.isfinite(v) for v in row):
            raise ValueError("Sparse values must be finite.")
        fmt, size = component
        if accessor.get("normalized") and accessor["componentType"] != 5126:
            divisor = (
                2 ** (size * 8 - 1) - 1 if fmt in {"b", "h"} else 2 ** (size * 8) - 1
            )
            row = [max(-1, v / divisor) for v in row]
        result[position] = row[0] if dimensions == 1 else row
    return result
