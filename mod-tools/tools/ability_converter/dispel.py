"""Disclosed FFBE dispel replacements using FFR's native status allowlists."""
from copy import deepcopy

MODES = {"buffs":(1181,"isDispelToOut"), "debuffs":(20012,"isAngelicFeatherToOut")}


def binding(native, mode):
    template, field = MODES[mode]
    params = [0,1,0,0,0,0,0,0,0,1]+[-1]*5 if mode == "buffs" else [0]*10+[1]+[-1]*4
    row = native.effects[template]
    if (row["EffectType"] != "CureStatusCondition" or row["ParamList"] != params
            or row["applyTiming"] != "AddEffect" or row["proceedTiming"] != "AddEffect"
            or row["effectEndActionNum"] != 1 or row["statusCondition"] != "None"):
        raise ValueError("Native dispel status-selection template changed")
    statuses = [s["statusCondition"] for s in native.inventory["statuses"] if s[field]]
    if not statuses:
        raise ValueError("Native dispel status allowlist is empty")
    for s in native.inventory["statuses"]:
        if s[field] and ((mode == "buffs" and s["isBadStatus"]) or (mode == "debuffs" and not s["isDebuff"])):
            raise ValueError("Native dispel allowlist changes the requested buff/debuff category")
    return {"mode":mode,"statuses":statuses,"template":template,"nativeField":field,
            "preservesUnremovable":True,"nativeApplication":"0x1450ffe90","nativeRemoval":"0x14523cb10"}


def convert(context):
    from .adapters import integer
    p=context.p
    if len(p) not in (1,2):
        raise ValueError("Dispel requires a selector and optional control")
    selection = 0 if p[0] == "none" else integer(p[0],"Dispel selector",0,2)
    controls = [integer(v,"Dispel control") for v in p[1:]]
    modes = ("buffs","debuffs") if selection == 0 else ("buffs",) if selection == 1 else ("debuffs",)
    context.r["semantic"] = {"kind":"dispel","selection":selection,"sourceSelection":deepcopy(p[0]),
        "sourceControls":controls,"nativeModes":list(modes),"replacement":"native_status_allowlists"}
    if any(controls):
        context.hold("Nonzero dispel control requires verified source removal semantics")
        return
    specifications = [binding(context.native,mode) for mode in modes]
    # CureStatusCondition tests the first enabled mode. Two independently
    # applied effects are necessary to select the union of both allowlists.
    for detail in specifications:
        spec=context.effect(detail["template"])
        spec["removal"] = detail
        validate(context.native,spec)
    context.replace("Purification" if selection == 0 else "Dispel" if selection == 1 else "Restoration",
        "FFBE's broad buff/debuff removal becomes FFR's native status allowlists for the selected categories. "
        "Ailments, Reraise, effects without a matching status and effects marked unremovable remain; combined removal applies buffs then debuffs.")


def validate(native, spec, depth=0):
    if depth > 64:
        raise ValueError("Dispel effect graph exceeds supported depth")
    if detail := spec.get("removal"):
        mode=detail.get("mode")
        if mode not in MODES:
            raise ValueError("Unknown native dispel mode")
        expected=binding(native,mode)
        if (detail != expected or spec["template"] != expected["template"]
                or spec["set"] != native.effect(expected["template"])["set"]
                or spec.get("children") or spec.get("randomChoices")):
            raise ValueError("Dispel must retain its complete native status-selection contract")
    elif spec["template"] in (1181,20012):
        raise ValueError("Dispel cannot omit its status allowlist binding")
    for child in [*spec.get("children",[]),*spec.get("randomChoices",[])]:
        validate(native,child,depth+1)
