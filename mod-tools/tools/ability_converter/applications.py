"""Source-timed damage and recovery using native AppendDamage application rows."""
from copy import deepcopy
import math


def elements(action, record):
    if action['kind'] != 'damage':
        return []
    values = action.get("elements", record.data.get("element_inflict")) or []
    values = [values] if isinstance(values, str) else values
    return list(dict.fromkeys("Thunder" if v == "Lightning" else v for v in values if v not in (None, "None")))


def signature(action, record):
    """Attributes that cannot be shared by one native damage row."""
    from .tag_attacks import bonus
    return (action["kind"], action["damageType"], action["target"], action.get("calc"),
            elements(action, record), action.get("powerBoost", 1.), action.get("breakBonus", 0),
            action.get("criticalHitRate", 3 if action["damageType"] == "Physic" else 2), action.get("accuracy", 100),bonus(action))


def target_key(target):
    return (target["shape"], target["relation"], target["state"],
            bool(target.get("ignoreSelf")), bool(target.get("eitherSide")))


def source_owners(result):
    """Rebuild chronological ownership, including expanded and interleaved hits."""
    from .compiler import Converter, execution_order
    from .sources import SourceRecord
    actions=[a for c in result['components'] for a in c['actions']]
    n=result['native'];jobs=[n,*n.get('applications',[])]
    record=SourceRecord(**{k:result['source'][k] for k in ('source','kind','id','level','path')},
        data={**result['sourceMetadata'],'effects_raw':[c['raw'] for c in result['components']]})
    reader=Converter.__new__(Converter)
    _,_,groups=reader.timing(record,actions)
    hits=sorted(((frame,execution_order(a),i,local) for i,(a,g) in enumerate(zip(actions,groups))
                 for local,frame in enumerate(g['frames'])),key=lambda h:(h[0],h[1]))
    if len(hits)!=len(jobs):
        raise ValueError('Appended bindings must cover the source hit schedule')
    owners=[]
    for ordinal,(frame,order,index,local) in enumerate(hits):
        job=jobs[ordinal]
        if ordinal and (job['component']!=actions[index]['component'] or job['order']!=list(order)
                or job['source']!=groups[index]['source'] or job['sourceHitIndex']!=local
                or job['frame']!=frame or job['index']!=ordinal):
            raise ValueError('Appended owner differs from its source application')
        owners.append(index)
    return owners


def row_target(row):
    return {"shape":row["TargetType"], "relation":row["defaultTargetRelation"],
            "state":row["defaultTargetState"], "ignoreSelf":row["isTargetIgnoreSelf"],
            "eitherSide":row["TargetType"] != "All" and not row["isSameRelationTargetingDisabled"] and not row["isHostilityRelationTargetingDisabled"]}


def recipient_binding(primary, target):
    """Factory 0x144f7bdd0 builds Self/Group/SkillTarget recipient lists.

    AppendDamage mode zero retains that list. Independent single/random
    choices and per-bundle caster/side filters are absent from this factory.
    """
    if target_key(primary) == target_key(target):
        return "skill_selection"
    if target["state"] == "Alive" and not target.get("ignoreSelf") and not target.get("eitherSide"):
        if target["shape"] == "Self" and target["relation"] == "Friendlies":
            return "caster"
        if target["shape"] == "Group" and target["relation"] in ("Friendlies", "Enemies"):
            return "living_group"
    raise ValueError("Independent selected targets or filtered appended recipients require separate targeting jobs")


