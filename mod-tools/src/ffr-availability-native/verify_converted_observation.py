"""Verify a real converted Cure cast, its native row, target, healing and MP cost."""
from verify_combat_observation import diagnostic_skill_id
from collections import Counter
import argparse
import json
import re
from verify_combat_observation import OUT, read_json, sha, verify_artifacts


def verify(directory, build):
    skill_id = diagnostic_skill_id(directory)
    run = verify_artifacts(directory, build)
    assert run["convertedAbilityRequested"] and run.get("fixtureCompleted") and run.get("fixtureTerminated")
    fixture = read_json(directory / "converted-ability-build.json")
    profile = read_json(directory / "converted-profile.json")
    assert fixture["status"] == "built" and fixture["scope"] == "temporary_converted_cure_fixture"
    assert fixture["source"] == "JP_2024/magic/10020" and fixture["skillId"] == skill_id
    assert sha(directory / "converted-profile.json") == fixture["profileSha256"]
    assert profile["supported"] and profile["conversion"]["validation"]["tableCompatible"]
    assert profile["snapshot"]["root"] == fixture["source"]
    assert profile["set"]["Cost"] == 4 and profile["timeline"]["hitFrames"] == [90]
    assert profile["set"]["parameterVariationType"] == "Increase"
    assert len(run["temporaryContentPackages"]) == 3
    assert sorted(value.lower() for value in run["temporaryContentPackages"].values()) == sorted(fixture["files"].values())
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
    assert log.count(f"row_verified skill={skill_id} cost=4 magnification=62 hits=1 sequence={skill_id+1}") == 1
    assert log.count("baseline_attack_requested ") == 1 and log.count("baseline_attack_returned") == 1
    assert log.count("converted_command_requested ") == 1 and log.count("converted_command_returned") == 1
    assert log.count("converted_observation_complete") == 1
    requests = re.findall(r"converted_command_requested owner=(\d+) skill=(\d+) target=(\d+) hp=(\d+) mp=(\d+)", log)
    assert len(requests) == 1
    owner, skill, target, hp, mp = map(int, requests[0])
    assert (owner, skill, target) == (0, skill_id, 0)
    heals = re.findall(r"healing_observed before_hp=(\d+) after_hp=(\d+) before_mp=(\d+) after_mp=(\d+)", log)
    assert len(heals) == 1
    old_hp, new_hp, old_mp, new_mp = map(int, heals[0])
    assert old_hp == hp and old_mp == mp and 0 < old_hp < new_hp and new_mp == old_mp-4
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
    healing_line = next(number for number, line in enumerate(log.splitlines(), 1) if "healing_observed " in line)
    assert guard["logLine"] < healing_line
    return {"run": directory.name, "runSha256": sha(directory / "run.json"), "logSha256": sha(log_path),
        "fixtureManifestSha256": sha(directory / "converted-ability-build.json"),
        "source": fixture["source"], "skillId": skill, "eventCounts": dict(sorted(counts.items())),
        "nativeGuard": guard, "command": decisions[0], "skillStartNotifications": len(starts),
        "healing": {"beforeHp": old_hp, "afterHp": new_hp, "beforeMp": old_mp, "afterMp": new_mp, "mpCost": old_mp-new_mp},
        "targetUniqueId": target, "originalSaveFilesUnchanged": True,
        "originalPackagesUnchanged": True, "temporaryPackagesAndRuntimeRemoved": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    build = read_json(OUT / "native-bridge-validation.json")
    cases = []
    for name in args.runs:
        assert re.fullmatch(r"\d{8}_\d{6}_\d{3}", name), "Expected a run ID."
        cases.append(verify(OUT / "native-battle-runs" / name, build))
    report = {"status": "passed", "scope": "converted_cure_native_cast", "cases": cases,
        "converterAbilityRecordsTested": 1, "lifecycleBinding": "unbound", "compatibleRecordsReleased": 0,
        "limitations": ["One source Cure record, one caster and one selected living target.",
                        "Native Rain animation window; no FFBE sprite or audiovisual fidelity claim.",
                        "Explicit transient skill-list request; inventory/menu granting is not validated.",
                        "No cooldown, charge, limited-use, repeat or dual-wield enforcement enabled."]}
    (OUT / "native-converted-cure-validation.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
