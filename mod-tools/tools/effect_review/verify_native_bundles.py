"""Exhaustive editor import audit from the per-vision bundled conversions."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui')]
import reviewed_kits
import vision_import
from ability_converter import commands


def main():
    start = time.monotonic()
    index = json.loads((ROOT/'build/native-editor/host/ffbe/index.json').read_text(encoding='utf-8'))
    counts = Counter(); failures = []
    with patch.object(reviewed_kits, 'PATH', ROOT/'build/native-editor/unavailable.sqlite'), patch.object(commands, 'profile', side_effect=AssertionError('Real-time conversion during import')):
        for form in sorted(index['unitBundles']):
            try:
                unit = {'id':13500,'key':'audit','jp':'Audit','ffbe':{'id':form},'skills':{},'awakening':[[],[],[],[]],'synchro':[]}
                vision_import.hydrate(unit)
                assert not unit['skills'] and not any(unit['awakening']), 'Opening a vision assigned ordinary moves'
                vision_import.import_native(unit, 'abilities'); vision_import.import_native(unit, 'bonuses')
                expected = {e['sourceKey'] for e in unit['ffbeLibrary'] if e['kind'] != 'LB'}
                assert set(unit['nativeImports']) == expected, 'Bulk import lost a native entry'
                assert len(unit['skills']) <= 10 and all(len(t) <= 8 for t in unit['awakening'])
                for tier in unit['awakening']:
                    for kind, sid in tier:
                        assert str(sid) in unit['skills' if kind == 'ActiveSkill' else 'convertedPassives']
                before = deepcopy(unit)
                vision_import.import_native(unit, 'abilities'); vision_import.import_native(unit, 'bonuses')
                assert before == unit, 'Repeated import changed the kit'
                counts['forms'] += 1
                counts['memberships'] += len(unit['ffbeLibrary'])
                counts['importedOrdinaryEntries'] += len(expected)
                counts['assignedCommands'] += len(unit['skills'])
                counts['assignedBonuses'] += len(unit.get('convertedPassives', {}))
                counts['resonances'] += bool(unit.get('lb_custom'))
            except Exception as ex: failures.append({'form':form,'error':str(ex)})
            if (counts['forms'] + len(failures)) % 250 == 0: print(dict(counts), f'failures={len(failures)}', flush=True)
    result = {'counts':dict(counts),'failures':failures,'seconds':round(time.monotonic()-start), 'databaseAvailable':False, 'realTimeConversionAllowed':False}
    (ROOT/'build/native-editor/import-validation.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result),flush=True)
    if failures: raise SystemExit(1)


if __name__ == '__main__': main()
