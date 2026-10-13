"""Build the private five-battle Mitra NPC on top of installed visions and party.

Rebuild after Studio imports, after rebuilding the party addon. No saves change.
"""
from copy import deepcopy
from datetime import datetime
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/ffbe2ss6")]
import ffrenv
from verify_mod import equivalent
from npc_assets import (MAP, PERSISTENT_MAP, SCHEMAS, EVENT, clone_npc, build_boss_sprite,
                        add_battle_streaming, streaming_levels, property_of, dump, sha, dt, run)
from make_party_mod import check_cooked, export_json
from battle_music import build as build_music, append_to_native

STEM = "zzzz_PrivateBattles_3_P"
RETURN = "Private_Battles_Return"
CHOICE = "UI.Dialog.Choice.PrivateBattles"
SEQUENCE = "Sequencer/Event/Private/SEQ_PrivateBattles"
RETURN_SEQUENCE = "/Game/Sequencer/Event/Gimmick/Majipot/SEQ_Gim_EV_Majipot_Escape"
BATTLE_STAGE = 5
STAGE_TABLE = "Asset/Battle/Stage/CDT_BtlStageAsset_Demo"
TRAINING_FORM = "1052510"
TRAINING_UNIT = 9467
# Read from CPP_BFL_Unit in the installed native build. Using int32 max exceeds
# the game's supported range and can crash while constructing battle actors.
TRAINING_HP_MAX = 99_999_999
TRAINING_STAT_MAX = 9_999
ENEMIES = [
    ("3080410", "Resentful Noise Spirit"),
    ("900000061", "Aldhibah"),
    ("900000004", "Grandbun the Unreasonably Old"),
    ("900000053", "Shadow Esther"),
    ("900000054", "Vestige of the Eggsterminator"),
    ("10000066", "Producer"),
    (TRAINING_FORM, "Training Dummy"),
]
BATTLES = [
    ("1. Resentful Noise Spirit", [9461], "la561_bgm_touch_it_remix_verse_to_chorus"),
    ("2. Aldhibah & Grandbun", [9462, 9463], "la5th001_bgm_ffbe_5th_battle_normal"),
    ("3. Shadow Esther & the Eggsterminator", [9464, 9465], "la403_la3_n009_battle_baroque"),
    ("4. Producer", [9466], "la416_bgm_ffbe_8thanniv_m04_final"),
    ("5. Training Dummy", [TRAINING_UNIT], "la5th001_bgm_ffbe_5th_battle_normal"),
]
# Explicit native sequence IDs avoid enemy skills whose sequences are absent in
# the demo. Mechanics remain the corresponding enemy spells, at test strength.
SPELLS = [(694610, 250030, 220032, "Firaga"), (694620, 250110, 220112, "Thundaga"),
          (694630, 250070, 220072, "Blizzaga"), (694640, 505860, 408051, "Dystopia")]
EVENT_TABLES = ["Event/TalkEvent/FreeTalk/01Gra/DT_TalkEventData_Town_01Gra_20", "Event/TalkEvent/CDT_TalkEventData_Demo"]
TABLES = ["Unit/DT_UnitParameter", "Unit/AI/DT_BtlUnitAIParameter",
          "Asset/Battle/Unit/DT_BtlUnitAsset", "Battle/Unit/DT_BtlUnitDesignParameter",
          "Encount/DT_BattleGroup", "Map/MapData/DT_MapData_01Gra", "Map/CDT_MapData_Demo",
          *EVENT_TABLES, "UI/Common/Dialog/DT_DIalogChoice", "Skill/DT_SkillData",
          "Asset/Skill/CDT_SkillAsset_Demo", STAGE_TABLE]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def extract(paks, work):
    inputs = work / "inputs"; inputs.mkdir()
    for path in [*paks.glob("*.utoc"), *paks.glob("*.ucas")]:
        (inputs / path.name).symlink_to(path.resolve())
    installed = []
    for mod in sorted((paks / "~mods").glob("*.utoc")):
        if mod.stem == STEM:
            continue
        for path in (mod, mod.with_suffix(".ucas")):
            shutil.copy2(path, inputs / path.name)
        installed.append({"file": str(mod), "sha256": sha(mod), "ucasSha256": sha(mod.with_suffix(".ucas"))})
    legacy = work / "legacy"
    for filt in ["Datatable", MAP, PERSISTENT_MAP, *SCHEMAS, "Chara/summon/summon13110/",
                 RETURN_SEQUENCE.replace("/Game/", "FFRS/Content/"),
                 "Sequencer/Event/FreeTalk/SEQ_CcommonFreeTalk", "Sound/Cri/Bgm/BGM_PP/BGM_PP",
                 "Sound/Cri/Se/SE_PP/SE_BTL_PP/SE_BTL_PP"]:
        run([ffrenv.RETOC, "to-legacy", "--no-shaders", "--filter", filt, inputs, legacy])
    return legacy, installed


