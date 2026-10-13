"""Build the private Raegen/Helena demo party addon, preserving installed visions.

python -B tools/private/make_party_mod.py --install
Rebuild after installing a new Studio vision package. Save edits are backed up.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/ffbe2ss6"), str(Path(__file__).parent)]
from PIL import Image, ImageChops, ImageDraw
import ffrenv
import build_sprites as sprites
from ffbe_frames import load_unit
from ffr_party_save import add_test_party, Save
from verify_mod import equivalent

# Explicit patch version keeps shared tables above the Studio's unversioned _P.
STEM = "zzzz_PrivateParty_2_P"
BLAST = 798700
UNITS = [
    {"name": "Raegen", "key": "raegen", "id": 1007, "row": "ジェイク", "form": "100045807",
     "element": "Light", "attack": 798710, "levelId": 9007, "sprite": "unit0070",
     "skills": [798710, BLAST, 210250, 210260, 798720],
     "portrait": [2.0, 480, 120], "button": [411, 32, 581, 96], "eye": [395, 42, 610, 82],
     "spriteFace": [-13, -63, 11, -39], "battleScale": 0.78, "attackCuts": [2, 8],
     "sex": "Male", "role": "Attacker", "voiceRow": "レイン"},
    {"name": "Helena", "key": "helena", "id": 1008, "row": "サクラ", "form": "339001207",
     "element": "Dark", "attack": 798810, "levelId": 9008, "sprite": "unit0080",
     "skills": [798810, BLAST, 798820, 798830],
     "portrait": [1.8, 295, 30], "button": [211, 98, 381, 162], "eye": [196, 92, 411, 132],
     "spriteFace": [-15, -63, 17, -31], "battleScale": 0.80, "attackCuts": [3, 10],
     "sex": "Female", "role": "Attacker", "voiceRow": "フィーナ"},
]
TABLES = ["Unit/DT_UnitParameter", "Unit/DT_PlayableUnitParameter", "Unit/DT_UnitBattleCmd",
          "Unit/LevelParameter/DT_UnitLevelParameterList", "Asset/Battle/Unit/DT_BtlUnitAsset",
          "Asset/Battle/Unit/DT_BtlPlayableUnitAsset", "Battle/Unit/DT_BtlUnitDesignParameter",
          "Skill/DT_SkillData", "Asset/Skill/DT_SkillAsset", "Asset/Skill/CDT_SkillAsset_Demo",
          "Battle/Sequencer/DT_BtlHitEffectData"]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, *, env=None):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, env=env, capture_output=True,
                            text=True, encoding="utf-8", errors="replace")
    if result.returncode:
        raise RuntimeError(f"{' '.join(map(str, args[:2]))}\n{result.stdout[-5000:]}\n{result.stderr[-2000:]}")
    return result.stdout


def dt(command, *args):
    import cooked_command_cache
    return cooked_command_cache.run([*ffrenv.FFRDT, command, *args, "--usmap", ffrenv.USMAP],
                                    run, ROOT / 'build/cooked-native-cache')


def rows(legacy, work, rel):
    output = work / "rows" / (rel + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    dt("rows", legacy / "FFRS/Content/Datatable" / (rel + ".uasset"), output)
    return json.loads(output.read_text(encoding="utf-8-sig"))["rows"]


def extract_sources(paks, work):
    legacy = work / "legacy"
    # retoc must see the base containers while converting the Studio tables:
    # otherwise hard references to native growth tables become UnknownExport.
    # Exclude our previous addon so a rebuild starts from current Studio data.
    container = work / "inputs"
    container.mkdir()
    for path in [*paks.glob("*.utoc"), *paks.glob("*.ucas")]:
        (container / path.name).symlink_to(path.resolve())
    installed = []
    for mod in sorted((paks / "~mods").glob("*.utoc")):
        if mod.stem in (STEM, "zzzz_PrivateParty_P", "zzzz_PrivateBattles_3_P"):
            continue
        for path in (mod, mod.with_suffix(".ucas")):
            shutil.copy2(path, container / path.name)
        installed.append({"file": str(mod), "sha256": sha(mod), "ucasSha256": sha(mod.with_suffix(".ucas"))})
    for name in ("Datatable", "Chara/Unit/unit0010/", "Chara/menu/unit0010/", "ICON_UnitFace_unit1001"):
        run([ffrenv.RETOC, "to-legacy", "--no-shaders", "--filter", name, container, legacy])
    return legacy, installed


def export_json(paks, asset, output):
    env = dict(os.environ, FFR_PAKS=str(paks))
    run(["dotnet", ROOT / "src/ffr-export/bin/Release/net10.0/ffr-export.dll", "json", asset, output], env=env)
    return json.loads(output.read_text(encoding="utf-8-sig"))


def check_cooked(work, package):
    """Resolve the finished addon alongside its base-game and Studio inputs."""
    for path in package.glob("*.u*"):
        (work / "inputs" / path.name).symlink_to(path.resolve())
    data = {}
    for key, rel in (("levels", "Unit/LevelParameter/DT_UnitLevelParameterList"),
                     ("units", "Unit/DT_UnitParameter"), ("skills", "Skill/DT_SkillData")):
        data[key] = export_json(work / "inputs", "/Game/Datatable/" + rel, work / (key + "-cooked.json"))["Rows"]
    missing = [k for k, v in data["levels"].items() if not v.get("DataTable")]
    if missing:
        raise ValueError(f"Cooked growth-table references are missing: {missing}")
    skills = {row["ID"]: row for row in data["skills"].values()}
    for unit in UNITS:
        actual = data["units"][unit["row"]]
        if actual["Name"].get("CultureInvariantString") != unit["name"] or actual["LevelParamId"] != unit["levelId"]:
            raise ValueError(f"{unit['name']}: cooked party tables lost priority")
        if skills[unit["attack"]]["SortId"] != skills[401010]["SortId"]:
            raise ValueError(f"{unit['name']}: Attack command ordering differs from the native attack")
        if actual["BattleVoiceLabel"] != data["units"][unit["voiceRow"]]["BattleVoiceLabel"]:
            raise ValueError(f"{unit['name']}: cooked party voice differs from the selected native voice")
    return {"growthReferencesResolved": len(data["levels"]), "partyTablePriority": True, "attackCommandOrder": True,
            "battleVoices": {u["name"]: data["units"][u["row"]]["BattleVoiceLabel"] for u in UNITS}}


def native_motion(name):
    low = name.lower()
    if "death" in low or low == "dead":
        return "dead"
    if low in ("dying", "damage", "sleep"):
        return "dying"
    if "win" in low or "rankup" in low:
        return "win" if "loop" in low else "winbefore+win"
    if "step" in low or "move" in low or "back" in low or "dash" in low:
        return "move"
    if "magic_idle" in low or "anticipation" in low or "awaken" in low:
        return "magic_standby"
    if "magic" in low or low.startswith("m_attack"):
        return "magicatk"
    if low.startswith("lb"):
        return "limitatk"
    if "attack" in low or "atk" in low or "bunshinken" in low:
        return "atk"
    if "jump" in low:
        return "jump"
    if low in ("command", "cushion", "cushion_pose", "lock", "action"):
        return "standby"
    return "idle"


def party_sheet(unit):
    atlas, frames, animations = load_unit(str(ROOT / "build/ffbe_cpk/jp_live_dec"), unit["form"])

    def rect(part):
        return tuple(part[k] for k in ("imgX", "imgY", "imgW", "imgH", "pageId"))

    # Remove only the persistent aura cells identified in idle. Other sword
    # trails and spell effects remain available in their attack animations.
    aura = {rect(p) for step in animations["idle"] for p in frames[step["frame"]]
            if p["blendMode"] == 1 or (unit["key"] == "helena" and p["opacity"] == 50)}
    frames = [[p for p in frame if rect(p) not in aura] for frame in frames]

    def timed(steps, duration):
        # Rain's native attack plays three separate motions for 20, 12, 16
        # frames. Split the FFBE attack across them instead of restarting it.
        if not steps or len(steps) > duration:
            raise ValueError("Attack phase does not fit the native sequence")
        lengths = [s["delay"] for s in steps]
        remaining = duration - len(steps)
        boundaries = [round(sum(lengths[:i]) / sum(lengths) * remaining) for i in range(len(steps) + 1)]
        return [{**s, "delay": 1 + boundaries[i + 1] - boundaries[i]} for i, s in enumerate(steps)]

    first, second = unit["attackCuts"]
    attack = animations["atk"]
    for name, steps, duration in (("party_windup", attack[:first], 20),
                                  ("party_attack", attack[first:second], 12),
                                  ("party_recovery", attack[second:], 16)):
        animations[name] = timed(steps, duration)
    return sprites.Sheets((atlas, frames, animations)), sorted(aura)


def build_sprite(unit, legacy, assets, work, native):
    sheet, aura = party_sheet(unit)
    report = {}
    for kind, folder, default_anims in (("battle", "Unit", sprites.BATTLE_ANIMS),
                                         ("menu", "menu", sprites.MENU_ANIMS)):
        project = native[kind]["Properties"]["AnimeList"][0]
        animations = dict(default_anims)
        if kind == "battle":
            animations["anticipation2"] = "magic_standby"  # Native Dystopia caster pose
        for anim in project["AnimeList"]:
            name = anim["AnimationName"]
            if name != "Setup":
                animations.setdefault(name, native_motion(name))
        if kind == "battle":
            animations.update(anticipation_1="party_windup", attack_A="party_attack", attack_A_pose="party_recovery")
        atlas, spec = sprites.build(sheet, list(animations.items()), unit["sprite"], 4096)
        # Rain's model calls its drawable part 'unit'; FFBE already includes the
        # weapon, so suppress the donor's separate weapon and baked sprite layers.
        for animation in spec["animations"]:
            parts = animation["parts"]
            parts["unit"] = parts.pop("part_0")
            parts["weapon"] = {"Hide": [[0, 1.0]]}
            parts["bake"] = {"Hide": [[0, 1.0]]}
            parts["position"] = {"Posx": [[0, 0.0]], "Posy": [[0, 0.0]], "Sclx": [[0, 1.0]], "Scly": [[0, 1.0]]}
        name = unit["sprite"]
        spec.update(cellmapName=name, animePackName=name, imagePath=name + "_tex.png")
        target = work / "sprites" / unit["key"] / kind
        target.mkdir(parents=True)
        atlas.save(target / "atlas.png")
        sprites.write_bgra(atlas, target / "tex.bgra")
        write_json(target / "spec.json", spec)
        old = f"Chara/{folder}/unit0010/unit0010"
        new = f"Chara/{folder}/{name}/{name}"
        dt("make-ss6", legacy / "FFRS/Content" / (old + ".uasset"), target / "spec.json",
           assets / "FFRS/Content" / (new + ".uasset"), "/Game/" + old, "/Game/" + new, f"unit0010={name}")
        dt("make-texture", legacy / "FFRS/Content" / (old + "_tex.uasset"), target / "tex.bgra", *atlas.size,
           assets / "FFRS/Content" / (new + "_tex.uasset"), "/Game/" + old + "_tex", "/Game/" + new + "_tex", f"unit0010={name}")
        if kind == "battle":
            sprites.write_flat_bc5(*atlas.size, sprites.FLAT_NORMAL, target / "normal.bc5")
            sprites.write_flat_bgra(*atlas.size, sprites.FLAT_MREO, target / "mreo.bgra")
            for suffix, payload in (("_normal", "normal.bc5"), ("_mreo", "mreo.bgra")):
                dt("make-texture", legacy / "FFRS/Content" / (old + suffix + ".uasset"), target / payload, *atlas.size,
                   assets / "FFRS/Content" / (new + suffix + ".uasset"), "/Game/" + old + suffix,
                   "/Game/" + new + suffix, f"unit0010={name}")
        report[kind] = {"animations": animations, "atlas": list(atlas.size), "project": "/Game/" + new,
                        "removedAuraCells": aura}
    return report


def build_portraits(unit, legacy, assets, work):
    art = Image.open(ROOT / "party" / (unit["key"] + ".webp")).convert("RGBA")
    output = work / "portraits" / unit["key"]
    output.mkdir(parents=True)
    full = Image.new("RGBA", (512, 1024))
    scale, center, top = unit["portrait"]
    enlarged = art.resize((round(art.width * scale), round(art.height * scale)), Image.Resampling.LANCZOS)
    full.alpha_composite(enlarged, (round(256 - center * scale), top))
    # Native buttons fill the left ~340 pixels; eye strips occupy x=112..560.
    # Filling the entire eye texture stretched the face across the battle menu.
    button = Image.new("RGBA", (512, 128))
    detail = art.crop(unit["button"]).resize((341, 128), Image.Resampling.LANCZOS)
    fade = Image.new("L", detail.size)
    fade.putdata([round(255 * min(1, max(0, (341 - x) / 64)) * min(1, max(0, (128 - y) / 20)))
                  for y in range(128) for x in range(341)])
    detail.putalpha(ImageChops.multiply(detail.getchannel("A"), fade))
    button.alpha_composite(detail)
    eye = Image.new("RGBA", (1024, 128))
    eye.alpha_composite(art.crop(unit["eye"]).resize((448, 84), Image.Resampling.LANCZOS), (112, 0))
    # Match the native timeline's small pixel-art head and diamond silhouette.
    face = Image.new("RGBA", (128, 128))
    draw = ImageDraw.Draw(face)
    draw.polygon([(64, 3), (125, 64), (64, 125), (3, 64)], fill="#b7b8b6")
    draw.polygon([(64, 9), (119, 64), (64, 119), (9, 64)], fill="#382e4c")
    sheet, _ = party_sheet(unit)
    idle = sheet.compose("a", sheet.anims("a")["idle"][0]["frame"])
    head = idle.crop(tuple(512 + v for v in unit["spriteFace"])).resize((90, 90), Image.Resampling.NEAREST)
    face.alpha_composite(head, (19, 12))
    templates = {"portrait": (full, f"UI/Textures/Picture/Char/Long/T_Chara_Menu_long_{unit['id']}"),
                 "button": (button, f"UI/Textures/Picture/Char/T_Chara_Button_{unit['id']}"),
                 "eye": (eye, f"UI/Textures/Picture/Char/T_Chara_EYE_{unit['id']}"),
                 "icon": (face, f"UI/Textures/Icon/Unit_Face_Timeline/ICON_UnitFace_unit{unit['id']}")}
    donor = "UI/Textures/Icon/Unit_Face_Timeline/ICON_UnitFace_unit1001"
    for kind, (image, path) in templates.items():
        image.save(output / (kind + ".png"))
        payload = output / (kind + ".bgra")
        sprites.write_bgra(image, payload)
        dt("make-texture", legacy / "FFRS/Content" / (donor + ".uasset"), payload, *image.size,
           assets / "FFRS/Content" / (path + ".uasset"), "/Game/" + donor, "/Game/" + path,
           "ICON_UnitFace_unit1001=" + path.split("/")[-1])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game", default=ffrenv.detect_game())
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--save", type=Path, action="append", help="Explicit GameSaveData save to update; repeatable")
    parser.add_argument("--keep-saves", action="store_true", help="Rebuild the assets without changing saves")
    args = parser.parse_args()
    if not ffrenv.is_game_root(args.game):
        parser.error("A valid demo installation is required")
    paks = Path(args.game) / "FFRS/Content/Paks"
    work = ROOT / "build/party-members" / datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    work.mkdir(parents=True)
    assets = work / "assets"
    assets.mkdir()
    print("Preparing current game and vision tables", flush=True)
    legacy, installed = extract_sources(paks, work)
    tables = {rel: rows(legacy, work, rel) for rel in TABLES}
    for rel, data in tables.items():
        if "UnknownExport" in json.dumps(data):
            raise ValueError(f"Unresolved native asset reference in {rel}")
    native = {kind: export_json(paks, f"/Game/Chara/{folder}/unit0010/unit0010", work / ("rain-" + kind + ".json"))
              for kind, folder in (("battle", "Unit"), ("menu", "menu"))}
    patch = {"legacyRoot": str(legacy), "outRoot": str(assets), "tables": []}
    edits = {}

    def table(rel):
        if rel not in edits:
            edits[rel] = {"asset": "FFRS/Content/Datatable/" + rel, "add": [], "set": []}
            patch["tables"].append(edits[rel])
        return edits[rel]

    def add(rel, name, donor, values):
        table(rel)["add"].append({"row": name, "cloneFrom": donor, "set": values})

    def key_for(rel, uid):
        return next(k for k, value in tables[rel].items() if value.get("ID") == uid)

    def skill(uid, donor, name, changes):
        row_name = f"PrivateParty_{uid}"
        values = {"ID": uid, "SortId": uid, "Name": name, "hasUnit": "All", **changes}
        add("Skill/DT_SkillData", row_name, key_for("Skill/DT_SkillData", donor), values)
        for rel in ("Asset/Skill/DT_SkillAsset", "Asset/Skill/CDT_SkillAsset_Demo"):
            found = False
            for offset in (0, 1, 2):
                source = next((k for k, v in tables[rel].items() if v.get("ID") == donor + offset), None)
                if source:
                    add(rel, row_name + f"_{offset}", source, {"ID": uid + offset})
                    found = True
            if not found:
                raise ValueError(f"No native sequence for {donor}")
        rel = "Battle/Sequencer/DT_BtlHitEffectData"
        source = next((k for k, v in tables[rel].items() if v.get("ID") == donor), None)
        if source:
            add(rel, row_name, source, {"ID": uid})

    skill(BLAST, 445020, "Raegen Blast", {"Description": "Instantly staggers all enemies. Deals no damage.",
        "belongCommandList": [1], "magnification": 0, "breakDamageValue": 9999, "accuracy": 500, "Cost": 0,
        "element": "Thunder", "SkillIcon.TagName": "UI.Skill.Action.Icon.Thunder",
        "effectBundleList[0].effectId": -1, "effectBundleList[1].effectId": -1, "totalDamageDisplayRule": "Hidden"})
    skill(798720, 445020, "Sacred Wave", {"belongCommandList": [1], "Cost": 12})
    # The demo omits Dark/Darkra/Darkga sequences. Its opening Dystopia has
    # working dark effects; its caster poses are included in both sprite projects.
    skill(798820, 408050, "Dark Pulse", {"belongCommandList": [1], "Cost": 5,
        "magnification": 17, "TargetType": "Single", "Description": "Deals dark magic damage to one enemy."})
    skill(798830, 408050, "Dystopia", {"belongCommandList": [1], "Cost": 18})
    sprite_report = {}
    for unit in UNITS:
        print(f"Building {unit['name']} sprites and portraits", flush=True)
        sprite_report[unit["key"]] = build_sprite(unit, legacy, assets, work, native)
        build_portraits(unit, legacy, assets, work)
        skill(unit["attack"], 401010, "Attack", {"element": unit["element"], "belongCommandList": [-1],
              "SortId": tables["Skill/DT_SkillData"][key_for("Skill/DT_SkillData", 401010)]["SortId"],
              "DamageType": "Magic" if unit["key"] == "helena" else "Physic",
              "damageCalcType": "Magic" if unit["key"] == "helena" else "Physic"})
        name, uid, row = unit["name"], unit["id"], unit["row"]
        add("Unit/DT_UnitParameter", row, "レイン", {"ID": uid, "SaveId": uid, "SortId": uid,
            "Name": name, "Description": f"{unit['element']} party member for vision testing.", "Sex": unit["sex"],
            "LevelParamId": unit["levelId"], "FaceIconId": uid,
            "BattleVoiceLabel": tables["Unit/DT_UnitParameter"][unit["voiceRow"]]["BattleVoiceLabel"]})
        add("Unit/DT_PlayableUnitParameter", row, "レイン", {"ID": uid,
            "attackType": "Magic" if unit["key"] == "helena" else "Physic", "roles": ["eUnitRole::" + unit["role"]]})
        add("Unit/DT_UnitBattleCmd", row, "レイン", {"ID": uid, "detailData[0].SkillId": unit["attack"]})
        add("Battle/Unit/DT_BtlUnitDesignParameter", row, "レイン", {"ID": uid, "Scale": unit["battleScale"]})
        sprite = f"/Game/Chara/Unit/{unit['sprite']}/{unit['sprite']}"
        add("Asset/Battle/Unit/DT_BtlUnitAsset", row, "レイン", {"ID": uid,
            **{"animationAssetList[0]." + key: sprite + suffix for key, suffix in
               (("Ss6Project", ""), ("textureBaseColor", "_tex"), ("textureNormal", "_normal"), ("textureMetallicRoughness", "_mreo"))}})
        add("Asset/Battle/Unit/DT_BtlPlayableUnitAsset", row, "レイン", {
            key: sprite + suffix for key, suffix in (("Ss6Project", ""), ("textureBaseColor", "_tex"),
               ("textureNormal", "_normal"), ("textureMetallicRoughness", "_mreo"))})
        source = "Unit/LevelParameter/Playable/DT_UnitLevelParameterRain"
        destination = f"Unit/LevelParameter/Playable/DT_PrivateParty_{name}"
        source_asset = legacy / "FFRS/Content/Datatable" / (source + ".uasset")
        dest_asset = legacy / "FFRS/Content/Datatable" / (destination + ".uasset")
        dt("clone-package", source_asset, dest_asset, "/Game/Datatable/" + source, "/Game/Datatable/" + destination,
           f"DT_UnitLevelParameterRain=DT_PrivateParty_{name}")
        level_rows = rows(legacy, work, destination)
        tables[destination] = level_rows
        table(destination)["set"] = [{"row": key, "set": {"AddSkills": []}} for key in level_rows]
        level_list = "Unit/LevelParameter/DT_UnitLevelParameterList"
        add(level_list, f"PrivateParty_{name}", key_for(level_list, 1), {"ID": unit["levelId"], "DataTable": "/Game/Datatable/" + destination})

    write_json(work / "patch.json", patch)
    print("Writing and checking party tables", flush=True)
    (work / "patch.log").write_text(dt("patch", work / "patch.json"), encoding="utf-8")
    checked = {}
    authored = {}
    for rel, edit in edits.items():
        actual = rows(assets, work / "verification", rel)
        authored[rel] = actual
        changed = {item["row"] for key in ("set", "add") for item in edit[key]}
        for key, value in tables[rel].items():
            if key not in changed and not equivalent(value, actual.get(key)):
                raise ValueError(f"Unrelated row changed: {rel}/{key}")
        for key in changed:
            if key not in actual:
                raise ValueError(f"Missing authored row: {rel}/{key}")
        checked[rel] = {"rows": len(actual), "edited": sorted(changed), "unrelatedRowsUnchanged": True}
    skills_by_id = {v["ID"]: v for v in authored["Skill/DT_SkillData"].values()}
    for unit in UNITS:
        for uid in unit["skills"]:
            skill_row = skills_by_id[uid]
            sequence_id = skill_row["playSequencerId"]
            candidates = {sequence_id} if sequence_id > 0 else {uid, uid + 1, uid + 2}
            for rel in ("Asset/Skill/DT_SkillAsset", "Asset/Skill/CDT_SkillAsset_Demo"):
                if not any(v["ID"] in candidates and v.get("LevelSequence") for v in authored[rel].values()):
                    raise ValueError(f"{unit['name']}: skill {uid} has no playable sequence in {rel}")
    saves = []
    if not args.keep_saves:
        selected = args.save or sorted((Path(os.environ["LOCALAPPDATA"]) / "FFRS_DEMO/Steam").glob("*/GameSaveData*.sav"))
        if not selected:
            raise ValueError("No demo progress saves found; use --save or --keep-saves")
        config = ROOT / "extracted/pak/FFRS/Config/DefaultSaveGameUtility.ini"
        key = re.search(r"^SaveDataEncryptionKey=(.+)$", config.read_text(), re.M).group(1).strip().encode()
        for path in selected:
            raw = path.read_bytes()
            parsed = Save(raw, key)
            rain = next(row for row in parsed.units() if row["UnitId"].integer() == 1001)
            experience = rain["Experience"].integer()
            hp = tables["Unit/DT_UnitParameter"]["レイン"]["MaxHitPoint"]
            mp = tables["Unit/DT_UnitParameter"]["レイン"]["MaxMagicPoint"]
            accumulated = 0
            for growth in sorted(tables["Unit/LevelParameter/Playable/DT_PrivateParty_Raegen"].values(), key=lambda r: r["Level"]):
                accumulated += growth["RequiredExperience"]
                if accumulated > experience:
                    break
                hp += growth["AddMaxHitPoint"]
                mp += growth["AddMaxMagicPoint"]
            save_units = [{**unit, "startingHp": hp, "startingMp": mp} for unit in UNITS]
            result, report = add_test_party(raw, key, save_units)
            staged = work / "saves" / path.parent.name / path.name
            staged.parent.mkdir(parents=True, exist_ok=True)
            staged.write_bytes(result)
            saves.append({"path": str(path), "staged": str(staged), "sha256": hashlib.sha256(raw).hexdigest(),
                          "newSha256": sha(staged), **report})
    package = work / "package"
    package.mkdir()
    print("Packing the local party addon", flush=True)
    (work / "pack.log").write_text(run([ffrenv.RETOC, "to-zen", "--version", "UE5_6", assets, package / (STEM + ".utoc")]), encoding="utf-8")
    cooked_check = check_cooked(work, package)
    result = {"work": str(work), "sourceMods": installed, "units": UNITS, "sprites": sprite_report,
              "tables": checked, "cookedReadback": cooked_check, "saves": saves, "gameplay": "Pending user test",
              "package": {p.name: {"bytes": p.stat().st_size, "sha256": sha(p)} for p in package.iterdir()}}
    if args.install:
        if ffrenv.game_running():
            write_json(work / "verification.json", result)
            raise RuntimeError("The package is ready. Close the game before installing it: " + str(work))
        for source in installed:
            path = Path(source["file"])
            if sha(path) != source["sha256"] or sha(path.with_suffix(".ucas")) != source["ucasSha256"]:
                raise RuntimeError("The Studio package changed while building; rebuild the party addon")
        for save in saves:
            if sha(Path(save["path"])) != save["sha256"]:
                raise RuntimeError("A save changed while building; rebuild before installing")
        backup = work / "backup"
        target = paks / "~mods"
        target.mkdir(exist_ok=True)
        for path in package.iterdir():
            destination = target / path.name
            if destination.exists():
                folder = backup / "mod"
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, folder / path.name)
        for save in saves:
            path = Path(save["path"])
            destination = backup / "saves" / path.parent.name / path.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        for path in package.iterdir():
            shutil.copy2(path, target / path.name)
            assert sha(path) == sha(target / path.name)
        for save in saves:
            shutil.copy2(save["staged"], save["path"])
            assert sha(Path(save["path"])) == save["newSha256"]
        result.update(installed=str(target), backup=str(backup))
    write_json(work / "verification.json", result)
    write_json(ROOT / "build/party-members/latest.json", result)
    print("Ready:", work, flush=True)


if __name__ == "__main__":
    main()
