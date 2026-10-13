#!/usr/bin/env python
"""locres.py - parse Unreal Engine .locres localization files (versions 0-3).

usage:  python tools/locres.py <file.locres> [out.json]
module: from locres import read_locres  ->  {namespace: {key: text}}
"""
import struct, sys, json, io

# FTextLocalizationResourceVersion::LocResMagic = FGuid(0x7574140E, 0xFC034A67, 0x9D1BB484, 0x24A6E1F8), serialized little-endian
MAGIC = struct.pack("<4I", 0x7574140E, 0xFC034A67, 0x9D90154A, 0x1B7F37C3)

def _fstring(f):
    (n,) = struct.unpack("<i", f.read(4))
    if n == 0:
        return ""
    if n < 0:
        b = f.read(-n * 2)
        return b.decode("utf-16-le")[:-1]
    b = f.read(n)
    return b.decode("utf-8", "replace")[:-1]

def read_locres(path):
    data = open(path, "rb").read()
    f = io.BytesIO(data)
    version = 0
    if data[:16] == MAGIC:
        f.seek(16)
        version = f.read(1)[0]
    else:
        f.seek(0)  # legacy (version 0) has no magic
    strings = None
    if version >= 1:
        (str_off,) = struct.unpack("<q", f.read(8))
        here = f.tell()
        f.seek(str_off)
        (count,) = struct.unpack("<i", f.read(4))
        strings = []
        for _ in range(count):
            s = _fstring(f)
            if version >= 2:
                f.read(4)  # ref count
            strings.append(s)
        f.seek(here)
    if version >= 2:
        f.read(4)  # entries count
    (ns_count,) = struct.unpack("<i", f.read(4))
    out = {}
    for _ in range(ns_count):
        if version >= 2:
            f.read(4)  # namespace key hash
        ns = _fstring(f)
        (key_count,) = struct.unpack("<i", f.read(4))
        table = out.setdefault(ns, {})
        for _ in range(key_count):
            if version >= 2:
                f.read(4)  # key hash
            key = _fstring(f)
            f.read(4)  # source string hash
            if version >= 1:
                (idx,) = struct.unpack("<i", f.read(4))
                table[key] = strings[idx]
            else:
                table[key] = _fstring(f)
    return out

if __name__ == "__main__":
    res = read_locres(sys.argv[1])
    total = sum(len(v) for v in res.values())
    print(f"namespaces={len(res)} entries={total}")
    if len(sys.argv) > 2:
        json.dump(res, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("wrote", sys.argv[2])
