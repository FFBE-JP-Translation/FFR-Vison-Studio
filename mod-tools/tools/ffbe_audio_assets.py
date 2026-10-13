"""Small audio manifests and shared, content-addressed FFBE HCA recordings."""
import hashlib
import json
from pathlib import Path


def read(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema") != "ffr-audio-1":
        raise ValueError("Unsupported FFBE audio manifest")
    return doc


def waves(path, doc):
    # Unit LBs and shared effect banks keep recordings in the same hash cache.
    root = Path(path).parent
    if root.name in ("lb", "effects"):
        root = root.parent
    result = {}
    for key, info in doc["waves"].items():
        digest = info["sha256"]
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("Invalid FFBE audio checksum")
        data = (root / "samples" / (digest + ".hca")).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("FFBE sound recording checksum mismatch")
        result[int(key)] = data
    return result
