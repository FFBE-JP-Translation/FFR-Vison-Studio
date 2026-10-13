"""Verify the experimental converted Fire cast without releasing its phase hold."""
from verify_combat_observation import diagnostic_skill_id
from collections import Counter
import argparse
import json
import re
from verify_combat_observation import OUT, read_json, sha, verify_artifacts


def verify_fire_artifacts(directory, build, weakness_phase="after", expiry=False, *, multi=False, multi_cancel=False, repeat=False, repeat_control=False, repeat_suppressed=False):
    skill_id = diagnostic_skill_id(directory)
    run = verify_artifacts(directory, build, multi=multi, multi_cancel=multi_cancel, repeat=repeat, repeat_control=repeat_control, repeat_suppressed=repeat_suppressed)
    assert run["convertedAbilityRequested"] and run.get("fixtureCompleted") and run.get("fixtureTerminated")
    assert bool(run.get("convertedExpiryRequested")) == expiry
    fixture = read_json(directory / "converted-ability-build.json")
    profile = read_json(directory / "converted-profile.json")
    assert fixture["status"] == "built" and fixture["scope"] == "temporary_converted_fire_fixture"
    assert fixture["source"] == "JP_2024/magic/20010" and fixture["skillId"] == skill_id
    assert bool(fixture.get('nativeMultiCommand')) == multi
    assert bool(fixture.get('nativeRepeatCommand')) == repeat
    assert bool(fixture.get('nativeRepeatControl')) == repeat_control
    assert bool(fixture.get('nativeRepeatSuppressed')) == repeat_suppressed
    if skill_id == 900010:
        log = (directory/'collected-ue4ss/UE4SS.log').read_text(encoding='utf8',errors='replace')
        assert log.count('loaded_category id=900010 category=2') == 1
    assert sha(directory / "converted-profile.json") == fixture["profileSha256"]
    assert profile["conversion"]["validation"]["tableCompatible"]
    assert profile["snapshot"]["root"] == fixture["source"]
    if profile['supported']:
        assert not profile['issues'] and fixture['experiment']['productionSupported']
        assert fixture['experiment']['productionHold'] is None
        assert profile['timeline']['effectPhases'][0]['effectType']=='AddElementResistance'
        assert profile['timeline']['effectPhases'][0]['evidence']['durationClock']=='native_shared_battle_turn'
    else:
        assert profile["issues"] == [fixture["experiment"]["productionHold"]]
    assert fixture["experiment"]["releaseAuthorized"] is False
    assert weakness_phase in ("before", "after")
    assert fixture["experiment"].get("weaknessPhase", "after") == weakness_phase
    assert profile["timeline"]["hitFrames"] == [80]
    native = profile["conversion"]["native"]
    assert native["set"]["Cost"] == 4 and native["set"]["magnification"] == 15
    assert native["set"]["parameterVariationType"] == "Decrease"
    assert [(e["set"]["EffectType"], e["activeTiming"]) for e in native["effects"]] == [
        ("AddElementResistance", "AfterDamageCalculation"), ("ParameterVariation", "AfterDamageCalculation")]
    assert native["effects"][0]["set"]["ParamList"][:2] == [1, 1]
    assert native["effects"][0]["set"]["effectEndActionNum"] == 5
    assert native["effects"][1]["set"]["ParamList"][:5] == [4, 4, 2, -1, 0]
    bundles = fixture["expectedRow"]["effectBundleList"]
    assert [(b["effectId"], b["TargetType"], b["targetRelation"], b["activeSkillAddTiming"]) for b in bundles] == [
        ((skill_id*100), "SkillTarget", "Enemies", "BeforeDamageCalculation" if weakness_phase == "before" else "AfterDamageCalculation"),
        ((skill_id*100+1), "Self", "Friendlies", "AfterDamageCalculation")]
    assert len(run["temporaryContentPackages"]) == 3
    assert sorted(value.lower() for value in run["temporaryContentPackages"].values()) == sorted(fixture["files"].values())
    return run, fixture, profile


