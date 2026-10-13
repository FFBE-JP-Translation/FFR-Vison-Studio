"""Check the effective cooked tables after all retained addons are mounted."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import skill_icons
import ffbe_resonance


def export_json(paks, asset, output):
    # Mounted readback must not import the unrelated save editor or its codecs.
    output = Path(output); output.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, FFR_PAKS=str(Path(paks).resolve()))
    result = subprocess.run(['dotnet', str(ROOT/'src/ffr-export/bin/Release/net10.0/ffr-export.dll'),
                             'json', asset, str(output)], env=env, capture_output=True, text=True, encoding='utf-8')
    if result.returncode: raise RuntimeError(result.stdout+result.stderr)
    return json.loads(output.read_text(encoding='utf-8-sig'))


def sequence_path(reference):
    """Normalize the cooked soft reference without accepting empty references."""
    value = reference.get('AssetPathName') if isinstance(reference, dict) else reference
    if not isinstance(value, str) or not value.startswith('/Game/'):
        raise ValueError('missing or invalid LevelSequence reference')
    return value.split('.', 1)[0]


def verify_limit_burst(unit, visions, skills, sequences, read_sequence):
    recipe = unit.get('lb_custom')
    if not recipe:
        return None
    # Same ID contract as make_vision_mod.lb_id, independent of the UI loadout.
    sid = 440000 + (unit['id'] - 13099) * 10
    name = unit['en']
    if visions[unit['id']].get('finishBlowSkill') != sid:
        raise ValueError(f'{name}: installed finishBlowSkill does not reference custom LB {sid}')
    if sid not in skills:
        raise ValueError(f'{name}: installed custom LB skill {sid} is missing')
    if unit.get('testingMPCost') is not None and skills[sid]['Cost'] != unit['testingMPCost']:
        raise ValueError(f'{name}: limit-burst testing cost differs')
    authored = ffbe_resonance.uses_ffbe(unit, {**recipe, 'resonance': True})
    variants = [sid + offset for offset in (0, 1, 2) if sid + offset in sequences]
    if not variants or (authored and any(sid + offset not in sequences for offset in (1, 2))):
        raise ValueError(f'{name}: custom LB {sid} is missing its installed sequence variants')
    expected = f'/Game/Sequencer/Battle/Skill/{sid}/{sid+1}/SEQ_Battle_{sid+1}_Master'
    paths = set()
    for variant in variants:
        try:
            path = sequence_path(sequences[variant].get('LevelSequence'))
        except ValueError as error:
            raise ValueError(f'{name}: custom LB sequence {variant}: {error}') from error
        if authored and path != expected:
            raise ValueError(f'{name}: custom LB sequence {variant} points to another move: {path}')
        paths.add(path)
    for path in sorted(paths):
        try:
            data = read_sequence(path)
        except Exception as error:
            raise ValueError(f'{name}: custom LB sequence is not readable from installed packages: {path}') from error
        if not isinstance(data, dict) or data.get('Type') != 'LevelSequence':
            raise ValueError(f'{name}: custom LB reference is not a packaged LevelSequence: {path}')
    return {'id': sid, 'sequenceIds': variants, 'packagedSequences': sorted(paths)}


def verify(paks, units, work):
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    def table(rel):
        return export_json(paks, '/Game/Datatable/'+rel, work/(rel.replace('/','_')+'.json'))['Rows']
    skills = {r['ID']:r for r in table('Skill/DT_SkillData').values()}
    passives = {r['ID']:r for r in table('Skill/DT_PassiveSkillData').values()}
    effects = {r['ID'] for r in table('Skill/DT_SkillEffectData').values()}
    commands = {r['ID']:r for r in table('Skill/DT_CommandSkillData').values()}
    visions = {r['ID']:r for r in table('Item/Vision/DT_VisionItemData').values()}
    awakening = {(r['ID'],r['Level']):r for r in table('Item/Vision/DT_VisionAwakeningMasteryData').values()}
    sequences = {r['ID']:r for r in table('Asset/Skill/DT_SkillAsset').values()}
    owners = next(iter(table('Skill/Other/DT_SkillGeneralData').values()))['equipperActionVisionSkills']
    reactions = {r['ID']:r for r in table('Battle/Sequencer/DT_BtlHitEffectData').values()}
    icons = {r['Tag']['TagName']:r for r in table('UI/Skill/CDT_SkillIcon').values()}
    sequence_cache = {}
    def read_sequence(path):
        if path not in sequence_cache:
            output = work / ('LB_' + path.removeprefix('/Game/').replace('/', '_') + '.json')
            sequence_cache[path] = export_json(paks, path, output)
        return sequence_cache[path]
    result = []
    for unit in units:
        vid = unit['id']; command = unit['command']['id']; name = unit['en']
        if vid not in visions or commands.get(command,{}).get('unitIdToUseSkill') != vid:
            raise ValueError(f'{name}: another installed pack overrides the vision/command tables')
        limit_burst = verify_limit_burst(unit, visions, skills, sequences, read_sequence)
        for group, rows in (('skills',skills), ('convertedPassives',passives)):
            for sid, recipe in unit.get(group, {}).items():
                row = rows.get(int(sid))
                if row is None: raise ValueError(f'{name}: installed {group} table is missing {sid}')
                if group == 'skills':
                    if unit.get('testingMPCost') is not None and row['Cost'] != unit['testingMPCost']:
                        raise ValueError(f'{name}: active ability {sid} testing cost differs')
                    if command not in row['belongCommandList']:
                        raise ValueError(f'{name}: ability {sid} is missing its vision command')
                    explicit = row.get('playSequencerId', -1)
                    if explicit > 0:
                        if explicit not in sequences:
                            raise ValueError(f'{name}: ability {sid} has no explicit sequence {explicit}')
                    elif not any(int(sid)+offset in sequences for offset in (0,1,2)):
                        raise ValueError(f'{name}: ability {sid} has no installed sequence')
                    if recipe.get('mechanics') == 'converted':
                        if int(sid) in owners or row['mimicableUnitId'] != vid:
                            raise ValueError(f'{name}: ability {sid} is not assigned to the vision execution path')
                        if row['parameterVariationType'].endswith('Increase'):
                            reaction = reactions[int(sid)]
                            if any(reaction[field] != -1 for field in ('NormalEffectID','CriticalEffectID','WeaknessEffectID','PlayShakeID')):
                                raise ValueError(f'{name}: recovery {sid} still has damage feedback')
                for effect in row.get('effectBundleList', []):
                    if effect['effectId'] != -1 and effect['effectId'] not in effects:
                        raise ValueError(f'{name}: {sid} references missing effect {effect["effectId"]}')
                expected = recipe.get('set',{}).get('SkillIcon.TagName')
                actual = row.get('SkillIcon',{}).get('TagName')
                if expected and actual != expected: raise ValueError(f'{name}: icon override lost for {sid}')
                if actual and actual.startswith(skill_icons.PREFIX):
                    if actual not in icons: raise ValueError(f'{name}: missing installed icon {actual}')
        for tier, grants in enumerate(unit['awakening']):
            row = awakening.get((vid,tier), {})
            actual = [[d['parameterType'].split('::')[-1], *[v for v in d['params'] if v != -1]]
                      for d in row.get('detailData',[]) if not d['parameterType'].endswith('::None')]
            if actual != grants: raise ValueError(f'{name}: awakening tier {tier+1} differs from the Studio build')
            for grant in grants:
                rows = {'ActiveSkill':skills, 'PassiveSkill':passives}.get(grant[0])
                if rows is not None and grant[1] not in rows:
                    raise ValueError(f'{name}: awakening grants missing {grant[0]} {grant[1]}')
        result.append({'vision': name, 'abilities': len(unit.get('skills',{})),
                       'bonuses': len(unit.get('convertedPassives',{})), 'tiersVerified': 4,
                       **({'limitBurst': limit_burst} if limit_burst else {})})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--spec', type=Path, default=ROOT/'build/visions_mod/units-built.json')
    args = parser.parse_args()
    if not args.spec.is_file(): raise ValueError('Rebuild the mod in Studio to verify the installed loadout.')
    result = verify(args.game/'FFRS/Content/Paks', json.loads(args.spec.read_text(encoding='utf-8')), args.out.parent/'readback')
    args.out.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print('Installed vision abilities, limit bursts, bonuses, awakening tiers and icons verified: '+json.dumps(result))


if __name__ == '__main__': main()
