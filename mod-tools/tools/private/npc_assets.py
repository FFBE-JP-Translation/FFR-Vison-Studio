"""Native NPC cloning and FFBE enemy SpriteStudio assets."""
from copy import deepcopy
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/ffbe2ss6")]
import ffrenv
from ffbe_frames import read_cgg, read_cgs
import build_sprites as sprites
from PIL import Image

EVENT = "Private_Battles_Menu"
MAP = "FFRS/Content/Map/Town/01Gra/01Gra_20/EV/Town_01Gra_20_EV.umap"
PERSISTENT_MAP = "FFRS/Content/Map/Town/01Gra/01Gra_20/Town_01Gra_20_PL.umap"
SCHEMAS = ["FFRS/Content/UI/Field/Object/Head/Component/WC_ObjectHead.uasset",
           "FFRS/Content/BP/Map/Unit/BP_MapUnit_NPC.uasset"]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    with path.open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def run(args):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="")
    if result.returncode:
        raise RuntimeError(f"Command failed ({result.returncode}): {args[0:2]}")
    return result.stdout


def dt(command, *args, schemas=()):
    opts = [v for p in schemas for v in ("--schema", str(p))]
    import cooked_command_cache
    return cooked_command_cache.run([*ffrenv.FFRDT, command, *args, "--usmap", ffrenv.USMAP, *opts],
                                    run, ROOT / 'build/cooked-native-cache')


def property_of(export, name):
    return next(p for p in export["Data"] if p["Name"] == name)


def set_leaf(prop, path, value):
    """Follow typed UAssetAPI properties, retaining their serialized types."""
    cur = prop
    for part in path:
        cur = cur["Value"][part] if isinstance(part, int) else next(p for p in cur["Value"] if p["Name"] == part)
    cur["Value"] = value
    cur["IsZero"] = False


def streaming_levels(data):
    """Read the cooked UWorld tail: persistent level, extra objects, stream list."""
    world = next(x for x in data["Exports"] if x["ClassIndex"] < 0 and
                 data["Imports"][-x["ClassIndex"] - 1]["ObjectName"] == "World")
    tail = base64.b64decode(world["Extras"])
    persistent, extra_count = struct.unpack_from("<ii", tail)
    if extra_count != 0:
        raise ValueError("Recheck UWorld streaming layout: extra object references are present")
    count, = struct.unpack_from("<i", tail, 8)
    if count < 0 or len(tail) != 12 + count * 4:
        raise ValueError("Unexpected cooked UWorld tail size")
    indices = list(struct.unpack_from("<" + "i" * count, tail, 12))
    if not 0 < persistent <= len(data["Exports"]) or any(not 0 < i <= len(data["Exports"]) for i in indices):
        raise ValueError("Invalid UWorld level reference")
    return world, persistent, indices


def add_battle_streaming(original, levels):
    """Register the arena's lighting and geometry like the native world map.

    battleStage selects a registered arena; it does not add missing streaming
    levels to a town's UWorld. Keep them dynamic so town mode can hide them.
    """
    data = deepcopy(original)
    world, persistent, indices = streaming_levels(data)
    paths = {property_of(data["Exports"][i-1], "WorldAsset")["Value"]["AssetPath"]["PackageName"] for i in indices}
    template = next(data["Exports"][i-1] for i in indices if data["Exports"][i-1]["ObjectName"].startswith("LevelStreamingDynamic_"))
    added = []
    for path in levels:
        if path in paths:
            continue
        ex = deepcopy(template)
        ex["ObjectName"] = "LevelStreamingDynamic_PrivateBattle" + str(len(added))
        value = property_of(ex, "WorldAsset")["Value"]["AssetPath"]
        value.update(PackageName=path, AssetName=path.rsplit("/", 1)[1])
        for name in (ex["ObjectName"], value["PackageName"], value["AssetName"]):
            if name not in data["NameMap"]:
                data["NameMap"].append(name)
        data["Exports"].append(ex)
        data["DependsMap"].append([])
        index = len(data["Exports"])
        indices.append(index)
        world["CreateBeforeSerializationDependencies"].append(index)
        paths.add(path); added.append(path)
    world["Extras"] = base64.b64encode(struct.pack("<iii", persistent, 0, len(indices)) +
                                       struct.pack("<" + "i" * len(indices), *indices)).decode("ascii")
    data["NamesReferencedFromExportDataCount"] = len(data["NameMap"])
    for i, ex in enumerate(original["Exports"]):
        if ex["ObjectName"] != world["ObjectName"] and data["Exports"][i] != ex:
            raise AssertionError("Unrelated persistent-map export changed")
    return data, added