def compose(compiler, record, result, actions, effects):
    from .compiler import execution_order

    template = compiler.native.effects.get(59000, {})
    retained = compiler.native.effects.get(1051, {})
    if (template.get("EffectType") != "AppendDamage" or template.get("ParamList", [])[:2] != [440230,1]
            or retained.get("EffectType") != "AppendDamage" or retained.get("ParamList", [])[:2] != [501530,0]):
        raise ValueError("Native appended-damage templates changed; recipient and reaction binding needs review")

    if any(a["kind"] not in ("damage", "heal") or a["damageType"] not in ("Physic", "Magic")
           or a.get("calc", a["damageType"]) not in ("Physic", "Magic") for a in actions):
        raise ValueError("Unweighted damage formulas require separate damage budgets")
    healing = [a for a in actions if a["kind"] == "heal"]
    if len(healing) > 1:
        raise ValueError("Multiple recovery applications require separate recovery budgets")
    orders = [execution_order(a) for a in actions]
    if any(min(orders) < execution_order(e) < max(orders) for e in effects):
        raise ValueError("An effect between damage components requires ordered application jobs")
    frames, _, groups = compiler.timing(record, actions)
    total = sum(a["multiple"] for a in actions if a["kind"] == "damage")
    if total <= 0:
        raise ValueError("Appended composition requires a positive damage budget")
    hits = []
    for index, (action, group) in enumerate(zip(actions, groups)):
        recovery = action["kind"] == "heal"
        if recovery and (len(group["frames"]) != 1 or not compiler.action_timing(record, actions, action)["frames"]):
            raise ValueError("Appended recovery requires one explicit source application frame; healing ignores hit weights")
        group.update(budgetKind="recovery" if recovery else "damage",
                     budgetShare=1. if recovery else action["multiple"]/total)
        hits.extend((frame, execution_order(action), index, local, weight*group["budgetShare"])
                    for local, (frame, weight) in enumerate(zip(group["frames"], group["weights"])))
    hits.sort(key=lambda hit: (hit[0], hit[1]))
    primary_target = actions[hits[0][2]]["target"]
    if actions[hits[0][2]]["kind"] != "damage":
        raise ValueError("Recovery preceding the first attack requires separate selection and application jobs")
    bindings = [recipient_binding(primary_target, action["target"]) for action in actions]
    kinds = ["recovery" if actions[hit[2]]["kind"] == "heal" else "damage" for hit in hits]
    # Sequence weights describe the offensive budget. The recovery row has
    # its own full power and a conventional weight of one, ignored natively.
    weights = [0. if kind == "recovery" else hit[4] for hit, kind in zip(hits, kinds)]
    native, children, append_effects, child_elements = None, [], [], []
    for ordinal, (frame, order, index, local, share) in enumerate(hits):
        action = deepcopy(actions[index])
        # Position every formula on its own native ladder using the SAME total
        # source coefficient. The row's hit weight then assigns only its share.
        if action["kind"] == "damage":
            action["multiple"] = total
        action["timing"] = {"frames":[frame], "weights":[1.], "binding":groups[index]["timingBinding"]}
        projected = {**result, "components":[{**c, "actions":[], "effects":deepcopy(c["effects"]) if ordinal == 0 else []}
                                             for c in result["components"]]}
        projected["components"][action["component"]]["actions"] = [action]
        row = compiler.assemble(record, projected)
        settings = row["set"]
        settings["hitDamageRatioList"] = [0.]*max(len(settings["hitDamageRatioList"]), ordinal+1)
        settings["hitDamageRatioList"][ordinal] = share
        budget = {"kind":kinds[ordinal], "offset":ordinal, "share":share}
        if ordinal == 0:
            native = row
            native["hitBudget"] = budget
        else:
            settings["Cost"] = 0
            child = {"index":ordinal, "hitNumber":ordinal+1, "frame":frame, "component":actions[index]["component"],
                     "order":list(order), "source":groups[index]["source"], "sourceHitIndex":local,
                     "cloneFrom":row["cloneFrom"], "set":settings, "hitBudget":budget}
            if row.get('multipleElements'):
                child['multipleElements'] = row['multipleElements']
                for spec in row['effects']:
                    if 'skillElement' not in spec:
                        raise ValueError('Private appended elements cannot carry ordinary support effects')
                    spec['skillElement'].update(binding='application_skill', applicationIndex=ordinal)
                    child_elements.append(spec)
            children.append(child)
            if row.get('tagAttack'):
                child['tagAttack']=row['tagAttack']
            effect = compiler.native.effect(59000, [-1, 0])
            effect.update(component=actions[index]["component"], target=deepcopy(action["target"]),
                          activeTiming="AfterDamageCalculation", applicationIndex=ordinal,
                          targetBinding=bindings[index], targetBindingEvidence={"skillId":440210,"effectId":59000,
                              "bundleTargetType":"SkillTarget" if bindings[index] == "skill_selection" else action["target"]["shape"],
                              "recipientFactory":"0x144f7bdd0", "groupCollector":"0x144faff50", "recipientMode":0,
                              "recipientModeEvidence":{"effectId":1051,"nativeFunction":"0x144f6db90"}})
            append_effects.append(effect)
    # After support is calculated only after all appended damage portions.
    # Before support remains before the primary calculation, as in stock skills.
    before = [e for e in native["effects"] if e["activeTiming"] == "BeforeDamageCalculation"]
    after = [e for e in native["effects"] if e["activeTiming"] == "AfterDamageCalculation"]
    native["effects"] = before + child_elements + append_effects + after
    native["applications"] = children
    native["sequence"].update(hitFrames=frames, hitWeights=weights, components=groups, applicationKinds=kinds)
    native["composition"] = {"kind":"append_damage", "totalSourceMultiple":total, "hits":len(hits),
                             "recoveryApplications":len(healing), "costOwner":"primary",
                             "recipientMode":"per_application" if any(b != "skill_selection" for b in bindings) else "existing_skill_selection",
                             "nativeEvidence":{"skillId":440210,"effectId":59000,"childSkillId":440230}}
    validate(compiler.native, native)
    result["changes"].append("Distinct action formulas, attributes and recipients use source-timed native appended applications; damage portions share one coefficient budget and the primary command pays once.")
    if healing:
        result["changes"].append("One recovery application keeps its own full healing power. Recovery ignores native hit weights and does not consume the attack's damage budget.")
    return native


