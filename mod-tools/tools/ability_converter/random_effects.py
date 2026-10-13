"""Native random effect trees with explicit, equally sized outcome branches."""
from copy import deepcopy


def bundle(context, choices, *, random):
    template = 11901 if random else 1376
    spec = context.native.effect(template, [0]+[-1]*(5 if random else 4))
    spec.update(target=deepcopy(context.r["target"]), component=context.r["index"])
    if random:
        spec["randomChoices"] = choices
    else:
        spec["set"].update(applyTiming="AddEffect", proceedTiming="AddEffect", effectEndActionNum=1)
        spec["children"] = choices
    return spec


def together(context, effects):
    if len(effects) == 1:
        return effects[0]
    if len(effects) <= 4:
        return bundle(context, effects, random=False)
    return together(context, [together(context,effects[i:i+4]) for i in range(0,len(effects),4)])


def choose_one(context, outcomes):
    """Native selection reads five slots; equal subtrees preserve uniformity.

    Six outcomes use two branches of three, eight use two of four. A prime
    seven-way pool cannot become unequal subtrees or a dummy failure outcome.
    """
    if len(outcomes) == 1:
        return outcomes[0]
    if len(outcomes) <= 5:
        return bundle(context,outcomes,random=True)
    divisor = next((n for n in range(2,6) if len(outcomes)%n == 0),None)
    if divisor is None:
        raise ValueError("Random ailment pool needs an unbiased native selection tree")
    size = len(outcomes)//divisor
    return bundle(context,[choose_one(context,outcomes[i:i+size]) for i in range(0,len(outcomes),size)],random=True)


def convert(context):
    from .adapters import AILMENTS, integer, number
    p, code = context.p, context.code
    if len(p) != 10:
        raise ValueError("Random ailments require ten source parameters")
    chances = p[:8] if code == 34 else p[0]
    if not isinstance(chances,list) or len(chances) != 8:
        raise ValueError("Random ailment chance vector must contain eight entries")
    chances = [number(v,"random ailment chance",0,100) for v in chances]
    maximum = integer(p[9],"random ailment selection count",0,8)
    controls = [integer(v,"random ailment control") for v in (p[8:9] if code == 34 else p[1:9])]
    context.r["semantic"] = {"kind":"random_status_selection", "maximum":maximum,
        "chances":chances, "controls":deepcopy(controls), "nativeCandidate":"AddRandEffect"}
    if controls != ([1] if code == 34 else [0]*8):
        context.hold("Unknown random-ailment control parameters need source selection semantics")
        return
    pool = [name for name,chance in zip(AILMENTS,chances) if chance]
    if not maximum or not pool:
        context.r["semantic"] = {}
        return
    if code == 34:
        from .ordered_ailments import convert as ordered_convert
        ordered_convert(context,chances,maximum)
        return
    if any(chance not in (0,100) for chance in chances):
        context.hold("Partial random-ailment chances need verified selection-versus-chance order")
        return
    if maximum not in (1,len(pool)):
        context.hold("Multiple random ailments need sampling without replacement before native application")
        return
    template = context.native.effects[11901]
    if (template["EffectType"] != "AddRandEffect" or template["ParamList"][:6] != [0,1023,1034,1027,1028,1029]
            or template["applyTiming"] != "AddEffect" or template["proceedTiming"] != "None"):
        raise ValueError("Native random-effect template changed; selection binding needs review")
    outcomes=[]
    for name in pool:
        start = len(context.r["effects"])
        context.inflict(name,100)
        effects = context.r["effects"][start:]
        del context.r["effects"][start:]
        outcomes.append(together(context,effects))
    spec = choose_one(context,outcomes) if maximum == 1 else together(context,outcomes)
    spec["randomSelection"] = {"count":maximum,"pool":pool,"sourceChances":chances,
        "selection":"one_uniform_outcome" if maximum == 1 else "all_outcomes",
        "nativeEvidence":{"skillId":400750,"effectId":11901,"selectionFunction":"0x14513d1e0",
                          "applicationFunction":"0x14512d9a0","targetMode":0}}
    validate(spec)
    context.r["effects"].append(spec)
    context.r["semantic"]["selection"] = spec["randomSelection"]["selection"]
    context.change("Guaranteed random ailment selection uses native effect choices; each selected ailment keeps native resistance and duration rules. Disease remains one paired ATK/MAG reduction outcome.")


def validate(spec, depth=0, in_selection=False, native=None):
    """Check unresolved choice trees before any destination ID is allocated."""
    if ("orderedAilments" in spec or "ailmentEffects" in spec
            or (spec.get("randomSelection") or {}).get("selection")=="ordered_capped_outcomes"):
        from .ordered_ailments import validate as validate_ordered
        validate_ordered(spec,native)
        return 1
    if depth > 8:
        raise ValueError("Native random effect tree exceeds its supported depth")
    in_selection = in_selection or bool(spec.get("randomSelection"))
    row = spec["set"]
    if in_selection and (row["addProbability"] != 100 or row["activationProbability"] != 100
            or row["activationCondition"]["Condition"] != "None"):
        raise ValueError("Guaranteed ailment selection cannot acquire another chance or condition")
    if choices := spec.get("randomChoices"):
        if (spec.get("children") or not 2 <= len(choices) <= 5 or spec["template"] != 11901
                or row["EffectType"] != "AddRandEffect" or row["ParamList"] != [0]+[-1]*14
                or row["applyTiming"] != "AddEffect" or row["proceedTiming"] != "None"
                or row["effectEndActionNum"] != -1 or row["statusCondition"] != "None"
                or row["isUnremovable"] or row["isExecutingReaction"]
                or row["addProbability"] != 100 or row["activationProbability"] != 100):
            raise ValueError("Random choices require the native five-slot selection contract")
        if any(c["target"] != spec["target"] for c in choices):
            raise ValueError("Random choices must retain their recipient")
        sizes = [validate(c,depth+1,True,native) for c in choices]
        if len(set(sizes)) != 1:
            raise ValueError("Random choices require equally sized outcome subtrees")
        return sum(sizes)
    if "randomChoices" in spec or row["EffectType"] == "AddRandEffect":
        raise ValueError("Random choices cannot be missing or empty")
    if in_selection and (spec.get("children") or row["EffectType"] == "AddEffect"):
        if (spec["template"] != 1376 or row["EffectType"] != "AddEffect" or not 1 <= len(spec.get("children",[])) <= 4
                or row["ParamList"] != [0]+[-1]*14 or row["applyTiming"] != "AddEffect"
                or row["proceedTiming"] != "AddEffect" or row["effectEndActionNum"] != 1
                or any(c["target"] != spec["target"] for c in spec["children"])):
            raise ValueError("Paired ailment effects require one native recipient bundle")
    for child in spec.get("children",[]):
        validate(child,depth+1,in_selection,native)
    return 1
