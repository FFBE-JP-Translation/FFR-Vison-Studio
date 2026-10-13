"""Audit completed bulk exports and stage an opt-in local Studio catalog.

This reads ZIP directories and manifests, not every byte of the 800+ GiB library.
The importer verifies archive and payload checksums when a unit is selected.
It never resumes conversion, edits its reports, or publishes to the website.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ffbe_effect_bundle as effects


def audit_archive(result, delivery, base_info=None):
    form = effects.form_id(result['form'])
    path = delivery / (form + '.ffr')
    metadata = result.get('unitBundle') or base_info
    if path.stat().st_size != metadata['size']:
        raise ValueError('Archive size differs from completed conversion record')
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names = {effects.safe_name(i.filename): i for i in infos}
        if len(names) != len(infos) or len(infos) > effects.MAX_FILES:
            raise ValueError('Duplicate entries or file-count limit exceeded')
        if sum(i.file_size for i in infos) > effects.MAX_BYTES:
            raise ValueError('Archive exceeds unpacking limit')
        if metadata.get('effects'):
            manifest = json.loads(archive.read(f'presentation/effects/{form}.json'))
            if manifest['form'] != form or manifest['schema'] != effects.VERSION:
                raise ValueError('Effects manifest identity mismatch')
            for name, info in manifest['files'].items():
                if name not in names or names[name].file_size != info['size']:
                    raise ValueError('Missing or wrong-sized dependency: ' + name)
            raw = archive.read(f'presentation/{form}.json')
            if hashlib.sha256(raw).hexdigest() != manifest['files'][f'presentation/{form}.json']['sha256']:
                raise ValueError('Presentation checksum mismatch')
            presentation = json.loads(raw)
            if set(presentation['moves']) != set(result['preparedMoves']):
                raise ValueError('Prepared moves differ from the completed result')
        else:
            presentation = {'moves': {}}
    return {**metadata, 'localArchive': str(path.resolve()),
            'preparedMoveCount': len(presentation['moves']),
            'missingMoveCount': len(result.get('failedMoves', [])),
            'heldMoveCount': len(result.get('heldMoves', []))}


def prepare(delivery, baseline, out, fallback_index=None):
    report_path = delivery / 'catalog-conversion.json'
    report = json.loads(report_path.read_bytes())
    catalog = json.loads(baseline.read_bytes())
    owners = {str(f): u for u in catalog['units'] for f in u.get('packs', u.get('forms', []))}
    entries, rejected, inventory = {}, [], []
    results = {r['form']: r for r in report['results']}
    errors = {r['form']: r for r in report['errors']}
    def check(result):
        try:
            info = audit_archive(result, delivery, catalog['unitBundles'][result['form']])
            return result['form'], info, None
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as ex:
            return result['form'], None, str(ex)
    with ThreadPoolExecutor(max_workers=4) as pool:
        for i, (form, info, error) in enumerate(pool.map(check, report['results']), 1):
            if error:
                rejected.append({'form': form, 'error': error})
            else:
                entries[form] = {**catalog['unitBundles'][form], **info}
            if i % 100 == 0:
                print(f'Audited {i}/{len(results)} archives; {len(rejected)} rejected', flush=True)
    for form in report['requestedForms']:
        info = entries.get(form)
        error = errors.get(form, {}).get('error', '')
        if form in results and not info:
            error = next(r['error'] for r in rejected if r['form'] == form)
        inventory.append({'form': form, 'unit': owners.get(form, {}).get('name', ''),
            'status': ('exported with gaps' if info['missingMoveCount'] else 'exported') if info else ('failed' if error else 'unfinished'),
            'preparedMoves': info['preparedMoveCount'] if info else 0,
            'missingMoves': info['missingMoveCount'] if info else '',
            'heldMoves': info['heldMoveCount'] if info else '', 'error': error})
    failure_kinds = Counter('All selected moves failed' if '0 prepared' in e['error'] else e['error'] for e in report['errors'])
    move_errors = Counter(m['error'].split(':')[0] for r in report['results'] for m in r.get('failedMoves', []))
    summary = {k: v for k, v in report['summary'].items() if k != 'units'}
    summary['conversionReportStatus'] = summary.pop('status', None)
    summary['status'] = 'audited_catalog_snapshot'
    summary.update(auditedExports=len(entries), animatedForms=sum(bool(e['preparedMoveCount']) for e in entries.values()),
        rejectedArchives=rejected,
        exportsWithoutMoveFailures=sum(not e['missingMoveCount'] for e in entries.values()),
        exportsWithMoveFailures=sum(bool(e['missingMoveCount']) for e in entries.values()),
        unfinishedForms=len(report['requestedForms']) - len(results) - len(errors),
        failureReasons=dict(failure_kinds), moveFailureReasons=dict(move_errors),
        exportedBytes=sum(e['size'] for e in entries.values()),
        lastHeartbeat=report.get('runtime', {}).get('heartbeatUtc'),
        verification='ZIP directories, file sizes and presentation manifests checked; full checksums checked on import')
    out.mkdir(parents=True, exist_ok=True)
    # Keep the production shard URLs for forms whose conversion did not finish.
    # The converter's source index uses staging-relative URLs, not public ones.
    fallback = json.loads((fallback_index or baseline).read_bytes())
    fallback_path = out / 'hosted-baseline.json'
    fallback_path.write_text(json.dumps(fallback, ensure_ascii=False), encoding='utf-8')
    manifest = {'schema': 'ffr-local-converted-units-1', 'baseline': str(fallback_path.resolve()),
        'delivery': str(delivery.resolve()), 'reportSha256': hashlib.sha256(report_path.read_bytes()).hexdigest(),
        'summary': summary, 'unitBundles': entries}
    out.mkdir(parents=True, exist_ok=True)
    (out / 'converted-units.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    (out / 'assessment.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    with (out / 'unit-coverage.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(inventory[0]))
        writer.writeheader(); writer.writerows(inventory)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--delivery', type=Path, default=ROOT / 'build/ffbe-all-animations/delivery')
    parser.add_argument('--baseline', type=Path, default=ROOT / 'build/native-editor/host/ffbe/index.json')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/converted-moves-test')
    parser.add_argument('--fallback-index', type=Path, default=ROOT / 'build/devui/ffbe_index_cache.json')
    args = parser.parse_args()
    prepare(args.delivery, args.baseline, args.out, args.fallback_index)
