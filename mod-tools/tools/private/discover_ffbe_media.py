"""Resolve discovery dependencies across existing regional exports, without importing them."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/devui'), str(ROOT / 'tools/ffbe_effects')]
from ffbe_effects import ibmb, catalog
from ffbe_effects.acb_cues import cues

OUT = ROOT / 'docs/discovery/ffbe-step3'
GL = Path('T:/ffbe_patch/gl_extracted/common_lang/sd')
JP = ROOT / 'build/ffbe_cpk/effects_dec'


def sha(p):
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def main():
    audit = json.loads((OUT / 'source-audit.json').read_text(encoding='utf-8'))
    index = defaultdict(list)
    for folder in (GL / 'battleEffect', GL / 'effectResource'):
        for p in folder.rglob('*'):
            if p.is_file(): index[p.name.lower()].append(p)
    def locate(name):
        choices = index[name.lower()]
        return choices[0] if len(choices) == 1 else None
    effects = []
    for source in audit['effects']:
        name = source['file']; gl = locate(name)
        p = gl or (JP / name)
        row = {'file': name, 'path': str(p), 'exists': p.exists(), 'region': 'GL export' if gl else 'JP/shared fallback',
               'candidatePaths': [str(x) for x in index[name.lower()]]}
        if not p.exists(): effects.append(row); continue
        row['sha256'] = sha(p)
        if gl and (JP / name).is_file(): row['matchesCentralBytes'] = sha(JP / name) == row['sha256']
        try:
            e = ibmb.parse(str(p)); resources = []
            for resource, ext in [(x, '.png') for x in e.textures] + [(x, '.m3r') for x in e.models]:
                n = resource if Path(resource).suffix else resource + ext
                chosen = locate(n); location = chosen or JP / n
                resources.append({'file': n, 'path': str(location), 'exists': location.is_file(),
                                  'region': 'GL export' if chosen else 'JP/shared fallback',
                                  **({'sha256': sha(location)} if location.is_file() else {})})
            row.update(durationFrames=e.duration, emitters=len(e.emitters()), models=e.models,
                       textures=e.textures, resources=resources)
        except Exception as ex: row['parseError'] = str(ex)
        effects.append(row)
    audio = []
    routing = []
    required = {'SE': {100}, 'System': {40, 45}}
    for unit in audit['units']:
        for move in unit['moves']:
            sources = [p['catalog'] for p in move.get('provenance', [])]
            if move.get('rawSourceCatalog'): sources.append(move['rawSourceCatalog'])
            for source in sources:
                for group in source.get('groups', []):
                    for sound in (group.get('group') or {}).get('sounds', []):
                        flag = int(sound.get('extra', ['1'])[0])
                        bank = 'SE' if flag == 1 else 'System'
                        cid = int(sound['seId']); required[bank].add(cid)
                        routing.append({'vision': unit['name'], 'move': move['name'], 'sourceKey': move['sourceKey'],
                                        'groupId': group['groupId'], 'frame': group['frame'] + sound['frame'],
                                        'bank': bank, 'rawBankFlag': flag, 'cueId': cid})
    for bank in (ROOT / 'data/ffbe/audio/SE.acb', ROOT / 'data/ffbe/audio/System.acb',
                 Path('S:/FFBE JP Data Export/public/SE.acb'), Path('S:/FFBE JP Data Export/public/System.acb')):
        if bank.is_file():
            c = cues(str(bank))
            needed = required[bank.stem]
            audio.append({'path': str(bank), 'sha256': sha(bank), 'cueCount': len(c),
                          'requiredIds': sorted(needed), 'missingRequiredIds': sorted(needed-set(c)),
                          'common': {str(i): c.get(i) for i in (40, 45, 100, 647)}})
    original_sprite_roots = [Path('S:/FFBE JP Data Export/BFFrameAnimator-master/Units/401006807')]
    original_sprite_roots += list((GL / 'unit').glob('*/401006807'))
    sprite_files = list((GL / 'unit').rglob('*401006807*'))
    sprite_files += [p for root in original_sprite_roots if root.exists() for p in root.iterdir() if p.is_file()]
    report = {'scope': 'Locations and hashes only; no source assets copied or converted',
              'effects': effects, 'audioBanks': audio, 'sourceSoundRoutes': routing,
              'soundRoutingEvidence': {'binary': 'FFBEWW 9.1.0.9101 arm64 libgame.so',
                                      'function': 'GameUtils::playSEWithGroupID at 0x19f4e7c',
                                      'selector': '0x19f4fec..0x19f5058: absent/1 is common SE; other values select System',
                                      'limit': 'Local available banks are JP exports; cue existence does not establish regional audible parity'},
              'originalEstherSprites': [{'path': str(p), 'sha256': sha(p)} for p in sorted(set(sprite_files)) if p.is_file()]}
    report['summary'] = {
        'effects': len(effects), 'resolved': sum(e['exists'] for e in effects),
        'glExport': sum(e['region'] == 'GL export' for e in effects),
        'centralByteDifferences': [e['file'] for e in effects if e.get('matchesCentralBytes') is False],
        'parseErrors': [{'file': e['file'], 'error': e['parseError']} for e in effects if 'parseError' in e],
        'missingResources': sorted({r['file'] for e in effects for r in e.get('resources', []) if not r['exists']}),
        'originalEstherSpriteFiles': len(report['originalEstherSprites'])}
    (OUT / 'media-audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report['summary'], indent=2))


if __name__ == '__main__': main()
