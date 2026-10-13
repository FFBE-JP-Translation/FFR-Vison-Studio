"""Adapt the FFBE SE bank's category and bus commands to FFR's audio config.

Only routing metadata changes. Nested table allocations, cue graphs, timing and
the embedded AWB (including multi-wave cues) retain their original layout.
"""
import struct

from .acb_cues import SIZES, utf, commands


def blob_fields(data):
    """Yield (column, row, value-slot, payload-start, size) for UTF blob fields."""
    if data[:4] != b"@UTF":
        raise ValueError("Expected a UTF table")
    _, rows, strings, payload, _, count, stride, nrows = struct.unpack_from(">HHIIIHHI", data, 8)
    if struct.unpack_from(">I", data, 4)[0] + 8 != len(data):
        raise ValueError("UTF table size mismatch")
    columns, pos, row_offset = [], 32, 0
    for _ in range(count):
        flags, name_offset = struct.unpack_from(">BI", data, pos)
        pos += 5
        kind, storage = flags & 15, flags & 240
        begin = 8 + strings + name_offset
        name = data[begin:data.index(b"\0", begin)].decode("utf-8")
        size = SIZES[kind][0] if kind in SIZES else {10: 4, 11: 8}[kind]
        if storage == 0x30:
            slots = [(0, pos)]
            pos += size
        elif storage == 0x50:
            slots = [(r, 8 + rows + r * stride + row_offset) for r in range(nrows)]
            row_offset += size
        elif storage in (0x10, 0x00):
            slots = []
        else:
            raise ValueError(f"Unsupported UTF storage {storage:#x}")
        if kind == 11:
            for row, slot in slots:
                offset, length = struct.unpack_from(">II", data, slot)
                start = 8 + payload + offset
                if start + length > len(data):
                    raise ValueError("UTF blob exceeds its table")
                columns.append((name, row, slot, start, length))
    return columns


def replace_blobs(data, replacement):
    out = bytearray(data)
    for name, row, slot, start, length in blob_fields(data):
        if not length:
            continue
        value = replacement(name, row, data[start:start + length])
        if len(value) > length:
            raise ValueError(f"Routing replacement exceeds {name}'s allocation")
        out[start:start + length] = value + bytes(length - len(value))
        struct.pack_into(">I", out, slot + 4, len(value))
    return bytes(out)


def route_commands(data, strings):
    out = bytearray()
    for opcode, args in commands(data):
        if opcode == 0x6f:  # BusSend: string-table index, level / 10000
            if len(args) != 4:
                raise ValueError("Unexpected CRI BusSend layout")
            index = struct.unpack_from(">H", args)[0]
            if index >= len(strings):
                raise ValueError("CRI BusSend string index is out of range")
            if strings[index] != "MasterOut":
                continue
        elif opcode == 0x41:  # Category: list of uint32 category IDs
            if not args or len(args) % 4:
                raise ValueError("Unexpected CRI Category layout")
            # FFR's native SE_BTL_PP bank identifies the shared SE category as 3.
            args = struct.pack(">I", 3)
        out += struct.pack(">HB", opcode, len(args)) + args
    return bytes(out)


def routing_references():
    """Small UTF table declaring only the two host resources we actually use."""
    strings = bytearray()
    def name(value):
        offset = len(strings)
        strings.extend(value.encode("utf-8") + b"\0")
        return offset
    table_name = name("AcfReference")
    cols = b"".join(struct.pack(">BI", flag, name(key)) for flag, key in
                    [(0x50, "Type"), (0x5a, "Name"), (0x5a, "Name2"), (0x54, "Id")])
    empty, category, bus = name(""), name("SE"), name("MasterOut")
    rows = struct.pack(">BIII", 3, category, empty, 3) + struct.pack(">BIII", 9, bus, empty, 0xffffffff)
    rows_offset = 24 + len(cols)
    strings_offset = rows_offset + len(rows)
    payload_offset = strings_offset + len(strings)
    header = struct.pack(">HHIIIHHI", 0, rows_offset, strings_offset, payload_offset, table_name, 4, 13, 2)
    body = header + cols + rows + strings
    return b"@UTF" + struct.pack(">I", len(body)) + body


def adapt(data):
    header = utf(data)[1][0]
    strings = [r["StringValue"] for r in utf(header["StringValueTable"])[1]]
    refs = utf(header["AcfReferenceTable"])[1]
    if "MasterOut" not in strings or any(r["Type"] not in (3, 9) for r in refs):
        raise ValueError("Unsupported FFBE bank routing; expected only categories and buses")
    command_tables = {"SynthCommandTable", "TrackCommandTable", "SeqCommandTable"}
    def replace(name, row, value):
        if name in command_tables:
            return replace_blobs(value, lambda col, r, blob: route_commands(blob, strings) if col == "Command" else blob)
        if name == "AcfReferenceTable":
            return routing_references()
        return value
    return replace_blobs(data, replace)
