"""Portable prepared effects: validation and packaging, without source conversion.

ZIP entries are relative to data/ffbe, so the same payload can accompany a unit.
This module deliberately imports only Python's standard library. Studio needs
the prepared SpriteStudio projects and recordings, never FFBE particle decoders.
"""
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import zipfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
VERSION = 'ffr-effects-1'
# A full prepared cinematic contains multiple uncompressed BGRA atlas pages.
# The v1 reader has a separate bounded budget from older sprite-only unit packs.
MAX_BYTES = 1024 * 1024 * 1024
MAX_FILES = 16384
MAX_TEXTURE_BYTES = 64 * 1024 * 1024
MAX_ENCODED_TEXTURE_BYTES = MAX_TEXTURE_BYTES + 64 * 1024
COMPRESSION_CACHE = None  # Opt-in offline cache; Studio remains dependency-free.
PRESENTATIONS = ('ffr-presentation-1', 'ffr-presentation-2')


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def form_id(value):
    value = str(value)
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError('Invalid effects form ID')
    return value


def safe_name(name):
    """Require a single canonical spelling, including on Windows."""
    if not isinstance(name, str) or not name or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('The archive contains an unsafe filename')
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or any(p in ('.', '..') or p.endswith((' ', '.')) for p in path.parts):
        raise ValueError('The archive contains an unsafe filename')
    for part in path.parts:
        if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part):
            raise ValueError('The archive contains an unsafe filename')
    return name


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value):
        raise ValueError('Invalid effects checksum')
    return value


