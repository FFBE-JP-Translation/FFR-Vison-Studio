"""Lossless adaptation of the four FFBE battle tracks to FFR's HCA 3 format.

These stereo recordings encode two independent channels: no joint stereo or
high-frequency reconstruction. With minimum resolution 1 their frame layout is
unchanged in v3. Versioned decoding rules:
https://github.com/vgmstream/vgmstream/blob/master/src/coding/libs/clhca.c
Other stereo layouts must be converted, not relabelled.
"""
import struct

from ffbe_effects.hca_host import crc, encryption_table


def adapt(raw, key, subkey):
    if (len(raw) < 68 or raw[:6] != b"HCA\0\x02\0" or
            raw[8:13] != b"fmt\0\x02" or raw[24:28] != b"comp" or
            raw[30:40] != bytes([1, 15, 1, 0, 128, 128, 0, 0, 0, 0]) or
            raw[40:44] != b"loop" or raw[56:66] != b"ciph\0\0pad\0"):
        raise ValueError("Battle HCA requires unencrypted v2 discrete stereo with loops and no HFR")
    header_size = int.from_bytes(raw[6:8], "big")
    frame_count = int.from_bytes(raw[16:20], "big")
    frame_size = int.from_bytes(raw[28:30], "big")
    if (header_size < 68 or frame_size < 4 or not frame_count or
            len(raw) != header_size + frame_count * frame_size or
            any(raw[66:header_size-2]) or crc(raw[:header_size])):
        raise ValueError("Invalid battle HCA size, padding or header checksum")
    loop_start, loop_end = struct.unpack_from(">II", raw, 44)
    if not 0 <= loop_start <= loop_end < frame_count:
        raise ValueError("Invalid battle HCA loop frames")
    header = bytearray(raw[:header_size])
    header[4:6] = b"\x03\0"
    header[60:62] = b"\0\x38"
    for offset in (0, 8, 24, 40, 56, 62):
        header[offset:offset+4] = bytes(v | 128 if v else 0 for v in header[offset:offset+4])
    header[-2:] = struct.pack(">H", crc(header[:-2]))
    table = encryption_table(key, subkey)
    result = bytearray(header)
    for offset in range(header_size, len(raw), frame_size):
        frame = raw[offset:offset+frame_size]
        if frame[:2] != b"\xff\xff" or crc(frame):
            raise ValueError("Invalid battle HCA frame or checksum")
        encrypted = frame[:-2].translate(table)
        result.extend(encrypted + struct.pack(">H", crc(encrypted)))
    return bytes(result)
