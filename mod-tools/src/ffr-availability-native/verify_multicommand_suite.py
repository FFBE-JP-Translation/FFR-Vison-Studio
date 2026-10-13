"""Recheck multi-command diagnostics and reject cross-mode availability traces."""
import argparse
import json
import re
from pathlib import Path
from verify_combat_observation import OUT, ROOT, read_json, sha
from verify_multicommand_observation import verify
from verify_denial_observation import verify as denial
from verify_limited_observation import verify as limited
from verify_source_observation import verify as source
from verify_cooldown_observation import verify as cooldown
from verify_owned_observation import verify as owned
from verify_life_observation import verify as life
from verify_reset_observation import verify as reset
from verify_loadout_observation import verify as loadout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('normal_run'); parser.add_argument('cancel_run'); args = parser.parse_args()
    assert args.normal_run != args.cancel_run
    assert all(re.fullmatch(r'\d{8}_\d{6}_\d{3}', name) for name in (args.normal_run, args.cancel_run))
    build = read_json(OUT/'native-bridge-validation.json')
    cases = [verify(OUT/'native-battle-runs'/name, build, cancel=cancel)
             for name, cancel in ((args.normal_run, False), (args.cancel_run, True))]
    runtime = ROOT/'tools/ability_converter/runtime'
    here = Path(__file__).resolve().parent
    assert all(case['canonicalRuntimeSha256'] == sha(runtime/'availability.lua')
               and case['canonicalHostSha256'] == sha(runtime/'native_host.lua')
               and case['driverSha256'] == sha(here/'multicommand_driver.lua') for case in cases)
    previous = read_json(OUT/'native-availability-validation.json')
    assert previous['status'] == 'passed' and len(previous['cases']) == 11
    assert previous['canonicalRuntimeSha256'] == cases[0]['canonicalRuntimeSha256']
    verifiers = [denial, limited, lambda d,b: limited(d,b,menu=True), source, cooldown, owned,
                 lambda d,b: owned(d,b,vision=True), life, lambda d,b: owned(d,b,cancel=True), reset, loadout]
    rejected = 0
    def reject(callback):
        nonlocal rejected
        try: callback()
        except AssertionError: rejected += 1
        else: raise AssertionError('Another fixture mode was accepted')
    for index, case in enumerate(cases):
        directory = OUT/'native-battle-runs'/case['run']
        reject(lambda: verify(directory, build, cancel=not bool(index)))
        for check in verifiers: reject(lambda: check(directory, build))
    for case, check in zip(previous['cases'], verifiers):
        directory = OUT/'native-battle-runs'/case['run']
        assert check(directory, build)['status'] == 'passed'
        for cancel in (False, True): reject(lambda: verify(directory, build, cancel=cancel))
    assert rejected == 46
    failed = ['20260911_015151_920', '20260911_015424_299']
    incomplete = ['20260911_015558_719']
    for name in failed+incomplete: reject(lambda: verify(OUT/'native-battle-runs'/name, build))
    report = {'status': 'passed', 'scope': 'native_multicommand_selection_and_cancellation_diagnostics',
              'cases': cases, 'wrongModeRejections': 46, 'failedAttemptsRejected': failed,
              'insufficientTraceRejected': incomplete,
              'nativeBridgeDllSha256': build['dllSha256'],
              'canonicalRuntimeSha256': cases[0]['canonicalRuntimeSha256'],
              'canonicalHostSha256': cases[0]['canonicalHostSha256'],
              'availabilityRegressionSha256': sha(OUT/'native-availability-validation.json'),
              'verifierInputs': {p.relative_to(ROOT).as_posix(): sha(p) for p in
                  [Path(__file__), here/'verify_multicommand_observation.py', here/'verify_fire_observation.py',
                   here/'verify_combat_observation.py', here/'multicommand_driver.lua', here/'fixture/build_ability.py']},
              'binding': {'nativeSelectionBatch': 'wrapper_and_two_distinct_child_jobs_verified',
                          'selectionMpReservation': 'refunded_on_cancellation_and_final_dispatch',
                          'availabilitySelectionReservations': 'unbound', 'automaticRepeatAndDualWield': 'unbound',
                          'productionEnabled': False, 'availabilityHoldsReleased': 0}}
    (OUT/'native-multicommand-suite-validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'status': 'passed', 'runs': [c['run'] for c in cases], 'wrongModeRejections': 46,
                      'rejectedFailedOrIncompleteTraces': 3, 'binding': report['binding']}, indent=2))


if __name__ == '__main__': main()
