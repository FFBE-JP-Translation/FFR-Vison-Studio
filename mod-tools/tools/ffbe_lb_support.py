"""Translate supported non-damaging FFBE LB components into native FFR effects.

Native mixed-target reference: skill 503550. Parameter/stat enums and templates
come from the extracted game, not the vision's selected damage donor.
"""
from copy import deepcopy

TYPES = {3, 33, 111}
ELEMENTS = ("Fire", "Ice", "Thunder", "Water", "Wind", "Earth", "Light", "Dark")
ELEMENT_IDS = (1, 2, 5, 6, 3, 4, 7, 8)
STATS = (("ATK", 5, "AttackUp"), ("DEF", 6, "DeffenceUp"),
         ("MAG", 7, "IntelligenceUp"), ("SPR", 8, "MindUp"))
CONDITION = {"Condition": "None", "param1": -1, "param2": -1, "param3": -1}


def application_frames(row):
    """A shared frame or one application per effect; no damage hit inference."""
    types = (row.get("effect_type") or "").split("@")
    if not types or any(not t.isdigit() or int(t) not in TYPES for t in types):
        return None
    groups = (row.get("attack_frames") or "").split("@")
    if len(groups) == 1:
        groups *= len(types)
    if len(groups) != len(types):
        return None
    frames = []
    for group in groups:
        fields = group.split(":")
        if "-" in group or len(fields) < 2 or not fields[0].isdigit():
            return None
        frames.append(int(fields[0]))
    return frames


def integer(value, label, minimum=0):
    if type(value) not in (int, float) or not minimum <= value <= 10000 or int(value) != value:
        raise ValueError(f"{label} must be a whole number from {minimum} to 10000")
    return int(value)


def target(component):
    relation, shape = component["target"], component["range"]
    if relation == 3 and shape == 0:
        return "Self", "Friendlies", "the user"
    if relation in (1, 2) and shape == 2:
        return "Group", "Enemies" if relation == 1 else "Friendlies", "all enemies" if relation == 1 else "all allies"
    # Individual mixed-side targets need separate selection/application jobs.
    raise ValueError(f"Support target/range {relation}/{shape} needs a targeting adapter")


def translate(component):
    kind, params = component["type"], component["params"]
    shape, relation, label = target(component)
    effects, descriptions, warnings = [], [], []

    def effect(template, values, status="None", turns=None):
        settings = {"ParamList": values + [-1] * (15 - len(values)), "statusCondition": status,
                    "isUnremovable": False, "addProbability": 100, "activationProbability": 100,
                    "activationCondition": deepcopy(CONDITION)}
        if turns is not None:
            settings.update(applyTiming="None", proceedTiming="BeginTurn", effectEndActionNum=turns)
        effects.append({"template": template, "set": settings, "TargetType": shape,
                        "targetRelation": relation, "component": component["index"]})

    if kind == 3:
        if len(params) != 6 or params[5] != 1:
            raise ValueError("Stat buff parameters need an adapter")
        turns = integer(params[4], "Buff duration", 1)
        raised = []
        for value, (stat, stat_id, status) in zip(params[:4], STATS):
            amount = integer(value, stat + " buff")
            if amount:
                # ParameterContinuousVariation, RatioIncrease (2). Do not use
                # Protect/Shell's damage reduction as a substitute for DEF/SPR.
                effect(16605, [amount, stat_id, 2, 0, 0, 0], status, turns)
                raised.append(f"{stat} +{amount}%")
        if raised:
            descriptions.append(f"Raises {', '.join(raised)} for {label} for {turns} turns.")
    elif kind == 33:
        if len(params) != 10 or params[8] != 1:
            raise ValueError("Resistance effect parameters need an adapter")
        turns = integer(params[9], "Resistance duration", 1)
        for value, element, element_id in zip(params[:8], ELEMENTS, ELEMENT_IDS):
            amount = integer(value, element + " resistance", -10000)
            if amount > 0:
                raise ValueError("Positive elemental resistance needs a resistance adapter")
            if amount:
                effect(1092, [element_id, 1], turns=turns)  # AddElementResistance / Weakness
                descriptions.append(f"Inflicts {element} weakness on {label} for {turns} turns.")
                warnings.append(f"FFBE {element} resistance {amount}% is translated to FFR's native weakness category; the percentage is not reproduced exactly.")
    elif kind == 111:
        if len(params) != 6 or any(params[:4]) or any(p not in (0, 1) for p in params[4:]):
            raise ValueError("Only Stop/Charm removal is supported for this status-removal component")
        for enabled, status, status_id in zip(params[4:], ("Stop", "Charm"), (9, 8)):
            if enabled:
                effect(1035, [0, 0, 0, status_id, 0, 0, 0, 0, 0, 1])
                descriptions.append(f"Removes {status} from {label}.")
    else:
        raise ValueError(f"Support effect type {kind} needs an adapter")
    if not effects:
        raise ValueError(f"Support effect type {kind} has no translated effect")
    return effects, descriptions, warnings


