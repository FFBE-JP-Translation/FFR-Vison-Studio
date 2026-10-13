r"""acb_cues.py - cue id -> cue name (and waveform index) of a CRI ACB bank, read from its @UTF tables.

FFBE's effect groups name sounds by cue id (F_EFFECT_GROUP_MST "frame:seId"); vgmstream lists the bank's streams by cue name.
This joins the two: python tools/ffbe_effects/acb_cues.py "S:\FFBE JP Data Export\public\SE.acb" [cueId ...]
"""
import struct, sys, json


def utf(buf, base=0):
    """Parses one @UTF table at buf[base:] -> (name, [row dicts]). Offsets inside are relative to base + 8."""
    assert buf[base:base + 4] == b"@UTF", "not a @UTF table"
    size = struct.unpack_from(">I", buf, base + 4)[0]
    o = base + 8
    rows_off, str_off, data_off, name_off, ncol, rowlen, nrows = struct.unpack_from(">HHIIIHHI", buf, o)[1:]
    # the header is: u16 version, u16 rows_offset, u32 strings_offset, u32 data_offset, u32 name_offset, u16 columns, u16 row_length, u32 rows
    version, rows_off, str_off, data_off, name_off, ncol, rowlen, nrows = struct.unpack_from(">HHIIIHHI", buf, o)
    strings = buf[o + str_off:o + data_off]
    def cstr(off):
        end = strings.index(b"\0", off)
        return strings[off:end].decode("utf-8", "replace")
    cols = []
    p = o + 0x18
    for _ in range(ncol):
        flags = buf[p]; p += 1
        typ, storage = flags & 0x0F, flags & 0xF0
        cname = cstr(struct.unpack_from(">I", buf, p)[0]); p += 4
        const = None
        if storage == 0x30:
            const, p = read_value(buf, p, typ, strings, o + data_off)
        cols.append((cname, typ, storage, const))
    rows = []
    for r in range(nrows):
        p = o + rows_off + r * rowlen
        row = {}
        for cname, typ, storage, const in cols:
            if storage == 0x50:
                row[cname], p = read_value(buf, p, typ, strings, o + data_off)
            elif storage == 0x30:
                row[cname] = const
            else:
                row[cname] = None
        rows.append(row)
    return cstr(name_off), rows


SIZES = {0: (1, ">B"), 1: (1, ">b"), 2: (2, ">H"), 3: (2, ">h"), 4: (4, ">I"), 5: (4, ">i"), 6: (8, ">Q"), 7: (8, ">q"), 8: (4, ">f"), 9: (8, ">d")}


def read_value(buf, p, typ, strings, data_base):
    if typ in SIZES:
        n, fmt = SIZES[typ]
        return struct.unpack_from(fmt, buf, p)[0], p + n
    if typ == 0xA:
        off = struct.unpack_from(">I", buf, p)[0]
        end = strings.index(b"\0", off)
        return strings[off:end].decode("utf-8", "replace"), p + 4
    if typ == 0xB:
        off, size = struct.unpack_from(">II", buf, p)
        return buf[data_base + off:data_base + off + size], p + 8
    raise ValueError(f"utf type {typ}")


def cues(path):
    """-> {cueId: {"name", "cueIndex", "referenceType", "referenceIndex", "waveformIndex"}}"""
    with open(path, "rb") as file:
        buf = file.read()
    _, header = utf(buf)
    h = header[0]
    cue_rows = utf(h["CueTable"])[1]
    name_rows = utf(h["CueNameTable"])[1]
    graph = CueGraph(h)
    names = {r["CueIndex"]: r["CueName"] for r in name_rows}
    out = {}
    for i, c in enumerate(cue_rows):
        try:
            waves = graph.waveforms(c["ReferenceType"], c["ReferenceIndex"])
        except ValueError:
            waves = []  # unknown graphs are not misrepresented as a direct wave
        out[c["CueId"]] = {"name": names.get(i), "cueIndex": i, "referenceType": c.get("ReferenceType"), "referenceIndex": c.get("ReferenceIndex"),
                          "waveformIndex": waves[0] if len(waves) == 1 else None, "waveformIndices": waves}
    return out


