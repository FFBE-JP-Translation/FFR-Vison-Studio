"""Verify current native startup/test-map evidence, without claiming combat coverage."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/abilities'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build = json.loads((OUT/'native-bridge-validation.json').read_text())
    verified = []
    last_verified_run = None
    for directory in sorted((OUT/'native-battle-runs').iterdir()):
        log = directory/'collected-ue4ss/UE4SS.log'
        if not log.exists():
            continue
        lines = log.read_text(encoding='utf8', errors='replace').splitlines()
        if not any('"event":"native_attached"' in line for line in lines):
            continue
        run = json.loads((directory/'run.json').read_text())
        if run.get('debugCombatRequested'):
            continue  # Combat attempts have separate verification requirements.
        used = json.loads((directory/'Mods/FFRAvailabilityRuntime/manifest.json').read_text())
        if used['dllSha256'] != build['dllSha256']:
            continue
        for name in ('availability.lua', 'native_host.lua', 'main.lua', 'availability_probe.lua', 'availability_probe_main.lua'):
            path = directory/'Mods/FFRAvailabilityRuntime/Scripts'/name
            assert sha(path) == used['files']['Scripts/'+name], path
        assert sha(directory/'Mods/FFRAvailabilityRuntime/dlls/main.dll') == build['dllSha256']
        assert run['cleaned'] and not run['changedSaveFiles'] and not run['newSaveFiles']
        assert all(not Path(path).exists() for path in run['installedPaths'])
        assert sum('"event":"native_attached"' in line for line in lines) == 1
        assert sum('"event":"registered"' in line for line in lines) == 13
        guards = sum('"event":"native_guard"' in line for line in lines)
        test_map = any('object=World /Game/Debug/BattleTest/DBG_BattleTest.' in line for line in lines)
        if test_map:
            assert run['saveProtection'] == 'existing_sav_files_locked_against_write_and_delete'
            assert len(run['protectedSaveFiles']) == 5
        verified.append({'run': directory.name, 'runSha256': sha(directory/'run.json'),
                         'logSha256': sha(log), 'nativeAttached': True, 'reflectedRegistrations': 13,
                         'testMapLoaded': test_map, 'nativeGuardObservations': guards,
                         'originalSaveFilesUnchanged': True, 'temporaryInstallationRemoved': True})
        last_verified_run = run
    assert verified and any(run['testMapLoaded'] for run in verified)
    assert all(run['nativeGuardObservations'] == 0 for run in verified), 'Combat traces require a separate lifecycle/guard review.'
    # These SHA-1 values were read from Steam's unchanged remote-cache metadata
    # before the protected runs. No gameplay slot was loaded or imported.
    expected_slots = {'GameSaveData0.sav': '7e3e3c22479ca3457f4cfb34010e3c50172cf579',
                      'GameSaveData1.sav': 'de05dd12abe554363ea798cd7decc3d10beda54f',
                      'GameSaveData2.sav': 'fb82e77e35336b3ad989018b73cbc7fb37926dec'}
    slots = {Path(path).name: hashlib.sha1(Path(path).read_bytes()).hexdigest()
             for path in last_verified_run['beforeSaves'] if Path(path).name in expected_slots}
    assert slots == expected_slots
    report = {'status': 'passed', 'scope': 'native_startup_and_debug_map_only',
              'dllSha256': build['dllSha256'], 'runs': verified,
              'nativeBattle': 'no_combat_started', 'lifecycleBinding': 'unbound',
              'saveNamespaceOverride': 'ineffective_in_tested_build',
              'gameplaySlotSha1': slots,
              'initialStartupSideEffect': 'Before SQEX paths were located and protected, run 20260910_193417_309 rewrote OptionSaveData.sav and a Steam cache. Gameplay slots retained their earlier hashes/timestamps.',
              'compatibleRecordsReleased': 0}
    (OUT/'native-startup-validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
