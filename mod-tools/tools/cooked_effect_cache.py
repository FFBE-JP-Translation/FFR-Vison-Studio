"""Reuse cooked particle assets only with identical inputs and verified outputs."""
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


@lru_cache(maxsize=4096)
def _hash(path, size, mtime):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def digest(path):
    path = Path(path); stat = path.stat()
    return _hash(str(path.resolve()), stat.st_size, stat.st_mtime_ns)


def identity(root, legacy, mapping, compiler, name, spec_dir, donor, texture_donor):
    root, legacy = Path(root), Path(legacy)
    source = root / spec_dir
    spec = json.loads((source / 'spec.json').read_bytes())
    files = [source / 'spec.json', Path(mapping), Path(compiler)]
    library = Path(compiler).parent / 'UAssetAPI.dll'
    if library.exists(): files.append(library)
    for i, page in enumerate(spec.get('cellmaps', [spec])):
        filename = page.get('textureFile', 'tex' + (f'_{i}' if i else '') + '.bgra')
        if Path(filename).name != filename or '/' in filename or '\\' in filename:
            raise ValueError('Invalid texture filename')
        files.append(source / filename)
    for uid, suffix in ((donor, ''), (texture_donor, '_tex')):
        stem = legacy / f'FFRS/Content/Chara/summon/summon{uid}/summon{uid}{suffix}'
        for extension in ('.uasset', '.uexp', '.ubulk'):
            path = stem.with_suffix(extension)
            if path.exists(): files.append(path)
    signature = {'schema': 1, 'name': name, 'donor': donor, 'textureDonor': texture_donor,
                 'inputs': [digest(p) for p in files]}
    return hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()


def restore(cache, key, target):
    folder = Path(cache) / key
    receipt = folder / 'receipt.json'
    if not receipt.is_file(): return False
    try:
        files = json.loads(receipt.read_bytes())['files']
        if not files: return False
        for name, expected in files.items():
            if Path(name).name != name or digest(folder / name) != expected: return False
    except (OSError, ValueError, KeyError):
        return False
    Path(target).mkdir(parents=True, exist_ok=True)
    for name in files: shutil.copy2(folder / name, Path(target) / name)
    return True


def store(cache, key, source):
    cache = Path(cache); cache.mkdir(parents=True, exist_ok=True)
    target = cache / key
    files = {p.name: digest(p) for p in Path(source).iterdir() if p.suffix in ('.uasset', '.uexp', '.ubulk')}
    if not files: raise ValueError('Cannot cache an empty effect')
    with tempfile.TemporaryDirectory(prefix='cook-', dir=cache) as temp:
        temporary = Path(temp)
        for name in files: shutil.copy2(Path(source) / name, temporary / name)
        (temporary / 'receipt.json').write_text(json.dumps({'files': files}), encoding='utf-8')
        target.mkdir(exist_ok=True)
        # Publish each completed file atomically and the receipt last. Readers
        # reject any mismatch; a corrupt cache is repaired after a fresh cook.
        for name in files: os.replace(temporary / name, target / name)
        os.replace(temporary / 'receipt.json', target / 'receipt.json')
