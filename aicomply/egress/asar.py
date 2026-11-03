"""Read-only reader for Electron .asar archives (header pickle + concatenated files)."""

from __future__ import annotations

import json
import struct
from collections.abc import Iterator


def iter_asar(path: str) -> Iterator[tuple[str, bytes]]:
    """Yields (inner path, bytes) for every packed file, reading entries one at a time."""
    with open(path, "rb") as f:
        head = f.read(16)
        if len(head) < 16:
            raise ValueError("asar header too short")
        header_size = struct.unpack_from("<I", head, 4)[0]
        json_len = struct.unpack_from("<I", head, 12)[0]
        header = json.loads(f.read(json_len).decode("utf-8"))
        base = 8 + header_size

        def walk(node: dict, prefix: str):
            for name, entry in node.get("files", {}).items():
                inner = f"{prefix}/{name}" if prefix else name
                if "files" in entry:
                    yield from walk(entry, inner)
                elif not entry.get("unpacked") and "offset" in entry:
                    f.seek(base + int(entry["offset"]))
                    yield inner, f.read(int(entry["size"]))

        yield from walk(header, "")


def build_asar(files: dict[str, bytes]) -> bytes:
    """Builds a minimal archive. Used by the tests, not by the scanner."""
    tree: dict = {"files": {}}
    blobs, offset = [], 0
    for name, content in files.items():
        node = tree
        *dirs, leaf = name.split("/")
        for d in dirs:
            node = node["files"].setdefault(d, {"files": {}})
        node["files"][leaf] = {"size": len(content), "offset": str(offset)}
        blobs.append(content)
        offset += len(content)
    header = json.dumps(tree).encode("utf-8")
    padded = header + b"\0" * ((4 - len(header) % 4) % 4)
    pickle = struct.pack("<II", len(padded) + 4, len(header)) + padded
    return struct.pack("<II", 4, len(pickle)) + pickle + b"".join(blobs)