def validate(catalog, native):
    """Validate the whole budget and private-row contract before allocation."""
    children = native.get("applications", [])
    if not children or native.get("composition", {}).get("kind") != "append_damage":
        raise ValueError("Appended damage requires an explicit composition")
    jobs = [{"set":native["set"],"hitBudget":native["hitBudget"]}, *children]
    weights, kinds = [], []
    recovery_count = 0
    for index, job in enumerate(jobs):
        row, budget = job["set"], job["hitBudget"]
        if row["hitCount"] != 1 or budget["offset"] != index:
            raise ValueError("Appended damage rows require one hit at their global reaction index")
        kind = "recovery" if row["parameterVariationType"] == "Increase" else "damage"
        if (row["skillEffectType"] != "DamageAndRecovery" or row["parameterType"] != "HitPoint"
                or row["damageCalcType"] not in ("Physic", "Magic") or budget.get("kind") != kind):
            raise ValueError("Appended application formula and declared budget disagree")
        if kind == "recovery":
            recovery_count += 1
            if index == 0 or budget["share"] != 1. or recovery_count > 1:
                raise ValueError("One appended recovery application must keep its full independent budget")
        if index and (job["index"] != index or job["hitNumber"] != index+1 or row["Cost"]
                      or row["effectBundleList"] or row["belongCommandList"] or row["playSequencerId"] != -1):
            raise ValueError("Private appended rows cannot pay costs, grant effects or become commands")
        if index and job["frame"] != native["sequence"]["hitFrames"][index]:
            raise ValueError("Appended damage frame differs from its source reaction schedule")
        catalog.validate_skill(row, hit_offset=budget["offset"], budget_share=budget["share"])
        weights.append(0. if kind == "recovery" else budget["share"])
        kinds.append(kind)
    if not math.isclose(sum(weights), 1., abs_tol=1e-6):
        raise ValueError("Appended damage must share exactly one total hit budget")
    if (native["sequence"]["hitWeights"] != weights or len(native["sequence"]["hitFrames"]) != len(jobs)
            or native["sequence"].get("applicationKinds") != kinds
            or native["composition"].get("recoveryApplications") != recovery_count):
        raise ValueError("Appended rows and source reaction schedule disagree")
    after = [e for e in native["effects"] if e["activeTiming"] == "AfterDamageCalculation"]
    if [e.get("applicationIndex") for e in after[:len(children)]] != list(range(1,len(jobs))):
        raise ValueError("Appended damage must precede after-phase support in global hit order")
    for effect, child in zip(after, children):
        target = row_target(child["set"])
        if (effect["set"]["EffectType"] != "AppendDamage" or effect["set"]["ParamList"][:2] != [-1,0]
                or target_key(effect["target"]) != target_key(target)
                or effect.get("targetBinding") != recipient_binding(row_target(native["set"]), target)):
            raise ValueError("Appended application must bind its generated child and verified recipients")
    if any("applicationIndex" in e for e in after[len(children):]):
        raise ValueError("Duplicate appended damage application")
