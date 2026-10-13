"""Audit the focused trial's actual mounted mechanics and command membership."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
from verify_vision_install import export_json, sequence_path

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'build/effects-step3'

def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))

def main():
    rows = read(WORK / 'readback/Skill_DT_SkillData.json')['Rows']
    skills = {row['ID']: row for row in rows.values()}
    units = read(WORK / 'units.json')
    selected = {int(sid) for unit in units for sid in unit['skills']}
    selected.update(440000 + (unit['id'] - 13099) * 10 for unit in units)
    assert len(selected) == 14
    assert all(skills[sid]['Cost'] == 1 for sid in selected)
    assert all(not unit.get('convertedPassives') for unit in units)
    retired = read(WORK / 'focused-selection.json')['retiredSkills']
    assert len(retired) == 45
    for sid in retired:
        if sid not in skills:
            continue  # Some old source commands never had an installed row.
        assert not skills[sid]['belongCommandList'], sid
        assert skills[sid]['commandIdBelongDebuggingAllSkills'] == [-1, -1], sid
    lb = skills[444010]
    for key, expected in {'DamageType':'Physic', 'damageCalcType':'Physic',
                          'element':'Thunder', 'TargetType':'Group',
                          'defaultTargetRelation':'Enemies'}.items():
        assert lb[key].split('::')[-1] == expected, (key, lb[key])
    assert lb['hitCount'] == 30 and len(lb['hitDamageRatioList']) == 30
    assert abs(sum(lb['hitDamageRatioList']) - 1) < 1e-5
    assert not lb['effectBundleList']
    # FFR enumerates this registry during boot. A missing bank can crash before
    # a battle even when that move is not selected, so audit the whole registry.
    paks = ROOT / 'build/cast-camera-step1/game/FFRS/Content/Paks'
    sound_work = WORK / 'readback/sound'
    sound_work.mkdir(exist_ok=True)
    registry = export_json(paks, '/Game/Datatable/Asset/Sound/DT_SoundCueSheetAsset',
                           sound_work / 'registry.json')['Rows']
    ffbe = [r for r in registry.values() if r['CueSheetName'].startswith('FFBE_')]
    def check_bank(row):
        name = row['CueSheetName']
        bank = export_json(paks, sequence_path(row['pCueSheet']), sound_work / (name+'.json'))
        assert bank['Type'] == 'SoundAtomCueSheet', name
        assert bank['Properties']['CueSheetName'] == name, name
        assert bank['Properties']['CueInfos'], name
        return name
    with ThreadPoolExecutor(max_workers=3) as pool:
        registered = list(pool.map(check_bank, ffbe))
    result = {'selectedCommands':14, 'allCostsOneMP':True,
              'retiredCommandsHidden':45, 'noConvertedPassives':True,
              'registeredSoundBanksReadable':len(registered),
              'estherRaikiri':{'hits':30, 'damage':'physical', 'element':'Thunder',
                              'targets':'all enemies', 'extraEffects':0}}
    (WORK / 'focused-tables-verification.json').write_text(
        json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))

if __name__ == '__main__':
    main()
