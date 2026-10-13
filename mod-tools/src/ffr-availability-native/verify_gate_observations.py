"""Reverify disposable native availability fixtures and reject mixed modes."""
import argparse
import json
import re
from pathlib import Path
from verify_combat_observation import OUT, read_json, sha, verify_artifacts
from verify_denial_observation import verify as verify_denial
from verify_limited_observation import verify as verify_limited
from verify_source_observation import verify as verify_source
from verify_cooldown_observation import verify as verify_cooldown
from verify_owned_observation import verify as verify_owned
from verify_life_observation import verify as verify_life
from verify_reset_observation import verify as verify_reset
from verify_loadout_observation import verify as verify_loadout


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('denial_run')
    parser.add_argument('limited_run')
    parser.add_argument('menu_run')
    parser.add_argument('--source-run')
    parser.add_argument('--cooldown-run')
    parser.add_argument('--owned-run')
    parser.add_argument('--vision-run')
    parser.add_argument('--life-run')
    parser.add_argument('--cancel-run')
    parser.add_argument('--reset-run')
    parser.add_argument('--loadout-run')
    args=parser.parse_args()
    if bool(args.source_run)!=bool(args.cooldown_run):parser.error('Provide both real-source runs together')
    if args.owned_run and not args.source_run:parser.error('Ownership verification requires both real-source runs')
    if args.vision_run and not args.owned_run:parser.error('Vision verification requires the ordinary ownership run')
    if args.life_run and not args.owned_run:parser.error('Life verification requires the ordinary ownership run')
    if args.cancel_run and not args.owned_run:parser.error('Cancellation verification requires the ordinary ownership run')
    if args.reset_run and not args.owned_run:parser.error('Battle reset verification requires the ordinary ownership run')
    if args.loadout_run and not args.vision_run:parser.error('Loadout verification requires the equipped Vision run')
    names=[args.denial_run,args.limited_run,args.menu_run]
    verifiers=[verify_denial,verify_limited,lambda directory,build:verify_limited(directory,build,menu=True)]
    if args.source_run:
        names.extend([args.source_run,args.cooldown_run]);verifiers.extend([verify_source,verify_cooldown])
    if args.owned_run:
        names.append(args.owned_run);verifiers.append(verify_owned)
    if args.vision_run:
        names.append(args.vision_run);verifiers.append(lambda directory,build:verify_owned(directory,build,vision=True))
    if args.life_run:
        names.append(args.life_run);verifiers.append(verify_life)
    if args.cancel_run:
        names.append(args.cancel_run);verifiers.append(lambda directory,build:verify_owned(directory,build,cancel=True))
    if args.reset_run:
        names.append(args.reset_run);verifiers.append(verify_reset)
    if args.loadout_run:
        names.append(args.loadout_run);verifiers.append(verify_loadout)
    assert len(set(names))==len(names) and all(re.fullmatch(r'\d{8}_\d{6}_\d{3}',n) for n in names)
    directories=[OUT/'native-battle-runs'/n for n in names]
    build=read_json(OUT/'native-bridge-validation.json')
    results=[verify(directory,build) for verify,directory in zip(verifiers,directories)]
    assert all(r['status']=='passed' for r in results)
    # A valid gate run cannot silently pass a different semantic verifier.
    rejected=0
    for index,directory in enumerate(directories):
        for other,verify in enumerate(verifiers):
            if index==other: continue
            try: verify(directory,build)
            except AssertionError: rejected+=1
            else: raise AssertionError('Fixture was accepted as the wrong mode')
    assert rejected==len(names)*(len(names)-1)
    runtime=Path(__file__).resolve().parents[2]/'tools/ability_converter/runtime'
    assert all(r['canonicalRuntimeSha256']==sha(runtime/'availability.lua')
               and r['canonicalHostSha256']==sha(runtime/'native_host.lua') for r in results[1:])
    here=Path(__file__).resolve().parent
    report={'status':'passed','scope':'ordinary_native_availability_fixtures',
        'nativeBridgeDllSha256':build['dllSha256'],
        'canonicalRuntimeSha256':sha(runtime/'availability.lua'),
        'canonicalHostSha256':sha(runtime/'native_host.lua'),
        'cases':results,'wrongModeRejections':rejected,
        'activeSkillFixtureIds':{d.name:read_json(d/'converted-ability-build.json')['skillId'] for d in directories},
        'explicitQueryBindingRuns':[d.name for d in directories
            if read_json(d/'fixture-build.json').get('queryBinding')=='explicit_active_skill_id'
            and read_json(d/'run.json').get('nativeMenuLimitedRequested')],
        'fixtureDlls':{d.name:read_json(d/'fixture-build.json')['dllSha256'] for d in directories},
        'verifierInputs':{p.name:sha(p) for p in [Path(__file__),here/'verify_denial_observation.py',
                            here/'verify_limited_observation.py',here/'verify_combat_observation.py',
                            here/'verify_source_observation.py',here/'verify_cooldown_observation.py',
                            here/'verify_owned_observation.py',
                            here/'verify_life_observation.py',here/'fixture/life_controls.py',
                            here/'verify_reset_observation.py',here/'verify_return_observation.py',
                            here/'verify_loadout_observation.py',
                            here/'fixture/source_availability.py']},
        'binding':{'ordinaryNativeBattleBegin':'verified_in_fixture',
            'ordinaryOwnerAndSelection':'verified_in_fixture','nativeExecutionDenial':'verified_in_fixture',
            'canonicalOneUseState':'verified_in_fixture','viewModelQuery':'verified_in_fixture',
            'generalLifecycleAndLoadout':'unbound','repeatMulticastDualWield':'unbound',
            'renderedMenu':'not_inspected','sourceAvailabilityPayload':'two_source_records_verified_in_fixture' if args.source_run else 'not_run',
            'sourceCooldownReuse':'owner_turns_1_and_6_verified' if args.source_run else 'not_run',
            'nativeLearnedOwnership':'two_ordinary_actors_verified' if args.owned_run else 'not_run',
            'independentNativeOwners':'two_separate_one_use_balances_verified' if args.owned_run else 'not_run',
            'equippedVisionGrants':'two_equipping_actors_verified' if args.vision_run else 'not_run',
            'ownerDeathAndRevival':'spent_use_and_owner_turns_preserved' if args.life_run else 'not_run',
            'commandSelectionCancellation':'two_owners_keep_turn_resources_and_unused_charge' if args.cancel_run else 'not_run',
            'battleEndAndReset':'two_native_escape_cycles_clear_owners_and_restore_uses' if args.reset_run else 'not_run',
            'lateGrantsAndRegrants':'two_native_equipment_grants_preserve_spent_uses' if args.loadout_run else 'not_run',
            'productionEnabled':False,'candidatePayloadsReleased':0}}
    (OUT/'native-availability-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':report['status'],'runs':names,'wrongModeRejections':rejected,
        'binding':report['binding']},indent=2))


if __name__=='__main__':main()
