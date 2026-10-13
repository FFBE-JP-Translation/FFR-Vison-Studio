"""Stop keeps its native status identity on the proven incapacitation effect."""
from copy import deepcopy

PARAMS = [3,-1,-1,2000,0,1,0,0,-1,-1,0,0,0,-1,-1]
EVIDENCE = {"templateId":1033,"statusId":9,"automaticMode":3,"actor":"effect_recipient",
    "initializationFunction":"0x1451420b0","applicationFunction":"0x1450ff9a0",
    "expiryFunction":"0x145148bd0","runtime":"not_run"}
POLICY = {"isBadStatus":True,"isDebuff":False,"negateStatusCondition":"None",
    "isEsunaToOut":True,"isDispelToOut":False,"isDispellingEvilToOut":False,"isAngelicFeatherToOut":False,
    "isExtendLifeTurn":True,"isAllowDuplicate":False,"shouldOverwrite":False,"isRemoveAdditionalTurn":True,
    "isControlDisabled":True,"isActionDisabled":True,"isBuffTurnExtensionTarget":False,
    "canPlayVoice":False,"isPlayBadStatusVoice":True,"releaseDamageType":"None"}


def templates(native):
    row = native.effects[1033]
    if (row["EffectType"] != "AutomaticSkill" or row["statusCondition"] != "Paralyzation"
            or row["ParamList"] != PARAMS or row["applyTiming"] != "ActionBegin"
            or row["proceedTiming"] != "ActionEnd" or row["effectEndActionNum"] != 2
            or row["isUnremovable"] or row["isExecutingReaction"] or row["addProbability"] != 100
            or row["activationProbability"] != 100 or row["activationCondition"]["Condition"] != "None"):
        raise ValueError("Native Stop incapacitation template changed")
    for name, sid in (("Stop",9),("Paralyzation",5)):
        status = next(s for s in native.inventory["statuses"] if s["statusCondition"] == name)
        if (native.inventory["enums"]["eUnitStatusCondition"][name] != sid
                or {k:v for k,v in status.items() if k not in ("row","statusCondition")} != POLICY):
            raise ValueError("Native Stop/Paralysis status policy changed")


def convert(context):
    from .adapters import integer
    p = context.p
    if len(p) not in (2,10):
        raise ValueError("Stop requires chance and duration, optionally followed by eight zero padding slots")
    chance = integer(p[0],"Stop chance",0,100)
    source_turns = context.turn(1)
    padding = [integer(v,"Stop padding") for v in p[2:]]
    maximum = integer(context.native.general["effectMaxLifeTime"],"Native maximum effect lifetime",1)
    turns = min(source_turns,maximum)
    context.r["semantic"] = {"kind":"stop","chance":chance,"turns":turns,"sourceTurns":source_turns,
        "sourcePadding":padding,"nativeBinding":deepcopy(EVIDENCE)}
    if any(padding):
        context.hold("Nonzero Stop padding has no verified source semantics")
        return
    templates(context.native)
    spec = context.effect(1033,turns=turns,chance=chance,status="Stop")
    spec["stop"] = {"chance":chance,"turns":turns,"nativeEvidence":deepcopy(EVIDENCE)}
    validate(context.native,spec)
    if turns != source_turns:
        context.change(f"Stop duration is capped from {source_turns} to the native maximum of {maximum} turns.")
    context.change("Stop retains its native status identity, application chance, resistance and cure category. It uses native incapacitation with a turn lifetime and native non-stacking refresh rules.")


def validate(native, spec, depth=0):
    if depth > 64:
        raise ValueError("Stop effect graph exceeds supported depth")
    row = spec["set"]
    if "stop" in spec:
        from .adapters import integer
        binding = spec["stop"]
        chance = integer(binding["chance"],"Stop chance",0,100)
        turns = integer(binding["turns"],"Stop duration",1,native.general["effectMaxLifeTime"])
        templates(native)
        expected = native.effect(1033,turns=turns,chance=chance,status="Stop")["set"]
        if (spec["template"] != 1033 or row != expected
                or binding != {"chance":chance,"turns":turns,"nativeEvidence":EVIDENCE}
                or spec.get("children") or spec.get("randomChoices")):
            raise ValueError("Stop requires its complete native incapacitation contract")
    elif row["statusCondition"] == "Stop":
        raise ValueError("Stop cannot omit its native incapacitation binding")
    for child in [*spec.get("children",[]),*spec.get("randomChoices",[])]:
        validate(native,child,depth+1)
