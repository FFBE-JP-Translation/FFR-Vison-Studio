"""Verify runtime query transport game cases against the retained fixture baseline."""
import json
from pathlib import Path
import runpy
from verify_combat_observation import ROOT,OUT,read_json as read,sha
from verify_gate_observations import (verify_denial,verify_limited,verify_source,verify_cooldown,
    verify_owned,verify_life,verify_reset,verify_loadout)
from verify_multicommand_observation import verify as multi
from verify_repeat_observation import verify as repeat
from verify_fire_expiry_observation import verify as expiry

HERE=Path(__file__).resolve().parent
_build=runpy.run_path(str(HERE/'build.py'))
fingerprint,imports=_build['fingerprint'],_build['imports']
MODES={'denial':verify_denial,'limited':verify_limited,'menu':lambda d,b:verify_limited(d,b,menu=True),
       'source':verify_source,'cooldown':verify_cooldown,'owned':verify_owned,
       'vision':lambda d,b:verify_owned(d,b,vision=True),'life':verify_life,
       'cancel':lambda d,b:verify_owned(d,b,cancel=True),'reset':verify_reset,'loadout':verify_loadout}

def matrix(runs,build):
    cases=[];rejected=0
    for mode,name in runs.items():
        assert mode in MODES
        directory=OUT/'native-battle-runs'/name
        case=MODES[mode](directory,build);assert case['status']=='passed';cases.append(case)
        for other in runs:
            if other==mode:continue
            try:MODES[other](directory,build)
            except AssertionError:rejected+=1
            else:raise AssertionError('Mismatched query transport case accepted')
    assert rejected==len(runs)*(len(runs)-1)
    return cases,rejected

def main():
    progress=read(OUT/'query-transport-progress.json')
    assert progress['status']=='passed' and set(progress['runs'])=={'menu','cooldown','loadout','reset'}
    build=read(OUT/'native-bridge-validation.json')
    assert build['status']=='passed' and build['inputs']==fingerprint()
    assert build['queryTransport']=='native_active_skill_set_v1'
    assert build['tests']['checks']==134 and build['tests']['guardChecks']==49 and build['tests']['queryChecks']==85
    binary=OUT/'native-bridge-build/Release/main.dll'
    assert sha(binary)==build['dllSha256'] and imports(binary)==build['ue4ssImports'] and len(build['ue4ssImports'])==28
    fixture=read(OUT/'native-fixture-build.json')
    assert fixture['queryBinding']=='production_runtime_active_skill_set'
    assert sha(Path(fixture['dll']))==fixture['dllSha256']
    for path,digest in fixture['inputs'].items():assert sha(ROOT/path)==digest,path
    assert 'FFRBattleFixtureBindQuery' not in (HERE/'fixture/mod.cpp').read_text()
    cases,rejected=matrix(progress['runs'],build)
    for case in cases:
        directory=OUT/'native-battle-runs'/case['run']
        assert read(directory/'fixture-build.json')==fixture
        assert read(directory/'run.json')['fixtureCompleted']
        ability=read(directory/'converted-ability-build.json')
        assert ability['skillId']==900010 and ability['nativeSkillCategory']=='ActiveSkill'
        for path,digest in ability['inputs'].items():assert sha(ROOT/path)==digest,path
        assert sha(directory/'Mods/FFRAvailabilityRuntime/Scripts/query_fixture.lua')==sha(HERE/'query_fixture.lua')
        assert case['canonicalRuntimeSha256']==sha(ROOT/'tools/ability_converter/runtime/availability.lua')
        assert case['canonicalHostSha256']==sha(ROOT/'tools/ability_converter/runtime/native_host.lua')
    # Historical cases must use their exact archived DLL, never be attributed
    # to this newer build. Recheck their semantics with current verifiers.
    baseline=OUT/'native-query-fixture-baseline-20260911'
    old_build=read(baseline/'native-bridge-validation.json')
    original=read(baseline/'native-query-id-final-checks.json')
    assert original['status']=='passed' and old_build['dllSha256']!=build['dllSha256']
    old_runs=read(baseline/'query-id-matrix-progress.json')['runs']
    baseline_cases,baseline_rejected=matrix({k:v for k,v in old_runs.items() if k!='expiry'},old_build)
    expired=expiry(OUT/'native-battle-runs'/old_runs['expiry'],old_build)
    assert expired['status']=='passed' and expired['clock']['elapsed']==5
    manual=read(baseline/'native-multicommand-suite-validation.json')
    for index,case in enumerate(manual['cases']):assert multi(OUT/'native-battle-runs'/case['run'],old_build,cancel=bool(index))['status']=='passed'
    repeats=read(baseline/'native-repeat-suite-validation.json')
    for case,mode in zip(repeats['cases'],({}, {'control':True}, {'suppressed':True})):
        assert repeat(OUT/'native-battle-runs'/case['run'],old_build,**mode)['status']=='passed'
    ordinary=read(OUT/'converted-ability-fixture.json')
    assert ordinary==read(OUT/'native-battle-runs'/old_runs['expiry']/'converted-ability-build.json')
    assert ordinary['case']=='fire' and not ordinary['nativeOwnedSource'] and not ordinary['nativeMultiCommand'] and not ordinary['nativeRepeatCommand']
    runpy.run_path(str(OUT/'verify_current.py'))
    catalog=read(OUT/'v1/report.json')
    files=[*HERE.glob('verify_*observation.py'),HERE/'verify_query_transport.py',HERE/'query_fixture.lua']
    report={'status':'passed','scope':'production_native_query_transport_with_fixture_lifecycle_resolvers',
        'nativeBridgeDllSha256':build['dllSha256'],'fixtureDllSha256':fixture['dllSha256'],
        'tests':build['tests'],'ue4ssImports':28,'cases':cases,'wrongModeRejections':rejected,
        'invalidNativeAttachCallsRejected':28,'duplicateNativeAttachCallsRejected':4,
        'baseline':{'directory':str(baseline),'buildSha256':old_build['dllSha256'],
            'nativeAvailabilityCasesRechecked':len(baseline_cases),'wrongModeRejections':baseline_rejected,
            'fireExpiryTurns':5,'manualCommandCasesRechecked':2,'repeatCasesRechecked':3,
            'originalFinalChecksSha256':sha(baseline/'native-query-id-final-checks.json')},
        'records':catalog['records'],'statuses':catalog['statuses'],
        'canonicalRuntimeSha256':sha(ROOT/'tools/ability_converter/runtime/availability.lua'),
        'canonicalHostSha256':sha(ROOT/'tools/ability_converter/runtime/native_host.lua'),
        'verifierInputs':{p.relative_to(ROOT).as_posix():sha(p) for p in files},
        'productionAvailabilityEnabled':False,'availabilityHoldsReleased':0,
        'nextWork':'Bind native command selection entries to created jobs and generalize lifecycle/owner resolution.'}
    (OUT/'native-query-transport-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({k:report[k] for k in ('status','scope','tests','wrongModeRejections','baseline','records','statuses','nextWork')},indent=2))

if __name__=='__main__':main()