class CueGraph:
    """ACB references: 1 waveform, 2 synth, 3 sequence. See vgmstream/meta/acb.c."""
    def __init__(self, header):
        self.tables = {name: utf(header[name])[1] if header.get(name) else [] for name in
                       ("SequenceTable", "SynthTable", "TrackTable", "TrackEventTable", "WaveformTable")}
        # ACB <= 1.27 stores track events in the shared CommandTable.
        # See vgmstream/src/meta/acb.c, preload_acb_trackcommand.
        if not header.get("TrackEventTable") and header.get("CommandTable"):
            self.tables["TrackEventTable"] = utf(header["CommandTable"])[1]

    def row(self, table, index):
        rows = self.tables[table]
        if not 0 <= index < len(rows):
            raise ValueError(f"ACB {table} reference out of bounds: {index}")
        return rows[index]

    def track_reference(self, index):
        # Keep this adapter deliberately narrow: one immediate note-on per track.
        # Delays, loops, action tracks and layered tracks need a separate renderer.
        track = self.row("TrackTable", index)
        events = self.row("TrackEventTable", track["EventIndex"])["Command"]
        refs = []
        for opcode, args in commands(events):
            if opcode == 2000 and len(args) == 4:
                refs.append(struct.unpack(">HH", args))
            elif opcode != 0:
                raise ValueError(f"Unsupported ACB track command {opcode}")
        if len(refs) != 1:
            raise ValueError("Expected one immediate ACB note-on")
        return refs[0]

    def waveforms(self, kind, index, seen=()):
        if (kind, index) in seen or len(seen) >= 16:
            raise ValueError("Cyclic or excessive ACB cue graph")
        seen = (*seen, (kind, index))
        if kind == 1:
            self.row("WaveformTable", index)
            return [index]
        if kind == 2:
            row = self.row("SynthTable", index)
            items = row["ReferenceItems"]
            if len(items) % 4:
                raise ValueError("Truncated synth reference")
            refs = [struct.unpack_from(">HH", items, i) for i in range(0, len(items), 4)]
        elif kind == 3:
            row = self.row("SequenceTable", index)
            if len(row["TrackIndex"]) != 2 * row["NumTracks"]:
                raise ValueError("Sequence track count mismatch")
            refs = [self.track_reference(int.from_bytes(row["TrackIndex"][i:i+2], "big"))
                    for i in range(0, len(row["TrackIndex"]), 2)]
        else:
            raise ValueError(f"Unsupported ACB reference type {kind}")
        return list(dict.fromkeys(w for ref in refs for w in self.waveforms(*ref, seen)))

    def alternatives(self, cue):
        """Single-wave cues or equal-weight random alternatives; never flatten layers."""
        kind, index = cue["ReferenceType"], cue["ReferenceIndex"]
        if kind == 3:
            seq = self.row("SequenceTable", index)
            if len(seq["TrackIndex"]) != 2 * seq["NumTracks"]:
                raise ValueError("Sequence track count mismatch")
            if seq["NumTracks"] > 1:
                weights = seq.get("TrackValues") or b""
                if (seq["Type"] not in (3, 4) or len(weights) != seq["NumTracks"]*2 or
                        len(set(struct.unpack(">" + "H"*seq["NumTracks"], weights))) != 1):
                    raise ValueError("Layered, sequential or weighted-random cues need an audio adapter")
            refs = [self.track_reference(int.from_bytes(seq["TrackIndex"][i:i+2], "big"))
                    for i in range(0, len(seq["TrackIndex"]), 2)]
        else:
            refs = [(kind, index)]
        result = []
        for ref in refs:
            result.append(self.single_wave(*ref))
        if not result:
            raise ValueError("Empty ACB cue")
        return result

    def single_wave(self, kind, index, seen=()):
        # Do not use the deduplicated discovery list to accept layers: two
        # simultaneous copies of the same recording are still a layered cue.
        if (kind, index) in seen or len(seen) >= 16:
            raise ValueError("Cyclic or excessive ACB cue graph")
        seen = (*seen, (kind, index))
        if kind == 1:
            self.row("WaveformTable", index)
            return index
        if kind == 2:
            items = self.row("SynthTable", index)["ReferenceItems"]
            if len(items) == 4:
                return self.single_wave(*struct.unpack(">HH", items), seen)
        if kind == 3:
            seq = self.row("SequenceTable", index)
            if seq["NumTracks"] == 1 and len(seq["TrackIndex"]) == 2:
                return self.single_wave(*self.track_reference(int.from_bytes(seq["TrackIndex"], "big")), seen)
        raise ValueError("Layered or unsupported ACB sounds cannot become a single-wave cue")


def commands(data):
    """CRI command records: big-endian opcode, one-byte operand size, operands."""
    pos = 0
    while pos < len(data):
        if pos + 3 > len(data):
            raise ValueError("Truncated CRI command header")
        opcode, size = struct.unpack_from(">HB", data, pos)
        end = pos + 3 + size
        if end > len(data):
            raise ValueError("Truncated CRI command operands")
        yield opcode, data[pos + 3:end]
        pos = end


if __name__ == "__main__":
    table = cues(sys.argv[1])
    want = [int(x) for x in sys.argv[2:]]
    if want:
        print(json.dumps({k: table.get(k) for k in want}, indent=1, ensure_ascii=False))
    else:
        print(len(table), "cues")
        for k in sorted(table)[:40]: print(k, table[k])
