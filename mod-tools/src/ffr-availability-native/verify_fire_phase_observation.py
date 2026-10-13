"""Compare converted Fire with a control that changes only weakness timing."""
import argparse
from copy import deepcopy
import json
import re
from pathlib import Path
from verify_fire_observation import verify
from verify_combat_observation import OUT, read_json, sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("after_run")
    parser.add_argument("before_run")
    args = parser.parse_args()
    build = read_json(OUT / "native-bridge-validation.json")
    cases, fixtures = [], []
    for name, phase in ((args.after_run, "after"), (args.before_run, "before")):
        assert re.fullmatch(r"\d{8}_\d{6}_\d{3}", name), "Expected a run ID."
        directory = OUT / "native-battle-runs" / name
        cases.append(verify(directory, build, phase))
        fixtures.append(read_json(directory / "converted-ability-build.json"))
    after, before = fixtures
    assert after["profileSha256"] == before["profileSha256"], "Source profiles differ."
    assert after["plan"] == before["plan"] and after["skillId"] == before["skillId"]
    control = deepcopy(before["expectedRow"])
    control["effectBundleList"][0]["activeSkillAddTiming"] = "AfterDamageCalculation"
    assert after["expectedRow"] == control, "More than the first bundle timing changed."
    patches = [read_json(Path(f["directory"]) / "patch.json") for f in fixtures]
    control = deepcopy(patches[1])
    root_table = next(t for t in control["tables"] if t["asset"].endswith("/Skill/DT_SkillData"))
    assert len(root_table["add"]) == 1
    root_table["add"][0]["set"]["effectBundleList"][0]["activeSkillAddTiming"] = "AfterDamageCalculation"
    assert patches[0]["tables"] == control["tables"] and patches[0]["clones"] == control["clones"]
    for fixture, patch in zip(fixtures, patches):
        cooked = Path(fixture["directory"]) / "cooked-skill-rows.json"
        assert sha(cooked) == fixture["cookedRowsSha256"]
        row = read_json(cooked)["rows"][fixture["rowName"]]
        assert row["effectBundleList"] == fixture["expectedRow"]["effectBundleList"]
        cooked_effects = Path(fixture["directory"]) / "cooked-effect-rows.json"
        assert sha(cooked_effects) == fixture["cookedEffectsSha256"]
        effects = read_json(cooked_effects)["rows"]
        effect_table = next(t for t in patch["tables"] if t["asset"].endswith("/Skill/DT_SkillEffectData"))
        for added in effect_table["add"]:
            assert all(effects[added["row"]][field] == value for field, value in added["set"].items())
    for key in ("beforeHp",):
        assert cases[0]["damage"][key] == cases[1]["damage"][key]
    assert cases[0]["combatStats"] and cases[0]["combatStats"] == cases[1]["combatStats"]
    assert cases[0]["combatStats"]["casterDying"] == cases[0]["combatStats"]["enemyDying"] == "false"
    for key in ("beforeMp", "afterMp", "mpCost"):
        assert cases[0]["casterResources"][key] == cases[1]["casterResources"][key], key
    assert cases[0]["enemyFireResistance"] == cases[1]["enemyFireResistance"]
    assert cases[1]["damage"]["amount"] > cases[0]["damage"]["amount"]
    report = {"status": "passed", "scope": "experimental_fire_weakness_phase_comparison", "cases": cases,
        "onlyAuthoredMechanicChanged": "First bundle activeSkillAddTiming: after to before damage calculation",
        "observation": "Moving the weakness earlier increased first-cast damage while the final weakness and MP cost matched.",
        "additionalLbGainWithEarlierWeakness": cases[1]["casterResources"]["lbGain"]-cases[0]["casterResources"]["lbGain"],
        "productionCommandHoldAtFixtureBuild": "retained" if not cases[0]['productionSupportedAtBuild'] else "after_damage_released", "compatibleRecordsReleased": 0,
        "limitations": ["One cast per phase on Rain and Goblin; damage distributions and other recipients were not tested.",
            "Caster initial HP and LB may differ with enemy turn order; magic stats and non-dying status must match, and no other cast may intervene.",
            "No instruction-level trace of the damage calculation or extra LB reward; this is a controlled behavioral observation.",
            "Five-turn lifetime was read, but effect expiry and availability enforcement were not tested."]}
    (OUT / "native-fire-phase-validation.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
