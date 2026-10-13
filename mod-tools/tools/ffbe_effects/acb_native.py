"""Build small one-shot banks using the host's ACB schema and FFBE recordings.

Only immediate single-wave cues and equal-weight random alternatives are adapted.
Alternative recordings get separate named cues; the scheduler cycles them. This
avoids importing FFBE's old control-work indices, routing and cue-limit graph.
"""
from copy import deepcopy
import hashlib
import math
import struct

from .acb_cues import CueGraph, SIZES, utf
from .acb_routing import routing_references
from . import hca_host

DEFAULT_GAIN = 0.15
REVISION = 1


def schema(data):
    _, _, strings, _, _, count, _, _ = struct.unpack_from(">HHIIIHHI", data, 8)
    columns, pos = [], 32
    for _ in range(count):
        flags, off = struct.unpack_from(">BI", data, pos); pos += 5
        start = 8 + strings + off
        columns.append((data[start:data.index(b"\0", start)].decode("utf-8"), flags & 15))
        if flags & 240 == 0x30:
            pos += SIZES[flags & 15][0] if flags & 15 in SIZES else {10: 4, 11: 8}[flags & 15]
    return columns


def encode_table(name, columns, rows):
    """Emit typed per-row UTF fields, preserving the host's column types."""
    strings = bytearray(b"\0"); offsets = {"": 0}; blobs = bytearray()
    def string(value):
        value = value or ""
        if value not in offsets:
            offsets[value] = len(strings); strings.extend(value.encode("utf-8") + b"\0")
        return offsets[value]
    name_offset = string(name)
    cols = b"".join(struct.pack(">BI", 0x50 | kind, string(key)) for key, kind in columns)
    records = bytearray()
    for row in rows:
        for key, kind in columns:
            value = row.get(key)
            if kind in SIZES:
                records += struct.pack(SIZES[kind][1], 0 if value is None else value)
            elif kind == 10:
                records += struct.pack(">I", string(value))
            elif kind == 11:
                value = value or b""
                blobs += bytes((-len(blobs)) % 32)
                records += struct.pack(">II", len(blobs), len(value))
                blobs += value
            else:
                raise ValueError(f"Unsupported UTF type {kind}")
    stride = sum(SIZES[k][0] if k in SIZES else {10: 4, 11: 8}[k] for _, k in columns)
    row_offset = 24 + len(cols); string_offset = row_offset + len(records)
    data_offset = string_offset + len(strings)
    padding = (-data_offset - 8) % 32
    header = struct.pack(">HHIIIHHI", 0, row_offset, string_offset, data_offset + padding,
                         name_offset, len(columns), stride, len(rows))
    body = header + cols + records + strings + bytes(padding) + blobs
    return b"@UTF" + struct.pack(">I", len(body)) + body


def awb_files(data):
    if data[:4] != b"AFS2":
        raise ValueError("Expected an embedded AFS2 wave bank")
    width, id_width = data[5:7]
    count = int.from_bytes(data[8:12], "little")
    alignment = int.from_bytes(data[12:14], "little")
    if width not in (2, 4, 8) or id_width not in (2, 4) or not alignment:
        raise ValueError("Unsupported AWB layout")
    offsets = 16 + count * id_width; result = {}
    for i in range(count):
        wave_id = int.from_bytes(data[16+i*id_width:16+(i+1)*id_width], "little")
        start = int.from_bytes(data[offsets+i*width:offsets+(i+1)*width], "little")
        end = int.from_bytes(data[offsets+(i+1)*width:offsets+(i+2)*width], "little")
        start = (start + alignment - 1) // alignment * alignment
        if not 0 <= start < end <= len(data):
            raise ValueError("AWB wave exceeds the bank")
        result[wave_id] = data[start:end]
    return result


def encode_awb(waves, subkey=0, id_width=2):
    alignment = 32; count = len(waves)
    if id_width not in (2, 4):
        raise ValueError("Unsupported AWB ID width")
    header = b"AFS2" + bytes([2, 4, id_width, 0]) + struct.pack("<IHH", count, alignment, subkey)
    header += b"".join(i.to_bytes(id_width, "little") for i in range(count))
    cursor = len(header) + (count + 1) * 4
    offsets, payload = [cursor], bytearray()
    for wave in waves:
        padding = (-cursor) % alignment
        payload += bytes(padding) + wave
        cursor += padding + len(wave); offsets.append(cursor)
    return header + struct.pack("<" + "I"*len(offsets), *offsets) + payload


