"""Bind shared conversion results to the existing authored resonance builder."""
from copy import copy, deepcopy
from functools import lru_cache

from .compiler import Converter, TableWriter
from .general import merge_patch
from .sources import SourceRecord, master_record


@lru_cache(maxsize=1)
def converter():
    return Converter()


def source_record(source):
    """Project the structured profile without parsing nested GL vectors as text."""
    components=source.get('components') or []
    if not components or any(not isinstance(c.get('params'),list) for c in components):
        raise ValueError('Converted resonance requires structured component parameters')
    raw=source.get('rawLb') or {}
    master=master_record({**raw,'lb_id':source['lbId'],
        'attack_frames':source.get('rawAttackFrames',raw.get('attack_frames',''))},'F_LIMITBURST_MST')
    data={'name':source.get('name'),
        'effects_raw':[[c['range'],c['target'],c['type'],deepcopy(c['params'])] for c in components],
        'attack_frames':master.data['attack_frames'],'attack_damage':master.data['attack_damage'],
        'element_inflict':source.get('elements',[]),'lb_cost':raw.get('cost',raw.get('lb_cost',0))}
    return SourceRecord('BOUND_LB','lb',str(source['lbId']),data)


def profile(source):
    """Accept the structured schema-2 LB source already resolved by Studio.

    The existing sequencer supports one damage timeline or one common support
    application. More complex application jobs remain blocked at this boundary,
    even when their individual mechanics fit native data tables.
    """
    result = {"mode":"converted", "supported":False, "issues":[], "warnings":[]}
    if not source:
        result["issues"].append("This form's structured LB source is unavailable")
        return source, result
    result.update(lbId=source["lbId"], name=source.get("name"), availableLbIds=source.get("availableLbIds", []))
    try:
        record=source_record(source);compiler=converter()
        if 'conversionSource' in source:
            from .commands import SnapshotResolver
            resolver=SnapshotResolver(source['conversionSource']);saved=resolver.root
            if (saved.kind!='lb' or saved.id!=record.id or
                    any(saved.data.get(k)!=v for k,v in record.data.items() if k!='name')):
                raise ValueError('LB snapshot mechanics differ from its selected structured profile')
            record=saved;compiler=copy(compiler);compiler.resolver=resolver
        converted = compiler.convert(record)
        result["conversion"] = converted
        if not converted["validation"]["tableCompatible"]:
            raise ValueError("; ".join(converted["issues"]) or "LB has no executable mechanics")
        if source.get("moveType") not in (0,1,4):
            raise ValueError(f"Movement type {source.get('moveType')} needs a movement adapter")
        native = converted["native"]
        actions = [a for c in converted["components"] for a in c["actions"]]
        from .commands import damage_phase_bindings
        phases = damage_phase_bindings(converted)
        timeline = deepcopy(source)
        if actions:
            frames = native["sequence"]["hitFrames"]
            weights = native["sequence"]["hitWeights"]
        else:
            from .commands import application_frames
            frames=application_frames(converted);weights=[1.]
            timeline["supportFrames"] = frames
        timeline.update(hitFrames=frames, hitPercents=[w*100 for w in weights])
        if native["sequence"].get("applicationKinds"):
            timeline["applicationKinds"] = list(native["sequence"]["applicationKinds"])
        if phases:
            timeline["effectPhases"] = phases
        from ffbe_lb import element_color
        result.update(supported=True, set=deepcopy(native["set"]), description=TableWriter.description(converted),
                      hits=len(frames), damageType=native["set"]["DamageType"], totalPower=native["set"]["magnification"],
                      elements=source.get("elements", []), fieldColor=element_color(source.get("elements", [])),
                      warnings=converted["changes"], runtimeValidation="not_run",
                      binding={"gaugePolicy":"native_finish_blow", "actor":"equipping_actor",
                               "sourceHitFrames":frames, "source":"structured_lb_profile"})
        if any("applicationIndex" not in phase for phase in phases):
            phase_kind = "recovery" if native["set"]["parameterVariationType"] == "Increase" else "damage"
            result["warnings"] = [*result["warnings"], f"Effects use FFR's native before/after {phase_kind} phases in source component order; separate source effect timestamps are not reproduced."]
        if any(phase['effectType']=='AddElementResistance' for phase in phases):
            from .resistance_phases import CHANGE
            result['warnings'].append(CHANGE)
        return timeline, result
    except (ValueError, TypeError, KeyError, IndexError) as ex:
        result["issues"].append(str(ex))
        return source, result


def materialize(profile, skill_id, row_name, tbl, row_by):
    """Stage private effects and checked overflow before extending build rows."""
    if not profile.get("supported"):
        raise ValueError("Cannot materialize a held converted resonance")
    result = profile["conversion"]
    table = result["native"]["table"]
    kind = "passives" if table.endswith("DT_PassiveSkillData") else "skills"
    from .skill_ids import validate_id
    validate_id(kind, skill_id)
    ledger = {"skills":{}, "passives":{}, "effects":{}}
    ledger[kind][result["source"]["key"]] = skill_id
    from .effect_ids import OwnedEffectWriter
    existing = tbl("Skill/DT_SkillEffectData")
    writer = OwnedEffectWriter(converter().native,ledger,skill_id,
        (r['set']['ID'] for r in existing['add']),
        (r['set']['ID'] for r in tbl('Skill/DT_SkillData')['add']))
    first = skill_id*100
    if not 0 < first < 2147483547:
        raise ValueError("Converted effect range is outside native integer limits")
    writer.next_ids["effects"] = first
    writer.add(result)
    if writer.next_ids["effects"] > first+100:
        raise ValueError("Converted ability exceeds its skill-owned effect range")
    # A passive owns its root row in the passive table, but its automatic
    # children are active skill rows. Stage both tables before adding either.
    child_groups = {name:(writer.tables.get(name, {}).get('add', [])[1:] if name==table
                         else writer.tables.get(name, {}).get('add', []))
                    for name in (table,'Skill/DT_SkillData')}
    child_groups = {name:rows for name,rows in child_groups.items() if rows}
    for name,child_rows in child_groups.items():
        child_table = tbl(name)
        used_child_ids = {r["set"]["ID"] for r in child_table["add"]}
        used_child_names = {r["row"] for r in child_table["add"]}
        for child in child_rows:
            if child["set"]["ID"] in used_child_ids or child["row"] in used_child_names:
                raise ValueError(f"Duplicate converted application ID {child['set']['ID']}")
    effect_rows = writer.tables.get("Skill/DT_SkillEffectData", {}).get("add", [])
    used_ids = {r["set"]["ID"] for r in existing["add"]}
    used_names = {r["row"] for r in existing["add"]}
    for row in effect_rows:
        if row["set"]["ID"] in used_ids or row["row"] in used_names:
            raise ValueError(f"Duplicate converted effect ID {row['set']['ID']}")
        row_by("Skill/DT_SkillEffectData", "ID", next(k for k,v in converter().native.effect_names.items() if v == row["cloneFrom"]))
    settings = deepcopy(writer.tables[table]["add"][0]["set"])
    for field in ("Name", "Description", "ID", "SortId"):
        settings.pop(field, None)
    existing["add"].extend(effect_rows)
    for name,child_rows in child_groups.items():
        tbl(name)["add"].extend(child_rows)
    merge_patch(tbl,converter().native,writer.general.additions)
    return settings
