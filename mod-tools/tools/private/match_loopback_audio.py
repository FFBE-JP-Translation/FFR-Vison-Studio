"""Compare decoded source cues with a bounded WASAPI recording.

Waveform correlation is evidence of media playback, not native visual/hit parity.
Supports PCM/IEEE float WAVE, including Windows extensible playback mix formats.
"""
import argparse
import json
from pathlib import Path
import struct

import numpy as np


def read_wave(path):
    data = Path(path).read_bytes()
    if data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError(f'{path}: expected RIFF/WAVE')
    chunks = {}
    offset = 12
    while offset + 8 <= len(data):
        name, size = struct.unpack_from('<4sI', data, offset)
        if offset + 8 + size > len(data):
            raise ValueError(f'{path}: truncated {name!r} chunk')
        chunks[name] = data[offset+8:offset+8+size]
        offset += 8 + size + (size & 1)
    fmt, raw = chunks[b'fmt '], chunks[b'data']
    tag, channels, rate, _, align, bits = struct.unpack_from('<HHIIHH', fmt)
    if tag == 0xfffe:
        if len(fmt) < 40:
            raise ValueError(f'{path}: short extensible WAVE format')
        tag = struct.unpack_from('<H', fmt, 24)[0]
    if align != channels * bits // 8 or len(raw) % align:
        raise ValueError(f'{path}: inconsistent WAVE frame size')
    if tag == 3 and bits in (32, 64):
        values = np.frombuffer(raw, dtype='<f'+str(bits//8)).astype(np.float64)
    elif tag == 1 and bits in (16, 32):
        values = np.frombuffer(raw, dtype='<i'+str(bits//8)).astype(np.float64) / (1 << (bits-1))
    elif tag == 1 and bits == 24:
        packed = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        values = packed[:, 0] | (packed[:, 1] << 8) | (packed[:, 2] << 16)
        values = ((values ^ 0x800000) - 0x800000).astype(np.float64) / 8388608
    else:
        raise ValueError(f'{path}: unsupported WAVE encoding {tag}/{bits}')
    values = values.reshape(-1, channels).mean(axis=1)
    if not np.isfinite(values).all():
        raise ValueError(f'{path}: non-finite samples')
    return rate, values


def match(captured, capture_rate, source, source_rate):
    if np.dot(captured, captured) < 1e-12:
        raise ValueError('Capture contains no measurable signal; playback verification is unavailable')
    count = round(len(source) * capture_rate / source_rate)
    if count < 1 or count > len(captured):
        raise ValueError('Source must be nonempty and shorter than the capture')
    # The Windows playback resampler differs slightly from linear interpolation;
    # report the measured similarity rather than assuming sample identity.
    reference = np.interp(np.arange(count) * source_rate / capture_rate,
                          np.arange(len(source)), source)
    energy = np.dot(reference, reference)
    if energy < 1e-12:
        raise ValueError('Source cue contains no measurable signal')
    nfft = 1 << (len(captured) + count - 2).bit_length()
    cross = np.fft.irfft(np.fft.rfft(captured, nfft) *
                         np.conj(np.fft.rfft(reference, nfft)), nfft)[:len(captured)-count+1]
    prefix = np.concatenate(([0.], np.cumsum(captured * captured)))
    windows = prefix[count:] - prefix[:-count]
    scores = np.zeros(len(cross))
    audible = windows > 1e-12
    scores[audible] = cross[audible] / np.sqrt(energy * windows[audible])
    index = int(np.argmax(scores))
    return {'startSeconds': index / capture_rate, 'startSample': index,
            'correlation': float(scores[index]), 'linearGain': float(cross[index] / energy),
            'sourceSeconds': len(source) / source_rate,
            'sourceRms': float(np.sqrt(energy / count)),
            'captureWindowRms': float(np.sqrt(windows[index] / count))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    parser.add_argument('sources', type=Path, nargs='+')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    rate, capture = read_wave(args.capture)
    result = {'capture': str(args.capture.resolve()), 'sampleRate': rate,
              'seconds': len(capture) / rate, 'cues': []}
    for path in args.sources:
        source_rate, source = read_wave(path)
        result['cues'].append({'source': str(path.resolve()),
                               **match(capture, rate, source, source_rate)})
    encoded = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(encoded + '\n', encoding='utf-8')
    print(encoded)


if __name__ == '__main__':
    main()
