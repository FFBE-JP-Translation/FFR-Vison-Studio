r"""Fill vision loadouts with the shared structured ability converter.

Commands and passives retain their source snapshots. Held mechanics and
abilities beyond the loadout capacity remain in conversionReview.

python tools/devui/autoport.py <unit key> [more keys...]   (edits mods/EstherTsukiko/units.json in place)
"""
import json, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, "tools")); sys.path.insert(0, HERE)
import ffr_catalog, ffbe_catalog
from ability_converter import commands
from ability_converter.effect_policy import VERSION as EFFECT_POLICY, decisions, LABELS
from ability_converter.studio import StudioResolver
from ability_converter.skill_ids import vision_passive_base, validate_id

SPEC = os.path.join(ROOT, "mods", "EstherTsukiko", "units.json")


def unique_skill_base(vid): return 445000 + (vid - 13100) * 100


def tier_for(level):
    lvl = int(level or 1)
    return 0 if lvl <= 30 else 1 if lvl <= 60 else 2 if lvl <= 90 else 3

def ability_score(ab, profile):
    """Loadout priority uses decoded mechanics and exclusivity, never wording."""
    if not profile["supported"]:
        return -100
    result = profile["conversion"]
    action = any(c["actions"] for c in result["components"])
    return (50 if action else 25) + (20 if result["sourceMetadata"].get("unique") else 0)


def renumber(unit, vid, command_id=None):
    """move a spec to another vision id: unique skill ids, master skill, sort order and every reference to them"""
    old_base = unique_skill_base(unit["id"]); new_base = unique_skill_base(vid)
    ids = {int(k): new_base + (int(k) - old_base) for k in unit.get("skills", {})}
    old_master = unit.get("master", {}).get("id"); new_master = vid * 100
    passive_ids = {int(k): vision_passive_base(vid) + int(k) - vision_passive_base(unit['id'])
                   for k in unit.get("convertedPassives", {})}
    for value in ids.values(): validate_id('skills', value)
    for old, value in passive_ids.items():
        validate_id('passives', old); validate_id('passives', value)
    unit["skills"] = {str(ids[int(k)]): v for k, v in unit.get("skills", {}).items()}
    unit["convertedPassives"] = {str(passive_ids[int(k)]): v for k,v in unit.get("convertedPassives", {}).items()}
    def fix(grant):
        if grant and grant[0] == "ActiveSkill" and grant[1] in ids: return ["ActiveSkill", ids[grant[1]]]
        if grant and grant[0] == "MasterSkill" and grant[1] == old_master: return ["MasterSkill", new_master]
        if grant and grant[0] == "PassiveSkill" and grant[1] in passive_ids: return ["PassiveSkill", passive_ids[grant[1]]]
        return grant
    for key in ("awakening", "synchro"):
        unit[key] = [[fix(g) for g in tier] for tier in unit.get(key, [])]
    fm = unit.setdefault("ffbeMap", {"skills": {}, "passives": {}})
    fm["skills"] = {k: ids.get(v, v) for k, v in fm.get("skills", {}).items()}
    for v in fm.get("passives", {}).values():
        if isinstance(v, dict): v["grant"] = fix(v.get("grant"))
    unit["id"] = vid; unit["sort"] = vid + 70
    if "master" in unit: unit["master"]["id"] = new_master
    if command_id is not None and "command" in unit: unit["command"]["id"] = command_id
    return unit

PLATE_WORDS = ("strobe", "bg_", "_bg", "plate", "flash", "blackout", "whiteout", "screen")
# FFBE effect units -> unit sprite pixels. From the Firaga recording both the group-centre fireball and the per-target flame
# come out 1.6x larger than the file's (half-extent-doubled) numbers against a ~75 px unit, while the group offsets are 1:1
# sprite pixels; so the factor sits on the layer's `scale` (positions + sizes of the effect) and not on the offsets.
EFFECT_UNIT_SCALE = 1.6

