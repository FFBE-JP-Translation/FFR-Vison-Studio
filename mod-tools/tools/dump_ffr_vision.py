#!/usr/bin/env python
"""dump_ffr_vision.py - collect everything that defines one FINAL FANTASY RESONANCE Vision into units/ffr/<name>/

usage: python tools/dump_ffr_vision.py <VisionId> <folder-name>      e.g. 13110 cloud

Reads the JSON row dumps in extracted/rows/ (made by ffr-dt rows), the locres dumps (extracted/locres_en.json / _ja.json)
and copies the legacy sprite assets from extracted/legacy/. Output:
  units/ffr/<name>/vision.json        one merged, human-readable document (unit row, vision row, level table, commands,
                                      LB, master skill, awakening + synchro masteries, resolved skills/passives/effects, strings)
  units/ffr/<name>/tables/*.json      the raw rows per table (exactly as in the game data)
  units/ffr/<name>/assets/            legacy .uasset/.uexp of the Ss6Project + textures (battle + menu)
  units/ffr/<name>/README.md          summary
"""
import json, os, shutil, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROWS = os.path.join(ROOT, "extracted", "rows")
LEGACY = os.path.join(ROOT, "extracted", "legacy", "FFRS", "Content")

def load(rel):
    p = os.path.join(ROWS, rel + ".json")
    return json.load(open(p, encoding="utf-8"))["rows"]

