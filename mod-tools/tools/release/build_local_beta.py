"""Freeze a local animation beta without copying the complete effects library.

Run with the local Python, then build/copy the Flutter beta app separately.
The beta has its own engine, authored roster and build outputs. Immutable media
can be hard-linked on this PC; mutable JSON and scripts are independent copies.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/release')]
import ffbe_effect_bundle as legacy
import ffbe_effect_refs as refs
import build_release


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path, data): refs.atomic(path, legacy.encoded(data))
def sha(path):
    with Path(path).open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def copy(source, target, immutable=False):
    source, target = Path(source), Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists(): return
    if immutable:
        try: os.link(source, target); return
        except OSError: pass
    shutil.copy2(source, target)


def tree(source, target, media_links=False):
    source, target = Path(source), Path(target)
    if not source.is_dir(): raise FileNotFoundError(source)
    for folder, directories, names in os.walk(source):
        directories[:] = [d for d in directories if d not in ('__pycache__', '.git', 'node_modules', '.dart_tool')]
        for name in names:
            path = Path(folder)/name
            if path.suffix == '.pyc': continue
            copy(path, target/path.relative_to(source), immutable=media_links and path.suffix in ('.bgra', '.z', '.hca', '.png', '.webp', '.uasset', '.uexp', '.ubulk'))


def snapshot(out, source_path):
    catalog_path = out/'catalog/converted-units.json'
    if catalog_path.is_file(): return read(catalog_path)
    source = read(source_path)
    delivery = out/'catalog/units'
    baseline_path = out/'catalog/baseline.json'
    copy(source['baseline'], baseline_path)
    baseline = read(baseline_path)
    entries = source['unitBundles']
    inventory = {}
    frozen = {}
    print('Checking frozen unit archives and their shared-media references', flush=True)

    def one(item):
        form, info = item
        target = delivery/(form+'.ffr')
        # A worker may finish between the live manifest read and this copy.
        # Retry with its atomic result receipt, never accept mismatched bytes.
        for attempt in range(3):
            src = Path(info['localArchive'])
            payload = src.read_bytes()
            if len(payload) == info['size'] and hashlib.sha256(payload).hexdigest() == info['sha256']:
                break
            receipt = source_path.parent/'results'/(form+'.json')
            info = {**baseline['unitBundles'][form], **read(receipt)}
        else: raise ValueError('Unit changed during snapshot: '+form)
        refs.atomic(target, payload)
        files = legacy.read_archive(target)
        index = refs.verify_thin(files, form)
        if len(index['moves']) != info['preparedMoveCount']:
            raise ValueError('Move count mismatch: '+form)
        return form, {**info, 'localArchive': str(target.resolve())}, index['files']

    with ThreadPoolExecutor(max_workers=4) as pool:
        for number, (form, info, files) in enumerate(pool.map(one, entries.items()), 1):
            frozen[form] = info
            for descriptor in files.values():
                digest = descriptor['sha256']
                if digest in inventory:
                    if inventory[digest] != descriptor['size']: raise ValueError('Conflicting shared file size')
                    continue
                # Runtime imports check full hashes for the selected moves.
                # Do not traverse the entire offline library to launch a local
                # beta; this snapshot freezes the already-published references.
                inventory[digest] = descriptor['size']
            if number % 200 == 0 or number == len(entries):
                print(f'Frozen {number}/{len(entries)} forms', flush=True)
    summary = {'channel': 'beta', 'label': 'Animation Beta 1', 'status': 'beta_snapshot',
        'frozenAtUtc': datetime.now(timezone.utc).isoformat(), 'bundledForms': len(frozen),
        'requestedForms': len(frozen), 'withinThreshold': sum(e['withinThreshold'] for e in frozen.values()),
        'aboveThreshold': sum(not e['withinThreshold'] for e in frozen.values()),
        'maxMissingActiveMoves': 3, 'unitArchiveBytes': sum(e['size'] for e in frozen.values()),
        'sharedPayloadCount': len(inventory), 'sharedPayloadBytes': sum(inventory.values()),
        'sharedPayloadVerification': 'full checksums when equipped; representative native import/build tests'}
    result = {'schema': 'ffr-local-converted-units-1', 'delivery': str(delivery.resolve()),
        'effectsDelivery': str(Path(source.get('effectsDelivery', source['delivery'])).resolve()), 'baseline': str(baseline_path.resolve()),
        'summary': summary, 'unitBundles': frozen}
    write(out/'catalog/shared-inventory.json', inventory)
    write(catalog_path, result)
    print(json.dumps(summary, indent=2), flush=True)
    return result


def stage_engine(out, catalog):
    engine = out/'engine'
    if (engine/'.seeded').is_file(): return
    print('Preparing separate beta engine and game inputs', flush=True)
    for source in (ROOT/'tools').glob('*.py'):
        if source.name not in build_release.OFFLINE_TOOL_FILES: copy(source, engine/'tools'/source.name)
    copy(ROOT/'tools/vision_card_names.json', engine/'tools/vision_card_names.json')
    for name in ('devui', 'ability_converter', 'effect_review', 'ffbe2ss6', 'retoc', 'repak', 'private', 'scripts'):
        tree(ROOT/'tools'/name, engine/'tools'/name)
    build_release.ship_effect_runtime(engine/'tools')
    build_release.assert_effect_boundary(engine/'tools')
    for relative in ('assets', 'extracted/legacy', 'extracted/rows', 'data/ability_converter',
                     'build/devui/icons', 'build/icons/donors', 'data/vision_cards',
                     'src/ffr-dt/bin/Release/net8.0'):
        tree(ROOT/relative, engine/relative, media_links=True)
    for source in (ROOT/'src').glob('*/bin/Release'):
        if source.parent.parent.name != 'ffr-dt': tree(source, engine/source.relative_to(ROOT))
    for relative in ('extracted/Mappings.usmap', 'extracted/CXXHeaderDump/mucha_enums.hpp',
                     'extracted/locres_en.json', 'extracted/utoc_filelist.tsv',
                     'build/devui/ffr_catalog.json', 'build/devui/ffbe_en.json',
                     'build/visions_mod/check/da/DA_UIUnitSsLayout.json',
                     'mods/EstherTsukiko/units.json', 'mods/EstherTsukiko/icon_layout.json'):
        copy(ROOT/relative, engine/relative)
    for name in ('ffr-effects.json', 'ffbe-effects.json', 'proposed-map.json', 'proposed-policies.json'):
        copy(ROOT/'docs/build16'/name, engine/'docs/build16'/name)
    baseline = read(catalog['baseline'])
    write(engine/'data/ffbe/catalog.json', {'units': baseline['units']})
    write(engine/'build/devui/ffbe_index.json', baseline['units'])
    write(engine/'build/devui/ffbe_index_cache.json', baseline)
    # These compact catalog sounds are shared with the released importer.
    with zipfile.ZipFile(ROOT/'build/build15/host/ffbe/common-1.0.0.13.zip') as z:
        for name in z.namelist():
            if not name.endswith('/'):
                refs.atomic(engine/'data/ffbe'/legacy.safe_name(name), z.read(name))
    tree(ROOT/'data/ffbe/ability_icons', engine/'data/ffbe/ability_icons', media_links=True)
    # Carry forward the accepted four-unit roster, with independent metadata.
    roster = read(engine/'mods/EstherTsukiko/units.json')
    for unit in roster:
        form = unit['ffbe']['id']
        source = ROOT/'data/ffbe/presentation'/(form+'.json')
        presentation = read(source)
        for entry in presentation['moves'].values():
            for visual in entry.get('visuals', []):
                tree(ROOT/visual['spec'], engine/visual['spec'], media_links=True)
            for bank in set(entry.get('audioBanks', {}).values()) | ({entry['audioBank']} if entry.get('audioBank') else set()):
                copy(ROOT/bank, engine/bank)
                for wave in read(ROOT/bank)['waves'].values():
                    relative = 'data/ffbe/audio/samples/'+wave['sha256']+'.hca'
                    copy(ROOT/relative, engine/relative, immutable=True)
        copy(source, engine/source.relative_to(ROOT))
        for folder in ('native_kits', 'lb_profiles'):
            profile = ROOT/'data/ffbe'/folder/(form+'.json')
            # The accepted Esther/Rain & Fina kits contain their authored LB
            # directly and predate the optional standalone profile cache.
            if folder == 'native_kits' or profile.is_file():
                copy(profile, engine/'data/ffbe'/folder/(form+'.json'))
        for fid in {form, unit['ffbe'].get('base', form)}:
            for folder in ('sprites',):
                if (ROOT/'data/ffbe'/folder/fid).is_dir(): tree(ROOT/'data/ffbe'/folder/fid, engine/'data/ffbe'/folder/fid, media_links=True)
        # Sprite directories and unit.json are sufficient; original raw tables
        # are already represented by the native kit's source snapshots.
        unit_dir = Path(unit['ffbe']['dir']).parent.parent
        tree(ROOT/unit_dir/'sprites', engine/unit_dir/'sprites', media_links=True)
        if (ROOT/unit_dir/'unit.json').is_file(): copy(ROOT/unit_dir/'unit.json', engine/unit_dir/'unit.json')
    for path in (ROOT/'data/ffbe/unit_records').glob('*.json'):
        copy(path, engine/'data/ffbe/unit_records'/path.name)
    refs.atomic(engine/'VERSION', b'1.0.0.15-beta.3\n')
    refs.atomic(engine/'.seeded', b'Independent roster, engine scripts and mutable metadata. Immutable inputs may be hard-linked.\n')
    print('Beta engine prepared', flush=True)


def stage_local_addons(out):
    """Inputs for retaining this PC's party, battle NPC and card addons."""
    engine = out/'engine'
    for name in ('DefaultEngine.ini', 'DefaultGameplayTags.ini'):
        relative = Path('extracted/pak/FFRS/Config')/name
        copy(ROOT/relative, engine/relative)
    tree(ROOT/'tools/vgmstream', engine/'tools/vgmstream')
    for name in ('raegen.webp', 'helena.webp'):
        copy(ROOT/'party'/name, engine/'party'/name, immutable=True)
    if (ROOT/'build/cooked-effect-cache').is_dir():
        tree(ROOT/'build/cooked-effect-cache', engine/'build/cooked-effect-cache', media_links=True)
    for form in ('100045807', '339001207'):
        for path in (ROOT/'build/ffbe_cpk/jp_live_dec').glob('*'+form+'*'):
            if path.is_file(): copy(path, engine/path.relative_to(ROOT), immutable=True)
    picker = Path('build/ffbe-asset-picker')
    copy(ROOT/picker/'manifest.json', engine/picker/'manifest.json')
    for form in ('3080410', '900000061', '900000004', '900000053', '900000054', '10000066', '1052510'):
        tree(ROOT/picker/'Enemy Sources'/form, engine/picker/'Enemy Sources'/form, media_links=True)
    # Music manifest source paths already point to the local prepared recordings.
    for folder in ('icons', 'idle'):
        source = ROOT/'build/build15/host/ffbe'/folder
        if source.is_dir(): tree(source, out/'home'/('idles' if folder == 'idle' else folder), media_links=True)
    # Refresh the small runtime patch if staging overlapped the last test fix.
    for name in ('unit_downloads.py', 'converted_units.py', 'ffbe_catalog.py', 'vision_import.py', 'server.py'):
        shutil.copy2(ROOT/'tools/devui'/name, engine/'tools/devui'/name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/studio-beta/20260928-b1')
    parser.add_argument('--catalog', type=Path, default=ROOT/'build/animation-recovery/converted-units.json')
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(ROOT/'build/studio-beta'): raise ValueError('Beta output must be in build/studio-beta')
    out.mkdir(parents=True, exist_ok=True)
    catalog = snapshot(out, args.catalog)
    stage_engine(out, catalog)
    stage_local_addons(out)
    write(out/'beta.json', {'schema': 'ffr-local-studio-beta-1', 'label': 'Animation Beta 1',
        'catalog': str((out/'catalog/converted-units.json').resolve()), 'summary': catalog['summary'],
        'engine': str((out/'engine').resolve()), 'sourceRoot': str(ROOT),
        'python': sys.executable, 'rosterSha256': sha(out/'engine/mods/EstherTsukiko/units.json')})
    print('Local beta staged at '+str(out), flush=True)


if __name__ == '__main__': main()
