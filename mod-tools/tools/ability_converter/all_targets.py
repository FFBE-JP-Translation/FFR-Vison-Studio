"""All-side actions use the native filtered selection, never an All bundle."""
from copy import deepcopy

EVIDENCE = {"skillId":505360,"targetType":"All","bundleTargetType":"SkillTarget",
    "selectionFunction":"0x144f514d0","collectorFunction":"0x144fb22c0",
    "filterFunction":"0x144f57b70","livingOnly":True,"runtime":"not_run"}
SETTINGS = {"TargetType":"All","defaultTargetRelation":"Enemies","defaultTargetState":"Alive",
    "isAliveOnly":True,"isTargetIgnoreSelf":False,"targetRage":"None",
    "isSameRelationTargetingDisabled":False,"isHostilityRelationTargetingDisabled":False}


def evidence(catalog):
    row = catalog.skills[catalog.skill_ids[505360]]
    if any(row[k] != v for k,v in SETTINGS.items()) or any(row[k] for k in
            ("canTargetStoneUnit","isIgnoreUnselectable","isGuestOrSummonNonTargetable")):
        raise ValueError("Native All selection evidence changed")
    if any(b["TargetType"] != "SkillTarget" for b in row["effectBundleList"] if b["effectId"] >= 0):
        raise ValueError("Native All effect bundles must retain selected recipients")
    return deepcopy(EVIDENCE)


def prepare(catalog, targeting, effects):
    selected_all = targeting["shape"] == "All"
    if selected_all:
        if targeting["state"] != "Alive" or targeting.get("ignoreSelf") or targeting.get("eitherSide"):
            raise ValueError("All selection requires the native living, unfiltered both-side policy")
        binding = evidence(catalog)
    for effect in effects:
        if effect["target"]["shape"] != "All":
            continue
        if not selected_all or effect["target"]["state"] != "Alive":
            raise ValueError("Independent all-side effects require separate recipient lists; an All bundle cannot gather targets")
        effect.update(targetBinding="skill_selection",targetBindingEvidence=deepcopy(binding))
    return deepcopy(binding) if selected_all else None


def validate(catalog, native):
    rows = [native["set"],*[job["set"] for job in native.get("applications",[])]]
    has_all = any(row.get("TargetType") == "All" for row in rows)
    if has_all or native.get("allTargeting"):
        if native["set"].get("TargetType") != "All" or native.get("allTargeting") != evidence(catalog):
            raise ValueError("All-side selection requires its complete native recipient binding")
        for row in rows:
            if row.get("TargetType") == "All" and any(row.get(k) != v for k,v in SETTINGS.items()):
                raise ValueError("All-side selection cannot discard or filter either side")
    def effect_tree(spec, depth=0):
        if depth > 64:
            raise ValueError("All-side effect graph exceeds supported depth")
        if spec["target"]["shape"] == "All":
            if (not has_all or spec["target"]["state"] != "Alive" or spec["target"]["relation"] != "Enemies"
                    or spec["target"].get("ignoreSelf") or spec["target"].get("eitherSide")):
                raise ValueError("All-side effect needs a living All command selection")
            # Nested bundle children inherit their root recipient list. Top-level
            # AppendDamage has its independently validated application evidence.
            if depth == 0 and (spec.get("targetBinding") != "skill_selection" or
                    "applicationIndex" not in spec and spec.get("targetBindingEvidence") != EVIDENCE):
                raise ValueError("All-side effects must use SkillTarget and retain selection evidence")
        for child in [*spec.get("children",[]),*spec.get("randomChoices",[])]:
            effect_tree(child,depth+1)
    for effect in native["effects"]:
        effect_tree(effect)
