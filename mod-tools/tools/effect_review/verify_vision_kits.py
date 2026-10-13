"""Replay every portable source and assemble every form's testing loadout."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys
import time
import zlib

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(ROOT/'tools/devui')]
from ability_converter import commands, reviewed
import reviewed_kits
import vision_import


def main():
    start = time.monotonic(); counts = Counter(); failures = []
    db = sqlite3.connect(reviewed_kits.PATH)
    for key, payload in db.execute('SELECT source_key,payload FROM profiles WHERE supported=1'):
        p = json.loads(zlib.decompress(payload))
        try:
            rebuilt = commands.from_spec({'effectPolicy': reviewed.VERSION, 'conversionSource': p['snapshot']})
            if not rebuilt['supported']: raise ValueError('; '.join(rebuilt['issues']))
            # JSON object keys are strings on disk (race maps use integer
            # keys in memory); compare the actual serialized representation.
            if json.loads(json.dumps(rebuilt['conversion']['native'])) != p['conversion']['native']:
                raise ValueError('Portable snapshot changes the native mechanics')
            counts['portableProfiles'] += 1
        except Exception as ex: failures.append({'source': key, 'issue': str(ex)})
    print(f"Replayed {counts['portableProfiles']:,} portable profiles; {len(failures)} failures", flush=True)
    for form, payload in db.execute('SELECT form,payload FROM kits'):
        k = json.loads(zlib.decompress(payload))
        unit = {'key': 'audit', 'id': 13500, 'jp': 'Audit', 'ffbe': {'id': form}, 'skills': {}, 'awakening': [[], [], [], []], 'synchro': []}
        try:
            vision_import.hydrate(unit)
            assert len(unit['ffbeLibrary']) == len(k['entries'])
            assert len(unit['skills']) <= 10
            assert all(len(t) <= 8 for t in unit['awakening'])
            vision_import.import_native(unit, 'abilities')
            vision_import.import_native(unit, 'bonuses')
            initial = deepcopy(unit)
            vision_import.hydrate(unit)
            assert unit == initial, 'Import is not idempotent'
            for tier in unit['awakening']:
                for kind, sid in tier:
                    assert str(sid) in unit['skills' if kind == 'ActiveSkill' else 'convertedPassives']
            counts['forms'] += 1
            counts['equippedCommands'] += len(unit['skills'])
            counts['equippedPassives'] += len(unit.get('convertedPassives', {}))
            counts['reviewedResonances'] += unit.get('lb_custom', {}).get('effectPolicy') == reviewed.VERSION
        except Exception as ex: failures.append({'form': form, 'issue': str(ex)})
        if counts['forms'] % 500 == 0: print(f"Assembled {counts['forms']:,} forms", flush=True)
    db.close()
    audit = {'counts': dict(counts), 'failures': failures, 'elapsedSeconds': round(time.monotonic()-start)}
    path = ROOT/'data/ability_converter/vision-kits-validation.json'
    path.write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(audit, indent=2)[:5000], flush=True)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
