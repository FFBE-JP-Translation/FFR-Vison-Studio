r"""cpk.py - minimal CRI CPK reader/extractor (UTF tables incl. the XOR-masked variant FFBE uses, CRILAYLA decompression).

python tools/devui/cpk.py list <file.cpk>
python tools/devui/cpk.py extract <file.cpk> <out dir> [name filter]
"""
import os, struct, sys

def unmask(buf):
    """FFBE masks its @UTF tables: b ^= m; m = m * t (m=0x5f, t=0x15)"""
    if buf[:4] == b"@UTF": return bytes(buf)
    out = bytearray(len(buf)); m, t = 0x5F, 0x15
    for i, b in enumerate(buf):
        out[i] = b ^ m; m = (m * t) & 0xFF
    return bytes(out)

def read_utf(chunk):
    """chunk = bytes starting at '@UTF' (possibly masked) -> (table name, list of row dicts)"""
    data = unmask(chunk[:4]) + chunk[4:]
    if data[:4] != b"@UTF": raise ValueError("not a UTF table")
    size = struct.unpack(">I", chunk[4:8])[0]
    body = unmask(chunk[8:8 + size]) if chunk[8:12] != b"\x00\x00\x00\x00" and unmask(chunk[:4]) == b"@UTF" and chunk[:4] != b"@UTF" else chunk[8:8 + size]
    # when the whole table is masked the mask runs continuously from the magic: re-derive over the full chunk
    if chunk[:4] != b"@UTF":
        full = unmask(chunk[:8 + size]); body = full[8:]
    rows_off, str_off, data_off, name_off, ncol, rowlen, nrows = struct.unpack(">IIIIHHI", body[:24])
    def cstr(o):
        s = body[str_off + o:]; return s[:s.index(b"\x00")].decode("utf-8", "replace")
    cols = []; p = 24
    for _ in range(ncol):
        flags = body[p]; p += 1
        name = cstr(struct.unpack(">I", body[p:p + 4])[0]); p += 4
        typ, storage = flags & 0x0F, flags & 0xF0
        const = None
        if storage == 0x30:   # constant value stored inline
            const, p = read_value(body, p, typ, str_off, data_off, cstr)
        cols.append((name, typ, storage, const))
    rows = []
    for r in range(nrows):
        p = rows_off + r * rowlen; row = {}
        for name, typ, storage, const in cols:
            if storage == 0x50: v, p = read_value(body, p, typ, str_off, data_off, cstr)
            elif storage == 0x30: v = const
            else: v = None
            row[name] = v
        rows.append(row)
    return cstr(name_off), rows

def read_value(body, p, typ, str_off, data_off, cstr):
    if typ in (0, 1): return (body[p] if typ == 0 else struct.unpack(">b", body[p:p + 1])[0]), p + 1
    if typ in (2, 3): return struct.unpack(">H" if typ == 2 else ">h", body[p:p + 2])[0], p + 2
    if typ in (4, 5): return struct.unpack(">I" if typ == 4 else ">i", body[p:p + 4])[0], p + 4
    if typ in (6, 7): return struct.unpack(">Q" if typ == 6 else ">q", body[p:p + 8])[0], p + 8
    if typ == 8: return struct.unpack(">f", body[p:p + 4])[0], p + 4
    if typ == 0xA: return cstr(struct.unpack(">I", body[p:p + 4])[0]), p + 4
    if typ == 0xB:
        o, n = struct.unpack(">II", body[p:p + 8]); return (data_off + o, n), p + 8
    raise ValueError(f"utf type {typ}")

def crilayla(data):
    if data[:8] != b"CRILAYLA": return data
    usize, hoff = struct.unpack("<II", data[8:16])
    prefix = data[0x10 + hoff:0x10 + hoff + 0x100]
    out = bytearray(usize + 0x100); out[:0x100] = prefix
    inp = data; in_off = 0x10 + hoff - 1; pool = 0; left = 0; produced = 0
    out_end = 0x100 + usize - 1
    def bits(n):
        nonlocal in_off, pool, left
        v = 0; got = 0
        while got < n:
            if left == 0: pool = inp[in_off]; left = 8; in_off -= 1
            take = min(left, n - got)
            v = (v << take) | ((pool >> (left - take)) & ((1 << take) - 1))
            left -= take; got += take
        return v
    while produced < usize:
        if bits(1):
            ref = out_end - produced + bits(13) + 3
            length = 3; lvl = 0
            for l in (2, 3, 5, 8):
                this = bits(l); length += this
                if this != (1 << l) - 1: break
                lvl += 1
            if lvl == 4:
                while True:
                    this = bits(8); length += this
                    if this != 255: break
            for _ in range(length):
                out[out_end - produced] = out[ref]; ref -= 1; produced += 1
        else:
            out[out_end - produced] = bits(8); produced += 1
    return bytes(out)

class Cpk:
    def __init__(self, path):
        self.path = path; self.f = open(path, "rb")
        if self.f.read(4) != b"CPK ": raise ValueError("not a CPK")
        self.f.seek(0x10)
        hdr = self.f.read(struct.unpack(">I", self.f.read(4)[:4])[0] + 8) if False else None
        self.f.seek(0x10); head = self.f.read(8); size = struct.unpack(">I", head[4:8])[0]
        self.f.seek(0x10); chunk = self.f.read(8 + size)
        _, rows = read_utf(chunk); h = rows[0]
        self.toc_off = h.get("TocOffset"); self.content_off = h.get("ContentOffset"); self.files = h.get("Files")
        self.entries = []
        if self.toc_off:
            self.f.seek(self.toc_off + 0x10); head = self.f.read(8); size = struct.unpack(">I", head[4:8])[0]
            self.f.seek(self.toc_off + 0x10); chunk = self.f.read(8 + size)
            _, trows = read_utf(chunk)
            base = min(self.toc_off, self.content_off) if self.content_off else self.toc_off
            for r in trows:
                self.entries.append({"dir": r.get("DirName") or "", "name": r.get("FileName"), "size": r.get("FileSize"), "extract": r.get("ExtractSize"),
                                     "offset": base + (r.get("FileOffset") or 0), "id": r.get("ID")})
    def read(self, e):
        self.f.seek(e["offset"]); raw = self.f.read(e["size"])
        return crilayla(raw)
    def extract(self, out, filt=None):
        n = 0
        for e in self.entries:
            if filt and filt not in (e["name"] or ""): continue
            dst = os.path.join(out, e["dir"], e["name"]) if e["dir"] else os.path.join(out, e["name"])
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(self.read(e)); n += 1
        return n

if __name__ == "__main__":
    cmd, path = sys.argv[1], sys.argv[2]
    c = Cpk(path)
    if cmd == "list":
        for e in c.entries: print(f"{e['size']:>10} {e['extract']:>10} {e['dir']}/{e['name']}")
        print(len(c.entries), "files")
    else:
        n = c.extract(sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None); print("extracted", n, "files to", sys.argv[3])
