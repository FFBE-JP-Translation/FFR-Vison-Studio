r"""ffr_catalog.py - everything the dev UI needs to know about FF Resonance, from extracted/rows + locres + the container listing.

Writes build/devui/ffr_catalog.json (skills, passives, effects, visions, icons, motions, Niagara effects, sequences, enums) and
exports the skill / element icon textures to build/devui/icons/<texture>.png with ffr-export. Re-run after extracting a new
game build (the full game installs over the demo): python tools/devui/ffr_catalog.py [--force-icons]
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROWS = os.path.join(ROOT, "extracted", "rows")
OUT = os.path.join(ROOT, "build", "devui")
ICONS = os.path.join(OUT, "icons")
EXPORT = os.path.join(ROOT, "src", "ffr-export", "bin", "Release", "net10.0", "ffr-export.dll")
ENUMS_HPP = os.path.join(ROOT, "extracted", "CXXHeaderDump", "mucha_enums.hpp")
UTOC = os.path.join(ROOT, "extracted", "utoc_filelist.tsv")

# FFR motion names of a converted vision project and the FFBE animation each one is built from (tools/ffbe2ss6/build_sprites.py)
MOTIONS = [
    ("idle", "idle"), ("command", "standby"), ("Lock", "standby"), ("cushion", "standby"),   # command = selected for an action: FFBE battle-ready pose ("step_front", "move"), ("step_back", "move"),
    ("attack_A", "atk"), ("attack_B", "atk"), ("attack_C", "atk"), ("attack_D", "atk"), ("attack_E", "atk"),
    ("M_attack01", "magicatk"), ("M_attack02", "magicatk"), ("magic_idle", "magic_standby"), ("magic_attack", "magicatk"),
    ("LB1_before", "magic_standby"), ("LB1", "limitatk"), ("jump", "jump"), ("dying", "dying"), ("dead", "dead"),
    ("win", "winbefore+win"), ("win_Loop", "win"), ("Rankup", "winbefore+win"), ("Rankup_Loop", "win"),
]
# motions a custom skill can ask its unit for (the sequence's UnitPlayAnimByName events are rewritten to this name)
SKILL_MOTIONS = ["attack_A", "M_attack01", "M_attack02", "magic_attack", "magic_idle", "LB1", "jump", "step_front"]

sys.path.insert(0, os.path.join(ROOT, "tools")); import ffrenv
def rows(rel):
    p = os.path.join(ROWS, rel + ".json")
    if not os.path.exists(p):   # tables outside the original dump: convert the legacy asset on demand
        legacy = os.path.join(ROOT, "extracted", "legacy", "FFRS", "Content", "Datatable", rel + ".uasset")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        subprocess.run(ffrenv.FFRDT + ["rows", legacy, p, "--usmap", ffrenv.USMAP], capture_output=True, text=True, env=dict(os.environ, MSYS_NO_PATHCONV="1"))
    return json.load(open(p, encoding="utf-8"))["rows"]

def enum_values(name):
    src = open(ENUMS_HPP, encoding="utf-8", errors="ignore").read()
    m = re.search(r"enum class %s\b[^{]*\{(.*?)\};" % re.escape(name), src, re.S)
    if not m: return []
    out = []
    for part in m.group(1).split(","):
        part = part.strip()
        if not part or "_MAX" in part: continue
        nm = part.split("=")[0].strip()
        if nm in ("Num",): continue
        out.append(nm)
    return out

def utoc_paths():
    out = []
    for l in open(UTOC, encoding="utf-8"):
        if "\t" not in l: continue
        p = l.split("\t")[1].strip().replace("../../../FFRS/Content/", "")
        out.append(p)
    return out

def texture_path(paths, name):
    for p in paths:
        if p.endswith("/" + name + ".uasset") and p.startswith("UI/"):
            return "/Game/" + p[:-7]
    return None

def export_icon(pkg, name, force=False):
    os.makedirs(ICONS, exist_ok=True)
    png = os.path.join(ICONS, name + ".png")
    if os.path.exists(png) and not force: return png
    if not os.path.exists(EXPORT):      # the packaged app ships the icons in data/icons (placed by setup.py); no CUE4Parse there
        return None
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    r = subprocess.run(["dotnet", EXPORT, "tex", pkg, png], capture_output=True, text=True, env=env)
    if r.returncode != 0 or not os.path.exists(png):
        print("  icon export failed:", name, (r.stderr or r.stdout)[-200:]); return None
    return png

def build(force_icons=False):
    loc = json.load(open(os.path.join(ROOT, "extracted", "locres_en.json"), encoding="utf-8"))
    def tx(ns, key, fallback=None):
        v = (loc.get(ns) or {}).get(key)
        return v if v else fallback
    paths = utoc_paths()
    seq_rows = rows("Asset/Skill/DT_SkillAsset"); seq_by_id = {v["ID"]: v for v in seq_rows.values()}
    hit_ids = {v["ID"] for v in rows("Battle/Sequencer/DT_BtlHitEffectData").values()}
    skills = []
    for k, v in rows("Skill/DT_SkillData").items():
        i = v["ID"]; offs = [o for o in (0, 1, 2) if i + o in seq_by_id]
        skills.append({
            "id": i, "row": k, "name": tx("ST_SkillName", f"SkillName{i}", k), "desc": tx("ST_SkillDescription", f"SkillDescription{i}", ""),
            "attr": v["skillAttrType"], "effectType": v["skillEffectType"], "dmgType": v["DamageType"], "calcType": v["damageCalcType"],
            "element": v["element"], "target": v["TargetType"], "relation": v["defaultTargetRelation"], "cost": v["Cost"], "mag": v["magnification"],
            "breakDmg": v["breakDamageValue"], "accuracy": v["accuracy"], "hits": v["hitCount"], "ratios": [r for r in v["hitDamageRatioList"] if r],
            "icon": v["SkillIcon"]["TagName"], "effects": [e["effectId"] for e in v["effectBundleList"] if e["effectId"] != -1],
            "seq": offs, "seqPath": seq_by_id[i + offs[0]]["LevelSequence"] if offs else None, "hit": i in hit_ids, "hasUnit": v["hasUnit"],
        })
    passives = []
    for k, v in rows("Skill/DT_PassiveSkillData").items():
        i = v["ID"]
        passives.append({"id": i, "row": k, "name": tx("ST_PassiveSkillName", f"PassiveSkillName{i}", k), "desc": tx("ST_PassiveSkillDescription", f"PassiveSkillDescription{i}", ""),
                         "icon": v["SkillIcon"]["TagName"], "effects": [e["effectId"] for e in v["effectBundleList"] if e["effectId"] != -1], "equipCost": v.get("equipCost")})
    effects = []
    for k, v in rows("Skill/DT_SkillEffectData").items():
        effects.append({"id": v["ID"], "row": k, "type": v["EffectType"], "params": v.get("ParamList"), "status": v.get("statusCondition"), "prob": v.get("addProbability")})
    # fill passive / skill descriptions' {Effect1Param1} placeholders from the first effect's params when possible
    eff_by = {e["id"]: e for e in effects}
    def fill(desc, eff_ids):
        def rep(m):
            n, p = int(m.group(1)), int(m.group(2))
            try:
                e = eff_by[eff_ids[n - 1]]; return str(e["params"][p - 1])
            except Exception: return m.group(0)
        return re.sub(r"\{Effect(\d+)Param(\d+)\}", rep, desc or "")
    for p in passives: p["desc"] = fill(p["desc"], p["effects"])
    for s in skills: s["desc"] = fill(s["desc"], s["effects"])
    # visions
    lvl = {v["ID"]: v["DataTable"] for v in rows("Unit/LevelParameter/DT_UnitLevelParameterList").values()}
    units = {v["ID"]: v for v in rows("Unit/DT_UnitParameter").values()}
    visions = []
    for k, v in rows("Item/Vision/DT_VisionItemData").items():
        i = v["ID"]; u = units.get(i, {})
        visions.append({"id": i, "row": k, "name": tx("ST_VisionName", f"VisionName{i}", k), "finishBlow": v["finishBlowSkill"], "commandId": v["CommandId"],
                        "attackType": v["attackType"], "roles": v["roles"], "levelParamId": u.get("LevelParamId"), "levelTable": lvl.get(u.get("LevelParamId")),
                        "stats": {x: u.get(x) for x in ("MaxHitPoint", "MaxMagicPoint", "Attack", "Defence", "Intelligence", "Mind", "Agility")},
                        "elemRes": u.get("ElementResistanceList")})
    # icons: action + command tags -> texture -> png
    icons = []
    seen = set()
    for rel in ("UI/Skill/CDT_SkillIcon", "UI/Skill/DT_ActionSkillIcon", "UI/Skill/DT_CommandSkillIcon"):
        try: tbl = rows(rel)
        except FileNotFoundError: continue
        for k, v in tbl.items():
            tag = v["Tag"]["TagName"]; tex = v["Brush"].get("ResourceObject")
            if tag in seen: continue
            seen.add(tag)
            png = None
            if tex:
                pkg = texture_path(paths, tex)
                if pkg: png = export_icon(pkg, tex, force_icons)
            icons.append({"tag": tag, "row": k, "texture": tex, "png": os.path.basename(png) if png else None})
    niagara = sorted("/Game/" + p[:-7] for p in paths if p.startswith("Effect/") and "/NS_" in p and p.endswith(".uasset") and (p.startswith("Effect/03_SKL/") or p.startswith("Effect/04_BTL/")))
    skill_by = {s["id"]: s for s in skills}
    sequences = []
    for k, v in seq_rows.items():
        sid = v["ID"]; base = next((sid - o for o in (0, 1, 2) if (sid - o) in skill_by), None)
        sequences.append({"seqId": sid, "skillId": base, "name": skill_by[base]["name"] if base else k, "row": k, "path": v["LevelSequence"], "sound": v["soundSequence"]})
    lb_templates = [s for s in skills if s["attr"] == "FinishBlow" and s["seq"]]
    # screen tints: PostSetColorGradingGlobalParameter events reference these presets (1 = the blue Blizzard tint of Hibernal Fury)
    color_grading = sorted(({"id": v["ID"], "name": k} for k, v in rows("PostProcess/DT_ColorGradingParameter").items()), key=lambda x: x["id"])
    enums = {n: enum_values(n) for n in ("eElement", "eSkillTargetType", "eSkillAttributeType", "eSkillDamageType", "eSkillDamageCalcType", "eUnitRole",
                                          "eResistance", "eRelation", "eVisionMasteryParameterType", "eUnitParameterType", "eSkillEffectType", "eBtlSequenceEventType")}
    # awakening mastery: per vision, one row per tier (Level 0..3) with up to 8 grants each
    aw_rows = {}
    try:
        for k, v in rows("Item/Vision/DT_VisionAwakeningMasteryData").items():
            grants = []
            for d in v.get("detailData") or []:
                t = d.get("parameterType"); pr = d.get("params") or []
                if t in (None, "None") or not pr or pr[0] in (-1, None): continue
                grants.append([t, pr[0]] + ([pr[1]] if t == "BaseParameter" and len(pr) > 1 and pr[1] not in (-1, None) else []))
            aw_rows.setdefault(v["ID"], []).append((v.get("Level", 0), grants))
    except Exception as ex:
        print("awakening rows unavailable:", ex)
    for vis in visions:
        tiers = [g for _, g in sorted(aw_rows.get(vis["id"], []), key=lambda x: x[0])]
        vis["awakening"] = (tiers + [[], [], [], []])[:4]
    cat = {"schema": SCHEMA, "skills": skills, "passives": passives, "effects": effects, "visions": visions, "icons": icons, "niagara": niagara, "sequences": sequences, "studioSkills": STUDIO_SKILLS,
           "lbTemplates": [{"id": s["id"], "name": s["name"], "target": s["target"], "relation": s["relation"], "dmgType": s["dmgType"], "hits": s["hits"], "seqPath": s["seqPath"],
                            **TEMPLATE_NOTES.get(s["id"], {"good": None, "window": None, "length": None, "who": None, "blurb": None})} for s in lb_templates if s["id"] not in (440010, 440090, 440110)],
           "motions": [{"name": a, "ffbe": b} for a, b in MOTIONS], "skillMotions": SKILL_MOTIONS, "targetEffects": TARGET_EFFECTS, "enums": enums, "colorGrading": color_grading,
           "ffbeResonance": {"defaultFieldColor": "#808080", "lbProfiles": True, "audio": True},
           "unusedIconTags": [13104, 13106, 13107, 13109, 13111, 13112, 13114, 13115, 13117, 13119, 13121, 13122, 13126, 13129, 13131, 13132]}
    os.makedirs(OUT, exist_ok=True)
    json.dump(cat, open(os.path.join(OUT, "ffr_catalog.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print(f"ffr catalog: {len(skills)} skills ({sum(1 for s in skills if s['seq'])} with sequences), {len(passives)} passives, {len(effects)} effects, "
          f"{len(visions)} visions, {len(icons)} icons, {len(niagara)} Niagara systems, {len(sequences)} sequences, {len(lb_templates)} Resonance templates")
    return cat

SCHEMA = 9   # native LB audio and CG-free imported resonance choices

# Moves the studio provides beyond the game's own abilities: a recipe cloned into the unit's own skill range when granted.
STUDIO_SKILLS = [
    {"key": "raegen_blast", "name": "Raegen Blast", "desc": "Staggers every enemy instantly. No damage.", "group": "Studio moves",
     "recipe": {"from": 445020, "visuals": 445020, "set": {"magnification": 0, "breakDamageValue": 9999, "accuracy": 500, "Cost": 0, "element": "Thunder",
                                                          "SkillIcon.TagName": "UI.Skill.Action.Icon.Thunder", "effectBundleList[0].effectId": -1, "effectBundleList[1].effectId": -1,
                                                          "totalDamageDisplayRule": "Hidden"}},
     "note": "Sacred Wave's sequence (all enemies, Light, break 25) with the damage removed and the break value raised past any stagger bar."},
]

# What each Resonance animation template does to a ported unit. `window` = seconds the unit's own limit-burst motion (LB1) gets
# before the next motion key; `good` = the unit's motion is actually played. Measured from the game's Cut tracks, docs/09 section 4.
# What a Resonance built on an owner's cinematic can put on the targets in place of the owner's own hits: the demo's
# elemental bursts, taken from the magic that plays them on every target position (PosAll / Center systems).
TARGET_EFFECTS = [
    {"key": "none", "name": "Nothing extra (the hits still land)", "element": None, "path": None},
    {"key": "fire", "name": "Fire burst", "element": "Fire", "path": "/Game/Effect/03_SKL/skl220020/NS_EF_SKL220020_PosAll"},
    {"key": "ice", "name": "Ice burst", "element": "Ice", "path": "/Game/Effect/03_SKL/skl220060/NS_EF_SKL220060_001"},
    {"key": "thunder", "name": "Thunder burst", "element": "Thunder", "path": "/Game/Effect/03_SKL/skl220100/NS_EF_SKL220100_001_PosAll"},
    {"key": "water", "name": "Water burst", "element": "Water", "path": "/Game/Effect/03_SKL/skl220140/NS_EF_SKL220140_PosAll"},
    {"key": "wind", "name": "Wind burst", "element": "Wind", "path": "/Game/Effect/03_SKL/skl220180/NS_EF_SKL220180_PosAll"},
    {"key": "earth", "name": "Earth burst", "element": "Earth", "path": "/Game/Effect/03_SKL/skl220220/NS_EF_SKL220220_PosAll"},
    {"key": "light", "name": "Light burst", "element": "Light", "path": "/Game/Effect/03_SKL/skl210260/NS_EF_SKL210260_Vanishla_001_Center"},
    {"key": "heal", "name": "Healing wind", "element": None, "path": "/Game/Effect/03_SKL/skl414100/NS_EF_SKL414100_Action_001_PosAll"},
    {"key": "keep", "name": "The animation's own effect", "element": None, "path": "keep"},
]

TEMPLATE_NOTES = {
    414090: {"good": True, "window": 5.1, "length": 6.9, "who": "random enemies",
             "blurb": "Tronn's ice storm. The unit steps forward, casts, then plays its whole limit-burst motion while five ice bursts hit random enemies. 6.9 s."},
    414100: {"good": True, "window": 2.3, "length": 4.5, "who": "all allies",
             "blurb": "Leah's healing wind. A short cast, then the unit's limit-burst motion while a healing aura plays on the party. 4.5 s; motions longer than 2.3 s stretch the timing."},
    412600: {"good": True, "window": 2.5, "length": 5.7, "who": "all allies",
             "blurb": "Charlotte's rallying stance. A command pose, then the unit's limit-burst motion with a glow on the party. 5.7 s; motions longer than 2.5 s stretch the timing."},
    440010: {"good": False, "window": 0, "length": 19.0, "who": "all enemies",
             "blurb": "Warrior of Light's crystal Resonance, 19 s. The owner's CG movie is removed from copies; the unit holds a cast pose for most of it and its own limit-burst motion is never played."},
    440090: {"good": False, "window": 0, "length": 19.2, "who": "all enemies",
             "blurb": "Terra's riot blade Resonance, 19 s. The owner's CG movie is removed from copies; the unit holds a cast pose for most of it and its own limit-burst motion is never played."},
    440110: {"good": True, "cinematic": True, "window": 4.4, "length": 10.7, "who": "one enemy",
             "blurb": "Cloud's ascension, staged without a domain. The copy drops his CG movie, his lines and his own slashes and starts at the unit's limit-burst motion: a dash to the target, the motion, the hits, about 11 s. Pick what plays on the targets below."},
}

def load():
    p = os.path.join(OUT, "ffr_catalog.json")
    cat = build() if not os.path.exists(p) else json.load(open(p, encoding="utf-8"))
    if cat.get("schema") != SCHEMA:
        try: cat = build()
        except Exception as ex: print("catalog rebuild failed, serving the cached one:", ex)
    import skill_icons
    cat['icons'] = [i for i in cat['icons'] if not i['tag'].startswith(skill_icons.PREFIX)] + skill_icons.catalog()
    aliases = skill_icons.ICONS/'aliases.json'
    cat['ffbeIconAliases'] = json.loads(aliases.read_text(encoding='utf-8')) if aliases.is_file() else {}
    return cat

if __name__ == "__main__":
    build("--force-icons" in sys.argv)
