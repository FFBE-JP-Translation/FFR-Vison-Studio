"""Lossless host-format adaptation for FFBE's mono HCA 2 recordings.

The v2/v3 decoding rules and type-56 permutation are documented by vgmstream:
https://github.com/vgmstream/vgmstream/blob/master/src/coding/libs/clhca.c
https://github.com/vgmstream/vgmstream/blob/master/src/coding/hca_decoder.c
Stereo and HFR bitstreams need conversion, not a version-header change.
"""
from functools import lru_cache
import re
import struct


def key_from_config(path):
    text = path.read_text(encoding="utf-8-sig")
    section = re.search(r"(?ms)^\[/Script/CriWareRuntime\.CriWarePluginSettings\]\s*$(.*?)(?=^\[|\Z)", text)
    match = re.search(r"(?m)^DecryptKey=(\d+)\s*$", section[1]) if section else None
    if not match or not 0 < int(match[1]) < 2**64:
        raise ValueError("Extract FFR's CriWare DecryptKey into the supplied DefaultEngine.ini")
    return int(match[1])


@lru_cache(maxsize=1)
def crc_table():
    values = []
    for byte in range(256):
        value = byte << 8
        for _ in range(8):
            value = ((value << 1) ^ (0x8005 if value & 0x8000 else 0)) & 0xffff
        values.append(value)
    return values


def crc(data):
    value = 0
    table = crc_table()
    for byte in data:
        value = ((value << 8) ^ table[(value >> 8) ^ byte]) & 0xffff
    return value


@lru_cache(maxsize=8)
def encryption_table(key, subkey):
    if not 0 < key < 2**64 or not 0 <= subkey < 2**16:
        raise ValueError("Invalid HCA key or AWB subkey")
    effective = key * ((subkey << 16) | ((~subkey & 0xffff) + 2)) if subkey else key
    digits = ((effective - 1) & (2**64 - 1)).to_bytes(8, "little")
    def nibble_permutation(seed):
        value = seed >> 4
        result = []
        for _ in range(16):
            value = (value * (5 + 8 * (seed & 1)) + ((seed & 14) | 1)) % 16
            result.append(value)
        return result
    pairs = [(1,), (1,6), (2,3), (2,), (2,1), (3,4), (3,), (3,2),
             (4,5), (4,), (4,3), (5,6), (5,), (5,4), (6,1), (6,)]
    seeds = [digits[p[0]] ^ (digits[p[1]] if len(p) == 2 else 0) for p in pairs]
    high = nibble_permutation(digits[0])
    grid = [16 * high[row] + low for row, seed in enumerate(seeds) for low in nibble_permutation(seed)]
    shuffled = [grid[(17 * i) % 256] for i in range(1, 257)]
    decrypt = [0, *(v for v in shuffled if v not in (0, 255)), 255]
    encrypt = bytearray(256)
    for encrypted, plain in enumerate(decrypt):
        encrypt[plain] = encrypted
    return bytes(encrypt)


def validate_layout(raw):
    # This deliberately narrow layout covers the selected LB recordings. Keeping
    # min resolution 1 disables v3 noise filling; mono without HFR has identical
    # spectral decoding in v2 and v3, so no lossy re-encode is needed.
    if (len(raw) < 96 or raw[:6] != b"HCA\0\x02\0" or raw[6:8] != b"\0\x60" or
            raw[8:12] != b"fmt\0" or raw[12] != 1 or raw[24:28] != b"comp" or
            raw[30:34] != bytes([1, 15, 1, 1]) or raw[34] != raw[35] or
            raw[36:40] != bytes(4) or raw[40:46] != b"ciph\0\0" or raw[46:50] != b"pad\0"):
        raise ValueError("Host HCA adaptation requires unencrypted mono v2 without stereo, HFR or loops")
    frames = int.from_bytes(raw[16:20], "big")
    frame_size = int.from_bytes(raw[28:30], "big")
    if frame_size < 4 or len(raw) != 96 + frames * frame_size or crc(raw[:96]):
        raise ValueError("Invalid HCA size or header checksum")
    return frame_size


def adapt(raw, key, subkey):
    frame_size = validate_layout(raw)
    header = bytearray(raw[:96]); header[4:6] = b"\x03\0"; header[44:46] = b"\0\x38"
    for start in (0, 8, 24, 40, 46):
        header[start:start+4] = bytes(v | 0x80 if v else v for v in header[start:start+4])
    header[-2:] = struct.pack(">H", crc(header[:-2]))
    table = encryption_table(key, subkey)
    result = bytearray(header)
    for start in range(96, len(raw), frame_size):
        frame = raw[start:start+frame_size]
        if frame[:2] != b"\xff\xff" or crc(frame):
            raise ValueError("Invalid HCA frame or checksum")
        encrypted = frame[:-2].translate(table)
        result.extend(encrypted + struct.pack(">H", crc(encrypted)))
    return bytes(result)
