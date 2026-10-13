"""Attach prepared native kits to EVERY existing .ffr, without rebuilding sprites."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui'), str(ROOT/'tools/release')]
import reviewed_kits
from unit_assets import archive, encoded, write
import ffbe_catalog
import skill_icons


def build(source, out, install=False):
    source, out = Path(source), Path(out)
    index = json.loads((source/'ffbe/index.json').read_text(encoding='utf-8'))
    coverage = {'forms': 0, 'entries': 0, 'ready': 0, 'held': 0}
    with reviewed_kits.connect() as db:
        expected = {r[0] for r in db.execute('SELECT form FROM kits')}
        bundles = index['unitBundles']
        if set(bundles) != expected: raise ValueError('Unit archive coverage differs from the reviewed forms')
        for form in sorted(expected):
            native = reviewed_kits.export_bundle(form, db)
            content = encoded(native)
            with zipfile.ZipFile(source/'ffbe/units'/f'{form}.ffr') as z:
                files = {name: z.read(name) for name in z.namelist()}
            files[f'native_kits/{form}.json'] = content
            for entry in native['kit']['entries']:
                icon = ffbe_catalog.ability_icon_path(entry.get('icon'))
                if icon: files['ability_icons/'+Path(icon).name] = Path(icon).read_bytes()
                elif entry.get('icon'): raise ValueError(f"Missing icon for {form}: {entry['icon']}")
            files['ability_icons/aliases.json'] = (skill_icons.ICONS/'aliases.json').read_bytes()
            info = archive(out/'ffbe/units'/f'{form}.ffr', files)
            # The new staged index addresses this directory, never an old public
            # URL with a new checksum. Publishing assigns host routes separately.
            bundles[form].update(info, nativeKit=native['rulesSha256'], url=f'ffbe/units/{form}.ffr')
            if install: write(reviewed_kits.BUNDLES/f'{form}.json', content)
            with zipfile.ZipFile(out/'ffbe/units'/f'{form}.ffr') as z:
                if z.read(f'native_kits/{form}.json') != content: raise ValueError(f'Kit mismatch: {form}')
                if set(z.namelist()) != set(files): raise ValueError(f'Archive members changed: {form}')
            coverage['forms'] += 1
            for e in native['kit']['entries']:
                coverage['entries'] += 1
                coverage['ready' if e['status'] == 'ready' else 'held'] += 1
            if coverage['forms'] % 100 == 0: print(coverage, flush=True)
    write(out/'ffbe/index.json', encoded(index))
    write(out/'native-kit-coverage.json', encoded(coverage))
    print(json.dumps(coverage), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', default=str(ROOT/'build/build15/host'))
    parser.add_argument('--out', default=str(ROOT/'build/native-editor/host'))
    parser.add_argument('--install-local', action='store_true')
    args = parser.parse_args()
    build(args.source, args.out, args.install_local)
