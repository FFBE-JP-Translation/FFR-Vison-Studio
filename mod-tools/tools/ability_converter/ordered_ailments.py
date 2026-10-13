"""Capped, poison-first chance outcomes compiled to native four-way choices.

The FFBE active-34 client explanation establishes roll order. FFR resistance
is deliberately applied AFTER selecting a capped outcome, without retrying.
This is a disclosed replacement, not a claim about FFBE's resistance engine.
"""
from bisect import bisect_right
from copy import deepcopy
from fractions import Fraction
from functools import lru_cache

RESOLUTION = 65536  # 4**8: four native slots each receive exactly 8192 CRT draws.
POLICY = "ordered_rolls_before_native_resistance"
EVIDENCE = {"sourceOpcode":"active:34", "sourceTemplateLine":34,
    "sourceInventoryEntrySha256":"0b88b4de6813c59ae2c0ba24c868eeeaebfe2dd9a1942b5c22ca5ff76ebcfe20",
    "sourceOrder":"poison_to_petrify", "selector":"0x14513d1e0",
    "application":"0x14512d9a0", "targetMode":0, "randomSlots":4,
    "nativeBattle":"not_run"}


@lru_cache(maxsize=1024)
def distribution(chances, maximum):
    """Exact independent roll probabilities, stopping when the cap is reached."""
    states = {0:Fraction(1)}
    for index, chance in enumerate(chances):
        probability = Fraction(str(chance))/100
        next_states = {}
        for mask, weight in states.items():
            if mask.bit_count() >= maximum:
                next_states[mask] = next_states.get(mask,0)+weight
                continue
            for result, part in ((mask,1-probability),(mask|1<<index,probability)):
                if part:
                    next_states[result] = next_states.get(result,0)+weight*part
        states = next_states
    return tuple(sorted(states.items()))


@lru_cache(maxsize=1024)
def weights(chances, maximum):
    """Largest remainders preserve total probability with <1 ticket error."""
    exact = distribution(chances,maximum)
    scaled = [(mask,p*RESOLUTION) for mask,p in exact]
    values = {mask:int(p) for mask,p in scaled}
    remainder = RESOLUTION-sum(values.values())
    for mask,_ in sorted(scaled,key=lambda v:(-(v[1]-int(v[1])),v[0]))[:remainder]:
        values[mask] += 1
    return tuple(sorted(values.items()))


def metadata(chances, maximum):
    exact = dict(distribution(tuple(chances),maximum))
    counts = weights(tuple(chances),maximum)
    errors = [abs(Fraction(n,RESOLUTION)-exact[mask]) for mask,n in counts]
    return {"policy":POLICY,"resolution":RESOLUTION,
        "outcomes":[{"mask":mask,"tickets":n} for mask,n in counts],
        "maximumOutcomeErrorPercent":float(max(errors,default=0)*100),
        "totalVariationPercent":float(sum(errors)*50),
        "resistancePolicy":"no_retry_after_native_resistance",
        "evidence":deepcopy(EVIDENCE)}


def convert(context, chances, maximum):
    from .adapters import AILMENTS
    template=context.native.effects[11901]
    if (template['EffectType']!='AddRandEffect' or template['ParamList'][:6]!=[0,1023,1034,1027,1028,1029]
            or template['applyTiming']!='AddEffect' or template['proceedTiming']!='None'):
        raise ValueError('Native random-effect template changed; selection binding needs review')
    plan = metadata(chances,maximum)
    used = 0
    for outcome in plan["outcomes"]:
        if outcome["tickets"]:
            used |= outcome["mask"]
    leaves = []
    for index,name in enumerate(AILMENTS):
        if not used & 1<<index:
            continue
        start = len(context.r["effects"])
        context.inflict(name,100)
        effects = context.r["effects"][start:]
        del context.r["effects"][start:]
        leaves.append({"index":index,"effects":effects})
    spec = context.native.effect(11901,[0]+[-1]*14)
    spec.update(target=deepcopy(context.r["target"]),component=context.r["index"],
        orderedAilments=plan,ailmentEffects=leaves,
        randomSelection={"count":maximum,"pool":[n for n,c in zip(AILMENTS,chances) if c],
            "sourceChances":list(chances),"selection":"ordered_capped_outcomes"})
    validate(spec,context.native)
    context.r["effects"].append(spec)
    context.r["semantic"].update(selection="ordered_capped_outcomes",nativePolicy=deepcopy(plan))
    context.replace("Ordered Maladies", "Ailment rolls proceed from Poison to Petrify and stop at the source cap before FFR resistance is checked. "
        "Resisted ailments do not retry later candidates. Outcome probabilities are quantized to 65,536 tickets; "
        "each outcome differs by less than 0.001526 percentage points. Native ailment durations apply; Disease becomes paired ATK/MAG reductions.")