def _json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field in effects metadata')
            result[key] = value
        return result
    try:
        return json.loads(raw, object_pairs_hook=unique,
                          parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite effects metadata')))
    except (UnicodeDecodeError, json.JSONDecodeError) as ex:
        raise ValueError('Invalid effects JSON') from ex


def _path(value, prefix):
    safe_name(value)
    if not value.startswith('data/ffbe/' + prefix):
        raise ValueError('Effects reference is outside its prepared data directory')
    return value[len('data/ffbe/'):]


def _disk(data, name):
    path = data / safe_name(name)
    if not path.resolve().is_relative_to(data.resolve()):
        raise ValueError('Effects reference escapes its data directory')
    return path


def decode_texture(page, payload):
    """Validate one prepared texture page; never decode FFBE source artwork."""
    dimensions = page.get('pixelSize', [])
    if not isinstance(dimensions, list) or len(dimensions) != 2 or any(
            isinstance(n, bool) or not isinstance(n, (int, float)) or n <= 0 or n > MAX_TEXTURE_BYTES
            or not math.isfinite(n) or n != int(n) for n in dimensions):
        raise ValueError('Prepared effect has invalid texture dimensions')
    expected = int(dimensions[0]) * int(dimensions[1]) * 4
    if expected > MAX_TEXTURE_BYTES:
        raise ValueError('Prepared texture exceeds the decoded page budget')
    encoding = page.get('textureEncoding', 'raw')
    if encoding == 'raw':
        if len(payload) != expected:
            raise ValueError('Effects dependency size mismatch: raw texture')
        return payload
    if encoding != 'zlib':
        raise ValueError('Unsupported prepared texture encoding')
    if len(payload) > MAX_ENCODED_TEXTURE_BYTES:
        raise ValueError('Compressed texture exceeds the encoded page budget')
    if type(page.get('textureBytes')) is not int or page['textureBytes'] != expected:
        raise ValueError('Compressed texture decoded size differs from its dimensions')
    digest = _digest(page.get('textureSha256'))
    try:
        decoder = zlib.decompressobj()
        raw = decoder.decompress(payload, expected + 1)
    except zlib.error as error:
        raise ValueError('Invalid compressed prepared texture') from error
    if len(raw) != expected or not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
        raise ValueError('Compressed texture is truncated, oversized or has trailing data')
    if _sha(raw) != digest:
        raise ValueError('Compressed texture decoded checksum mismatch')
    return raw


def _dependencies(presentation, read):
    """Resolve the entire playback closure and verify authored dependency hashes."""
    if presentation.get('schema') not in PRESENTATIONS or not isinstance(presentation.get('moves'), dict):
        raise ValueError('Unsupported prepared presentation manifest')
    form = form_id(presentation.get('form'))
    dependencies = set()
    def require(name, digest=None, size=None):
        safe_name(name)
        raw = read(name)
        if digest is not None and _sha(raw) != _digest(digest):
            raise ValueError('Effects dependency checksum mismatch: ' + name)
        if size is not None and (type(size) is not int or size < 0 or size != len(raw)):
            raise ValueError('Effects dependency size mismatch: ' + name)
        dependencies.add(name)
        return raw
    for key, move in presentation['moves'].items():
        if not isinstance(move, dict) or move.get('sourceKey') != key:
            raise ValueError('Effects move source identity mismatch')
        _digest(move.get('sourceSha256'))
        profile = move.get('reconstructionProfile')
        if profile and (str(profile.get('form')) != form or profile.get('sourceKey') != key):
            raise ValueError('Effects staging profile belongs to another form or move')
        for visual in move.get('visuals', []):
            directory = _path(visual['spec'], 'presentation/assets/')
            checksums = visual.get('checksums', {})
            if 'spec.json' not in checksums:
                raise ValueError('Prepared effect has no project checksum')
            for name, digest in checksums.items():
                safe_name(name)
                if '/' in name or not (name == 'spec.json' or name.endswith(('.bgra', '.bgra.z'))):
                    raise ValueError('Unexpected file in prepared effects project')
                require(directory + '/' + name, digest)
            spec = _json(read(directory + '/spec.json'))
            maps = spec.get('cellmaps', [spec])
            if not isinstance(maps, list) or not maps:
                raise ValueError('Prepared effect has no texture maps')
            for index, page in enumerate(maps):
                filename = page.get('textureFile', 'tex' + (f'_{index}' if index else '') + '.bgra')
                if filename not in checksums:
                    raise ValueError('Prepared effect texture is missing its checksum')
                payload = require(directory + '/' + filename, checksums[filename])
                decode_texture(page, payload)
        banks = move.get('audioBanks', {})
        if not isinstance(banks, dict) or any(key not in ('SE', 'System') or not isinstance(value, str) or not value for key, value in banks.items()):
            raise ValueError('Unsupported prepared sound-bank routing')
        bank_paths = set(banks.values())
        if move.get('audioBank'): bank_paths.add(move['audioBank'])
        if any(s.get('sourceBank') == 'System' for s in move.get('sounds', [])) and not banks.get('System'):
            raise ValueError('System effect cues require their prepared System bank')
        if not bank_paths and (move.get('sounds') or move.get('cast')):
            raise ValueError('Prepared move references sounds without an audio bank')
        for bank_path in sorted(bank_paths):
            name = _path(bank_path, 'audio/')
            if not name.endswith('.json'):
                raise ValueError('Effects audio bank must be a prepared manifest')
            bank = _json(require(name))
            if bank.get('schema') != 'ffr-audio-1' or not isinstance(bank.get('waves'), dict):
                raise ValueError('Unsupported prepared audio manifest')
            for wave in bank['waves'].values():
                digest = _digest(wave['sha256'])
                require('audio/samples/' + digest + '.hca', digest, wave.get('size'))
    return dependencies


def read_archive(path):
    """Read a bounded ZIP, rejecting collisions, traversal and special entries."""
    files, names = {}, set()
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES or sum(e.file_size for e in entries) > MAX_BYTES:
            raise ValueError('The archive exceeds the Studio unpacking budget')
        for entry in entries:
            # ZipInfo normalizes backslashes on Windows; validate the original
            # central-directory spelling before considering its normalized name.
            safe_name(entry.orig_filename.rstrip('/') if entry.is_dir() else entry.orig_filename)
            name = safe_name(entry.filename.rstrip('/') if entry.is_dir() else entry.filename)
            lower = name.casefold()
            if lower in names:
                raise ValueError('The archive contains duplicate filenames')
            names.add(lower)
            kind = stat.S_IFMT(entry.external_attr >> 16)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise ValueError('The archive contains an unsupported entry')
            if not entry.is_dir():
                files[name] = archive.read(entry)
    filenames = {n.casefold() for n in files}
    if any(any(parent.as_posix().casefold() in filenames
               for parent in PurePosixPath(name).parents if str(parent) != '.') for name in files):
        raise ValueError('The archive contains conflicting file and directory names')
    return files


def _write_archive(path, files):
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_BYTES:
        raise ValueError('The archive exceeds the Studio unpacking budget')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as tmp:
        temporary = Path(tmp.name)
    try:
        # Compression streams to disk; do not keep another complete archive in
        # memory alongside several hundred MiB of prepared cinematic textures.
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name, raw in sorted(files.items()):
                entry = zipfile.ZipInfo(safe_name(name), (2026, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                # Atlas payloads already have their own validated zlib stream.
                # Recompressing them adds CPU work with negligible size savings.
                entry.compress_type = zipfile.ZIP_STORED if name.endswith('.bgra.z') else zipfile.ZIP_DEFLATED
                archive.writestr(entry, raw)
        with temporary.open('rb') as handle:
            digest = hashlib.file_digest(handle, 'sha256').hexdigest()
        size = temporary.stat().st_size
        same = False
        if path.is_file() and path.stat().st_size == size:
            with path.open('rb') as handle:
                same = hashlib.file_digest(handle, 'sha256').hexdigest() == digest
        if not same:
            temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'size': size, 'sha256': digest, 'unpackedBytes': sum(map(len, files.values()))}


def verify_files(files, expected_form=None, *, standalone=False):
    """Validate both standalone artifacts and effects embedded in a unit archive."""
    manifests = [n for n in files if re.fullmatch(r'presentation/effects/[0-9]+\.json', n)]
    if len(manifests) != 1:
        raise ValueError('Expected one effects bundle manifest')
    manifest = _json(files[manifests[0]])
    if manifest.get('schema') != VERSION:
        raise ValueError('Unsupported effects bundle schema')
    form = form_id(manifest.get('form'))
    if expected_form is not None and form != form_id(expected_form):
        raise ValueError('Effects bundle belongs to a different unit form')
    if manifests[0] != f'presentation/effects/{form}.json' or manifest.get('presentation') != f'presentation/{form}.json':
        raise ValueError('Effects manifest identity mismatch')
    index = manifest.get('files')
    if not isinstance(index, dict) or not index:
        raise ValueError('Effects bundle has no content index')
    for name, info in index.items():
        safe_name(name)
        if not name.startswith(('presentation/', 'audio/')) or name == manifests[0]:
            raise ValueError('Unexpected effects payload path')
        if name not in files:
            raise ValueError('Effects bundle is incomplete: ' + name)
        if len(files[name]) != info.get('size') or _sha(files[name]) != _digest(info.get('sha256')):
            raise ValueError('Effects payload checksum mismatch: ' + name)
    presentation_name = manifest['presentation']
    presentation = _json(files.get(presentation_name, b'{}'))
    if str(presentation.get('form')) != form:
        raise ValueError('Effects presentation belongs to a different form')
    if manifest.get('presentationSchema') != presentation.get('schema'):
        raise ValueError('Effects presentation schema metadata mismatch')
    summaries = {key: {'status': move.get('status', 'unknown'), 'issues': move.get('issues', [])}
                 for key, move in presentation.get('moves', {}).items()}
    if manifest.get('moves') != summaries:
        raise ValueError('Effects status metadata differs from the prepared move limitations')
    try:
        dependencies = _dependencies(presentation, files.__getitem__)
    except KeyError as ex:
        raise ValueError('Effects bundle is missing a playback dependency: ' + str(ex)) from ex
    reports = manifest.get('reports', [])
    for name in reports:
        safe_name(name)
        if not name.startswith(f'presentation/reports/{form}/') or not name.endswith('.json'):
            raise ValueError('Unexpected effects report path')
        if name in files:
            _json(files[name])
    expected = dependencies | {presentation_name} | set(reports)
    if set(index) != expected:
        raise ValueError('Effects content index does not match its playback dependencies')
    if standalone and set(files) != expected | {manifests[0]}:
        raise ValueError('Unexpected file in standalone effects archive')
    return manifest


def verify(path, expected_form=None):
    return verify_files(read_archive(path), expected_form, standalone=True)


def verify_installed(data, form):
    """Recheck installed dependencies, so a stale completion marker cannot hide loss."""
    data, form = Path(data), form_id(form)
    name = f'presentation/effects/{form}.json'
    manifest_raw = _disk(data, name).read_bytes()
    manifest = _json(manifest_raw)
    files = {name: manifest_raw}
    if not isinstance(manifest.get('files'), dict):
        raise ValueError('Effects bundle has no content index')
    size = len(manifest_raw)
    for filename in manifest['files']:
        path = _disk(data, filename)
        size += path.stat().st_size
        if size > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError('Effects bundle exceeds its unpacking budget')
        files[filename] = path.read_bytes()
    return verify_files(files, form, standalone=True)


def _compress_page(raw, compressed_by_sha):
    """Reuse portable bytes after each caller has validated its source page."""
    raw_sha = _sha(raw)
    compressed = compressed_by_sha.get(raw_sha)
    if compressed is None:
        if COMPRESSION_CACHE is None:
            compressed = zlib.compress(raw, level=9)
        else:
            from ffbe_effects.conversion_io import file_lock, atomic_bytes
            path = Path(COMPRESSION_CACHE) / ('zlib9-' + raw_sha + '.z')
            with file_lock(path.with_suffix('.lock')):
                if path.is_file():
                    candidate = path.read_bytes()
                    # Decode with a hard bound before trusting reusable bytes.
                    try:
                        decoder = zlib.decompressobj()
                        decoded = decoder.decompress(candidate, len(raw) + 1)
                        if decoder.eof and not decoder.unused_data and not decoder.unconsumed_tail and decoded == raw:
                            compressed = candidate
                    except zlib.error:
                        pass
                if compressed is None:
                    compressed = zlib.compress(raw, level=9)
                    atomic_bytes(path, compressed)
        compressed_by_sha[raw_sha] = compressed
    return raw_sha, compressed


def pack(presentation_path, output_path, *, root=ROOT, reports=None, compress_textures=True):
    """Package an existing preparation; reports maps simple filenames to JSON data."""
    root = Path(root)
    presentation = _json(Path(presentation_path).read_bytes())
    form = form_id(presentation.get('form'))
    files, size = {}, 0
    def source(name):
        path = _disk(root / 'data/ffbe', name)
        limit = MAX_TEXTURE_BYTES if name.endswith('.bgra') else (
            MAX_ENCODED_TEXTURE_BYTES if name.endswith('.bgra.z') else MAX_BYTES)
        if path.stat().st_size > limit:
            raise ValueError(('Prepared texture exceeds the decoded page budget: ' if name.endswith('.bgra')
                              else 'Effects bundle exceeds its unpacking budget: ') + name)
        return path.read_bytes()
    # Validate originals without retaining every raw atlas in memory. Only the
    # compressed portable payload is accumulated below; source files stay intact.
    dependencies = _dependencies(presentation, source)
    def put(name, raw):
        nonlocal size
        if name in files:
            if files[name] != raw:
                raise ValueError('Conflicting prepared dependency: ' + name)
            return
        size += len(raw)
        if size > MAX_BYTES or len(files) >= MAX_FILES:
            raise ValueError('Effects bundle exceeds its unpacking budget')
        files[name] = raw
    projects, transformed = {}, set()
    # Values are the same immutable bytes objects retained in files, not extra
    # image copies. This cache is discarded at the end of this one archive.
    compressed_by_sha = {}
    decoded_bytes = encoded_bytes = pages = 0
    if compress_textures:
        for move in presentation['moves'].values():
            for visual in move.get('visuals', []):
                directory = _path(visual['spec'], 'presentation/assets/')
                if directory not in projects:
                    original = visual['checksums']
                    spec_raw = source(directory + '/spec.json')
                    if _sha(spec_raw) != original['spec.json']:
                        raise ValueError('Prepared project changed during packaging')
                    spec = _json(spec_raw)
                    checksums = {}
                    maps = spec.get('cellmaps', [spec])
                    for index, page in enumerate(maps):
                        filename = page.get('textureFile', 'tex' + (f'_{index}' if index else '') + '.bgra')
                        payload = source(directory + '/' + filename)
                        if _sha(payload) != original[filename]:
                            raise ValueError('Prepared texture changed during packaging')
                        raw = decode_texture(page, payload)
                        raw_sha, compressed = _compress_page(raw, compressed_by_sha)
                        packed_name = filename if filename.endswith('.bgra.z') else filename + '.z'
                        page.update(textureFile=packed_name, textureEncoding='zlib',
                                    textureBytes=len(raw), textureSha256=raw_sha)
                        put(directory + '/' + packed_name, compressed)
                        checksums[packed_name] = _sha(compressed)
                        decoded_bytes += len(raw); encoded_bytes += len(compressed); pages += 1
                    # Preserve the existing first-page alias for single-page
                    # readers while the cellmaps list remains authoritative.
                    if 'cellmaps' in spec:
                        for key in ('textureFile', 'textureEncoding', 'textureBytes', 'textureSha256'):
                            spec[key] = maps[0][key]
                    packed_spec = encoded(spec)
                    put(directory + '/spec.json', packed_spec)
                    checksums['spec.json'] = _sha(packed_spec)
                    transformed.update(directory + '/' + name for name in original)
                    projects[directory] = checksums
                visual['checksums'] = dict(projects[directory])
    for name in sorted(dependencies - transformed):
        put(name, source(name))
    put(f'presentation/{form}.json', encoded(presentation))
    report_paths = []
    for filename, report in sorted((reports or {}).items()):
        safe_name(filename)
        if '/' in filename or not filename.endswith('.json'):
            raise ValueError('Effects report name must be a simple JSON filename')
        name = f'presentation/reports/{form}/{filename}'
        put(name, encoded(report))
        report_paths.append(name)
    manifest = {'schema': VERSION, 'form': form, 'presentation': f'presentation/{form}.json',
                'presentationSchema': presentation['schema'], 'reports': report_paths,
                'moves': {key: {'status': move.get('status', 'unknown'), 'issues': move.get('issues', [])}
                          for key, move in presentation['moves'].items()},
                'files': {name: {'size': len(raw), 'sha256': _sha(raw)} for name, raw in sorted(files.items())}}
    put(f'presentation/effects/{form}.json', encoded(manifest))
    verify_files(files, form, standalone=True)
    return {**_write_archive(output_path, files), 'format': VERSION, 'form': form,
            'presentation': presentation['schema'], 'effects': VERSION,
            **({'textureCompression': {'encoding': 'zlib', 'level': 9, 'pages': pages,
                                      'decodedBytes': decoded_bytes, 'encodedBytes': encoded_bytes}}
               if compress_textures else {})}


def merge(unit_path, effects_path, output_path):
    """Embed verified effects, retaining the unit's existing sprites, kit and audio."""
    effects = read_archive(effects_path)
    manifest = verify_files(effects, standalone=True)
    form = manifest['form']
    files = read_archive(unit_path)
    forms = {PurePosixPath(n).parts[1] for n in files if n.startswith('sprites/') and len(PurePosixPath(n).parts) > 2}
    if forms != {form}:
        raise ValueError('Effects bundle belongs to a different unit archive')
    if f'lb_profiles/{form}.json' not in files or not any(n.startswith('unit_records/') for n in files):
        raise ValueError('Expected a portable ffr-unit-1 archive')
    kit_name = f'native_kits/{form}.json'
    if kit_name in files:
        kit = _json(files[kit_name])
        presentation = _json(effects[manifest['presentation']])
        for key, move in presentation['moves'].items():
            profile = kit.get('profiles', {}).get(key)
            if not isinstance(profile, dict) or not isinstance(profile.get('snapshot'), dict):
                raise ValueError('Unit kit does not contain the prepared move: ' + key)
            records = [{k: record.get(k) for k in ('source', 'kind', 'id', 'level', 'data')}
                       for record in profile['snapshot'].get('records', [])]
            fingerprint = _sha(json.dumps(records, sort_keys=True, ensure_ascii=False).encode())
            if fingerprint != move['sourceSha256']:
                raise ValueError('Unit kit source differs from the prepared effects: ' + key)
    old_name = f'presentation/effects/{form}.json'
    if old_name in files:
        old = verify_files(files, form)
        for name in old['files']:
            # Preserve shared sound files also used by the unit's native LB bank.
            if name.startswith('presentation/'):
                files.pop(name, None)
        files.pop(old_name)
    files.update(effects)
    verify_files(files, form)
    return {**_write_archive(output_path, files), 'format': 'ffr-unit-1', 'form': form,
            'presentation': manifest['presentationSchema'], 'effects': VERSION}
