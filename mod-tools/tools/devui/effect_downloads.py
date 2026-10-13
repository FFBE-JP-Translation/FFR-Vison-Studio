"""Fetch only equipped moves into a shared, hash-verified effects cache."""
import hashlib
from pathlib import Path
import threading
from urllib.parse import urljoin
import ffbe_effect_bundle as old
import ffbe_effect_refs as refs

LOCK = threading.RLock()


def decorate_rows(form, rows):
    import unit_downloads as units
    data = units.ROOT / 'data/ffbe'
    marker = data / f'presentation/effects/{old.form_id(form)}.json'
    if not marker.is_file(): return
    if old._json(marker.read_bytes()).get('schema') != refs.VERSION: return
    index, _ = refs.read_installed(data, form)
    for row in rows:
        if row['kind'] == 'PASSIVE': continue
        names = index['moves'].get(row['sourceKey'])
        row['animationStatus'] = 'converted' if names is not None else 'unavailable'
        if names is not None:
            row['animationDownloadBytes'] = sum({index['files'][n]['sha256']: index['files'][n]['size'] for n in names}.values())


def ensure_move(form, key, report=lambda **kw: None):
    import unit_downloads as units
    data = units.ROOT / 'data/ffbe'
    marker = data / f'presentation/effects/{old.form_id(form)}.json'
    if not marker.is_file(): return False
    if old._json(marker.read_bytes()).get('schema') != refs.VERSION: return False
    with LOCK:
        index, presentation = refs.read_installed(data, form)
        if key not in index['moves']:
            # Explicitly reported conversion gaps retain the existing native
            # fallback; they do not stop the other moves in the form importing.
            return False
        info = units.index()['unitBundles'].get(str(form), {})
        base = info.get('effectBaseUrl')
        if not base: raise ValueError('This unit pack is missing its shared-effects download location')
        names = index['moves'][key]
        total = sum({index['files'][n]['sha256']: index['files'][n]['size'] for n in names}.values())
        received, seen = 0, set()
        for name in names:
            entry = index['files'][name]
            digest = entry['sha256']
            destination = old._disk(data, name)
            cached = False
            if destination.is_file() and destination.stat().st_size == entry['decodedSize']:
                with destination.open('rb') as stream:
                    cached = hashlib.file_digest(stream, 'sha256').hexdigest() == entry['decodedSha256']
            if not cached:
                report(stage=f"Preparing {presentation['moves'][key].get('name', 'move')} effects", received=received, total=total)
                target = units.app_root() / 'effect-cache' / digest[:2] / digest
                units.download({**entry, 'url': urljoin(base.rstrip('/') + '/', refs.blob_name(digest))}, target,
                    lambda **kw: report(**{**kw, 'received': received + kw.get('received', 0), 'total': total}))
                raw = refs.decode(entry, target.read_bytes())
                # Immutable content-named projects avoid overwriting another
                # form's files or the separately reviewed four-unit checkpoint.
                refs.materialize(destination, target, entry, raw)
            if digest not in seen:
                received += entry['size']; seen.add(digest)
        refs.verify_move(index, presentation, key, lambda name: old._disk(data, name).read_bytes())
        report(stage='Move effects ready', received=total, total=total)
        return True


def ensure_loadout(units, report=lambda **kw: None):
    for unit in units:
        if not unit.get('ffbe'): continue
        form = str(unit['ffbe']['id'])
        for move in [*unit.get('skills', {}).values(), unit.get('lb_custom', {})]:
            key = move.get('ffbe', {}).get('source')
            if key: ensure_move(form, key, report)