def recordings(data, ids, cue_names):
    header = utf(data)[1][0]; graph = CueGraph(header)
    cue_rows = {c["CueId"]: c for c in utf(header["CueTable"])[1]}
    result = []
    for cid in sorted(set(ids)):
        cue = cue_rows[cid]
        for variation, wave_index in enumerate(graph.alternatives(cue)):
            wave = graph.row("WaveformTable", wave_index)
            if wave["Streaming"] or wave["EncodeType"] not in (2, 6) or wave["ExtensionData"] != 65535:
                raise ValueError("Only embedded HCA recordings without external loop metadata are supported")
            wave_id = wave.get("MemoryAwbId", wave.get("Id"))  # old ACB banks use Id
            if wave_id is None:
                raise ValueError("Embedded HCA recording has no AWB ID")
            result.append({"sourceCueId": cid, "variation": variation, "sourceWaveIndex": wave_index,
                           "sourceWaveId": wave_id, "name": cue_names[cid] + f"__v{variation + 1}",
                           "durationMs": math.ceil(wave["NumSamples"] * 1000 / wave["SamplingRate"]),
                           "sourceEncodeType": wave["EncodeType"], "channels": wave["NumChannels"],
                           "sampleRate": wave["SamplingRate"], "samples": wave["NumSamples"]})
    return result


def build(source, native, name, selected, gain=DEFAULT_GAIN, waveform_profile=None, raw_waves=None):
    if not 0 < gain <= 1:
        raise ValueError("Bank gain must be in (0, 1]")
    host = utf(native)[1][0]
    if host["Version"] != 0x1420100:
        raise ValueError("Recheck the native ACB adapter against this host format version")
    if raw_waves is None:
        raw_waves = awb_files(utf(source)[1][0]["AwbFile"])
    subkey = int.from_bytes(host["AwbFile"][14:16], "little") if waveform_profile else 0
    id_width = host["AwbFile"][6] if waveform_profile else 2
    arrays = {key: [] for key in ("CueTable", "CueNameTable", "SequenceTable", "TrackTable", "TrackEventTable", "SynthTable", "WaveformTable")}
    templates = {key: utf(host[key])[1][0] for key in arrays}
    sounds = []
    for i, rec in enumerate(selected):
        raw = raw_waves[rec["sourceWaveId"]]
        header_size = int.from_bytes(raw[6:8], "big")
        hca = bytes(b & 127 for b in raw[:header_size]); cipher = hca.find(b"ciph")
        if hca[:4] != b"HCA\0" or cipher < 0 or raw[cipher+4:cipher+6] != b"\0\0" or b"loop" in hca:
            raise ValueError("Expected an unencrypted, non-looping HCA recording")
        sounds.append(hca_host.adapt(raw, waveform_profile["key"], subkey) if waveform_profile else raw)
        def row(key, **changes):
            value = deepcopy(templates[key]); value.update(changes); arrays[key].append(value)
        row("CueTable", CueId=i+1, ReferenceType=3, ReferenceIndex=i, Length=rec["durationMs"], NumRelatedWaveforms=1)
        row("CueNameTable", CueIndex=i, CueName=rec["name"])
        row("SequenceTable", NumTracks=1, TrackIndex=struct.pack(">H", i), CommandIndex=0, Type=0,
            TrackValues=b"", ControlWorkArea1=65535)
        row("TrackTable", EventIndex=i, CommandIndex=65535)
        row("TrackEventTable", Command=struct.pack(">HBHHHB", 2000, 4, 2, i, 0, 0))
        row("SynthTable", ReferenceItems=struct.pack(">HH", 1, i), CommandIndex=65535,
            ControlWorkArea1=65535, ControlWorkArea2=65535)
        # CRI documents HCA-MX as the same HCA bitstream. Select the host's
        # standard HCA voice pool instead of requiring a separate mobile MX pool.
        row("WaveformTable", MemoryAwbId=i, NumSamples=rec["samples"], SamplingRate=rec["sampleRate"],
            NumChannels=rec["channels"], EncodeType=2, LoopFlag=1, ExtensionData=65535)
    # Fresh bank metadata: no FFBE cue limits, sends to missing buses, or work indices.
    header = {k: b"" if isinstance(v, bytes) else v for k, v in host.items()}
    for k in ("AcfMd5Hash", "ProjectKey"):
        if k in host:
            header[k] = host[k]
    header.update(Name=name, AcbGuid=hashlib.md5(name.encode()).digest(), AcbVolume=1.0,
                  NumCueLimitListWorks=0, NumCueLimitNodeWorks=0, NumCueLimit=0,
                  AcfReferenceTable=routing_references(), AwbFile=encode_awb(sounds, subkey, id_width))
    for key, rows in arrays.items():
        header[key] = encode_table(utf(host[key])[0], schema(host[key]), rows)
    # Native float-volume opcode, shared SE category and the main output bus.
    command = struct.pack(">HBI", 0x41, 4, 3) + struct.pack(">HBf", 0x92, 4, gain) + struct.pack(">HBHH", 0x6f, 4, 0, 10000)
    header["SeqCommandTable"] = encode_table(utf(host["SeqCommandTable"])[0], schema(host["SeqCommandTable"]), [{"Command": command}])
    header["StringValueTable"] = encode_table(utf(host["StringValueTable"])[0], schema(host["StringValueTable"]), [{"StringValue": "MasterOut"}])
    result = encode_table("Header", schema(native), [header])
    check = utf(result)[1][0]
    if list(awb_files(check["AwbFile"]).values()) != sounds:
        raise ValueError("The authored bank changed a source recording")
    return result
