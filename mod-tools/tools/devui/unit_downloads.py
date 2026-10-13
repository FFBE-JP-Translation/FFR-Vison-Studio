"""Advanced Studio's on-demand unit packs; shares the native app's disk cache."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import threading
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[2]
LOCK = threading.Lock()


def app_root():
    return ROOT.parent if ROOT.name == 'engine' else ROOT / 'build/devui'


def index():
    cache = Path(os.environ.get('FFR_HOST_INDEX', str(app_root() / 'ffbe_index_cache.json')))
    import converted_units
    return converted_units.overlay(json.loads(cache.read_text(encoding='utf-8')) if cache.is_file() else {})


def preview_file(form, kind):
    if not re.fullmatch(r'\d+', form):
        return None
    path = app_root() / ('idles' if kind == 'idle' else 'icons') / (form + ('.webp' if kind == 'idle' else '.png'))
    return path if path.is_file() else None


def download(info, target, report):
    digest = info.get('sha256', '')
    if not re.fullmatch(r'[a-f0-9]{64}', digest):
        raise ValueError('The download catalog has an invalid checksum. Restart Studio to refresh it.')
    def matches(path):
        if not path.is_file() or path.stat().st_size != info['size']:
            return False
        with path.open('rb') as f:
            return hashlib.file_digest(f, 'sha256').hexdigest() == digest
    if matches(target):
        return target
    base = os.environ.get('FFR_STUDIO_HOST', 'https://ffbe.luminest.io/')
    url = urljoin(base, info['url'])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + '.' + uuid.uuid4().hex + '.advanced-part')
    for attempt in range(6):
        try:
            with urlopen(Request(url, headers={'Accept-Encoding': 'identity'}), timeout=45) as r, partial.open('wb') as out:
                size = 0
                while chunk := r.read(131072):
                    out.write(chunk); size += len(chunk)
                    if size > info['size']:
                        raise ValueError('Downloaded file is larger than its catalog entry.')
                    report(received=size, total=info['size'])
            if not matches(partial):
                raise ValueError('Download checksum did not match. Retry the import.')
            partial.replace(target)
            return target
        except (OSError, URLError, ValueError) as ex:
            if attempt == 5 or isinstance(ex, HTTPError) and ex.code not in (408, 429, 500, 502, 503, 504):
                raise ValueError(f'Could not download unit assets: {ex}') from ex
            wait = min(30, 2 ** (attempt + 1))
            if isinstance(ex, HTTPError) and ex.headers.get('Retry-After', '').isdigit():
                wait = min(60, int(ex.headers['Retry-After']))
            report(stage=f'Download interrupted; retrying in {wait} seconds', received=0, total=0)
            time.sleep(wait)
        finally:
            partial.unlink(missing_ok=True)


def ensure_form(form, info, report):
    data = ROOT / 'data/ffbe'
    sprite = data / 'sprites' / form
    modern = info.get('format') == 'ffr-unit-1'
    required = [f'sprites/{form}/unit_anime_{form}.png', f'sprites/{form}/unit_cgg_{form}.csv', f'sprites/{form}/unit_idle_cgs_{form}.csv']
    if modern:
        required += [f'unit_records/{info["unitId"]}.json', f'lb_profiles/{form}.json', f'audio/lb/{form}.json']
        if info.get('nativeKit'): required.append(f'native_kits/{form}.json')
        if info.get('presentation'): required.append(f'presentation/{form}.json')
        if info.get('effects'): required.append(f'presentation/effects/{form}.json')
    sounds = info.get('sounds', [])
    marker = sprite / '.complete'
    complete = marker.is_file() and marker.read_text() == info['sha256'] and all((data / p).is_file() for p in required)
    if info.get('effects'):
        import ffbe_effect_bundle
        import ffbe_effect_refs
        thin = info['effects'] == ffbe_effect_refs.VERSION
        if info['effects'] not in (ffbe_effect_bundle.VERSION, ffbe_effect_refs.VERSION):
            raise ValueError('This unit requires a newer prepared-effects reader. Update Studio.')
        if complete:
            try:
                if thin: ffbe_effect_refs.read_installed(data, form)
                else: ffbe_effect_bundle.verify_installed(data, form)
            except (OSError, ValueError, KeyError, TypeError):
                complete = False
    if not complete:
        report(stage=f'Downloading unit data ({form})', received=0, total=info['size'])
        archive = download(info, app_root() / 'downloads' / (form + ('.ffr' if modern else '.zip')), report)
        report(stage='Unpacking unit data', received=0, total=0)
        data.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='unit-', dir=data) as tmp, zipfile.ZipFile(archive) as z:
            staging = Path(tmp)
            limit = ffbe_effect_bundle.MAX_BYTES if info.get('effects') else 256 * 1024 * 1024
            if sum(i.file_size for i in z.infolist()) > limit:
                raise ValueError('The unit archive is too large when unpacked.')
            for entry in z.infolist():
                name = PurePosixPath(entry.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in entry.filename or ':' in entry.filename:
                    raise ValueError('The unit archive contains an unsafe filename.')
                if modern and name.parts[0] not in ('sprites', 'unit_records', 'lb_profiles', 'audio', 'ability_icons', 'native_kits', 'presentation'):
                    raise ValueError('The unit archive contains an unexpected file.')
                dest = staging / name if modern else staging / 'sprites' / form / name
                if entry.is_dir():
                    continue
                dest.parent.mkdir(parents=True, exist_ok=True)
                with z.open(entry) as src, dest.open('wb') as out:
                    shutil.copyfileobj(src, out)
            if any(not (staging / p).is_file() for p in required):
                raise ValueError('The unit archive is incomplete. Retry the import.')
            if info.get('effects'):
                # Validate the full closure before any of it replaces installed data.
                # The producer and decoder are not part of Studio's import path.
                if thin:
                    ffbe_effect_refs.verify_thin(ffbe_effect_bundle.read_archive(archive), form)
                    ffbe_effect_refs.read_installed(staging, form)
                else:
                    ffbe_effect_bundle.verify_files(ffbe_effect_bundle.read_archive(archive), form)
                    ffbe_effect_bundle.verify_installed(staging, form)
            for src in staging.rglob('*'):
                if src.is_file():
                    dest = data / src.relative_to(staging)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
    for n, sound in enumerate(sounds, 1):
        report(stage=f'Preparing limit burst sounds ({n}/{len(sounds)})', received=0, total=sound['size'])
        download(sound, data / 'audio/samples' / (sound['sha256'] + '.hca'), report)
    marker.write_text(info['sha256'])


def ensure_selection(uid, form, report=lambda **kw: None):
    catalog = index()
    bundles = catalog.get('unitBundles') or catalog.get('forms') or {}
    if not bundles:
        return  # Source-tree installations can still use their local FFBE dumps.
    row = next((r for r in catalog.get('units', []) if r['id'] == uid), None)
    if not row or form not in (row.get('packs') or row.get('spriteForms') or []):
        raise ValueError('This look is not available for the selected unit.')
    base = (row.get('shift', {}).get(form) or {}).get('base')
    wanted = list(dict.fromkeys([form] + ([base] if base else [])))
    report(stage='Waiting to prepare unit', received=0, total=0)
    with LOCK:
        for fid in wanted:
            if fid not in bundles:
                raise ValueError(f'No unit pack is available for {fid}.')
            ensure_form(fid, bundles[fid], report)
            if fid == form and bundles[fid].get('effects') == 'ffr-effects-ref-1':
                # A newly imported unit equips its prepared LB automatically.
                # Fetch it in this progress-reporting job, before Add unit.
                import ffbe_effect_refs
                import effect_downloads
                data = ROOT / 'data/ffbe'
                _, presentation = ffbe_effect_refs.read_installed(data, fid)
                native = json.loads((data / f'native_kits/{fid}.json').read_bytes())
                lb = next((e['sourceKey'] for e in native['kit']['entries'] if e['kind'] == 'LB'
                    and e['status'] == 'ready' and e['sourceKey'] in presentation['moves']), None)
                if lb: effect_downloads.ensure_move(fid, lb, report)
        import ffbe_catalog
        report(stage='Refreshing unit library', received=0, total=0)
        ffbe_catalog.build_index()
    report(stage='Unit data ready', received=0, total=0)
