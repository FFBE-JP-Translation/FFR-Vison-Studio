"""Opt-in local prepared archives; no conversion or public catalog mutation."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=2)
def _read(path, mtime_ns):
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('schema') != 'ffr-local-converted-units-1':
        raise ValueError('Unsupported local converted-unit catalog')
    return data


def manifest():
    selected = os.environ.get('FFR_CONVERTED_UNITS')
    if not selected:
        return None
    path = Path(selected)
    return _read(str(path.resolve()), path.stat().st_mtime_ns)


def overlay(catalog, base_url=None):
    data = manifest()
    if data is None:
        return catalog
    # Use the audited baseline, so a hosted refresh cannot discard local entries.
    baseline = json.loads(Path(data['baseline']).read_bytes())
    entries = dict(baseline['unitBundles'])
    for form, info in data['unitBundles'].items():
        entries[form] = {k: v for k, v in info.items() if k != 'localArchive'}
        if base_url:
            entries[form]['url'] = base_url.rstrip('/') + '/api/assets/converted/' + form
            if info.get('effects') == 'ffr-effects-ref-1':
                entries[form]['effectBaseUrl'] = base_url.rstrip('/') + '/api/assets/'
        else:
            entries[form]['url'] = (Path(data['delivery']).resolve() / (form + '.ffr')).as_uri()
            if info.get('effects') == 'ffr-effects-ref-1':
                entries[form]['effectBaseUrl'] = Path(data.get('effectsDelivery', data['delivery'])).resolve().as_uri() + '/'
    return {**baseline, 'unitBundles': entries, 'localConversion': data['summary']}


def archive(form):
    if not re.fullmatch(r'[0-9]+', form):
        raise ValueError('Invalid form')
    data = manifest()
    if data is None or form not in data['unitBundles']:
        raise FileNotFoundError('This form has no converted archive')
    info = data['unitBundles'][form]
    path = Path(info['localArchive']).resolve()
    if path != Path(data['delivery']).resolve() / (form + '.ffr'):
        raise ValueError('Converted archive is outside the audited delivery directory')
    if path.stat().st_size != info['size']:
        raise ValueError('Converted archive changed; audit the catalog again')
    return path


def blob(prefix, digest):
    import ffbe_effect_refs
    relative = ffbe_effect_refs.blob_name(digest)
    if prefix != digest[:2]: raise ValueError('Invalid effects shard')
    data = manifest()
    if not data: raise FileNotFoundError('No local effects library')
    path = Path(data.get('effectsDelivery', data['delivery'])) / relative
    if not path.is_file(): raise FileNotFoundError('Shared effect is unavailable')
    return path