def clone_npc(original, location, *, donor_name="BP_MapUnit_NPC_C_15",
              actor_name="BP_MapUnit_NPC_PrivateBattles", event=EVENT, unique_id=9460):
    """Clone an actor and every owned component, including delegate targets."""
    data = deepcopy(original)
    for name in (actor_name, event):
        if name not in data["NameMap"]:
            data["NameMap"].append(name)
    # JSON insertion does not call UAssetAPI's AddNameReference. IoStore keeps
    # only this prefix for serialized properties, so include our new event name.
    data["NamesReferencedFromExportDataCount"] = len(data["NameMap"])
    exports = data["Exports"]
    actor = next(i + 1 for i, e in enumerate(exports) if e["ObjectName"] == donor_name)
    owned = {actor}
    while True:
        children = {i + 1 for i, e in enumerate(exports) if e["OuterIndex"] in owned}
        if children <= owned:
            break
        owned |= children
    indices = {old: len(exports) + i + 1 for i, old in enumerate(sorted(owned))}
    reference_lists = {"SerializationBeforeSerializationDependencies", "CreateBeforeSerializationDependencies",
                       "SerializationBeforeCreateDependencies", "CreateBeforeCreateDependencies"}

    def remap(obj):
        if isinstance(obj, list):
            for v in obj:
                remap(v)
        elif isinstance(obj, dict):
            kind = obj.get("$type", "")
            if "ObjectPropertyData" in kind:
                obj["Value"] = indices.get(obj["Value"], obj["Value"])
            if kind.endswith("FDelegate, UAssetAPI"):
                obj["Object"] = indices.get(obj["Object"], obj["Object"])
            for key in ("OuterIndex", "ClassIndex", "SuperIndex", "TemplateIndex"):
                if key in obj:
                    obj[key] = indices.get(obj[key], obj[key])
            for key in reference_lists:
                if key in obj:
                    obj[key] = [indices.get(v, v) for v in obj[key]]
            for value in obj.values():
                remap(value)

    for old in sorted(owned):
        ex = deepcopy(exports[old - 1])
        if "RawExport" in ex["$type"]:
            raise ValueError(f"Missing Blueprint schema for NPC component {ex['ObjectName']}")
        remap(ex)
        exports.append(ex)
        data["DependsMap"].append([indices.get(v, v) for v in original["DependsMap"][old - 1]])
    new = exports[indices[actor] - 1]
    new["ObjectName"] = actor_name
    set_leaf(property_of(new, "m_UniqueId"), [], unique_id)
    set_leaf(property_of(new, "m_EventSettings"), ["EventList", 0, "EventList", 0, "EventId"], event)
    root = exports[property_of(new, "RootComponent")["Value"] - 1]
    vector = property_of(root, "RelativeLocation")["Value"][0]["Value"]
    vector.update(dict(zip(("X", "Y", "Z"), location)))
    level = exports[new["OuterIndex"] - 1]
    level["Actors"].append(indices[actor])
    level["CreateBeforeSerializationDependencies"].append(indices[actor])
    # The source actor and all its components must remain intact.
    for i, ex in enumerate(original["Exports"]):
        if i + 1 != new["OuterIndex"] and exports[i] != ex:
            raise AssertionError(f"Unrelated export changed: {ex['ObjectName']}")
    return data, {"actor": indices[actor], "components": len(owned) - 1, "location": location}


def build_boss_sprite(source, form, unit, work, legacy, assets):
    atlas = Image.open(source / f"monster_anime_{form}.png").convert("RGBA")
    cgg = read_cgg(source / f"monster_cgg_{form}.csv")
    idle = read_cgs(source / f"monster_idle_cgs_{form}.csv")
    attack = read_cgs(source / f"monster_atk_cgs_{form}.csv")
    sheet = sprites.Sheets((atlas, cgg, {"idle": idle, "atk": attack, "magicatk": attack}))
    names = sprites.BATTLE_ANIMS + [("damage", "idle"), ("break", "idle"), ("down", "idle"),
                                   ("attack", "atk"), ("magic", "atk"), ("anticipation2", "idle")]
    texture, spec = sprites.build(sheet, names, f"monster{unit}", 4096)
    w, h = texture.size
    sprite = work / "sprites" / form
    sprite.mkdir(parents=True)
    texture.save(sprite / "atlas.png")
    # A preview of the imported idle pose, rather than the source atlas pieces.
    frame = sheet.compose("a", idle[0]["frame"])
    frame.crop(frame.getbbox()).save(sprite / "preview.png")
    sprites.write_bgra(texture, sprite / "tex.bgra")
    sprites.write_flat_bc5(w, h, sprites.FLAT_NORMAL, sprite / "normal.bc5")
    sprites.write_flat_bgra(w, h, sprites.FLAT_MREO, sprite / "mreo.bgra")
    name = f"monster{unit}"
    spec.update(cellmapName=name, animePackName=name, imagePath=name + "_tex.png")
    dump(sprite / "spec.json", spec)
    src = "Chara/summon/summon13110/summon13110"
    dst = f"Chara/monster/{name}/{name}"
    target = assets / "FFRS/Content" / dst
    target.parent.mkdir(parents=True, exist_ok=True)
    dt("make-ss6", legacy / "FFRS/Content" / (src + ".uasset"), sprite / "spec.json",
       target.with_suffix(".uasset"), "/Game/" + src, "/Game/" + dst, f"summon13110={name}")
    for suffix, payload in [("_tex", "tex.bgra"), ("_normal", "normal.bc5"), ("_mreo", "mreo.bgra")]:
        dt("make-texture", legacy / "FFRS/Content" / (src + suffix + ".uasset"), sprite / payload,
           w, h, str(target) + suffix + ".uasset", "/Game/" + src + suffix, "/Game/" + dst + suffix,
           f"summon13110={name}")
    return "/Game/" + dst
