"""Read the complete, form-specific testing kits without the external datamine."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import zlib
from functools import lru_cache
from ability_converter import reviewed
from ability_converter import multicast

PATH = reviewed.ROOT / 'data/ability_converter/vision-kits.sqlite'
BUNDLES = reviewed.ROOT / 'data/ffbe/native_kits'


@lru_cache(maxsize=8)
def _bundle(path, modified):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema') != 'ffr-native-kit-1' or data.get('rulesSha256') != reviewed.fingerprint():
        raise ValueError('This vision bundle needs the matching reviewed effect rules')
    return data


def bundled(form):
    form = str(form)
    if not form.isdecimal(): raise ValueError('Invalid vision form')
    path = BUNDLES / (form + '.json')
    data = _bundle(str(path), path.stat().st_mtime_ns) if path.is_file() else None
    # Older downloaded archives can use the engine's newer precomputed kit.
    return data if data and data.get('studioPolicy') == multicast.VERSION else None


def export_bundle(form, db):
    """A .ffr carries its completed conversions and all source dependencies."""
    row = db.execute('SELECT payload FROM kits WHERE form=?', (str(form),)).fetchone()
    if row is None: raise ValueError(f'No reviewed kit for {form}')
    data = json.loads(zlib.decompress(row[0]))
    profiles = {}
    for entry in data['entries']:
        key = entry['sourceKey']
        value = db.execute('SELECT payload FROM profiles WHERE source_key=?', (key,)).fetchone()
        if value is None: raise ValueError(f'Missing prepared conversion: {key}')
        profiles[key] = json.loads(zlib.decompress(value[0]))
    return {'schema': 'ffr-native-kit-1', 'rulesSha256': reviewed.fingerprint(),
            'studioPolicy':multicast.VERSION, 'kit': data, 'profiles': profiles}


@contextmanager
def connect():
    if not PATH.is_file():
        raise ValueError('The reviewed vision kit bundle is missing. Run the vision kit build first.')
    db = sqlite3.connect(PATH.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        meta = dict(db.execute('SELECT key,value FROM metadata'))
        if meta.get('rulesSha256') != reviewed.fingerprint():
            raise ValueError('The vision kits and effect rules belong to different reviews')
        if meta.get('studioPolicy') != multicast.VERSION:
            raise ValueError('The prepared vision data needs the current multicast policy. Refresh the native kit bundle first.')
        yield db
    finally:
        db.close()


def kit(form):
    if data := bundled(form): return data['kit']
    with connect() as db:
        row = db.execute('SELECT payload FROM kits WHERE form=?', (str(form),)).fetchone()
    if row is None:
        raise ValueError(f'No reviewed kit exists for FFBE form {form}')
    return json.loads(zlib.decompress(row[0]))


def profile(key, form=None):
    if form is not None and (data := bundled(form)):
        if key not in data['profiles']: raise ValueError('That ability does not belong to this vision bundle')
        return data['profiles'][key]
    with connect() as db:
        row = db.execute('SELECT payload FROM profiles WHERE source_key=?', (key,)).fetchone()
    if row is None:
        raise ValueError(f'No reviewed ability exists for {key}')
    return json.loads(zlib.decompress(row[0]))


def entries(unit):
    return kit(unit['ffbe']['id'])
