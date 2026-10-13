"""Small unit manifests with content-addressed, independently bounded effects.

The runtime uses only stdlib. Source preparation and publishing live elsewhere.
One selected move is verified at a time; no whole-catalog unpacking allowance.
"""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
import time
import zlib
import ffbe_effect_bundle as legacy

VERSION = 'ffr-effects-ref-1'
MAX_FILE = 128 * 1024 * 1024
MAX_INDEX = 16 * 1024 * 1024
MAX_FILES = 65536


def atomic(path, raw):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
        for attempt in range(20):
            try:
                os.replace(temporary, path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 19: raise
                time.sleep(min(.05 * 2**attempt, 1.0))
    finally:
        Path(temporary).unlink(missing_ok=True)


def blob_name(digest):
    legacy._digest(digest)
    return f'blobs/{digest[:2]}/{digest}'


def materialize(destination, cache, info, raw):
    """Share already compressed pages physically when the filesystem permits."""
    destination = Path(destination)
    if info['encoding'] != 'raw':
        atomic(destination, raw)
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.effect-', suffix='.tmp', dir=destination.parent)
    os.close(fd)
    Path(temporary).unlink()
    try:
        try:
            os.link(cache, temporary)
            os.replace(temporary, destination)
        except OSError:
            atomic(destination, raw)
    finally:
        Path(temporary).unlink(missing_ok=True)


def descriptor(info):
    if not isinstance(info, dict):
        raise ValueError('Invalid shared effects descriptor')
    for key in ('sha256', 'decodedSha256'):
        legacy._digest(info.get(key))
    for key in ('size', 'decodedSize'):
        if type(info.get(key)) is not int or not 0 <= info[key] <= MAX_FILE:
            raise ValueError('Shared effects file exceeds its size budget')
    if info.get('encoding') not in ('raw', 'zlib'):
        raise ValueError('Unsupported shared effects encoding')
    if info['encoding'] == 'raw' and (info['size'] != info['decodedSize'] or info['sha256'] != info['decodedSha256']):
        raise ValueError('Invalid raw shared effects descriptor')
    return info


def decode(info, payload):
    descriptor(info)
    if len(payload) != info['size'] or legacy._sha(payload) != info['sha256']:
        raise ValueError('Shared effect download checksum mismatch')
    raw = payload
    if info['encoding'] == 'zlib':
        decoder = zlib.decompressobj()
        try:
            raw = decoder.decompress(payload, info['decodedSize'] + 1)
        except zlib.error as ex:
            raise ValueError('Invalid shared effect compression') from ex
        if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
            raise ValueError('Shared effect is truncated, oversized or has trailing data')
    if len(raw) != info['decodedSize'] or legacy._sha(raw) != info['decodedSha256']:
        raise ValueError('Shared effect decoded checksum mismatch')
    return raw


def validate(index, presentation, form=None):
    """Validate the thin index without trusting or downloading remote files."""
    fid = legacy.form_id(index.get('form'))
    if index.get('schema') != VERSION or form is not None and fid != str(form):
        raise ValueError('Shared effects index belongs to another format or form')
    if presentation.get('schema') not in legacy.PRESENTATIONS or str(presentation.get('form')) != fid:
        raise ValueError('Shared effects presentation identity mismatch')
    if legacy._sha(legacy.encoded(presentation)) != index.get('presentationSha256'):
        raise ValueError('Shared effects presentation checksum mismatch')
    files, moves = index.get('files'), index.get('moves')
    if not isinstance(files, dict) or len(files) > MAX_FILES or not isinstance(moves, dict):
        raise ValueError('Invalid shared effects content index')
    if set(moves) != set(presentation.get('moves', {})):
        raise ValueError('Shared effects move index mismatch')
    used = set()
    for name, info in files.items():
        legacy.safe_name(name)
        if not name.startswith(('presentation/assets/shared/', 'audio/effects/', 'audio/samples/')):
            raise ValueError('Unexpected shared effects destination')
        descriptor(info)
    for key, names in moves.items():
        move = presentation['moves'][key]
        if move.get('sourceKey') != key:
            raise ValueError('Shared effects source identity mismatch')
        legacy._digest(move.get('sourceSha256'))
        if not isinstance(names, list) or len(set(names)) != len(names) or not set(names) <= files.keys():
            raise ValueError('Shared effects move has missing dependencies')
        used.update(names)
    if used != set(files):
        raise ValueError('Shared effects index contains unreferenced files')
    return index


def read_installed(data, form):
    form = legacy.form_id(form)
    base = Path(data)
    paths = [base / f'presentation/effects/{form}.json', base / f'presentation/{form}.json']
    if any(path.stat().st_size > MAX_INDEX for path in paths):
        raise ValueError('Shared effects metadata exceeds its budget')
    index, presentation = [legacy._json(path.read_bytes()) for path in paths]
    validate(index, presentation, form)
    return index, presentation


def verify_move(index, presentation, key, read):
    if key not in index['moves']:
        raise ValueError('This move has no converted animation in this unit pack')
    names = set(index['moves'][key])
    def checked(name):
        if name not in names:
            raise ValueError('Move requested an unlisted shared dependency: ' + name)
        raw = read(name)
        info = index['files'][name]
        if len(raw) != info['decodedSize'] or legacy._sha(raw) != info['decodedSha256']:
            raise ValueError('Installed shared effect checksum mismatch: ' + name)
        return raw
    selected = {**presentation, 'moves': {key: presentation['moves'][key]}}
    if legacy._dependencies(selected, checked) != names:
        raise ValueError('Shared move dependency list differs from playback')


def verify_thin(files, form):
    index = legacy._json(files[f'presentation/effects/{form}.json'])
    presentation = legacy._json(files[f'presentation/{form}.json'])
    validate(index, presentation, form)
    # Effects referenced by this format are external, never hidden extra ZIPs.
    if any(name.startswith('presentation/assets/') for name in files):
        raise ValueError('A thin unit unexpectedly embeds effect atlases')
    return index