def pack_config(work, package):
    # retoc's Zen conversion omits loose INI files. Its companion PAK is empty
    # for this addon, so explicitly package the tag dictionary alongside IoStore.
    repak = ROOT / "tools/repak/repak.exe"
    pak = package / (STEM + ".pak")
    entries = set(run([repak, "list", pak]).splitlines())
    if entries - {"FFRS/Config/DefaultGameplayTags.ini"}:
        raise ValueError("Unexpected companion PAK contents; preserve them before adding config")
    config = work / "config/FFRS/Config/DefaultGameplayTags.ini"
    config.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(work / "assets/FFRS/Config/DefaultGameplayTags.ini", config)
    run([repak, "pack", "--version", "V11", work / "config", pak])
    contents = subprocess.run([str(repak), "get", str(pak), "FFRS/Config/DefaultGameplayTags.ini"],
                             check=True, capture_output=True, text=True, encoding="utf-8").stdout
    if CHOICE not in contents:
        raise ValueError("The packaged choice tag is missing")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default=ffrenv.detect_game())
    parser.add_argument("--picker", type=Path, default=ROOT / "build/ffbe-asset-picker")
    parser.add_argument("--hp", type=int, default=200)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--if-installed", action="store_true", help="Skip when the addon is not installed")
    args = parser.parse_args()
    if args.hp < 1 or not ffrenv.is_game_root(args.game):
        parser.error("Positive HP and a valid game folder are required")
    paks = Path(args.game) / "FFRS/Content/Paks"
    if args.if_installed and not (paks / "~mods" / (STEM + ".utoc")).exists():
        print("Private battle addon is not installed; skipping its rebuild.")
        return
    work = ROOT / "build/npc-battles" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work.mkdir(parents=True)
    legacy, installed = extract(paks, work)
    assets = work / "assets"
    schemas = [legacy / path for path in SCHEMAS]
    dt("tojson", legacy / MAP, work / "map-original.json", schemas=schemas)
    edited, npc = clone_npc(read(work / "map-original.json"), [443.212488, 2002.0, 296.47391174438224])
    dump(work / "map-edited.json", edited)
    (assets / MAP).parent.mkdir(parents=True)
    dt("fromjson", work / "map-edited.json", assets / MAP, schemas=schemas)
    dt("tojson", assets / MAP, work / "map-readback.json", schemas=schemas)
    map_check = read(work / "map-readback.json")
    assert len(map_check["Exports"]) == len(edited["Exports"])
    assert map_check["Exports"][npc["actor"]-1]["ObjectName"] == "BP_MapUnit_NPC_PrivateBattles"
    sequence = assets / ("FFRS/Content/" + SEQUENCE + ".uasset")
    sequence.parent.mkdir(parents=True)
    dt("make-choice-sequence", legacy / "FFRS/Content/Sequencer/Event/FreeTalk/SEQ_CcommonFreeTalk.uasset",
       sequence, "/Game/" + SEQUENCE, CHOICE)
    # Register our new choice tag while retaining the complete native tag config.
    config = ROOT / "extracted/pak/FFRS/Config/DefaultGameplayTags.ini"
    text = config.read_text(encoding="utf-8-sig")
    text += '\n+GameplayTagList=(Tag="' + CHOICE + '",DevComment="Private battle selection")\n'
    target = assets / "FFRS/Config/DefaultGameplayTags.ini"
    target.parent.mkdir(parents=True); target.write_text(text, encoding="utf-8")
    visual = {}
    for i, (form, name) in enumerate(ENEMIES):
        visual[9461+i] = build_boss_sprite(args.picker / "Enemy Sources" / form, form, 9461+i, work, legacy, assets)
        print("Imported enemy:", name, flush=True)
    payload = (legacy / "FFRS/Content/Sound/Cri/Bgm/BGM_PP/BGM_PP.uexp").read_bytes()
    start = payload.index(b"@UTF")
    native = payload[start:start + 8 + int.from_bytes(payload[start+4:start+8], "big")]
    bank, cues = build_music(ROOT, args.picker, work / "music", native, [b[2] for b in BATTLES])
    bank = append_to_native(native, bank.read_bytes(), work / "music/BGM_PP.acb")
    tables = {}
    for rel in TABLES:
        output = work / "rows" / (rel + ".json"); output.parent.mkdir(parents=True, exist_ok=True)
        dt("rows", legacy / "FFRS/Content/Datatable" / (rel + ".uasset"), output)
        tables[rel] = read(output)["rows"]
    stage = next(v for v in tables[STAGE_TABLE].values() if v["ID"] == BATTLE_STAGE)
    if stage["isLoadLevelInstance"]:
        raise ValueError("Recheck arena loading: this stage uses dynamic level instances")
    arena_levels = stage["battleLevelList"]
    for i, path in enumerate(arena_levels):
        export_json(work / "inputs", path, work / f"arena-source-{i}.json")
    dt("tojson", legacy / PERSISTENT_MAP, work / "persistent-original.json")
    persistent, added_levels = add_battle_streaming(read(work / "persistent-original.json"), arena_levels)
    dump(work / "persistent-edited.json", persistent)
    (assets / PERSISTENT_MAP).parent.mkdir(parents=True, exist_ok=True)
    dt("fromjson", work / "persistent-edited.json", assets / PERSISTENT_MAP)
    edits = {}
    def entry(rel):
        return edits.setdefault(rel, {"asset": "FFRS/Content/Datatable/" + rel, "add": [], "set": []})
    def add(rel, row, donor, values):
        if row in tables[rel]:
            raise ValueError(f"Private row collision: {rel}/{row}")
        entry(rel)["add"].append({"row": row, "cloneFrom": donor, "set": values})
    def donor(rel, uid):
        return next(k for k, v in tables[rel].items() if v.get("ID") == uid)
    for uid, source, sequence_id, name in SPELLS:
        native_asset = tables["Asset/Skill/CDT_SkillAsset_Demo"][donor("Asset/Skill/CDT_SkillAsset_Demo", sequence_id)]
        # Resolve real packages, not just strings in a data table.
        export_json(work / "inputs", native_asset["LevelSequence"], work / (f"spell-{uid}.json"))
        add("Skill/DT_SkillData", "Private_Battles_" + name, donor("Skill/DT_SkillData", source),
            {"ID": uid, "SortId": uid, "Name": name, "Cost": 0, "magnification": 1,
             "breakDamageValue": 0, "skillIdAfterModeChange": -1, "playSequencerId": sequence_id})
    for i, (form, name) in enumerate(ENEMIES):
        uid = 9461+i; row = "Private_Battles_" + form
        rel = "Unit/DT_UnitParameter"
        add(rel, row, donor(rel, 460), {"ID": uid, "Name": name, "Description": "Private resonance test opponent",
            "SortId": uid, "SaveId": uid, "Level": 1, "MaxHitPoint": args.hp, "MaxMagicPoint": 999,
            "MagicPoint": 999, "MaxBreakPoint": 100, "Attack": 5, "Defence": 10, "Intelligence": 5,
            "Mind": 10, "Agility": 10, "Experience": 0, "Money": 0, "Traits": [], "BattleVoiceLabel": "",
            "DropNormalItem": -1, "DropRareItem": -1, "StealNormalItem": -1, "StealRareItem": -1,
            "ElementResistanceList": {k: "eResistance::None" for k in tables[rel][donor(rel, 460)]["ElementResistanceList"]}})
        rel = "Unit/AI/DT_BtlUnitAIParameter"
        add(rel, row, donor(rel, 1), {"ID": uid, "fightSkillId": SPELLS[0][0], "silenceFightId": SPELLS[0][0],
            "skillRandData1": [{"SkillId": s[0], "Probability": 25.0} for s in SPELLS]})
        if uid == TRAINING_UNIT:
            entry("Unit/DT_UnitParameter")["set"].append({"row": row, "set": {
                "Description": "Animation practice. This dummy never acts; escape at any time.",
                "MaxHitPoint": TRAINING_HP_MAX, "Defence": TRAINING_STAT_MAX, "Mind": TRAINING_STAT_MAX,
                "Attack": 0, "Intelligence": 0, "Agility": 1, "MaxMagicPoint": 0, "MagicPoint": 0}})
            # AI 0 is the game's base/dummy AI. Clear every action path,
            # including inherited counter, chase, silence and high-risk skills.
            entry(rel)["set"].append({"row": row, "set": {
                "aiId": 0, "fightSkillId": -1, "silenceFightId": -1, "chaseSkillId": -1,
                "skillRandData1": [], "skillRandData2": [],
                "counterSkillIdList": [-1, -1], "highRiskSkillIdList": [-1, -1]}})
        rel = "Asset/Battle/Unit/DT_BtlUnitAsset"; path = visual[uid]
        add(rel, row, donor(rel, 460), {"ID": uid, "animationAssetList[0].Ss6Project": path,
            "animationAssetList[0].textureBaseColor": path + "_tex", "animationAssetList[0].textureNormal": path + "_normal",
            "animationAssetList[0].textureMetallicRoughness": path + "_mreo"})
        rel = "Battle/Unit/DT_BtlUnitDesignParameter"
        add(rel, row, donor(rel, 460), {"ID": uid, "Size": "L", "Scale": 1.0,
            "attackOffsetLocation.attackOffsetLocation": {"x": 0, "y": 60, "z": 0},
            "footRoundShadowScale.footRoundShadowScale": {"x": 2, "y": 2, "z": 2},
            "footRoundShadowOffsetLocation.footRoundShadowOffsetLocation": {"x": 0, "y": 0, "z": 0}})
    template = deepcopy(tables[EVENT_TABLES[1]]["C01_ArijigokuEncount"])
    template.update(encountGroupId=-1, IsRecover=True, IsGetOffVehicle=False,
                    MapStartupSettings={"ChangeBGM": "NotChange"})
    # Battle-finish events run behind the battle transition's black screen.
    # Native escape executes the header, fade-in, fade wait and footer. A blank
    # data-only event does not restore the screen even if its field UI is shown.
    export_json(work / "inputs", RETURN_SEQUENCE, work / "return-sequence-source.json")
    dt("tojson", legacy / (RETURN_SEQUENCE.replace("/Game/", "FFRS/Content/") + ".uasset"),
       work / "return-sequence-full.json")
    event_rows = {RETURN: {**deepcopy(template), "IsHiddenFieldUI": False,
                          "EventSequence": RETURN_SEQUENCE}}
    branches = []
    for i, (label, units, track) in enumerate(BATTLES):
        event = f"Private_Battles_{i+1}"
        group = 199461+i
        add("Encount/DT_BattleGroup", event, donor("Encount/DT_BattleGroup", 1),
            {"ID": group, "UnitIdList": units, "locationIdList": [10] if len(units) == 1 else [8, 19],
             "bgmCueName": cues[i]["name"], "CanEscape": True, "probabilityOfSuccessfulEscape": 100.0,
             "ap": 0, "isResultSkipOnWin": True, "isResultSkipOnLose": True,
             "battleFinishEventId": RETURN, "battleFinishEscapeEventId": RETURN, "battleFinishLoseEventId": RETURN})
        event_rows[event] = {**deepcopy(template), "encountGroupId": group}
        branches.append({"Index": i, "EventList": [{"Condition": "", "EventId": event}]})
    branches.append({"Index": len(BATTLES), "EventList": [{"Condition": "", "EventId": RETURN}]})
    event_rows[EVENT] = {**deepcopy(template), "IsRecover": False, "EventSequence": "/Game/" + SEQUENCE,
                         "ChoicesBranchEventList": branches, "Description": "Private battle selection"}
    for row in (EVENT, RETURN):
        event_rows[row]["HeaderSettings"]["IsVisibleNPC"] = True
    event_rows[RETURN]["MapStartupSettings"]["ChangeBGM"] = "MapBGM"
    event_rows[RETURN]["RestoreBGMSettings"].update(IsOverride=True, Type="MapBGM")
    for rel in EVENT_TABLES:
        branch_donor = next(k for k, v in tables[rel].items() if v["ChoicesBranchEventList"])
        for row, values in event_rows.items():
            add(rel, row, branch_donor, values)
    rel = "UI/Common/Dialog/DT_DIalogChoice"
    add(rel, "Private_Battles", "UI_DialogChoice_YesNo", {"ChoiceTag.TagName": CHOICE,
        "ChoiceTextList": [b[0] for b in BATTLES] + ["Leave"], "DefaultIndex": 0, "CancelIndex": len(BATTLES)})
    for rel in ["Map/MapData/DT_MapData_01Gra", "Map/CDT_MapData_Demo"]:
        entry(rel)["set"].append({"row": "01Gra_20", "set": {"battleStage": BATTLE_STAGE}})
    bank_asset = "FFRS/Content/Sound/Cri/Bgm/BGM_PP/BGM_PP"
    patch = {"legacyRoot": str(legacy), "outRoot": str(assets), "tables": list(edits.values()),
             "atomBanks": [{"from": bank_asset, "to": bank_asset, "appendCues": True,
                            "acb": str(bank), "sha256": sha(bank), "cues": cues}]}
    dump(work / "patch.json", patch); dt("patch", work / "patch.json")
    verified = {}
    for rel, edit in edits.items():
        output = work / "verified" / (rel + ".json"); output.parent.mkdir(parents=True, exist_ok=True)
        dt("rows", assets / (edit["asset"] + ".uasset"), output)
        actual = read(output)["rows"]
        changed = {v["row"] for k in ("add", "set") for v in edit[k]}
        for key, value in tables[rel].items():
            if key not in changed and not equivalent(value, actual.get(key)):
                raise ValueError(f"Unrelated row changed: {rel}/{key}")
        assert changed <= actual.keys()
        verified[rel] = {"rows": len(actual), "edited": sorted(changed), "unrelatedRowsUnchanged": True}
    package = work / "package"; package.mkdir()
    run([ffrenv.RETOC, "to-zen", "--version", "UE5_6", assets, package / (STEM + ".utoc")])
    pack_config(work, package)
    cooked = check_cooked(work, package)
    run([ffrenv.RETOC, "to-legacy", "--no-shaders", "--filter", MAP, work / "inputs", work / "cooked-map"])
    dt("tojson", work / "cooked-map" / MAP, work / "map-cooked.json", schemas=schemas)
    packed_map = read(work / "map-cooked.json")
    if packed_map["NameMap"].index(EVENT) >= packed_map["NamesReferencedFromExportDataCount"]:
        raise ValueError("The packed NPC event name is outside the map's serialized name table")
    cooked.update(npcEventNameResolved=True, choiceTagPackaged=True)
    run([ffrenv.RETOC, "to-legacy", "--no-shaders", "--filter", PERSISTENT_MAP, work / "inputs", work / "cooked-map"])
    dt("tojson", work / "cooked-map" / PERSISTENT_MAP, work / "persistent-cooked.json")
    packed_persistent = read(work / "persistent-cooked.json")
    _, _, indices = streaming_levels(packed_persistent)
    registered = [property_of(packed_persistent["Exports"][i-1], "WorldAsset")["Value"]["AssetPath"]["PackageName"] for i in indices]
    if any(registered.count(path) != 1 for path in arena_levels):
        raise ValueError("Packed Mitra world is missing or duplicating an arena streaming level")
    cooked["arenaLevelsRegistered"] = arena_levels
    for rel in ["Encount/DT_BattleGroup", EVENT_TABLES[1], "UI/Common/Dialog/DT_DIalogChoice"]:
        data = export_json(work / "inputs", "/Game/Datatable/" + rel, work / (Path(rel).name + "-cooked.json"))["Rows"]
        for v in edits[rel]["add"]:
            if v["row"] not in data:
                raise ValueError(f"Cooked addon lost row {v['row']}")
    result = {"work": str(work), "npc": npc, "enemies": ENEMIES, "battles": BATTLES, "hp": args.hp,
              "addedArenaLevels": added_levels,
              "sourceMods": installed, "tables": verified, "cooked": cooked, "music": cues,
              "files": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in package.iterdir()},
              "gameplay": "NOT_TESTED"}
    if args.install:
        if ffrenv.game_running():
            raise RuntimeError("Close the game before installing. Completed package: " + str(package))
        for source in installed:
            path = Path(source["file"])
            if sha(path) != source["sha256"] or sha(path.with_suffix(".ucas")) != source["ucasSha256"]:
                raise RuntimeError("Installed mods changed during this build; rebuild the addon")
        target = paks / "~mods"; target.mkdir(exist_ok=True)
        for p in package.iterdir():
            dst = target / p.name
            if dst.exists():
                backup = work / "backup"; backup.mkdir(exist_ok=True); shutil.copy2(dst, backup / p.name)
            shutil.copy2(p, dst)
            assert sha(p) == sha(dst)
        result["installed"] = str(target)
    dump(work / "verification.json", result)
    dump(ROOT / "build/npc-battles/latest.json", result)
    print("Ready:", work)


if __name__ == "__main__":
    main()