def validate(spec, native=None):
    from .adapters import AILMENTS, integer, number
    selection = spec.get("randomSelection") or {}
    chances = selection.get("sourceChances")
    if not isinstance(chances,list) or len(chances)!=8:
        raise ValueError("Ordered ailment chances require eight entries")
    chances = [number(c,"ordered ailment chance",0,100) for c in chances]
    maximum = integer(selection.get("count"),"ordered ailment cap",1,8)
    expected_selection = {"count":maximum,"pool":[n for n,c in zip(AILMENTS,chances) if c],
        "sourceChances":chances,"selection":"ordered_capped_outcomes"}
    if selection != expected_selection or spec.get("orderedAilments") != metadata(chances,maximum):
        raise ValueError("Ordered ailment outcome contract changed")
    row=spec["set"]
    if (spec["template"]!=11901 or row["EffectType"]!="AddRandEffect" or row["ParamList"]!=[0]+[-1]*14
            or row["applyTiming"]!="AddEffect" or row["proceedTiming"]!="None"
            or row["effectEndActionNum"]!=-1 or row["statusCondition"]!="None"
            or row["isUnremovable"] or row["isExecutingReaction"]
            or row["addProbability"]!=100 or row["activationProbability"]!=100
            or row["activationCondition"]!={"Condition":"None","param1":-1,"param2":-1,"param3":-1}
            or "children" in spec or "randomChoices" in spec):
        raise ValueError("Ordered ailments require the native selection contract")
    used=0
    for outcome in spec["orderedAilments"]["outcomes"]:
        if outcome["tickets"]:used|=outcome["mask"]
    leaves=spec.get("ailmentEffects",[])
    if [v["index"] for v in leaves]!=[i for i in range(8) if used & 1<<i]:
        raise ValueError("Ordered ailment leaves must match reachable outcomes")
    for leaf in leaves:
        name=AILMENTS[leaf["index"]]
        statuses=["AttackDown","IntelligenceDown"] if name=="Disease" else [name]
        if len(leaf["effects"])!=len(statuses):
            raise ValueError("Ordered ailment leaf has extra or missing effects")
        for effect,status in zip(leaf["effects"],statuses):
            e=effect["set"]
            if (effect["target"]!=spec["target"] or effect["component"]!=spec["component"]
                    or e["statusCondition"]!=status or e["addProbability"]!=100
                    or e["activationProbability"]!=100 or e["activationCondition"]["Condition"]!="None"
                    or any(k in effect for k in ("children","randomChoices","orderedAilments"))):
                raise ValueError("Ordered ailment leaves require one recipient and no extra rolls")
            if native is not None:
                expected = (native.effect(16605,[10,5 if status=="AttackDown" else 7,3,0,0,0],turns=3,status=status)
                    if name=="Disease" else native.effect(native.status_template(status),chance=100))
                if effect["template"]!=expected["template"] or e!=expected["set"]:
                    raise ValueError("Ordered ailment leaf differs from its native status template")
    if native is not None and row!=native.effect(11901,[0]+[-1]*14)["set"]:
        raise ValueError("Ordered ailment native selector template changed")
    if native is not None:
        expected=deepcopy(row)
        expected.update(EffectType='AddEffect',applyTiming='AddEffect',proceedTiming='AddEffect',effectEndActionNum=1)
        bundle=native.effect(1376,[0]+[-1]*14)['set']
        bundle.update(applyTiming='AddEffect',proceedTiming='AddEffect',effectEndActionNum=1)
        if bundle!=expected:
            raise ValueError('Ordered ailment native bundle template changed')


def expand(spec, native):
    """Build a compressed four-ary tree; runtime selection depth is at most 8.

    Store only the small outcome plan in catalog JSON. TableWriter interns
    identical native rows, including repeated choices and ailment bundles.
    """
    def node(kind,children):
        result={"template":spec["template"],"set":deepcopy(spec["set"]),
            "target":deepcopy(spec["target"]),"component":spec["component"]}
        if kind=="children":
            result.update(native.effect(1376,[0]+[-1]*14))
            result["set"].update(applyTiming="AddEffect",proceedTiming="AddEffect",effectEndActionNum=1)
        if children:result[kind]=children
        return result
    def together(effects):
        if len(effects)==1:return effects[0]
        if len(effects)<=4:return node("children",effects)
        return together([together(effects[i:i+4]) for i in range(0,len(effects),4)])
    ailment={v["index"]:v["effects"] for v in spec["ailmentEffects"]}
    ends=[];outcomes=[];total=0
    for entry in spec["orderedAilments"]["outcomes"]:
        if not entry["tickets"]:continue
        total+=entry["tickets"];ends.append(total)
        effects=[effect for i in range(8) if entry["mask"] & 1<<i for effect in ailment[i]]
        outcomes.append(together(effects) if effects else node("randomChoices",[]))
    def tree(start,size):
        index=bisect_right(ends,start)
        if start+size<=ends[index]:return outcomes[index]
        quarter=size//4
        return node("randomChoices",[tree(start+i*quarter,quarter) for i in range(4)])
    root=tree(0,RESOLUTION)
    # Preserve the outer AddRandEffect type used for native phase validation,
    # even when ordered guaranteed chances collapse to a single outcome.
    if root["set"]["EffectType"]!="AddRandEffect":root=node("randomChoices",[root])
    return root
