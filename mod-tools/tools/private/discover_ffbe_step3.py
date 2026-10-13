"""Read-only FFBE source audit; writes discovery records, never game assets."""
from collections import Counter
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/devui'), str(ROOT / 'tools/ffbe_effects')]
from ffbe_effects import catalog, ibmb
from ffbe_effects.prepare_vision import timeline

OUT = ROOT / 'docs/discovery/ffbe-step3'
SOURCES = ROOT / 'build/ffbe_cpk/effects_dec'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def write(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


@lru_cache(None)
def inspect_effect(filename):
    p = SOURCES / filename
    if not p.is_file():
        return {'file': filename, 'exists': False}
    result = {'file': filename, 'path': str(p), 'exists': True, 'sha256': sha(p)}
    try:
        e = ibmb.parse(str(p))
        resources = []
        for name, suffix in [(n, '.png') for n in e.textures] + [(n, '.m3r') for n in e.models]:
            resource = SOURCES / (name if Path(name).suffix else name + suffix)
            resources.append({'name': resource.name, 'exists': resource.is_file(),
                              **({'sha256': sha(resource)} if resource.is_file() else {})})
        result.update(durationFrames=e.duration, emitters=len(e.emitters()), textures=e.textures,
                      models=e.models, resources=resources,
                      unbounded=e.duration >= 0x7fffffff,
                      objectTypes=dict(Counter(str(c.type) for c in e.chunks)))
    except Exception as ex:
        result['parseError'] = str(ex)
    return result


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    installed = read(ROOT / 'mods/EstherTsukiko/units.json')
    forms = [('401006807', 'Esther'), ('401007407', 'A.I. Katy'),
             ('340000107', 'Sora (KHIII)'), ('100032707', 'Rain & Fina')]
    report = {'scope': 'Discovery only: no conversion, package build, roster change or installation',
              'selectedReplacement': {'name': 'Original Esther', 'form': '401006807',
                                      'base': '401006805', 'hostSlotPlanned': 13500}, 'units': []}
    all_files = set()
    for form, name in forms:
        kit_path = ROOT / 'data/ffbe/native_kits' / (form + '.json')
        kit = read(kit_path)
        entries = {e['sourceKey']: e for e in kit['kit']['entries']}
        manifest_path = ROOT / 'data/ffbe/presentation' / (form + '.json')
        manifest = read(manifest_path) if manifest_path.exists() else {'moves': {}}
        excluded = []
        if form == '401006807':
            selected = []
            for key, entry in entries.items():
                ancestry = []; e = entry
                while e:
                    ancestry.append(e['kind']); e = entries.get(e.get('parent'))
                if 'PASSIVE' in ancestry:
                    excluded.append({'sourceKey': key, 'name': entry['name'], 'reason': 'passive ancestry'})
                elif not entry.get('parent'):
                    selected.append((key, entry['name'], kit['profiles'].get(key, {}).get('snapshot')))
        else:
            unit = next(u for u in installed if u['ffbe']['id'] == form)
            selected = [(r.get('conversionSource', {}).get('root') or r.get('ffbe', {}).get('source'),
                         r['en'], r.get('conversionSource')) for r in [*unit['skills'].values(), unit['lb_custom']]]
        moves = []
        for key, move_name, snapshot in selected:
            row = {'name': move_name, 'sourceKey': key,
                   'preparedEntryExists': key in manifest['moves'] if key else False}
            if not snapshot or not snapshot.get('records'):
                snapshot = kit['profiles'].get(key, {}).get('snapshot')
            if not snapshot:
                row['status'] = 'native FFR command' if move_name == 'Raegen Blast' else 'no conversion snapshot'
                moves.append(row); continue
            profile = kit['profiles'].get(key, {})
            row['kitStatus'] = entries.get(key, {}).get('status', 'not in kit index')
            row['mechanicsSupported'] = profile.get('supported')
            row['snapshotSha256'] = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()
            try:
                t = timeline(snapshot, include_screen=True, source_matched=True)
                row.update(supported=t['supported'], motionType=t['motionType'], sourceMoveType=t.get('sourceMoveType'),
                           sounds=t['sounds'], spawns=t['spawns'], issues=t['issues'],
                           visualCoverage=t['visualCoverage'], sourcePlacement=t['sourcePlacement'],
                           provenance=t['provenance'])
                all_files.update(v['file'] for v in t['spawns'] if v.get('file'))
                # Include files held by placement/unsupported mechanics in the dependency inventory too.
                for record in t['provenance']:
                    for g in record['catalog']['groups']:
                        all_files.update(e['file'] for e in (g.get('group') or {}).get('effects', []) if e.get('file'))
                row['status'] = 'source-resolved' if t['visualCoverage']['complete'] else 'source-with-gaps'
            except Exception as ex:
                row.update(status='source-audit-error', error=str(ex))
                if row['kitStatus'] == 'held':
                    # Discovery still resolves art for moves whose gameplay cannot yet be authored.
                    # Do not remove their gameplay gates just to obtain a presentation inventory.
                    region, kind, ident, *_ = key.split('/')
                    raw = catalog.skill_effects(kind, ident, source=region)
                    row.update(status='mechanics-held/raw-art-inspected',
                               presentationAdapterError=str(ex), error=None,
                               rawSourceCatalog=raw, sounds=[])
                    for g in (raw or {}).get('groups', []):
                        group = g.get('group') or {}
                        all_files.update(e['file'] for e in group.get('effects', []) if e.get('file'))
                        row['sounds'] += [{'frame': g['frame'] + s['frame'], 'cueId': int(s['seId'])}
                                          for s in group.get('sounds', [])]
            if row['preparedEntryExists']:
                prepared = manifest['moves'][key]
                row['preparedSummary'] = {'status': prepared.get('status'), 'visualProjects': len(prepared.get('visuals', [])),
                                          'sounds': len(prepared.get('sounds', [])), 'issues': prepared.get('issues', []),
                                          'audioBank': prepared.get('audioBank')}
            moves.append(row)
        report['units'].append({'form': form, 'name': name, 'kitSha256': sha(kit_path), 'moves': moves,
                                'excluded': excluded, 'preparedManifestExists': manifest_path.exists()})

    common = []
    for gid in map(str, range(9000030, 9000130, 10)):
        group = catalog.group_detail(gid, source='GL_2024')
        common.append({'groupId': gid, 'data': group})
        all_files.update(e['file'] for e in group['effects'] if e.get('file'))
    report['castingGroups'] = common
    report['lbOpeningCandidates'] = [r for r in catalog.group_rows('GL_2024').values()
                                     if any(t in r.get('h9UFW3qt', '').lower() for t in ('limitopen', 'lb_charge'))
                                     or any(len(s) > 1 and s[1] == '647' for s in catalog.parse_frames(r.get('1fVZ3rKd', '')))
                                     or str(r.get('qIy86WvJ')) in ('9000190', '9000200', '9000210')]
    report['effects'] = [inspect_effect(f) for f in sorted(all_files)]
    report['sourceTables'] = list(catalog._table_identities.values())
    write('source-audit.json', report)
    summary = {'units': [], 'uniqueEffects': len(report['effects']),
               'missingEffects': [e['file'] for e in report['effects'] if not e['exists']],
               'parseErrors': [{'file': e['file'], 'error': e['parseError']} for e in report['effects'] if 'parseError' in e],
               'missingResources': sorted({r['name'] for e in report['effects'] for r in e.get('resources', []) if not r['exists']})}
    for unit in report['units']:
        summary['units'].append({'name': unit['name'], 'form': unit['form'], 'moves': len(unit['moves']),
                                 'preparedEntries': sum(m['preparedEntryExists'] for m in unit['moves']),
                                 'statuses': dict(Counter(m['status'] for m in unit['moves'])),
                                 'movesWithVisualGaps': [m['name'] for m in unit['moves'] if m.get('visualCoverage', {}).get('complete') is False],
                                 'heldMechanics': [m['name'] for m in unit['moves'] if m.get('kitStatus') == 'held']})
    write('summary.json', summary)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