def profile(source):
    result = {"mode": "support", "lbId": source["lbId"], "name": source.get("name"),
              "availableLbIds": source.get("availableLbIds", []), "elements": source.get("elements", []),
              "hits": 1, "damageType": "None", "totalPower": 0, "issues": list(source.get("issues", [])),
              "warnings": [], "effects": [], "movement": source.get("movement", {})}
    descriptions = []
    for component in source.get("components", []):
        try:
            effects, text, warnings = translate(component)
            result["effects"].extend(effects)
            descriptions.extend(text)
            result["warnings"].extend(warnings)
        except (ValueError, TypeError, KeyError) as ex:
            result["issues"].append(f"Component {component.get('index')}: {ex}")
    frames = source.get("supportFrames")
    if not frames or len(frames) != len(source.get("components", [])) or len(set(frames)) != 1:
        result["issues"].append("Support components need one verified common application frame.")
    if not 1 <= len(result["effects"]) <= 8:
        result["issues"].append("This support LB needs between one and eight native effects.")
    if source.get("moveType") not in (0, 1, 4):
        result["issues"].append(f"Movement type {source.get('moveType')} needs a movement adapter.")
    result["supported"] = not result["issues"]
    if not result["supported"]:
        return result
    # Native skill 503550 applies self/ally and enemy bundles from one action.
    # Group bundle targets resolve independently of the selected primary side.
    relations = {e["targetRelation"] for e in result["effects"]}
    allies = "Friendlies" in relations
    only_self = all(e["TargetType"] == "Self" for e in result["effects"])
    result["target"] = "Self" if only_self else "All allies and enemies" if len(relations) > 1 else "All allies" if allies else "All enemies"
    result["description"] = " ".join(descriptions)
    result["set"] = {"skillAttrType": "FinishBlow", "skillEffectType": "None", "parameterType": "None",
                     "parameterVariationType": "Increase", "DamageType": "None", "damageCalcType": "None",
                     "magnification": 0, "breakDamageValue": 0, "criticalHitRate": 0, "accuracy": 100,
                     "Cost": 0, "element": "None", "TargetType": "Self" if only_self else "Group", "targetRage": "None",
                     "defaultTargetRelation": "Friendlies" if allies else "Enemies", "defaultTargetState": "Alive",
                     "isSameRelationTargetingDisabled": False, "isHostilityRelationTargetingDisabled": False,
                     "isTargetIgnoreSelf": False, "isAliveOnly": True, "statusCondition": "None",
                     "isReverseDamageToUndead": False, "totalDamageDisplayRule": "Hidden",
                     "hitCount": 1, "hitDamageRatioList": [1.] + [0.] * 29,
                     "effectBundleList": [], "SkillIcon.TagName": "UI.Skill.Action.Icon.Support"}
    return result


def materialize(profile, skill_id, row_name, tbl, row_by):
    """Allocate native effects inside a skill-owned ID range and bind targets."""
    settings = deepcopy(profile["set"])
    effect_table = tbl("Skill/DT_SkillEffectData")
    for index, effect in enumerate(profile["effects"]):
        effect_id = skill_id * 100 + index
        if not 0 < effect_id < 2147483647:
            raise ValueError("Support effect ID is outside the game's integer range")
        name = f"{row_name}_effect_{index}"
        if any(r["row"] == name or r["set"]["ID"] == effect_id for r in effect_table["add"]):
            raise ValueError(f"Duplicate support effect ID {effect_id}")
        template = row_by("Skill/DT_SkillEffectData", "ID", effect["template"])[0]
        effect_table["add"].append({"row": name, "cloneFrom": template, "set": {"ID": effect_id, **deepcopy(effect["set"])}})
        settings["effectBundleList"].append({"effectId": effect_id, "TargetType": effect["TargetType"],
                                             "targetRelation": effect["targetRelation"],
                                             "activeSkillAddTiming": "AfterDamageCalculation", "passiveSkillAddTiming": "None",
                                             "conditionData": deepcopy(CONDITION)})
    return settings
