"""Private native Reraise graphs: timed grant, revival action, exact cleanup."""
from copy import deepcopy
import hashlib
import json

TABLE = "Skill/DT_SkillData"
PARAMS = [0,210240,1001,6000,0,0,1,1,-1,-1,0,0,0,-1,-1]
EVIDENCE = {"grantEffectId":1077, "reviveSkillId":210240, "reviveEffectId":1026,
    "cleanupEffectId":20015, "targetPolicyId":1001, "actor":"grant_recipient",
    "selectionFunction":"0x1451075b0", "applicationFunction":"0x1450ff9a0",
    "expiryFunction":"0x145148bd0", "cleanupFunction":"0x14523cb70", "runtime":"not_run"}


def templates(native):
    grant, revive, cleanup = (native.effects[i] for i in (1077,1026,20015))
    child = native.skills[native.skill_ids[210240]]
    policy = native.target_policies[1001]
    status = next(s for s in native.inventory["statuses"] if s["statusCondition"] == "Reraise")
    if (grant["EffectType"] != "AutomaticSkill" or grant["ParamList"] != PARAMS
            or grant["applyTiming"] != "Reraise" or grant["statusCondition"] != "Reraise"
            or not grant["isUnremovable"] or grant["isExecutingReaction"]
            or revive["EffectType"] != "Revival" or revive["ParamList"] != [25]+[-1]*14
            or cleanup["EffectType"] != "RemoveEffect" or cleanup["ParamList"] != [1077]+[-1]*9+[1]+[-1]*4):
        raise ValueError("Native Reraise grant/revival/cleanup graph changed")
    for row in (grant,revive,cleanup):
        if row["addProbability"] != 100 or row["activationProbability"] != 100 or row["activationCondition"]["Condition"] != "None":
            raise ValueError("Native Reraise graph requires unconditional effect templates")
    for row in (revive,cleanup):
        if row["applyTiming"] != "AddEffect" or row["proceedTiming"] != "AddEffect" or row["effectEndActionNum"] != 1:
            raise ValueError("Native Reraise revival and cleanup must apply immediately")
    if (policy["targetRelation"] != "Friendlies" or policy["isAlive"] or policy["skillTargetCondition"] != "Self"
            or policy["skillTargetConditionParamList"] != [-1,-1,-1]):
        raise ValueError("Native Reraise target policy must select the dead recipient itself")
    if (child["Cost"] != 0 or not child["isAvailableWhenDead"] or not child["isParallelExecutable"]
            or child["isAliveOnly"] or child["playSequencerId"] != -1 or child["sequencerIdWhenTargetFriendlies"] != -1
            or child["magnification"] != 0 or child["skillEffectType"] != "None"):
        raise ValueError("Native Reraise private action execution contract changed")
    bundles = [b for b in child["effectBundleList"] if b["effectId"] >= 0]
    if ([(b["effectId"],b["TargetType"]) for b in bundles] != [(1026,"SkillTarget"),(20015,"Self")]
            or any(b["targetRelation"] != "Friendlies" or b["activeSkillAddTiming"] != "AfterDamageCalculation"
                   or b["conditionData"]["Condition"] != "None" for b in bundles)):
        raise ValueError("Native Reraise action must revive, then clean up its own grant")
    if (status["isAllowDuplicate"] or status["shouldOverwrite"] or not status["isExtendLifeTurn"]
            or any(status[k] for k in ("isEsunaToOut","isDispelToOut","isDispellingEvilToOut","isAngelicFeatherToOut"))):
        raise ValueError("Native Reraise refresh/removal policy changed")
    return child


