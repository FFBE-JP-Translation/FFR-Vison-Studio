"""Verify bounded stock-combat traces; this does not certify converted abilities."""
from collections import Counter
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "build/abilities"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def diagnostic_skill_id(directory):
    """Read the pinned fixture identity; old runs retain their historical ID."""
    path = directory/'converted-ability-build.json'
    assert path.is_file(), 'A converted fixture manifest is required'
    fixture = read_json(path)
    skill = fixture['skillId']
    assert type(skill) is int and skill in (1900010,900010)
    if skill == 900010:
        assert fixture['nativeSkillCategory'] == 'ActiveSkill'
    else:
        assert 'nativeSkillCategory' not in fixture
    return skill


def verify_artifacts(directory, build, *, denial=False, limited=False, menu=False, source=False, owned=False, vision=False, life=False, cancel=False, reset=False, return_test=False, loadout=False, multi=False, multi_cancel=False, repeat=False, repeat_control=False, repeat_suppressed=False):
    run = read_json(directory / "run.json")
    assert run["started"] and run["cleaned"] and run["debugCombatRequested"]
    assert not (denial and limited)
    assert not menu or limited
    assert not source or (limited and menu)
    assert not owned or source
    assert not vision or owned
    assert not life or (owned and not vision)
    assert not cancel or (owned and not vision and not life)
    assert not reset or (owned and not vision and not life and not cancel)
    assert not return_test or (reset or not (limited or denial))
    assert not loadout or (vision and not (life or cancel or reset or return_test))
    assert not multi or not (limited or denial or return_test)
    assert not multi_cancel or multi
    assert not repeat or not (limited or denial or return_test or multi)
    assert not repeat_control or repeat
    assert not repeat_suppressed or (repeat and not repeat_control)
    mode='native_cancel_source_fixture' if cancel else 'native_life_source_fixture' if life else 'native_vision_source_fixture' if vision else 'native_owned_source_fixture' if owned else 'native_source_availability_fixture' if source else 'native_limited_menu_fixture' if menu else 'native_limited_fixture' if limited else 'native_denial_fixture' if denial else 'observation_only'
    if return_test:mode='native_battle_return_diagnostic'
    if reset:mode='native_reset_source_fixture'
    if loadout:mode='native_loadout_source_fixture'
    if multi:mode='native_multicommand_diagnostic'
    if multi_cancel:mode='native_multicommand_cancel_diagnostic'
    if repeat:mode='native_repeat_diagnostic'
    if repeat_control:mode='native_repeat_control_diagnostic'
    if repeat_suppressed:mode='native_repeat_suppressed_diagnostic'
    assert run["nativeBridgeEnabled"] and run["mode"] == mode
    assert bool(run.get('nativeDenialRequested'))==denial
    assert bool(run.get('nativeLimitedRequested'))==limited
    assert bool(run.get('nativeMenuLimitedRequested'))==menu
    assert bool(run.get('nativeSourceAvailabilityRequested'))==source
    assert bool(run.get('nativeOwnedSourceRequested'))==owned
    assert bool(run.get('nativeVisionSourceRequested'))==vision
    assert bool(run.get('nativeLifeSourceRequested'))==life
    assert bool(run.get('nativeCancelSourceRequested'))==cancel
    assert bool(run.get('nativeResetSourceRequested'))==reset
    assert bool(run.get('nativeLoadoutSourceRequested'))==loadout
    assert bool(run.get('nativeMultiCommandRequested'))==multi
    assert bool(run.get('nativeMultiCancelRequested'))==multi_cancel
    assert bool(run.get('nativeRepeatRequested'))==repeat
    assert bool(run.get('nativeRepeatControlRequested'))==repeat_control
    assert bool(run.get('nativeRepeatSuppressedRequested'))==repeat_suppressed
    assert bool(run.get('battleReturnRequested'))==(reset or return_test)
    assert not run.get("error") and not run["changedSaveFiles"] and not run["newSaveFiles"]
    assert not run["createdSaveFiles"], "This stock encounter should not create a save."
    assert run["saveProtection"] == "existing_sav_files_locked_against_write_and_delete"
    assert len(run["protectedSaveFiles"]) == 5
    assert run["exitCode"] == 0 or ((run.get("timeoutTerminated") or run.get("fixtureTerminated")) and run["exitCode"] == -1)
    assert not list((directory / "user").rglob("CrashContext.runtime-xml")), "Game crashed."
    assert all(not Path(path).exists() for path in run["installedPaths"])
    for path, expected in run["beforeSaves"].items():
        assert sha(Path(path)) == expected.lower(), path
    for path, expected in run["inputHashes"].items():
        # The runner archives its script before launch; source may later change.
        file = directory / "observe.ps1" if Path(path).name == "observe.ps1" else Path(path)
        assert sha(file) == expected.lower(), file
    staged = directory / "Mods/FFRAvailabilityRuntime"
    manifest = read_json(staged / "manifest.json")
    assert manifest["dllSha256"] == build["dllSha256"]
    for name, expected in manifest["files"].items():
        if (denial or limited) and name=='Scripts/main.lua':
            original=(staged/'Scripts/main.observer.lua').read_bytes()
            assert hashlib.sha256(original).hexdigest()==expected
            assert original.count(b'{mode="observe",reason=reason}')==1
            derived=original.replace(b'{mode="observe",reason=reason}',b'{mode="enforce_fixture",reason=reason}')
            module='owned_fixture' if owned else 'limited_fixture' if limited else 'denial_fixture'
            prefix=b'FFRAvailabilityFixtureMenu = true\n' if menu else b''
            if vision:prefix=b'FFRAvailabilityFixtureVision = true\n'+prefix
            if life:prefix=b'FFRAvailabilityFixtureLife = true\n'+prefix
            if reset:prefix=b'FFRAvailabilityFixtureReset = true\n'+prefix
            if loadout:prefix=b'FFRAvailabilityFixtureLoadout = true\n'+prefix
            if source:prefix=b'FFRAvailabilityFixtureSource = true\n'+prefix
            assert (staged/name).read_bytes()==prefix+f"require('{module}')\n".encode()+derived
        else:
            assert sha(staged / name) == expected, name
    fixture = read_json(directory / "fixture-build.json")
    assert fixture["status"] == "built" and fixture["scope"] == "temporary_test_fixture_only"
    assert sha(directory / "Mods/FFRBattleFixture/dlls/main.dll") == fixture["dllSha256"]
    if run.get('nativeSelectionJobsRequested'):
        assert multi or repeat
        selection=read_json(directory/'selection-build.json')
        assert selection['status']=='built' and selection['scope']=='selection_entry_job_observation_only'
        assert selection['binding']=='observation_only'
        assert sha(directory/'Mods/FFRSelectionProbe/dlls/main.dll')==selection['dllSha256']
        selection_log=(directory/'collected-ue4ss/UE4SS.log').read_text(encoding='utf8',errors='replace')
        assert selection_log.count('[FFRSelectionProbe] attached read_only=true')==1
        assert 'selection_observation_failed' not in selection_log and 'selection_observation_capacity' not in selection_log
    if fixture.get('queryBinding') in ('explicit_active_skill_id','production_runtime_active_skill_set'):
        log=(directory/'collected-ue4ss/UE4SS.log').read_text(encoding='utf8',errors='replace')
        bound=re.findall(r'\[FFRQueryFixture\] attached skill=(\d+) invalid_rejected=7 duplicate_rejected=true',log)
        assert bound == ([str(diagnostic_skill_id(directory))] if menu else [])
        if menu:
            skill=diagnostic_skill_id(directory)
            assert log.count(f'[FFRQueryFixture] attached skill={skill} invalid_rejected=7 duplicate_rejected=true')==1
            assert re.findall(r'\[FFRQueryFixture\] rejected ordinal=(\d+)',log)==list('1234567')
            if fixture['queryBinding']=='production_runtime_active_skill_set':
                assert manifest['queryTransport']=='native_active_skill_set_v1'
                assert log.count(f'[FFRQueryFixture] attached skill={skill} invalid_rejected=7 duplicate_rejected=true transport=runtime')==1
    game_bin = Path(run["installedPaths"][0]).parent
    package_dir = game_bin.parents[1] / "Content/Paks/~mods"
    for name, expected in run["existingGamePackages"].items():
        assert sha(package_dir / name) == expected.lower(), name
    return run


