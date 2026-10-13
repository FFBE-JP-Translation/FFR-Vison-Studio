"""Read cooked command channels, actor bindings, casting and recovery visuals."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import ffbe_resonance as sequence
import make_vision_mod as builder
from ability_converter import commands


def verify(units, assets, work):
    work = Path(work); work.mkdir(parents=True, exist_ok=True)
    def dump(path, verb):
        output = work/(path.stem+'-'+verb+'.json')
        result = subprocess.run([*builder.FFRDT, verb, str(path), str(output), '--usmap',builder.USMAP],
                                capture_output=True, text=True, encoding='utf-8',errors='replace')
        if result.returncode: raise RuntimeError(result.stdout+result.stderr)
        return json.loads(output.read_text(encoding='utf-8-sig'))
    def rows(rel):
        return dump(Path(assets)/('FFRS/Content/Datatable/'+rel+'.uasset'),'rows')['rows']
    skills = {r['ID']:r for r in rows('Skill/DT_SkillData').values()}
    reactions = {r['ID']:r for r in rows('Battle/Sequencer/DT_BtlHitEffectData').values()}
    general_path = Path(assets)/'FFRS/Content/Datatable/Skill/Other/DT_SkillGeneralData.uasset'
    if not general_path.is_file():
        general_path = Path(builder.LEGACY)/general_path.relative_to(assets)
    owners = next(iter(dump(general_path,'rows')['rows'].values()))['equipperActionVisionSkills']
    results = []
    for unit in units:
        for sid,recipe in unit.get('skills',{}).items():
            if recipe.get('mechanics') != 'converted': continue
            sid = int(sid); row = skills[sid]; label = f"{unit['en']}: {recipe['en']}"
            assert sid not in owners, label+' is assigned to the equipping party member'
            assert row['mimicableUnitId'] == unit['id'], label+' has the wrong vision identity'
            path = Path(assets)/f'FFRS/Content/Sequencer/Battle/Skill/{sid}/{sid+1}/SEQ_Battle_{sid+1}_Master.uasset'
            asset, functions = dump(path,'tojson'), dump(path,'seqdump')
            functions = {int(k.split(':')[0]):v for k,v in functions.items()}
            events = []
            for export in asset['Exports']:
                for prop in export.get('Data',[]):
                    if prop['Name'] != 'EventChannel': continue
                    times = sequence.child(prop['Value'],'KeyTimes')
                    values = sequence.child(prop['Value'],'KeyValues')
                    for time,value in zip(times,values):
                        tick = time
                        while not isinstance(tick,(int,float)):
                            tick = tick[0] if isinstance(tick,list) else tick['Value']
                        fid = sequence.child(value['Value'],'Ptrs','Function')
                        events.append((tick,functions[fid]))
            events.sort(key=lambda event:event[0])
            animations = [(tick,event) for tick,event in events if event['EventType'] == 'UnitPlayAnimByName']
            assert animations and all(e.get('Unit_PlayAnimByName_IsOnlyVisionUnit') for _,e in animations), label
            assert all(not e.get('Unit_PlayAnimByName_SkipDualcast') for _,e in animations), label
            motions = [(t,e['Unit_PlayAnimByName_AnimationName']) for t,e in animations]
            main = next((t,m) for t,m in motions if m in ('attack_A','magic_attack'))
            if main[1] == 'magic_attack':
                assert any(t < main[0] and m in ('magic_idle', 'command') for t,m in motions), label+' has no preparation phase'
            assert motions[-1][1] == 'idle', label+' does not finish its motion'
            profile = commands.from_spec(recipe)
            hits = [(t,e) for t,e in events if e['EventType'] == 'OtherReaction']
            assert [t for t,_ in hits] == [main[0]+frame*400 for frame in profile['timeline']['hitFrames']], label
            moving = profile['timeline']['moveType'] == 1
            if moving:
                assert any(t < main[0] and m == 'step_front' for t,m in motions), label
                assert any(m == 'step_back' for _,m in motions), label
                assert any(e['EventType'] == 'UnitMoveToTarget' and e.get('Unit_MoveToTarget_IsVisionUnit') for _,e in events), label
                move = next(e for _,e in events if e['EventType'] == 'UnitMoveToTarget')
                assert move['Unit_MoveToTarget_AddLocation'] == commands.APPROACH_OFFSET, label+' has the wrong approach position'
                assert not move.get('Unit_MoveToTarget_IsDisableOffset'), label+' disables native target clearance'
                assert any(e['EventType'] == 'UnitMoveToDefaultLocation' and e.get('Unit_MoveToDefaultLocation_IsVision') for _,e in events), label
            recovery = row['parameterVariationType'] == 'Increase' and row['skillEffectType'] == 'DamageAndRecovery'
            if recovery:
                reaction = reactions[sid]
                assert all(reaction[name] == -1 for name in ('NormalEffectID','CriticalEffectID','WeaknessEffectID','MissEffectID','AdditionalEffectID','DeathEffectID','PlayShakeID')), label+' retains damage effects'
                assert not reaction['IsAdditionalEffect'], label
                assert all(not e.get('Otber_Reaction_bReturnIdleMotion') and not e.get('Otber_Reaction_bChangeColor') for _,e in hits), label
                if row['parameterType'] == 'HitPoint':
                    assert any(e['EventType'] == 'EffectSpawnNiagaraAtTarget' and e.get('Effect_SpawnTarget_bAllTarget')
                               and 'NS_EF_SKL210030_Root' in str(e.get('Effect_SpawnTarget_NiagaraData'))
                               for _,e in events), label+' has no healing effect on its selected targets'
            results.append({'vision':unit['en'],'ability':recipe['en'],'id':sid,
                            'actor':'vision','motions':[m for _,m in motions],
                            'sourceHitTimesVerified':len(hits),'recoveryVisuals':recovery})
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec',type=Path,default=ROOT/'build/visions_mod/units-built.json')
    parser.add_argument('--assets',type=Path,default=Path(builder.OUT))
    parser.add_argument('--out',type=Path,required=True)
    args = parser.parse_args()
    result = verify(json.loads(args.spec.read_text(encoding='utf-8')),args.assets,args.out.parent/'command-readback')
    args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(f'Cooked vision execution, casting, source hit times and recovery visuals verified for {len(result)} commands.')
