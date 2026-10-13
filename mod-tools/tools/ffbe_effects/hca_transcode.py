"""Offline fallback for mono FFBE HCA recordings with HFR.

The runtime bank adapter stays lossless and dependency-free. Unsupported mono
recordings are decoded once and encoded at high quality without HFR, then
stored beside the ordinary content-addressed samples. Each conversion checks
the decoded sample count, sample rate and alignment before it can be bundled.
"""
from array import array
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import struct
import sys
import wave

from . import hca_host

REVISION = 1
MIN_SNR_DB = 55.0
BITRATE_PER_CHANNEL = 384000
ROOT = Path(__file__).resolve().parents[2]


def codec():
    try:
        return importlib.import_module("cricodecs.hca")
    except ImportError:
        # This optional encoder is only needed by offline preparation. A data
        # pack carries the validated sample, never an encoder dependency.
        paths = [os.environ.get("FFBE_CRICODECS_PATH"),
                 ROOT / "build/lb-sfx-reference/python"]
        for path in paths:
            if path and Path(path).is_dir():
                sys.path.insert(0, str(path))
                try:
                    return importlib.import_module("cricodecs.hca")
                except ImportError:
                    sys.path.remove(str(path))
        raise ValueError("Mono HFR conversion needs the offline cricodecs encoder; set FFBE_CRICODECS_PATH")


def source_layout(raw):
    if (len(raw) < 96 or raw[:8] != b"HCA\0\x02\0\0\x60" or
            raw[8:13] != b"fmt\0\x01" or raw[24:28] != b"comp" or
            raw[30:34] != bytes([1, 15, 1, 1]) or raw[36] != 0 or
            raw[38:46] != b"\0\0ciph\0\0" or raw[46:50] != b"pad\0" or
            not 0 < raw[35] < raw[34] <= 128 or not raw[37]):
        raise ValueError("Offline HCA conversion currently supports unencrypted, non-looping mono v2 HFR")
    size = int.from_bytes(raw[28:30], "big")
    frames = int.from_bytes(raw[16:20], "big")
    if size < 4 or not frames or len(raw) != 96 + frames * size or hca_host.crc(raw[:96]):
        raise ValueError("Invalid source HCA size or checksum")
    for start in range(96, len(raw), size):
        frame = raw[start:start + size]
        if frame[:2] != b"\xff\xff" or hca_host.crc(frame):
            raise ValueError("Invalid source HCA frame or checksum")
    return (int.from_bytes(raw[13:16], "big"),
            frames * 1024 - int.from_bytes(raw[20:22], "big") - int.from_bytes(raw[22:24], "big"))


def pcm(wav):
    with wave.open(io.BytesIO(wav)) as stream:
        if stream.getnchannels() != 1 or stream.getsampwidth() != 2:
            raise ValueError("HCA conversion verification requires mono 16-bit PCM")
        result = array("h", stream.readframes(stream.getnframes()))
        if sys.byteorder != "little":
            result.byteswap()
        return stream.getframerate(), result


def fidelity(before, after):
    if before[0] != after[0] or len(before[1]) != len(after[1]):
        raise ValueError("HCA conversion changed sample rate or sample count")
    signal = sum(v * v for v in before[1])
    error = sum((a - b) ** 2 for a, b in zip(before[1], after[1]))
    snr = 120.0 if not error else 10 * math.log10(max(1, signal) / error)
    return {"snrDb": round(snr, 4), "maxPcmError": max(abs(a - b) for a, b in zip(before[1], after[1]))}


def convert(raw):
    sample_rate, samples = source_layout(raw)
    hca = codec()
    decoded = hca.decode(raw)
    before = pcm(decoded)
    if (before[0], len(before[1])) != (sample_rate, samples):
        raise ValueError("Source decoder disagrees with the HCA sample metadata")
    config = hca.HcaEncodeConfig()
    config.version = 0x200
    config.quality = hca.HcaQuality.HIGHEST
    config.sample_rate = sample_rate
    config.channel_count = 1
    config.bitrate = BITRATE_PER_CHANNEL
    encoded = hca.encode(decoded, config)
    hca_host.validate_layout(encoded)
    checks = fidelity(before, pcm(hca.decode(encoded)))
    correction = 0
    if checks["snrDb"] < MIN_SNR_DB:
        # CriCodecs 1.2 emits an extra 128 leading samples. Correct its trim
        # metadata only if sample-for-sample decode comparison proves alignment and
        # fidelity. The total trim remains constant, preserving sample count.
        delay, padding = struct.unpack_from(">HH", encoded, 20)
        if padding >= 128 and delay <= 65535 - 128:
            adjusted = bytearray(encoded)
            adjusted[20:24] = struct.pack(">HH", delay + 128, padding - 128)
            adjusted[94:96] = struct.pack(">H", hca_host.crc(adjusted[:94]))
            corrected = fidelity(before, pcm(hca.decode(bytes(adjusted))))
            if corrected["snrDb"] >= MIN_SNR_DB:
                encoded, checks, correction = bytes(adjusted), corrected, 128
    if checks["snrDb"] < MIN_SNR_DB:
        raise ValueError(f"HCA conversion failed alignment/fidelity verification ({checks['snrDb']} dB)")
    hca_host.validate_layout(encoded)
    return encoded, {"revision": REVISION, "sourceSha256": hashlib.sha256(raw).hexdigest(),
                     "sha256": hashlib.sha256(encoded).hexdigest(), "codec": "cricodecs",
                     "format": "HCA v2 mono, no HFR", "bitrate": BITRATE_PER_CHANNEL,
                     "sampleRate": sample_rate, "samples": samples, "channels": 1,
                     "encoderDelayCorrection": correction, **checks}


def prepare(raw, samples_dir):
    from .conversion_io import file_lock
    key = hashlib.sha256(raw).hexdigest()
    with file_lock(Path(samples_dir) / '.hca-transcodes' / (key + '.lock')):
        return _prepare_locked(raw, samples_dir)


def _prepare_locked(raw, samples_dir):
    """Return a checked host-compatible sample and optional conversion record."""
    try:
        hca_host.validate_layout(raw)
        return raw, None
    except ValueError:
        source_layout(raw)
    samples_dir = Path(samples_dir)
    source_hash = hashlib.sha256(raw).hexdigest()
    index = samples_dir / ".hca-transcodes" / (source_hash + ".json")
    if index.is_file():
        record = json.loads(index.read_text(encoding="utf-8"))
        digest = record.get("sha256", "")
        if (record.get("revision") == REVISION and record.get("sourceSha256") == source_hash and
                len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)):
            path = samples_dir / (digest + ".hca")
            if path.is_file():
                encoded = path.read_bytes()
                if hashlib.sha256(encoded).hexdigest() == digest:
                    hca_host.validate_layout(encoded)
                    return encoded, record
    encoded, record = convert(raw)
    samples_dir.mkdir(parents=True, exist_ok=True)
    from .conversion_io import atomic_bytes
    atomic_bytes(samples_dir / (record["sha256"] + ".hca"), encoded)
    index.parent.mkdir(parents=True, exist_ok=True)
    atomic_bytes(index, json.dumps(record, sort_keys=True).encode('utf-8'))
    return encoded, record