def verify(directory, build):
    run = verify_artifacts(directory, build)
    assert not run.get("convertedAbilityRequested"), "Converted abilities require separate semantic verification."
    fixture = read_json(directory / "fixture-build.json")

    log_path = directory / "collected-ue4ss/UE4SS.log"
    log = log_path.read_text(encoding="utf8", errors="replace")
    events = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r"\[FFRAvailability(Native|Probe)\] (\{.*\})$", line)
        if match:
            event = json.loads(match[2])
            event["logLine"] = number
            events.append(event)
    counts = Counter(event["event"] for event in events)
    assert counts["native_attached"] == 1 and counts["registered"] == 13
    for failure in ("native_attach_failed", "registration_failed", "read_failed", "trace_capacity", "query_capacity", "native_observation_capacity"):
        assert counts[failure] == 0, failure
    assert "combat_driver_failed=" not in log and "turn_owner_failed=" not in log
    assert "native_stage_prepared=5" in log and "unit_count=2" in log
    units = [tuple(map(int, values)) for values in re.findall(r"unit actor=(\d+) id=(\d+) hp=(\d+) actions=(\d+)", log)]
    assert {unit[1] for unit in units} == {1001, 5}
    assert "bundle_level=" in log and "loaded=true visible=true" in log
    assert log.count("stock_command_requested ") == 1
    assert log.count("stock_command_handler_returned") == 1
    guards = [event for event in events if event["event"] == "native_guard"]
    player = [event for event in guards if event["skillId"] == 401010]
    assert len(player) == 1 and player[0]["nativeAllowed"] is True
    assert player[0]["actor"] > 0 and player[0]["job"] == player[0]["rootJob"]
    assert player[0]["actionCount"] == 1 and player[0]["targetCount"] == 1
    command = [event for event in events if event["event"] == "command_decide"]
    assert len(command) == 1 and command[0]["actions"] == [
        {"item": False, "skillId": 401010, "targets": [1], "uniqueId": 0}]
    assert command[0]["logLine"] < player[0]["logLine"]
    starts = [event for event in events if event["event"] in ("skill_begin_message", "skill_begin_libra") and event["skillId"] == 401010]
    assert starts and all(event["logLine"] > player[0]["logLine"] for event in starts)
    assert all(event["uniqueId"] == 0 and event["targets"] == [1] and
               event["owner"]["actorAddress"] == player[0]["actor"] and
               event["owner"]["sourceActorAddress"] == player[0]["actor"] and
               event["owner"]["unitId"] == 1001 for event in starts)
    turns = [event for event in events if event["event"] == "turn_begin"]
    assert any(event["uniqueId"] == 0 and event["logLine"] < player[0]["logLine"] for event in turns)
    assert any(event["uniqueId"] == 0 and event["logLine"] > player[0]["logLine"] for event in turns)
    if run.get("fixtureTerminated"):
        assert run.get("fixtureCompleted") and log.count("stock_observation_complete") == 1
    last_units = {unit[1]: unit for unit in units}
    assert last_units[1001][2] > 0 and last_units[1001][3] >= 2
    assert 0 < last_units[5][2] < 200, "Expected surviving Goblin with attack damage."
    owner_turns = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r"turn_owner unique=(\d+) actor=(\d+) parameter=(\d+) unit=(\d+) turn=(\d+)", line)
        if match:
            values = map(int, match.groups())
            owner_turns.append(dict(zip(("uniqueId", "actor", "parameter", "unitId", "counter"), values), logLine=number))
    if owner_turns:
        assert [event["uniqueId"] for event in owner_turns] == [event["uniqueId"] for event in turns]
        for unique, unit_id in ((0, 1001), (1, 5)):
            observed = [event for event in owner_turns if event["uniqueId"] == unique]
            assert len(observed) >= 2
            assert [event["counter"] for event in observed] == list(range(len(observed)))
            assert {event["unitId"] for event in observed} == {unit_id}
            assert {event["actor"] for event in observed} == {last_units[unit_id][0]}
            assert len({event["parameter"] for event in observed}) == 1
        for guard in guards:
            current = [event for event in owner_turns if event["logLine"] < guard["logLine"]][-1]
            assert current["actor"] == guard["actor"], "Guard actor does not match the observed current turn."
    return {
        "run": directory.name, "runSha256": sha(directory / "run.json"),
        "logSha256": sha(log_path), "fixtureDllSha256": fixture["dllSha256"],
        "eventCounts": dict(sorted(counts.items())), "nativeGuards": guards,
        "turnOwners": [event["uniqueId"] for event in turns],
        "playerCommand": command[0], "playerSkillStartNotifications": len(starts),
        "playerSkillStartPayloads": len({event["payload"] for event in starts}),
        "playerActorMatchesNativeGuard": True,
        "ownerTurnCountersAtPreHook": owner_turns,
        "ownerTurnCounterObservation": "zero_based_before_increment" if owner_turns else "not_collected",
        "originalSaveFilesUnchanged": True, "existingGamePackagesUnchanged": True,
        "temporaryInstallationRemoved": True,
        "lastUnitState": {str(key): {"actor": value[0], "hp": value[2], "turnOpportunities": value[3]} for key, value in last_units.items()},
        "endReason": "fixture_complete" if run.get("fixtureTerminated") else "bounded_timeout" if run.get("timeoutTerminated") else "normal_exit",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+", help="Completed run IDs under native-battle-runs")
    args = parser.parse_args()
    build = read_json(OUT / "native-bridge-validation.json")
    runs = []
    for name in args.runs:
        assert re.fullmatch(r"\d{8}_\d{6}_\d{3}", name), "Expected a run ID."
        runs.append(verify(OUT / "native-battle-runs" / name, build))
    report = {
        "status": "passed", "scope": "stock_single_command_native_guard_observation",
        "dllSha256": build["dllSha256"], "runs": runs,
        "nativeBattle": "stock_command_observed", "lifecycleBinding": "unbound",
        "convertedAbilityCombatValidation": "not_run", "compatibleRecordsReleased": 0,
        "limitations": [
            "Transient debug world with existing installed content packages retained.",
            "No converted ability was installed or executed by these traces.",
            "One stock player selection does not establish repeat, multicast or dual-wield identity.",
            "Reflected battle-begin and availability-query callbacks may be absent despite native combat.",
            "Battle-end return from this fixture is not validated; an earlier win crashed after its end event.",
        ],
    }
    (OUT / "native-combat-validation.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
