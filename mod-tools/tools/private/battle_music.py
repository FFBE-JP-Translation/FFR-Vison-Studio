"""Adapt selected FFBE music losslessly to looping native-format HCA 3 cues."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import numpy as np
from ffbe_effects.acb_native import utf, schema, encode_table, encode_awb, awb_files
from ffbe_effects.hca_host import key_from_config
from ffbe_effects.acb_cues import commands
from battle_hca import adapt

BANK = "BGM_PRIVATE_BATTLES"
# Match the native normal-battle cue after the playback fix passed in-game.
FIRST_BUILD_CUE_GAIN = 0.18
NATIVE_BATTLE_CUE_GAIN = 0.13
DEFAULT_CUE_GAIN = NATIVE_BATTLE_CUE_GAIN


def command(args):
    return subprocess.run(list(map(str, args)), check=True, capture_output=True, text=True, encoding="utf-8").stdout


def pcm(path):
    # vgmstream can produce IEEE float WAV, so use ffmpeg for normalized s16 input.
    with wave.open(str(path), "rb") as f:
        if f.getsampwidth() != 2 or f.getnchannels() != 2:
            raise ValueError("Expected stereo s16 PCM")
        return np.frombuffer(f.readframes(f.getnframes()), dtype="<i2"), f.getframerate()


def build(root, picker, output, native, tracks, gain=DEFAULT_CUE_GAIN):
    output.mkdir(parents=True, exist_ok=True)
    vgm = root / "tools/vgmstream/vgmstream-cli.exe"
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not vgm.exists():
        raise ValueError("ffmpeg and vgmstream-cli are required")
    host = utf(native)[1][0]
    if host["Version"] != 0x1420100:
        raise ValueError("Unsupported host ACB schema")
    cue_index = next(r["CueIndex"] for r in utf(host["CueNameTable"])[1] if r["CueName"] == "BGM_PP_BATTLE1")
    cue = utf(host["CueTable"])[1][cue_index]
    sequence = utf(host["SequenceTable"])[1][cue["ReferenceIndex"]]
    native_routing = utf(host["SeqCommandTable"])[1][sequence["CommandIndex"]]["Command"]
    routing = bytearray()
    volume_count = 0
    for op, args in commands(native_routing):
        if op == 0x92:
            if abs(struct.unpack(">f", args)[0] - NATIVE_BATTLE_CUE_GAIN) > 1e-6:
                raise ValueError("Native battle music gain changed; recheck the reference")
            args = struct.pack(">f", gain)
            volume_count += 1
        routing.extend(struct.pack(">HB", op, len(args)) + args)
    if volume_count != 1:
        raise ValueError("Native battle cue must have exactly one volume command")
    memory_wave = next(r for r in utf(host["WaveformTable"])[1] if not r["Streaming"] and r["LoopFlag"] == 2)
    decrypt_key = key_from_config(root / "extracted/pak/FFRS/Config/DefaultEngine.ini")
    subkey = int.from_bytes(host["AwbFile"][14:16], "little")
    id_width = host["AwbFile"][6]
    manifest = {r["id"]: r for r in json.loads((picker / "manifest.json").read_text(encoding="utf-8"))["music"]}
    sounds, records = [], []
    for i, track in enumerate(tracks):
        source = manifest[track]
        prefix = output / str(i + 1)
        decoded = prefix.with_suffix(".decoded.wav")
        original = prefix.with_suffix(".wav")
        hca = prefix.with_suffix(".hca")
        source_bytes = Path(source["source"]).read_bytes()
        source_waves = awb_files(utf(source_bytes)[1][0]["AwbFile"])
        if len(source_waves) != 1 or source["subsong"] != 1:
            raise ValueError("Battle music selection requires a single-recording source bank")
        data = adapt(next(iter(source_waves.values())), decrypt_key, subkey)
        hca.write_bytes(data)
        command([vgm, "-i", "-s", source["subsong"], "-o", decoded, source["source"]])
        command([ffmpeg, "-v", "error", "-y", "-i", decoded, "-c:a", "pcm_s16le", original])
        # vgmstream independently decrypts and decodes the actual host-format
        # recording. Key sidecars are temporary verification inputs, not assets.
        roundtrip = prefix.with_suffix(".roundtrip.wav")
        key_path = hca.with_suffix(".hcakey")
        key_path.write_bytes(decrypt_key.to_bytes(8, "big") + subkey.to_bytes(2, "big"))
        try:
            meta = json.loads(command([vgm, "-I", hca]))
            command([vgm, "-i", "-o", decoded, hca])
        finally:
            key_path.unlink()
        command([ffmpeg, "-v", "error", "-y", "-i", decoded, "-c:a", "pcm_s16le", roundtrip])
        a, rate = pcm(original); b, actual_rate = pcm(roundtrip)
        samples = meta["numberOfSamples"]
        start, end = source["loop"]["start"], source["loop"]["end"]
        if (rate != actual_rate or len(a) != samples * 2 or not np.array_equal(a, b) or
                meta["loopingInfo"] != {"start": start, "end": end} or meta["channels"] != 2):
            raise ValueError(f"Music host-format adaptation changed PCM, channels or loops: {track}")
        sounds.append(data)
        records.append({"id": i + 1, "name": f"{BANK}_{i+1}", "durationMs": 4294967295,
                        "source": source["source"], "track": source["name"], "sourceSha256": hashlib.sha256(source_bytes).hexdigest(),
                        "sampleRate": rate, "samples": samples, "loopStart": start, "loopEnd": end,
                        "pcmExact": True, "pcmSha256": hashlib.sha256(a.tobytes()).hexdigest(),
                        "hcaVersion": 0x300, "cipherType": 56, "decoder": meta, "cueGain": gain,
                        "gainDbRelativeToFirstBuild": round(float(20 * np.log10(gain / FIRST_BUILD_CUE_GAIN)), 2)})
        print(f"Music {i+1}: {source['name']} (HCA 3, exact PCM, cue gain {gain:.4f})", flush=True)
    keys = ("CueTable", "CueNameTable", "SequenceTable", "TrackTable", "TrackEventTable", "SynthTable",
            "SynthCommandTable", "WaveformTable", "WaveformExtensionDataTable")
    arrays = {k: [] for k in keys}
    for i, rec in enumerate(records):
        def row(key, **changes):
            value = deepcopy(memory_wave if key == "WaveformTable" else utf(host[key])[1][0])
            value.update(changes); arrays[key].append(value)
        row("CueTable", CueId=i+1, ReferenceIndex=i, Length=4294967295)
        row("CueNameTable", CueIndex=i, CueName=rec["name"])
        row("SequenceTable", TrackIndex=struct.pack(">H", i), CommandIndex=0)
        row("TrackTable", EventIndex=i)
        row("TrackEventTable", Command=struct.pack(">HBHHHB", 2000, 4, 2, i, 0, 0))
        row("SynthTable", ReferenceItems=struct.pack(">HH", 1, i), CommandIndex=i)
        row("SynthCommandTable")
        row("WaveformTable", MemoryAwbId=i, StreamAwbId=65535, Streaming=0, EncodeType=2,
            StreamAwbPortNo=65535, NumChannels=2, NumSamples=rec["samples"],
            SamplingRate=rec["sampleRate"], ExtensionData=i, LoopFlag=2)
        row("WaveformExtensionDataTable", LoopStart=rec["loopStart"], LoopEnd=rec["loopEnd"])
    header = {k: b"" if isinstance(v, bytes) else v for k, v in host.items()}
    for k in ("AcfMd5Hash", "ProjectKey"):
        header[k] = host[k]
    refs = [r for r in utf(host["AcfReferenceTable"])[1] if r["Name"] in ("BGM", "BGM_BTL", "MasterOut")]
    header.update(Name=BANK, AcbGuid=hashlib.md5(BANK.encode()).digest(), AcbVolume=1.0,
                  NumCueLimitListWorks=0, NumCueLimitNodeWorks=0, NumCueLimit=0,
                  AcfReferenceTable=encode_table("AcfReference", schema(host["AcfReferenceTable"]), refs),
                  AwbFile=encode_awb(sounds, subkey, id_width))
    for key, rows in arrays.items():
        header[key] = encode_table(utf(host[key])[0], schema(host[key]), rows)
    for key, rows in [("SeqCommandTable", [{"Command": bytes(routing)}]), ("StringValueTable", [{"StringValue": "MasterOut"}])]:
        header[key] = encode_table(utf(host[key])[0], schema(host[key]), rows)
    result = encode_table("Header", schema(native), [header])
    bank = output / (BANK + ".acb"); bank.write_bytes(result)
    if list(awb_files(utf(result)[1][0]["AwbFile"]).values()) != sounds:
        raise ValueError("ACB changed an HCA recording")
    # vgmstream exposes embedded HCA as a virtual .hca with the bank's stem.
    key_path = bank.with_suffix(".hcakey")
    key_path.write_bytes(decrypt_key.to_bytes(8, "big"))
    try:
        for i, rec in enumerate(records):
            metadata = json.loads(command([vgm, "-I", "-s", i + 1, bank]))
            if metadata["loopingInfo"] != {"start": rec["loopStart"], "end": rec["loopEnd"]} or metadata["channels"] != 2:
                raise ValueError("Packaged music loop or channel count changed")
            decoded = output / f"{i+1}.bank-float.wav"
            roundtrip = output / f"{i+1}.bank.wav"
            command([vgm, "-i", "-s", i + 1, "-o", decoded, bank])
            command([ffmpeg, "-v", "error", "-y", "-i", decoded, "-c:a", "pcm_s16le", roundtrip])
            a, rate = pcm(roundtrip)
            if rate != rec["sampleRate"] or hashlib.sha256(a.tobytes()).hexdigest() != rec["pcmSha256"]:
                raise ValueError("Packaged music decryption or PCM changed")
            rec.update(bankDecoder=metadata, bankPcmExact=True)
    finally:
        key_path.unlink()
    (output / "verification.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    return bank, records


def append_to_native(native, extra, output):
    """Append cues without altering native wave IDs, streamed AWB or cue graphs.

    PlayBGM takes only a cue name and uses the main BGM sheet. An independently
    registered cue sheet works for PlaySound2D, but is insufficient for PlayBGM.
    """
    host = utf(native)[1][0]; addon = utf(extra)[1][0]
    if addon["AwbFile"][6] != host["AwbFile"][6] or addon["AwbFile"][12:16] != host["AwbFile"][12:16]:
        raise ValueError("Music AWB format or decryption subkey differs from the host")
    keys = ("CueTable", "CueNameTable", "SequenceTable", "TrackTable", "TrackEventTable", "SynthTable",
            "SynthCommandTable", "WaveformTable", "WaveformExtensionDataTable", "SeqCommandTable")
    arrays = {k: deepcopy(utf(host[k])[1]) for k in keys}
    offsets = {k: len(v) for k, v in arrays.items()}
    old_waves = awb_files(host["AwbFile"])
    if list(old_waves) != list(range(len(old_waves))):
        raise ValueError("Native embedded wave IDs are not contiguous")
    waves = list(old_waves.values()) + list(awb_files(addon["AwbFile"]).values())
    native_ids = {r["CueId"] for r in arrays["CueTable"]}
    native_names = {r["CueName"] for r in arrays["CueNameTable"]}
    for key in keys:
        for row in deepcopy(utf(addon[key])[1]):
            if key == "CueTable":
                if row["CueId"] in native_ids:
                    raise ValueError("Native cue ID collision")
                row["ReferenceIndex"] += offsets["SequenceTable"]
            elif key == "CueNameTable":
                if row["CueName"] in native_names:
                    raise ValueError("Native cue name collision")
                row["CueIndex"] += offsets["CueTable"]
            elif key == "SequenceTable":
                row["TrackIndex"] = struct.pack(">H", struct.unpack(">H", row["TrackIndex"])[0] + offsets["TrackTable"])
                row["CommandIndex"] += offsets["SeqCommandTable"]
            elif key == "TrackTable":
                row["EventIndex"] += offsets["TrackEventTable"]
            elif key == "TrackEventTable":
                opcode, size, kind, index, end, zero = struct.unpack(">HBHHHB", row["Command"])
                row["Command"] = struct.pack(">HBHHHB", opcode, size, kind, index + offsets["SynthTable"], end, zero)
            elif key == "SynthTable":
                kind, index = struct.unpack(">HH", row["ReferenceItems"])
                row["ReferenceItems"] = struct.pack(">HH", kind, index + offsets["WaveformTable"])
                row["CommandIndex"] += offsets["SynthCommandTable"]
            elif key == "WaveformTable":
                row["MemoryAwbId"] += len(old_waves)
                row["ExtensionData"] += offsets["WaveformExtensionDataTable"]
            arrays[key].append(row)
    if utf(host["StringValueTable"])[1][0]["StringValue"] != "MasterOut":
        raise ValueError("Native BGM bus index changed")
    result = deepcopy(host)
    for key, rows in arrays.items():
        result[key] = encode_table(utf(host[key])[0], schema(host[key]), rows)
    result["AwbFile"] = encode_awb(waves, int.from_bytes(host["AwbFile"][14:16], "little"), host["AwbFile"][6])
    encoded = encode_table("Header", schema(native), [result]); output.write_bytes(encoded)
    check = utf(encoded)[1][0]
    for key in keys:
        if utf(check[key])[1][:offsets[key]] != utf(host[key])[1]:
            raise ValueError("Native music rows changed: " + key)
    for key in host.keys() - set(keys) - {"AwbFile"}:
        if check[key] != host[key]:
            raise ValueError("Native music metadata changed: " + key)
    if list(awb_files(check["AwbFile"]).values()) != waves:
        raise ValueError("Native music recordings changed")
    return output