def verify(directory, build, weakness_phase="after", expiry=False):
    skill_id = diagnostic_skill_id(directory)
    run, fixture, profile = verify_fire_artifacts(directory, build, weakness_phase, expiry)
    log_path = directory / "collected-ue4ss/UE4SS.log"
    log = log_path.read_text(encoding="utf8", errors="replace")
    assert not any(failure in log for failure in ("combat_driver_failed=", "turn_owner_failed=", "[FFRConvertedDriver] read_failed="))
    events = []
    for number, line in enumerate(log.splitlines(), 1):
        match = re.search(r"\[FFRAvailability(Native|Probe)\] (\{.*\})$", line)
        if match:
            record = json.loads(match[2])
            record["logLine"] = number
            events.append(record)
    counts = Counter(event["event"] for event in events)
    assert counts["registered"] == 13 and counts["native_attached"] == 1
    for failure in ("native_attach_failed", "registration_failed", "read_failed", "trace_capacity", "query_capacity", "native_observation_capacity"):
        assert counts[failure] == 0, failure
    assert log.count("fire_row_verified") == 1
    assert log.count("fire_command_requested ") == log.count("fire_command_returned") == 1
    assert log.count("converted_observation_complete") == 1
    request = re.findall(r"fire_command_requested owner=(\d+) skill=(\d+) target=(\d+) hp=(\d+) mp=(\d+) lb=(\d+) fire=(\d+)", log)
    assert len(request) == 1
    owner, skill, target, hp, mp, lb, resistance = map(int, request[0])
    assert (owner, skill, target, resistance) == (0, skill_id, 1, 0)
    sample_pattern = r"fire_sample caster_hp=(\d+) caster_mp=(\d+) caster_lb=(\d+) caster_fire=(\d+) enemy_hp=(\d+) enemy_mp=(\d+) enemy_lb=(\d+) enemy_fire=(\d+)"
    command_position = log.index("fire_command_requested ")
    preceding = re.findall(sample_pattern, log[:command_position])
    following = re.findall(sample_pattern, log[command_position:])
    assert preceding and len(following) == 1
    before, after = tuple(map(int, preceding[-1])), tuple(map(int, following[0]))
    assert (before[4], before[1], before[2], before[7]) == (hp, mp, lb, resistance)
    assert before[0] == after[0] > 0 and before[3] == after[3] == 0
    assert 0 < after[4] < before[4] and after[7] == 1
    assert after[1] == before[1]-4
    if weakness_phase == "after":
        assert after[2] == before[2]+4
    else:
        assert after[2] >= before[2]+4
    assert before[5:7] == after[5:7], "Enemy resources changed unexpectedly."
    effect_log = log.split("expiry_started ",1)[0] if expiry else log
    effects = re.findall(r"effect role=(\w+) id=(\d+) life=(\d+) actor=(\d+) target=(\d+)", effect_log)
    assert effects == [("enemy", str(skill_id*100), "5", "1001", "5")]
    results = re.findall(r"fire_result before_hp=(\d+) after_hp=(\d+) before_mp=(\d+) after_mp=(\d+) before_lb=(\d+) after_lb=(\d+) before_fire=(\d+) after_fire=(\d+)", log)
    assert len(results) == 1 and tuple(map(int, results[0])) == (hp, after[4], mp, after[1], lb, after[2], resistance, 1)
    guards = [event for event in events if event["event"] == "native_guard" and event["skillId"] == skill]
    assert len(guards) == 1 and guards[0]["nativeAllowed"] is True
    guard = guards[0]
    assert guard["actor"] > 0 and guard["job"] == guard["rootJob"]
    assert guard["targetCount"] == 1 and guard["actionCount"] == 1
    decisions = [event for event in events if event["event"] == "command_decide" and
                 any(action["skillId"] == skill for action in event["actions"])]
    assert len(decisions) == 1 and decisions[0]["actions"] == [
        {"item": False, "skillId": skill, "targets": [target], "uniqueId": owner}]
    assert decisions[0]["logLine"] < guard["logLine"]
    starts = [event for event in events if event["event"] in ("skill_begin_message", "skill_begin_libra") and event["skillId"] == skill]
    assert starts and all(event["logLine"] > guard["logLine"] and
        event["targets"] == [target] and event["uniqueId"] == owner and
        event["owner"]["unitId"] == 1001 and event["owner"]["actorAddress"] == guard["actor"] for event in starts)
    result_line = next(number for number, line in enumerate(log.splitlines(), 1) if "fire_result " in line)
    assert guard["logLine"] < result_line
    assert not [event for event in events if event["event"] == "native_guard" and
                guard["logLine"] < event["logLine"] < result_line], "Another cast confounds the result."
    stats = re.findall(r"fire_combat_stats caster_level=(\d+) caster_magic=(\d+) caster_intelligence=(\d+) enemy_level=(\d+) enemy_magic_defense=(\d+) enemy_mind=(\d+) caster_dying=(\w+) enemy_dying=(\w+)", log)
    assert len(stats) <= 1
    return {"run": directory.name, "runSha256": sha(directory / "run.json"), "logSha256": sha(log_path),
        "fixtureManifestSha256": sha(directory / "converted-ability-build.json"),
        "source": fixture["source"], "skillId": skill, "weaknessPhase": weakness_phase,
        "productionSupportedAtBuild":profile['supported'], "eventCounts": dict(sorted(counts.items())),
        "nativeGuard": guard, "command": decisions[0], "skillStartNotifications": len(starts),
        "damage": {"beforeHp": hp, "afterHp": after[4], "amount": hp-after[4]},
        "casterHp": before[0],
        "combatStats": dict(zip(("casterLevel", "casterMagic", "casterIntelligence", "enemyLevel", "enemyMagicDefense", "enemyMind", "casterDying", "enemyDying"), stats[0])) if stats else None,
        "casterResources": {"beforeMp": mp, "afterMp": after[1], "mpCost": 4, "beforeLb": lb, "afterLb": after[2],
            "lbGain": after[2]-lb, "convertedLbGainIsolated": weakness_phase == "after"},
        "enemyFireResistance": {"before": "None", "after": "Weakness", "effectId": (skill_id*100),
            "lifeTurnsObserved": 5, "sourceUnitId": 1001, "targetUnitId": 5},
        "casterFireResistanceUnchanged": True, "enemyResourcesUnchanged": True,
        "originalSaveFilesUnchanged": True, "originalPackagesUnchanged": True,
        "temporaryPackagesAndRuntimeRemoved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    build = read_json(OUT / "native-bridge-validation.json")
    cases = []
    for name in args.runs:
        assert re.fullmatch(r"\d{8}_\d{6}_\d{3}", name), "Expected a run ID."
        cases.append(verify(OUT / "native-battle-runs" / name, build))
    report = {"status": "passed", "scope": "converted_fire_native_cast", "cases": cases,
        "converterAbilityRecordsTested": 1, "productionCommandHold": "released_for_after_damage_resistance" if cases[-1]['productionSupportedAtBuild'] else "retained_at_fixture_build",
        "lifecycleBinding": "unbound", "compatibleRecordsReleased": 0,
        "limitations": ["One source Fire record, one caster and one living enemy.",
            "This cast-only report checks the resulting effect and lifetime; expiry and phase order have separate reports.",
            "FFBE imperil percentage is adapted to native weakness; separate effect timestamps are not reproduced.",
            "Native Rain animation window; no FFBE sprite or audiovisual fidelity claim.",
            "Transient skill-list request; inventory/menu granting and held availability enforcement are not validated."]}
    (OUT / "native-converted-fire-validation.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
