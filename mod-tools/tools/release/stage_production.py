"""Retain published downloads and route unit archives onto provisioned sites.

The MCP uploader accepts archives larger than the old UI's approximate 80 MiB
limit. Keep the first N-2 unit sites stable and combine remaining archives on
the last two sites when more website provisioning is unavailable.
"""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--previous', required=True, help='Previous deployed version tag')
    parser.add_argument('--unit-sites', type=int, required=True)
    args = parser.parse_args()
    if args.unit_sites < 2:
        parser.error('At least two provisioned unit sites are required')
    root = Path(__file__).resolve().parents[2]
    host = args.build_dir / 'host'; deploy = args.build_dir / 'deploy'
    output = args.build_dir / 'production'; output.mkdir(parents=True, exist_ok=True)
    index = json.loads((host / 'ffbe/index.json').read_text(encoding='utf-8'))
    manifest = json.loads((host / 'manifest.json').read_text())
    version = manifest['version']
    groups = {n: [] for n in range(1, args.unit_sites+1)}
    # Read the builder's original groups, so repeating staging is idempotent.
    for archive in sorted(deploy.glob(f'units-*-{version}.zip')):
        original = int(archive.name.split('-')[1])
        target = original if original <= args.unit_sites-2 else args.unit_sites-1 + (original-(args.unit_sites-1)) % 2
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                if name.endswith('.ffr'):
                    groups[target].append(Path(name).stem)
    sizes = []
    for n, forms in groups.items():
        size = 0
        with zipfile.ZipFile(output / f'units-{n}-{version}.zip', 'w', zipfile.ZIP_STORED) as z:
            for form in sorted(forms):
                info = index['unitBundles'][form]
                for sub, extension, meta in [('units', 'ffr', info), ('idle', 'webp', info.get('idle'))]:
                    if meta is None:
                        continue
                    file = host / 'ffbe' / sub / f'{form}.{extension}'
                    if hashlib.sha256(file.read_bytes()).hexdigest() != meta['sha256']:
                        raise ValueError(f'Asset checksum mismatch: {file}')
                    z.write(file, 'root/' + file.name)
                    meta['url'] = f'https://units{n}.luminest.io/{file.name}'
                    size += file.stat().st_size
        sizes.append(round(size/1048576, 1))
    manifest['packs']['unitBundles'].update(shards=[f'https://units{n}.luminest.io/' for n in groups], shardMB=sizes)
    (host / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (host / 'ffbe/index.json').write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    for site in ['engine', 'ffbe']:
        previous = root / 'deployment' / f'{site}-site-{args.previous}.zip'
        current = deploy / f'{site}-site-{version}.zip'
        overrides = {'root/manifest.json': host/'manifest.json', 'root/ffbe/index.json': host/'ffbe/index.json', 'root/index.html': host/'index.html'} if site == 'ffbe' else {}
        with zipfile.ZipFile(previous) as old, zipfile.ZipFile(current) as new, zipfile.ZipFile(output / current.name, 'w', zipfile.ZIP_STORED) as out:
            for src in [old, new]:
                for name in src.namelist():
                    if src is old and name in new.namelist():
                        continue
                    out.writestr(name, overrides[name].read_bytes() if name in overrides else src.read(name))
        if site == 'ffbe':
            with zipfile.ZipFile(output / current.name) as new, zipfile.ZipFile(previous) as old, zipfile.ZipFile(output / f'ffbe-assets-stage-{version}.zip', 'w', zipfile.ZIP_STORED) as out:
                for name in new.namelist():
                    source = old if name in {'root/index.html', 'root/manifest.json', 'root/ffbe/index.json'} else new
                    # Keep old control-file timestamps during asset staging.
                    # Giving old and new manifests the same ZIP timestamp and
                    # size can leave the origin's static-file cache on the old body.
                    out.writestr(source.getinfo(name), source.read(name))
    print(json.dumps({'units': sum(map(len, groups.values())), 'unitSites': len(groups), 'siteMiB': sizes}))


if __name__ == '__main__':
    main()