def main():
    vid = int(sys.argv[1]); name = sys.argv[2]
    out = os.path.join(ROOT, "units", "ffr", name)
    os.makedirs(os.path.join(out, "tables"), exist_ok=True)
    os.makedirs(os.path.join(out, "assets"), exist_ok=True)
    loc = {l: json.load(open(os.path.join(ROOT, "extracted", f"locres_{l}.json"), encoding="utf-8")) for l in ("en", "ja")}

    def text(t):
        """resolve an FText reference {table, key} into {ja, en}"""
        if not isinstance(t, dict) or "key" not in t:
            return t
        key = t["key"]; ns = t.get("table", "").split("/")[-1].split(".")[-1]
        res = {"key": key}
        for l in ("en", "ja"):
            tbl = loc[l].get(ns) or {}
            if key in tbl: res[l] = tbl[key]
            else:
                for _, tbl2 in loc[l].items():
                    if key in tbl2: res[l] = tbl2[key]; break
        return res

    def localize(obj):
        if isinstance(obj, dict):
            if "key" in obj and "table" in obj: return text(obj)
            return {k: localize(v) for k, v in obj.items()}
        if isinstance(obj, list): return [localize(x) for x in obj]
        return obj

    tables = {}
    def take(rel, pred, label):
        rows = {k: v for k, v in load(rel).items() if pred(k, v)}
        tables[label] = {"_table": rel, "rows": rows}
        return rows

    unit = take("Unit/DT_UnitParameter", lambda k, v: v.get("ID") == vid, "UNIT_PARAMETER")
    vision = take("Item/Vision/DT_VisionItemData", lambda k, v: v.get("ID") == vid, "VISION_ITEM_DATA")
    urow = next(iter(unit.values()), {}); vrow = next(iter(vision.values()), {})
    lvl_id = urow.get("LevelParamId")
    lvl_list = take("Unit/LevelParameter/DT_UnitLevelParameterList", lambda k, v: v.get("ID") == lvl_id, "UNIT_LEVEL_PARAMETER_LIST")
    lvl_table_name = next(iter(lvl_list.values()), {}).get("DataTable")
    level_rows = {}
    if lvl_table_name:
        for sub in ("Vision", "Playable", "summon"):
            p = os.path.join(ROWS, "Unit", "LevelParameter", sub, lvl_table_name + ".json")
            if os.path.exists(p):
                level_rows = json.load(open(p, encoding="utf-8"))["rows"]
                tables["UNIT_LEVEL_PARAMETER"] = {"_table": f"Unit/LevelParameter/{sub}/{lvl_table_name}", "rows": level_rows}
                break
    cmd_id = vrow.get("CommandId")
    cmd = take("Skill/DT_CommandSkillData", lambda k, v: v.get("ID") == cmd_id or v.get("unitIdToUseSkill") == vid, "COMMAND_SKILL_DATA")
    master = take("Skill/DT_MasterSkillData", lambda k, v: v.get("VisionId") == vid, "MASTER_SKILL_DATA")
    awaken = take("Item/Vision/DT_VisionAwakeningMasteryData", lambda k, v: v.get("ID") == vid, "VISION_AWAKENING_MASTERY")
    synchro = take("Item/Vision/DT_VisionSynchroMasteryData", lambda k, v: v.get("ID") == vid, "VISION_SYNCHRO_MASTERY")
    btl_asset = take("Asset/Battle/Unit/DT_BtlUnitAsset", lambda k, v: v.get("ID") == vid, "UNIT_ASSET_DATA")
    design = take("Battle/Unit/DT_BtlUnitDesignParameter", lambda k, v: v.get("ID") == vid, "BTL_UNIT_DESIGN_PARAMETER")
    ai = take("Unit/AI/DT_BtlUnitAIParameter", lambda k, v: v.get("ID") == vid or v.get("UnitId") == vid, "BTL_UNIT_AI_PARAMETER")
    upgrade = take("Item/Vision/DT_VisionUpgradeItemData", lambda k, v: True, "VISION_UPGRADE_ITEM_DATA")

    # ---- skills referenced by this vision ----
    all_skills = load("Skill/DT_SkillData"); all_passives = load("Skill/DT_PassiveSkillData"); all_effects = load("Skill/DT_SkillEffectData")
    by_skill_id = {v["ID"]: (k, v) for k, v in all_skills.items()}
    by_passive_id = {v["ID"]: (k, v) for k, v in all_passives.items()}
    by_effect_id = {v["ID"]: (k, v) for k, v in all_effects.items()}
    skill_ids, passive_ids = [], []
    def add_skill(i):
        if isinstance(i, int) and i > 0 and i not in skill_ids: skill_ids.append(i)
    def add_passive(i):
        if isinstance(i, int) and i > 0 and i not in passive_ids: passive_ids.append(i)
    add_skill(vrow.get("finishBlowSkill"))
    for k, v in all_skills.items():
        if cmd_id is not None and cmd_id in (v.get("belongCommandList") or []): add_skill(v["ID"])
    for v in level_rows.values():
        for s in v.get("AddSkills", []): add_skill(s)
    for p in urow.get("passiveSkillList", []): add_passive(p)
    for tbl in (awaken, synchro):
        for v in tbl.values():
            for d in v.get("detailData", []):
                t = d.get("parameterType"); ps = d.get("params", [])
                if t == "ActiveSkill": add_skill(ps[0] if ps else -1)
                elif t == "PassiveSkill": add_passive(ps[0] if ps else -1)
    skills = {}
    for i in skill_ids:
        if i in by_skill_id:
            k, v = by_skill_id[i]; skills[i] = {"_row": k, **v}
    passives = {}
    for i in passive_ids:
        if i in by_passive_id:
            k, v = by_passive_id[i]; passives[i] = {"_row": k, **v}
    effect_ids = []
    for s in list(skills.values()) + list(passives.values()):
        for b in s.get("effectBundleList", []):
            e = b.get("effectId")
            if isinstance(e, int) and e > 0 and e not in effect_ids: effect_ids.append(e)
    effects = {i: {"_row": by_effect_id[i][0], **by_effect_id[i][1]} for i in effect_ids if i in by_effect_id}
    tables["SKILL_DATA"] = {"_table": "Skill/DT_SkillData", "rows": {v["_row"]: {k2: v2 for k2, v2 in v.items() if k2 != "_row"} for v in skills.values()}}
    tables["PASSIVE_SKILL_DATA"] = {"_table": "Skill/DT_PassiveSkillData", "rows": {v["_row"]: {k2: v2 for k2, v2 in v.items() if k2 != "_row"} for v in passives.values()}}
    tables["SKILL_EFFECT_DATA"] = {"_table": "Skill/DT_SkillEffectData", "rows": {v["_row"]: {k2: v2 for k2, v2 in v.items() if k2 != "_row"} for v in effects.values()}}
    # skill assets (sequencer bindings) for those skills
    skill_assets = {}
    for rel in ("Asset/Skill/DT_SkillAsset", "Asset/Skill/CDT_SkillAsset_Demo"):
        p = os.path.join(ROWS, rel + ".json")
        if os.path.exists(p):
            for k, v in json.load(open(p, encoding="utf-8"))["rows"].items():
                if v.get("ID") in skills: skill_assets[k] = v
    tables["SKILL_ASSET_DATA"] = {"_table": "Asset/Skill/DT_SkillAsset", "rows": skill_assets}

    for label, t in tables.items():
        json.dump(t, open(os.path.join(out, "tables", label + ".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- merged document ----
    def skill_summary(v):
        return {"id": v["ID"], "row": v["_row"], "name": text(v.get("Name")), "description": text(v.get("Description")),
                "type": v.get("skillAttrType"), "effectType": v.get("skillEffectType"), "damage": v.get("DamageType"), "element": v.get("element"),
                "target": v.get("TargetType"), "cost": v.get("Cost"), "magnification": v.get("magnification"), "hits": v.get("hitCount"),
                "breakDamage": v.get("breakDamageValue"), "accuracy": v.get("accuracy"), "crit": v.get("criticalHitRate"),
                "statusCondition": v.get("statusCondition"), "sequencer": v.get("playSequencerId"), "equipCost": v.get("equipCost"),
                "effects": [{"effectId": b.get("effectId"), "target": b.get("TargetType"), "relation": b.get("targetRelation"),
                              "effect": (localize({k2: v2 for k2, v2 in by_effect_id[b["effectId"]][1].items()}) if b.get("effectId") in by_effect_id else None)}
                             for b in v.get("effectBundleList", [])]}
    doc = {
        "visionId": vid, "name": text(vrow.get("Name")), "description": text(vrow.get("Description")),
        "roles": vrow.get("roles"), "attackType": vrow.get("attackType"),
        "unit": localize(urow), "unitRowName": next(iter(unit), None),
        "visionItem": localize(vrow), "visionRowName": next(iter(vision), None),
        "levelTable": {"id": lvl_id, "table": lvl_table_name, "levels": level_rows},
        "commandSet": localize(cmd), "masterSkill": localize(master),
        "limitBurst": skill_summary(skills[vrow["finishBlowSkill"]]) if vrow.get("finishBlowSkill") in skills else None,
        "commandSkills": [skill_summary(s) for s in skills.values() if cmd_id is not None and cmd_id in (s.get("belongCommandList") or [])],
        "awakeningMastery": [{"row": k, "level": v["Level"], "points": v["masteryPoint"],
                               "grants": [{"type": d["parameterType"], "params": d["params"],
                                           "skill": (skill_summary(skills[d["params"][0]]) if d["parameterType"] == "ActiveSkill" and d["params"][0] in skills else None),
                                           "passive": (localize({**passives[d["params"][0]], "_effects": [effects.get(b.get("effectId")) for b in passives[d["params"][0]].get("effectBundleList", [])]}) if d["parameterType"] == "PassiveSkill" and d["params"][0] in passives else None)}
                                          for d in v["detailData"] if d["parameterType"] != "None"]}
                              for k, v in awaken.items()],
        "synchroMastery": [{"row": k, "level": v["Level"], "points": v["masteryPoint"],
                             "grants": [{"type": d["parameterType"], "params": d["params"],
                                         "passive": (localize({**passives[d["params"][0]], "_effects": [effects.get(b.get("effectId")) for b in passives[d["params"][0]].get("effectBundleList", [])]}) if d["parameterType"] == "PassiveSkill" and d["params"][0] in passives else None),
                                         "skill": (skill_summary(skills[d["params"][0]]) if d["parameterType"] == "ActiveSkill" and d["params"][0] in skills else None)}
                                        for d in v["detailData"] if d["parameterType"] != "None"]}
                            for k, v in synchro.items()],
        "assets": localize(btl_asset), "design": localize(design), "ai": localize(ai),
        "skillAssets": skill_assets,
    }
    json.dump(doc, open(os.path.join(out, "vision.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    # ---- copy sprite assets ----
    copied = []
    for anim in next(iter(btl_asset.values()), {}).get("animationAssetList", []):
        for key in ("Ss6Project", "textureBaseColor", "textureNormal", "textureMetallicRoughness"):
            path = anim.get(key)
            if not path: continue
            rel = path.replace("/Game/", "")
            for ext in (".uasset", ".uexp", ".ubulk"):
                src = os.path.join(LEGACY, rel + ext)
                if os.path.exists(src):
                    dst = os.path.join(out, "assets", "battle", os.path.basename(rel) + ext); os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy(src, dst); copied.append(dst)
    menu_dir = os.path.join(LEGACY, "Chara", "menu", f"summon{vid}")
    if os.path.isdir(menu_dir):
        dst = os.path.join(out, "assets", "menu"); os.makedirs(dst, exist_ok=True)
        for f in os.listdir(menu_dir): shutil.copy(os.path.join(menu_dir, f), dst); copied.append(os.path.join(dst, f))

    # ---- README ----
    nm = doc["name"] if isinstance(doc["name"], dict) else {"en": str(doc["name"])}
    lines = [f"# {nm.get('en', '?')} ({nm.get('ja', '')}) — Vision {vid}", "",
             f"* roles: {vrow.get('roles')}  attackType: {vrow.get('attackType')}",
             f"* unit row `{doc['unitRowName']}`: Lv{urow.get('Level')} HP {urow.get('MaxHitPoint')} MP {urow.get('MaxMagicPoint')} ATK {urow.get('Attack')} DEF {urow.get('Defence')} INT {urow.get('Intelligence')} MND {urow.get('Mind')} AGI {urow.get('Agility')}  (LevelParamId {lvl_id} -> {lvl_table_name}, {len(level_rows)} levels)",
             f"* limit burst: {doc['limitBurst']['name'].get('en') if doc['limitBurst'] else None} (skill {vrow.get('finishBlowSkill')})",
             f"* command set {cmd_id}: " + ", ".join(f"{s['name'].get('en', s['row'])} [{s['id']}]" for s in doc["commandSkills"]),
             f"* master skill: " + ", ".join(f"{text(v.get('Name')).get('en', k)} [{v['ID']}] cost {v.get('equipCost')}" for k, v in master.items()),
             f"* awakening tiers: {len(awaken)}  synchro tiers: {len(synchro)}",
             f"* skills resolved: {len(skills)}  passives: {len(passives)}  effects: {len(effects)}",
             f"* sprites: " + ", ".join(os.path.relpath(c, out) for c in copied), "",
             "Files: `vision.json` (merged, localized), `tables/*.json` (raw rows per table), `assets/` (legacy uasset/uexp: Ss6Project + tex/normal/mreo + menu sprites)."]
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write("\n".join(lines) + "\n")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
