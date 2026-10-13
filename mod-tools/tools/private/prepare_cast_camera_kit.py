"""Stage the four current visions' complete compatible kits for camera step one."""
from copy import deepcopy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui')]
import native_variants
import vision_import


def add_camera_tests(unit):
    """Expose remaining active families without claiming their mechanics work."""
    blast = next(deepcopy(s) for s in unit['skills'].values() if s.get('studio') == 'raegen_blast')
    for entry in native_variants.strongest(unit['ffbeLibrary'], 'abilities'):
        if entry['status'] == 'ready' or vision_import.imported(unit, entry['sourceKey']): continue
        base = 445000 + (unit['id']-13100)*100
        sid = next(i for i in range(base, base+100) if str(i) not in unit['skills'])
        recipe = deepcopy(blast)
        recipe.pop('studio', None)
        recipe.update(cameraTest=True, fullKitSequence=True, en=entry['name']+' [Camera Test]',
                      jp=f"{unit['jp']}_CameraTest_{sid}",
                      desc='Camera test only. Plays the casting sound and camera movement; no damage, recovery, or status effects.',
                      conversionSource={'root':entry['sourceKey']},
                      ffbe={'source':entry['sourceKey'], 'id':entry['id'], 'kind':entry['kind']},
                      unsupportedReasons=entry.get('issues', []))
        recipe['set'].update(Cost=0, magnification=0.0, breakDamageValue=0)
        unit['skills'][str(sid)] = recipe
        unit['awakening'][0].append(['ActiveSkill', sid])
    unit['cameraTestMissing'] = True


def prepare(units):
    result = deepcopy(units)
    blast = next(deepcopy(s) for u in units for s in u['skills'].values() if s.get('studio') == 'raegen_blast')
    report = []
    for unit in result:
        unit.update(fullKit=True, presentationStep='cast_camera')
        vision_import.hydrate(unit)
        selected = [e for group in ('abilities', 'bonuses')
                    for e in native_variants.strongest(unit['ffbeLibrary'], group) if e['status'] == 'ready']
        keys = {e['sourceKey'] for e in selected}
        # Preserve IDs for retained skills and archive only superseded variants.
        for group in ('skills', 'convertedPassives'):
            for sid, recipe in list(unit.get(group, {}).items()):
                if recipe.get('mechanics') == 'converted' and recipe.get('ffbe', {}).get('source') not in keys:
                    unit.setdefault('conversionArchive', []).append({'group': group, 'id': sid, 'entry': recipe,
                                                                    'reason': 'Full kit uses the strongest upgrade'})
                    vision_import.remove(unit, group, sid)
        for e in selected:
            vision_import.equip(unit, e['sourceKey'])
        if not any(s.get('studio') == 'raegen_blast' for s in unit['skills'].values()):
            base = 445000 + (unit['id']-13100)*100
            sid = next(s for s in range(base, base+100) if str(s) not in unit['skills'])
            recipe = deepcopy(blast)
            recipe['jp'] = unit['jp']+'_Raegen Blast'
            recipe['set'].update(belongCommandList=[unit['command']['id']], commandIdBelongDebuggingAllSkills=[unit['command']['id'], -1])
            unit['skills'][str(sid)] = recipe
        for recipe in unit['skills'].values():
            recipe['fullKitSequence'] = True
        # Native mastery detailData is a TArray; eight was the Studio editor's
        # convenience limit. Make this testing kit available at awakening one.
        retained = [g for tier in unit['awakening'] for g in tier if g[0] not in ('ActiveSkill', 'PassiveSkill')]
        unit['awakening'] = [[*retained, *[['ActiveSkill', int(s)] for s in unit['skills']],
                             *[['PassiveSkill', int(s)] for s in unit.get('convertedPassives', {})]], [], [], []]
        unit['nativeImports'] = sorted(keys)
        if unit.get('cameraTestMissing'): add_camera_tests(unit)
        report.append({'vision': unit['en'], 'activeIncludingRaegenBlast': len(unit['skills']),
                       'passives': len(unit.get('convertedPassives', {})), 'limitBursts': 1,
                       'held': [{'name': e['name'], 'kind': e['kind'], 'reasons': e.get('issues', [])}
                                for e in unit['ffbeLibrary'] if e['status'] != 'ready']})
    return result, report


if __name__ == '__main__':
    folder = ROOT/'build/cast-camera-step1'
    folder.mkdir(parents=True, exist_ok=True)
    spec = ROOT/'mods/EstherTsukiko/units.json'
    units, report = prepare(json.loads(spec.read_text(encoding='utf-8')))
    (folder/'units-before.json').write_bytes(spec.read_bytes())
    for name, data in (('units.json', units), ('kit-report.json', report)):
        (folder/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