def ffbe_effect_entries(unit, ab, skill_id, kind_override=None):
    """FFBE effect layers of an ability -> ffbe_effects entries (spawned from the cloned donor sequence at the FFBE frame).
    Skill-level group flags a:b:c (catalog.py): a = draw layer (1 front / 2 back); b = anchor: 1 each target unit, 2 the target group's
    centre (one instance, AoE), 3 the caster, 4 the screen (plates / strobes, skipped: FFR's own post effects stand in). Repeated spawns
    of one file in a group (Firaga's bm_2001_fire1 x 7, 20 frames apart) collapse into one layer with repeat / interval. Group offsets:
    x to the right, y toward the camera (down the screen in FFBE); FFR's battle camera looks along +X, so toward it is -X.
    Every layer is scaled by EFFECT_UNIT_SCALE. At most 3 layers per ability keep the first build bounded. Verified against
    the Firaga phone recording (docs/06)."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "tools", "ffbe_effects")); import catalog as fxcat
        kind = kind_override or ("magic" if ab.get("kind") == "MAGIC" else "ability")
        info = fxcat.skill_effects(kind, ab["id"])
    except Exception as ex:
        print(f"  {unit['key']}: effect lookup failed for {ab.get('name')}: {ex}"); return []
    out = []
    for g in (info or {}).get("groups") or []:
        grp = g.get("group") or {}
        flags = g.get("flags") or []
        layer = "back" if (flags[:1] == ["2"]) else "front"
        anchor = flags[1] if len(flags) > 1 else "1"
        if anchor == "4": continue
        at_target = anchor in ("1", "2")
        runs = {}
        for e in grp.get("effects") or []:
            f = e.get("file") or ""
            if not f or not e.get("exists") or any(w in f.lower() for w in PLATE_WORDS): continue
            runs.setdefault(f, []).append(e)
        for f, es in runs.items():
            es.sort(key=lambda e: e.get("frame", 0)); e = es[0]
            stem = os.path.splitext(f)[0]
            entry = {"name": f"fx_{stem}", "source": f, "id": f"fx_{stem}", "spawn": {"any": True, "index": len(out)},
                     "time": round((g.get("frame", 0) + e.get("frame", 0)) / 60.0, 2), "part": "NULL_Center",
                     "follow": not at_target, "at_target": at_target, "scale": EFFECT_UNIT_SCALE,
                     "offset": [(-80 if layer == "front" else 80) - float(e.get("y", 0)), float(e.get("x", 0)), 0.0],
                     "ffbeGroup": grp.get("name"), "anchor": anchor}
            if len(es) > 1:
                gaps = [b.get("frame", 0) - a.get("frame", 0) for a, b in zip(es, es[1:])]
                entry["repeat"] = len(es); entry["interval"] = round(sum(gaps) / len(gaps) / 60.0, 3)
            out.append(entry)
            if len(out) >= 3: return out
    return out

def add_grant(unit, tier, grant):
    for t in list(range(tier, 4)) + list(range(tier - 1, -1, -1)):
        if len(unit["awakening"][t]) < 8:
            unit["awakening"][t].append(grant); return t
    return None

def preview_entry(ab, region, resolver=None, choices=None):
    resolver = resolver or StudioResolver(ffbe_catalog)
    p = commands.profile(resolver.record(ab, region), resolver, effect_choices=choices or {})
    icon = ab.get("icon") or p["conversion"]["presentation"].get("icon")
    icon = os.path.basename(icon.replace("\\", "/")) if isinstance(icon, str) else None
    return p, {"id":ab["id"], "kind":ab.get("kind"), "name":ab.get("name"),
        "source":p["conversion"]["source"], "status":"ready" if p["supported"] else "held",
        "class":LABELS[p["conversion"]["status"]] if p["supported"] else "unsupported", "issues":p["issues"], "changes":p["warnings"],
        "snapshot":p["snapshot"], "decisions":decisions(p), "icon":icon,
        "iconUrl":"/api/ffbe/abilityicon/"+icon if icon and ffbe_catalog.ability_icon_path(icon) else None,
        "iconStatus":"available" if icon and ffbe_catalog.ability_icon_path(icon) else "missing",
        "gameplayValidation":"not_run", "effectChoices":choices or {}}


def imported_id(unit, source):
    for group in ("skills", "convertedPassives"):
        for sid, spec in unit.get(group, {}).items():
            if spec.get("ffbe", {}).get("source") == source:
                return sid
    return None


def review_existing(unit):
    """Recheck historical converter entries when the user imports a kit.

    Held recipes are archived in the draft, including their former grants.
    Hand-authored FFR abilities are outside this operation.
    """
    held = []
    for group, grant_kind in (("skills", "ActiveSkill"), ("convertedPassives", "PassiveSkill")):
        for sid, entry in list(unit.get(group, {}).items()):
            if entry.get("mechanics") != "converted" or not entry.get("conversionSource"): continue
            p = commands.from_snapshot(entry["conversionSource"], effect_choices=entry.get("effectChoices", {}))
            if p["supported"]:
                entry.update(effectPolicy=EFFECT_POLICY, conversionClass=LABELS[p["conversion"]["status"]],
                             conversionDecisions=decisions(p))
                continue
            grants = []
            for field in ("awakening", "synchro"):
                for tier, rows in enumerate(unit.get(field, [])):
                    grants.extend({"field":field,"tier":tier,"grant":g} for g in rows if g[:2] == [grant_kind,int(sid)])
                    rows[:] = [g for g in rows if g[:2] != [grant_kind,int(sid)]]
            unit.setdefault("conversionArchive", []).append({"id":sid,"entry":entry,"grants":grants})
            del unit[group][sid]
            for mapping in unit.get("ffbeMap", {}).values():
                for key, value in list(mapping.items()):
                    if value == int(sid) or isinstance(value, dict) and value.get("grant") == [grant_kind,int(sid)]:
                        del mapping[key]
            held.append({**entry.get("ffbe", {}), "source":p["conversion"]["source"], "status":"held", "class":"unsupported",
                         "issues":p["issues"], "snapshot":p["snapshot"], "decisions":decisions(p)})
    return held


def preview_kit(unit):
    base = unit.get("ffbe", {}).get("base") or unit["ffbe"]["id"][:7]+"05"
    detail = ffbe_catalog.unit_detail(base) or ffbe_catalog.unit_detail(unit["ffbe"]["id"])
    if not detail: raise ValueError("No FFBE unit data found")
    resolver = StudioResolver(ffbe_catalog)
    entries = []
    for ab in detail["abilities"] + detail["passives"]:
        try:
            _, info = preview_entry(ab, detail.get("region"), resolver)
            info["importedId"] = imported_id(unit, info["source"]["key"])
        except (ValueError, TypeError, KeyError) as ex:
            info = {"id":ab.get("id"), "kind":ab.get("kind"), "name":ab.get("name"), "status":"held",
                    "class":"unsupported", "issues":[str(ex)], "decisions":[], "iconUrl":ab.get("iconUrl")}
        info.pop("snapshot", None)
        entries.append({**info, "ability":ab})
    return {"region":detail.get("region"), "entries":entries, "policy":EFFECT_POLICY}


def import_entry(unit, ab, region, cat=None, resolver=None, resolved=None, choices=None):
    """Import one selected entry; return a review record if it cannot be bound."""
    resolver = resolver or StudioResolver(ffbe_catalog)
    try:
        p, review = resolved or preview_entry(ab, region, resolver, choices)
    except (ValueError, TypeError, KeyError) as ex:
        return {"id":ab.get("id"), "kind":ab.get("kind"), "name":ab.get("name"), "status":"held", "issues":[str(ex)]}
    if not p["supported"]:
        if p["conversion"]["status"] == "noop": review["status"] = "noop"
        return review
    passive = p["conversion"]["source"]["kind"] == "passive"
    unit.setdefault("skills", {}); unit.setdefault("convertedPassives", {})
    unit.setdefault("awakening", [[], [], [], []]); unit.setdefault("ffbeMap", {"skills":{}, "passives":{}})
    unit["ffbeMap"].setdefault("skills", {}); unit["ffbeMap"].setdefault("passives", {})
    kind = "passives" if passive else "skills"
    if imported_id(unit, p["conversion"]["source"]["key"]) is not None:
        return None
    try:
        base = vision_passive_base(unit["id"]) if passive else unique_skill_base(unit["id"])
        validate_id(kind, base); validate_id(kind, base+99)
    except ValueError as ex:
        return {**review, 'issues':[str(ex)]}
    target = unit["convertedPassives"] if passive else unit["skills"]
    used = {int(k) for k in target}
    sid = base
    while sid in used: sid += 1 if passive else 10
    if sid >= base+100:
        return {**review, "status":"loadout_full", "issues":["No native skill slot remains in this vision's loadout"]}
    tier = add_grant(unit, tier_for(ab.get("level")), ["PassiveSkill" if passive else "ActiveSkill", sid])
    if tier is None:
        return {**review, "status":"loadout_full", "issues":["No awakening grant slot remains in this vision's loadout"]}
    st = p["set"]
    entry = {"mechanics":"converted", "conversionSource":p["snapshot"],
             "effectPolicy":EFFECT_POLICY, "effectChoices":choices or {}, "conversionClass":review["class"],
             "conversionDecisions":review["decisions"],
             "conversionChanges":p["warnings"],
             "jp":f"{unit['jp']}_FFBE_{sid}", "en":ab.get("name") or str(ab["id"]),
             "desc":p["description"], "descAuto":True,
             "ffbe":{"id":ab["id"], "kind":ab.get("kind"), "name":ab.get("name"),
                     "effects":ab.get("effects"), "icon":review["icon"], "iconUrl":review["iconUrl"],
                     "source":p["conversion"]["source"]["key"]}}
    if not passive:
        native = commands.converter().native
        donor = next(i for i,name in native.skill_ids.items() if name == p["conversion"]["native"]["cloneFrom"])
        entry.update({"from":donor, "motion":"attack_A" if st["DamageType"] == "Physic" else "magic_attack", "set":st})
    target[str(sid)] = entry
    unit["ffbeMap"][kind][str(ab["id"])] = {"tier":tier, "grant":["PassiveSkill",sid], "name":entry["en"]} if passive else sid
    return None


def autoport(unit, cat=None, detail=None):
    base_id = (unit.get("ffbe") or {}).get("base") or unit["ffbe"]["id"][:7] + "05"
    detail = detail or ffbe_catalog.unit_detail(base_id) or ffbe_catalog.unit_detail(unit["ffbe"]["id"])
    if not detail: raise ValueError(f"{unit['key']}: no FFBE data for {base_id}")
    unit.setdefault("skills", {}); unit.setdefault("awakening", [[], [], [], []]); unit.setdefault("ffbeMap", {"skills": {}, "passives": {}})
    unit["ffbeMap"].setdefault("skills", {}); unit["ffbeMap"].setdefault("passives", {})
    resolver = StudioResolver(ffbe_catalog)
    pending, review = [], review_existing(unit)
    for i,ab in enumerate(detail["abilities"]):
        try:
            p, info = preview_entry(ab, detail.get("region"), resolver)
            if imported_id(unit, p["conversion"]["source"]["key"]) is not None: continue
        except (ValueError, TypeError, KeyError) as ex:
            review.append({"id":ab["id"], "kind":ab.get("kind"), "name":ab.get("name"), "status":"held", "issues":[str(ex)]})
            continue
        pending.append((-ability_score(ab,p), i, ab, (p, info)))
    for _,_,ab,p in sorted(pending, key=lambda v:v[:2]):
        held = import_entry(unit, ab, detail.get("region"), cat, resolver, p)
        if held: review.append(held)
    for ps in detail["passives"]:
        held = import_entry(unit, ps, detail.get("region"), cat, resolver)
        if held: review.append(held)
    unit["conversionReview"] = list({r.get("source", {}).get("key", f"{r.get('kind')}/{r.get('id')}"):r for r in review}.values())
    unit["effectPolicy"] = EFFECT_POLICY
    return unit


def main():
    """autoport.py [--reset] [--renumber VID[:COMMAND_ID]] <keys...>"""
    args = sys.argv[1:]; reset = "--reset" in args; renum = None
    if "--renumber" in args:
        i = args.index("--renumber"); renum = args[i + 1]; del args[i:i + 2]
    args = [a for a in args if not a.startswith("--")]
    units = json.load(open(SPEC, encoding="utf-8")); cat = ffr_catalog.load()
    keys = args or [u["key"] for u in units if u.get("ffbe") and not u.get("skills")]
    for u in units:
        if u["key"] in keys and u.get("ffbe"):
            if reset: u["skills"] = {}; u["convertedPassives"] = {}; u["awakening"] = [[], [], [], []]; u["ffbeMap"] = {"skills": {}, "passives": {}}
            autoport(u, cat)
            if renum:
                vid, _, cmd = renum.partition(":"); renumber(u, int(vid), int(cmd) if cmd else None)
            print(f"{u['key']}: {len(u['skills'])} skills, awakening {[len(t) for t in u['awakening']]}, passives mapped {len(u['ffbeMap']['passives'])}")
    json.dump(units, open(SPEC, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

# Keep custom, user-authored imports on their original path. Every catalog
# vision uses the complete approved form bundle, including historical visions.
_legacy_autoport, _legacy_preview_kit, _legacy_import_entry = autoport, preview_kit, import_entry

def autoport(unit, cat=None, detail=None):
    if unit.get('custom'): return _legacy_autoport(unit, cat, detail)
    from vision_import import hydrate
    return hydrate(unit, cat, detail)

def preview_kit(unit):
    if unit.get('custom'): return _legacy_preview_kit(unit)
    from vision_import import preview
    return preview(unit)

def import_entry(unit, ab, region, cat=None, resolver=None, resolved=None, choices=None):
    if unit.get('custom'): return _legacy_import_entry(unit, ab, region, cat, resolver, resolved, choices)
    from vision_import import hydrate, equip
    hydrate(unit)
    key = ab.get('sourceKey') or (ab.get('source') or {}).get('key')
    if key is None:
        matches = [e for e in unit['ffbeLibrary'] if str(e['id']) == str(ab['id']) and e['kind'] == ab['kind']]
        if len(matches) != 1: raise ValueError('Select the ability from this form’s reviewed FFBE kit')
        key = matches[0]['sourceKey']
    equip(unit, key)
    return None

if __name__ == "__main__":
    main()