def convert(context):
    from .adapters import integer
    p = context.p
    if len(p) not in (2,3):
        raise ValueError("Reraise requires HP recovery, duration and an optional control")
    hp = integer(p[0],"Reraise HP percentage",1,100)
    source_turns = context.turn(1)
    maximum = integer(context.native.general["effectMaxLifeTime"],"Native maximum effect lifetime",1)
    turns = min(source_turns,maximum)
    controls = [integer(v,"Reraise control") for v in p[2:]]
    context.r["semantic"] = {"kind":"reraise", "hpPercent":hp, "turns":turns, "sourceTurns":source_turns,
        "sourceControlParameters":controls, "nativeBinding":deepcopy(EVIDENCE)}
    if any(controls):
        context.hold("Nonzero Reraise control requires verified source refresh/removal semantics")
        return
    if turns != source_turns:
        context.change(f"Reraise duration is capped from {source_turns} to the native maximum of {maximum} turns.")
    templates(context.native)
    params = list(PARAMS); params[1] = -1
    spec = context.effect(1077,params,turns=turns,unremovable=True)
    spec["reraise"] = {"hpPercent":hp,"turns":turns,"nativeEvidence":deepcopy(EVIDENCE)}
    validate(context.native,spec)
    context.change("Reraise uses one private native revival and cleanup action on its recipient, restoring the requested HP percentage. Its lifetime follows native turn timing; native Reraise dispel immunity and non-stacking refresh rules apply.")


def validate(native, spec, depth=0):
    """Reject unresolved or altered automatic graphs before allocating IDs."""
    if depth > 64:
        raise ValueError("Reraise effect graph exceeds supported depth")
    row = spec["set"]
    if "reraise" in spec:
        from .adapters import integer
        binding = spec["reraise"]
        hp = integer(binding["hpPercent"],"Reraise HP percentage",1,100)
        turns = integer(binding["turns"],"Reraise duration",1,native.general["effectMaxLifeTime"])
        templates(native)
        params = list(PARAMS); params[1] = -1
        expected = native.effect(1077,params,turns=turns,unremovable=True)["set"]
        if (spec["template"] != 1077 or row != expected or binding != {"hpPercent":hp,"turns":turns,"nativeEvidence":EVIDENCE}
                or spec.get("children") or spec.get("randomChoices") or spec["target"]["state"] != "Alive"):
            raise ValueError("Reraise requires its complete unresolved private revival/cleanup contract")
    elif spec["template"] == 1077 or row["EffectType"] == "AutomaticSkill" and row["applyTiming"] == "Reraise":
        raise ValueError("Reraise cannot omit its private revival/cleanup binding")
    for child in [*spec.get("children",[]),*spec.get("randomChoices",[])]:
        validate(native,child,depth+1)


def emit(writer, spec):
    """Allocate the cycle before writing it; keep private skills after the root."""
    binding = spec["reraise"]
    signature = json.dumps({"set":spec["set"],"reraise":binding},sort_keys=True,separators=(",",":"))
    key = "reraise:"+hashlib.sha256(signature.encode()).hexdigest()
    grant_id = writer.allocate("effects",key)
    child_id = writer.allocate("skills","$"+key)
    if grant_id in writer.emitted:
        return grant_id
    revival_id = writer.emit_effect(writer.native.effect(1026,[binding["hpPercent"]]))
    cleanup_id = writer.emit_effect(writer.native.effect(20015,[grant_id]+[-1]*9+[1]))
    settings = deepcopy(spec["set"]);settings["ParamList"][1] = child_id
    writer.native.validate_effect({"template":1077,"set":settings})
    writer.tables.setdefault("Skill/DT_SkillEffectData",{"add":[]})["add"].append({
        "row":f"FFBE_effect_{grant_id}","cloneFrom":writer.native.effect_names[1077],"set":{"ID":grant_id,**settings}})
    child = deepcopy(templates(writer.native))
    child.update(ID=child_id,SortId=child_id,Name="Reraise",Description=f"Revives the user with {binding['hpPercent']}% HP and consumes Reraise.",
                 belongCommandList=[],commandIdBelongDebuggingAllSkills=[-1,-1],isMimicEnabled=False)
    child["effectBundleList"][0]["effectId"] = revival_id
    child["effectBundleList"][1]["effectId"] = cleanup_id
    writer.native.validate_skill(child)
    writer.pending_skills.append({"row":f"FFBE_{child_id}","cloneFrom":writer.native.skill_ids[210240],"set":child})
    writer.emitted.add(grant_id)
    return grant_id
