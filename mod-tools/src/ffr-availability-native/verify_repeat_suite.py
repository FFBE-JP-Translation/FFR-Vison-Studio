"""Compare automatic repeat, absent-passive and native exclusion controls."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import re
from verify_combat_observation import OUT, ROOT, read_json, sha, verify_artifacts
from verify_repeat_observation import verify
from verify_multicommand_observation import verify as multi


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('repeat_run');parser.add_argument('control_run');parser.add_argument('suppressed_run');args=parser.parse_args()
    names=[args.repeat_run,args.control_run,args.suppressed_run]
    assert len(set(names))==3 and all(re.fullmatch(r'\d{8}_\d{6}_\d{3}',n) for n in names)
    modes=[{}, {'control':True}, {'suppressed':True}]
    build=read_json(OUT/'native-bridge-validation.json')
    cases=[verify(OUT/'native-battle-runs'/name,build,**mode) for name,mode in zip(names,modes)]
    here=Path(__file__).resolve().parent
    runtime=ROOT/'tools/ability_converter/runtime'
    fixtures=[read_json(OUT/'native-battle-runs'/name/'converted-ability-build.json') for name in names]
    for case,fixture in zip(cases,fixtures):
        assert case['driverSha256']==sha(here/'repeat_driver.lua')
        assert case['canonicalRuntimeSha256']==sha(runtime/'availability.lua')
        assert case['canonicalHostSha256']==sha(runtime/'native_host.lua')
        for path,expected in fixture['inputs'].items(): assert sha(ROOT/path)==expected,path
    assert len({c['sourceProfileSha256'] for c in cases})==1
    assert all(f['expectedRow']==fixtures[0]['expectedRow'] and f['plan']==fixtures[0]['plan'] for f in fixtures)
    assert all(f['nativeRepeatPassive']==fixtures[0]['nativeRepeatPassive'] for f in fixtures)
    assert [c['nativeCasts'] for c in cases]==[2,1,1] and [c['totalMpSpent'] for c in cases]==[8,4,4]
    assert [c['passiveActive'] for c in cases]==[True,False,True]
    assert [c['nativeRepeatExcluded'] for c in cases]==[False,False,True]
    # The controls change only passive learning and the one native exclusion.
    patches=[]
    for fixture in fixtures:
        patch=read_json(Path(fixture['directory'])/'patch.json')
        tables=deepcopy(patch['tables'])
        for table in tables:
            if table['asset'].endswith('DT_UnitLevelParameterRain'):
                for row in table['set']:
                    row['set']['AddSkills']=[s for s in row['set']['AddSkills'] if s!=90000]
            if table['asset'].endswith('DT_SkillGeneralData'):
                for row in table['set']:
                    row['set'].pop('nonRepeatSkillsIds',None)
                table['set']=[row for row in table['set'] if row['set']]
        patches.append(tables)
    assert patches[0]==patches[1]==patches[2]
    rejected=0
    def reject(callback):
        nonlocal rejected
        try: callback()
        except AssertionError: rejected+=1
        else: raise AssertionError('Incorrect repeat mode or incomplete trace was accepted')
    ordinary_modes=[{}, {'denial':True}, {'limited':True}, {'limited':True,'menu':True},
                    {'limited':True,'menu':True,'source':True},
                    {'limited':True,'menu':True,'source':True,'owned':True},
                    {'multi':True}, {'multi':True,'multi_cancel':True}]
    for i,name in enumerate(names):
        directory=OUT/'native-battle-runs'/name
        for j,mode in enumerate(modes):
            if i!=j: reject(lambda:verify(directory,build,**mode))
        for mode in ordinary_modes: reject(lambda:verify_artifacts(directory,build,**mode))
    previous=read_json(OUT/'native-availability-validation.json')
    assert previous['status']=='passed' and len(previous['cases'])==11
    for case in previous['cases']:
        for mode in modes: reject(lambda:verify(OUT/'native-battle-runs'/case['run'],build,**mode))
    manual=read_json(OUT/'native-multicommand-suite-validation.json')
    for i,case in enumerate(manual['cases']):
        assert multi(OUT/'native-battle-runs'/case['run'],build,cancel=bool(i))['status']=='passed'
        for mode in modes: reject(lambda:verify(OUT/'native-battle-runs'/case['run'],build,**mode))
    assert rejected==69
    failed=['20260911_024729_424','20260911_024905_416','20260911_025354_041','20260911_025443_857','20260911_025521_336']
    for name in failed: reject(lambda:verify(OUT/'native-battle-runs'/name,build))
    report={'status':'passed','scope':'native_repeat_cost_and_per_skill_exclusion','cases':cases,
            'wrongModeRejections':69,'failedAttemptsRejected':failed,
            'nativeBridgeDllSha256':build['dllSha256'],
            'canonicalRuntimeSha256':cases[0]['canonicalRuntimeSha256'],'canonicalHostSha256':cases[0]['canonicalHostSha256'],
            'verifierInputs':{p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),here/'verify_repeat_observation.py',
                here/'verify_combat_observation.py',here/'verify_fire_observation.py',here/'repeat_driver.lua',
                here/'fixture/build_ability.py',here/'observe.ps1']},
            'manualComparison':{'reportSha256':sha(OUT/'native-multicommand-suite-validation.json'),
                'explicitWActionChildren':2,'manualNativeCasts':2,'manualMpSpent':8},
            'binding':{'automaticRepeat':'one_selection_two_distinct_self_rooted_jobs',
                'repeatStackEvent':'absent_in_tested_RepeatAction_path',
                'nativeRepeatExclusion':'nonRepeatSkillsIds_suppresses_repeat_with_passive_active',
                'productionEnabled':False,'availabilityHoldsReleased':0},
            'limitations':['The tested effect is native RepeatAction 1012, not FFBE dual wield.',
                'The suppression test does not yet validate manual W Action with the same exclusion.',
                'Production selection, repeat identity and general lifecycle bindings remain unbound.']}
    (OUT/'native-repeat-suite-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'passed','runs':names,'casts':[2,1,1],'mpSpent':[8,4,4],
                      'wrongModeRejections':69,'failedAttemptsRejected':len(failed),'binding':report['binding']},indent=2))


if __name__=='__main__': main()
