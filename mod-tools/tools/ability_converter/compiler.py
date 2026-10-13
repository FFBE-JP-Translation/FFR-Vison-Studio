"""Compile complete source records, retaining every component and restriction."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .adapters import ComponentAdapter, Context, integer, number, target
from .native import CONDITION, ELEMENT_IDS, NativeCatalog
from .general import GeneralBindings, TABLE as GENERAL_TABLE
from .sources import ARTIFACTS, ROOT, read
from .runs import file_hashes

SCHEMA_VERSION = "ffbe-ffr-ability/1"


def source_costs(data):
    embedded = data.get("cost") if isinstance(data.get("cost"), dict) else {}
    return {"mp_cost":data.get("mp_cost", embedded.get("MP",0)),
            "lb_cost":data.get("lb_cost", embedded.get("LB",0)),
            "ev_cost":data.get("ev_cost", embedded.get("EV",embedded.get("EP",0)))}


class Converter:
    def __init__(self, directory=ARTIFACTS, native=None, resolver=None):
        directory = Path(directory)
        self.native = native or NativeCatalog(directory)
        proposal = read(directory/"proposed-map.json")
        self.registry = {r["key"]: r for r in proposal["effects"]}
        if len(self.registry) != len(proposal["effects"]):
            raise ValueError("Duplicate opcode in generated effect map")
        self.adapters = ComponentAdapter(self.native, self.registry)
        self.resolver = resolver
        self.artifact_paths = {name:directory/name for name in
            ("ffr-effects.json", "ffbe-effects.json", "proposed-map.json", "proposed-policies.json")}
        self.artifact_paths.update({"native:"+name:path for name,path in self.native.reference_paths.items()})
        self.artifacts = file_hashes(self.artifact_paths)

    def convert(self, record, _stack=()):
        if record.key in _stack:
            raise ValueError("Immediate child cycle: "+" -> ".join((*_stack, record.key)))
        if len(_stack) >= 64:
            raise ValueError("Immediate child expansion exceeds 64 nested actions")
        data = record.data
        result = {"schemaVersion": SCHEMA_VERSION, "source": record.provenance(), "name": data.get("name"),
                  "status": "blocked", "components": [], "issues": list(record.issues), "changes": [],
                  "validation": {"sourceDecoded": False, "tableCompatible": False, "runtime": "not_run"},
                  "costs": source_costs(data),
                  "presentation": {k: deepcopy(data.get(k)) for k in
                                   ("icon", "attack_frames", "attack_damage", "attack_count", "effect_frames", "move_type", "element_inflict")},
                  "sourceMetadata": {k: v for k, v in data.items() if k not in ("effects_raw", "levels")},
                  "dependencies": [], "native": None}
        result["resourceCosts"] = []
        raw_effects = data.get("effects_raw")
        if not isinstance(raw_effects, list) or not raw_effects:
            result["issues"].append("Source has no structured effect components")
            return result
        for index, raw in enumerate(raw_effects):
            component = self.adapters.convert(record, raw, index)
            if component["semantic"].get("mode") == "inline" and not component["issues"]:
                self.expand(record, component, (*_stack, record.key))
            if component['semantic'].get('mode')=='delayed' and not component['issues']:
                from .delayed_actions import bind
                bind(self,record,component,(*_stack,record.key))
            if component['semantic'].get('mode')=='automatic_passive' and not component['issues']:
                from .automatic_passives import bind
                bind(self,record,component,(*_stack,record.key))
            result["components"].append(component)
            result["dependencies"].extend({**dep, "component": index} for dep in component["dependencies"])
        try:
            from .tag_attacks import bind_actions
            bind_actions(record,result['components'])
            self.race_damage_rewards(record, result["components"])
        except (ValueError, TypeError, KeyError, IndexError) as ex:
            result["issues"].append(str(ex))
        result["validation"]["sourceDecoded"] = all(c["status"] != "blocked" or bool(c["semantic"]) for c in result["components"])
        result["changes"] = list(dict.fromkeys(v for c in result["components"] for v in c["changes"]))
        result["issues"].extend(f"Component {c['index']} ({c.get('key', 'malformed')}): {issue}"
                                for c in result["components"] for issue in c["issues"])
        for key in ("mp_cost", "lb_cost", "ev_cost"):
            try:
                integer(result["costs"][key] or 0, key, 0)
            except ValueError as ex:
                result["issues"].append(str(ex))
        if isinstance(data.get("cost"), dict):
            unknown = {k:v for k,v in data["cost"].items() if k not in ("MP","LB","EV","EP") and v}
            if unknown:
                result["issues"].append("Unknown source resource costs must not be omitted: "+", ".join(sorted(unknown)))
            if data["cost"].get("EV") and data["cost"].get("EP") and data["cost"]["EV"] != data["cost"]["EP"]:
                result["issues"].append("Conflicting esper resource costs in EV and EP fields")
        if record.kind != "lb" and result["costs"]["lb_cost"]:
            try:
                crystals = integer(result["costs"]["lb_cost"], "LB crystal cost", 1)
                if record.namespace != "active":
                    raise ValueError("Only an active skill can spend LB gauge")
                if self.native.lb_cost_ladder != [100,200]:
                    raise ValueError("Native LB cost ladder changed; resource normalization needs review")
                # Native LimitBurst skills use 100 or 200 points. Retain this
                # observed one/two-gauge cost ladder while ordinary MP remains
                # on the skill row. Both the cost and affordability check bind
                # through the native skill general-settings table.
                result["resourceCosts"].append({"costType":"LB","Cost":100 if crystals <= 30 else 200})
                result["changes"].append("LB crystal cost becomes one native gauge up to 30 crystals, otherwise two gauges; MP remains a separate cost.")
            except ValueError as ex:
                result["issues"].append(str(ex))
        if result["costs"]["ev_cost"]:
            result["issues"].append("Esper-gauge cost requires a destination resource-cost rule")
        for key in ("equip_requirement", "mission_requirement"):
            if data.get(key):
                result["issues"].append(f"Source {key} must be bound before playable export")
        if record.kind == "field":
            return result
        if all(c["status"] == "noop" for c in result["components"]):
            result["status"] = "noop" if not result["issues"] else "blocked"
            return result
        try:
            result["native"] = self.assemble(record, result)
            from .tag_attacks import finalize
            finalize(self.native,result)
        except (ValueError, TypeError, KeyError, IndexError) as ex:
            result["issues"].append(str(ex))
        if not result["issues"] and result["native"]:
            result["status"] = "replaced" if any(c["status"] == "replaced" for c in result["components"]) else "adapted" if result["changes"] else "converted"
            result["validation"]["tableCompatible"] = True
        return result

    def expand(self, record, component, stack):
        """Inline only the unconditional effect proxy defined by active:71.

        Keep the child's complete conversion in provenance. Copied mechanics
        retain lexicographic execution order, source timing and elements while
        the owning command pays the parent's cost once.
        """
        try:
            if self.resolver is None:
                raise ValueError("Immediate child requires a source catalog")
            child_record = self.resolver.resolve(record.provenance(), component["dependencies"][0])
            component["dependencies"][0]["resolved"] = child_record.key
            if child_record.namespace != "active" or child_record.kind == "lb":
                raise ValueError("Immediate proxy must reference an active skill")
            child = self.convert(child_record, stack)
            component["expanded"] = child
            if child.get("resourceCosts"):
                raise ValueError("Immediate child has an additional resource cost that cannot be omitted")
            if child["status"] == "blocked":
                raise ValueError(f"Immediate child {child_record.key} has blocking issues (see expanded record)")
            child_actions = [a for c in child["components"] for a in c["actions"]]
            for c in child["components"]:
                for field in ("effects", "actions"):
                    for original in c[field]:
                        mechanic = deepcopy(original)
                        mechanic["order"] = [component["index"], *original.get("order", [original["component"]])]
                        mechanic["component"] = component["index"]
                        mechanic.setdefault("source", child_record.key)
                        if field == "actions":
                            mechanic["timing"] = self.action_timing(child_record, child_actions, original)
                            mechanic.setdefault("elements", child_record.data.get("element_inflict"))
                        component[field].append(mechanic)
            component["status"] = child["status"]
            component["changes"].extend(child["changes"])
            component["changes"].append("Immediate child mechanics are expanded in order; the parent command pays its cost once.")
            component["semantic"].update(child=child_record.key, costOwner=record.key)
        except (ValueError, TypeError, KeyError, IndexError) as ex:
            component["status"] = "blocked"
            component["issues"].append(str(ex))

    def race_damage_rewards(self, record, components):
        """Pool race clauses after inline expansion, preserving all base hits.

        A child has a valid standalone reward, but an inlined parent rebuilds
        one shared reward instead of copying a full bonus from each child.
        """
        actions = [a for c in components for a in c["actions"] if a.get("raceBonus")]
        if not actions:
            return
        for component in components:
            component["effects"] = [e for e in component["effects"] if e.get("generated") != "race_damage_reward"]
            component["semantic"].pop("raceDamageReward",None)
        anchor = components[actions[-1]["component"]]
        scratch = {"params":[], "code":22, "index":anchor["index"], "target":target([0,3],"active"),
                   "effects":[], "changes":[], "issues":[], "semantic":{}}
        pairs = [(a["raceBonus"]["race"],a["raceBonus"]["bonusPercent"]) for a in actions]
        subtypes = {a["raceBonus"]["subtype"] for a in actions}
        context = Context(self.native,record,scratch)
        if max(v for _,v in pairs) >= 10:
            context.killers(pairs,1,"physical_and_magic" if len(subtypes)>1 else next(iter(subtypes)))
        else:
            context.change("The pooled race bonus rounds below one native bonus point; only the base attacks remain.")
        # Offensive themes benefit this attack and can survive for a follow-up,
        # including themes that boost a different stat than this attack uses.
        # Defensive/recovery themes cover the interval after the attack.
        sources = [{"source":a.get("source",record.key),"order":list(execution_order(a)), **a["raceBonus"]} for a in actions]
        for effect in scratch["effects"]:
            settings=effect["set"]
            offensive = settings["EffectType"] in ("CriticalRateVariation","BreakDamageVariation") or (
                settings["EffectType"] == "ParameterContinuousVariation" and settings["ParamList"][1] in (5,7,9))
            if offensive:
                settings["effectEndActionNum"] = 2
            effect.update(generated="race_damage_reward", order=[-1 if offensive else len(components)], raceDamageSources=deepcopy(sources))
            self.native.validate_effect(effect)
        anchor["effects"].extend(scratch["effects"])
        anchor["changes"].extend(v for v in scratch["changes"] if v not in anchor["changes"])
        scratch["semantic"].pop("turns",None)
        anchor["semantic"]["raceDamageReward"] = {"owner":"equipping_actor", "timing":"around_complete_attack",
            "lifetimes":{"offensive":2,"defensiveAndRecovery":1}, "sources":sources, "theme":scratch["semantic"]}

    def assemble(self, record, result):
        effects = sorted([deepcopy(e) for c in result["components"] for e in c["effects"]], key=execution_order)
        actions = [deepcopy(a) for c in result["components"] for a in c["actions"]]
        passive = record.namespace == "passive"
        # Do not collapse distinct component applications (two heals, two
        # probabilistic attempts, or two ordered child actions). Repeated IDs
        # inside a single component may still share one persistent mechanic.
        unique = {}
        for effect in effects:
            identity = json.dumps(effect, sort_keys=True)
            unique.setdefault(identity, effect)
        effects = list(unique.values())
        if passive:
            if actions:
                raise ValueError("Passive emitted an immediate action")
            name, donor = next(iter(self.native.passives.items()))
            settings = {"effectBundleList": [], "bBattleOnly": True, "equipCost": 0, "isRemovable": True}
            if any(e.get('passiveTiming')=='BeginBattle' for e in effects):
                # Match native startup passives: the event supplies the battle
                # boundary without adding a separate in-battle-state gate.
                settings['bBattleOnly']=False
            return {"table": "Skill/DT_PassiveSkillData", "cloneFrom": name, "set": settings,
                    # The native passive dispatcher iterates TArray.Num at
                    # row+0x58, visiting every 24-byte bundle. Keep distinct
                    # event timings and all source effects in that array.
                    "effects": effects, "sequence": None, "owner": "equipping_actor"}
        primary = actions[0] if actions else None
        if len(actions) > 1:
            from .applications import signature, compose
            if any(signature(a, record) != signature(primary, record) for a in actions[1:]):
                return compose(self, record, result, actions, effects)
        if primary and any(a["kind"] != primary["kind"] or a["damageType"] != primary["damageType"] or
                           a["target"] != primary["target"] or a.get("calc") != primary.get("calc") for a in actions):
            raise ValueError("Mixed damage/healing formulas or action targets require separate sequencer application jobs")
        if len(actions) > 1:
            indices = [execution_order(a) for a in actions]
            if any(min(indices) < execution_order(e) < max(indices) for e in effects):
                raise ValueError("An effect between damage components requires ordered application jobs")
        if primary:
            targeting = deepcopy(primary["target"])
        else:
            sides = {e["target"]["relation"] for e in effects}
            only_self = bool(effects) and all(e["target"]["shape"] == "Self" for e in effects)
            shapes = {e["target"]["shape"] for e in effects}
            targeting = {"shape": "Self" if only_self else "All" if "All" in shapes else "Group" if "Group" in shapes else "Random" if "Random" in shapes else "Single",
                         "relation": "Friendlies" if "Friendlies" in sides else "Enemies",
                         "state": "Dead" if effects and all(e["target"]["state"] == "Dead" for e in effects) else "Alive"}
            if targeting["shape"] == "All":
                targeting["relation"] = "Enemies"
            candidates = [e["target"] for e in effects if all(e["target"].get(k) == targeting[k] for k in ("shape","relation","state"))]
            for flag in ("ignoreSelf","eitherSide"):
                values = {bool(t.get(flag)) for t in candidates}
                if len(values) > 1:
                    raise ValueError("Effects require different caster-exclusion or side-selection filters")
                targeting[flag] = values == {True}
        from .all_targets import prepare as prepare_all
        all_targeting = prepare_all(self.native,targeting,effects)
        for effect in effects:
            t = effect["target"]
            if t["shape"] in ("Single", "Random") and (t["relation"] != targeting["relation"] or t["state"] != targeting["state"]):
                raise ValueError("Independently selected mixed-side targets need separate targeting jobs")
            if t["shape"] in ("Single", "Random") and t["shape"] != targeting["shape"]:
                raise ValueError("Different single/random/group selections need separate targeting jobs")
            if t["shape"] != "Self" and t["state"] != targeting["state"]:
                raise ValueError("Living and dead group recipients need separate targeting jobs")
            same_selection = all(t.get(k) == targeting.get(k) for k in ("shape","relation","state"))
            same_filters = all(bool(t.get(k)) == bool(targeting.get(k)) for k in ("ignoreSelf","eitherSide"))
            if (t.get("ignoreSelf") or t.get("eitherSide")) and not (same_selection and same_filters):
                raise ValueError("Per-effect caster exclusion or side selection needs a recipient filter")
            if same_selection and not same_filters:
                raise ValueError("Effects require different caster-exclusion or side-selection filters")
            if t.get("ignoreSelf") or t.get("eitherSide"):
                effect["targetBinding"] = "skill_selection"
                effect["targetBindingEvidence"] = self.native.filtered_selection_evidence(t["shape"],t["relation"],t["state"],
                    ignore_self=bool(t.get("ignoreSelf")), either_side=bool(t.get("eitherSide")))
        def element_list(value):
            value = [value] if isinstance(value, str) else value or []
            return list(dict.fromkeys("Thunder" if e == "Lightning" else e for e in value if e not in ("None", None)))
        elements = element_list(primary.get("elements", record.data.get("element_inflict"))) if primary and primary['kind'] == 'damage' else []
        if any(element_list(a.get("elements", record.data.get("element_inflict"))) != elements for a in actions if a['kind'] == 'damage'):
            raise ValueError("Linked damage actions have different elements and require separate application jobs")
        if any(e not in ELEMENT_IDS for e in elements):
            raise ValueError("Unknown source element")
        from .multiple_elements import prepare as prepare_elements
        element_binding, element_effects = prepare_elements(self.native,result,primary,elements)
        damage = bool(primary and primary["kind"] == "damage")
        healing = bool(primary and primary["kind"] == "heal")
        multiple = sum(a["multiple"] for a in actions)
        power = self.native.power(multiple, primary["damageType"], record.kind == "lb") if damage else 0
        if healing:
            power = max(15, min(330, round(multiple*20+sum(a.get("base",0) for a in actions)/100)))
        if primary:
            power = round(power*max(a.get("powerBoost", 1.) for a in actions))
        frames, ratios, groups = self.timing(record, actions)
        hits = len(ratios) or 1
        donor_id = 440110 if record.kind == "lb" and damage else 503550
        donor_name = self.native.skill_ids[donor_id]
        settings = {"skillAttrType": "FinishBlow" if record.kind == "lb" else "Magic" if record.kind == "magic" else "Ability",
                    "skillEffectType": "DamageAndRecovery" if primary else "None",
                    "parameterVariationType": "Decrease" if damage else "Increase",
                    "DamageType": ("None" if primary.get("calc") == "Fixed" else primary["damageType"]) if primary else "None",
                    "damageCalcType": primary.get("calc", "Magic") if primary else "None",
                    "parameterType": "HitPoint" if primary else "None", "element": elements[0] if elements and damage else "None",
                    "TargetType": targeting["shape"], "defaultTargetRelation": targeting["relation"],
                    "defaultTargetState": targeting["state"], "isAliveOnly": targeting["state"] == "Alive",
                    "isSameRelationTargetingDisabled": targeting["relation"] == "Enemies" and targeting["shape"] != "All",
                    "isHostilityRelationTargetingDisabled": targeting["relation"] == "Friendlies" and not targeting.get("eitherSide"),
                    "isTargetIgnoreSelf": targeting.get("ignoreSelf",False), "targetRage": "None", "isReverseDamageToUndead": False,
                    "Cost": 0 if record.kind == "lb" else min(99, round(number(result["costs"]["mp_cost"] or 0)*1.5)),
                    "magnification": power, "breakDamageValue": ((25 if primary["damageType"] == "Physic" else 20)+max(a.get("breakBonus",0) for a in actions)) if damage else 0,
                    "criticalHitRate": primary.get("criticalHitRate", 3 if primary["damageType"] == "Physic" else 2) if damage else 0,
                    "accuracy": primary.get("accuracy",100) if primary else 100,
                    "statusCondition": "None", "hitCount": hits,
                    # FSKILL_DATA uses TArray<float>, not a fixed hit buffer.
                    # Retain the donor's padding and extend for every source hit.
                    "hitDamageRatioList": (ratios or [1.]) + [0.]*max(0,len(self.native.skills[donor_name]["hitDamageRatioList"])-hits),
                    "effectBundleList": [], "totalDamageDisplayRule": "Default" if primary else "Hidden",
                    "playSequencerId": -1, "sequencerIdWhenTargetFriendlies": -1,
                    "belongCommandList": [], "commandIdBelongDebuggingAllSkills": [-1,-1],
                    "SkillIcon.TagName": "UI.Skill.Action.Icon."+(elements[0] if elements and damage else "Attack" if damage else "Support")}
        for effect in effects:
            effect["activeTiming"] = "BeforeDamageCalculation" if primary and execution_order(effect) < execution_order(primary) else "AfterDamageCalculation"
        self.native.validate_skill(settings)
        from .tag_attacks import marker
        tag_binding = marker(self.native,actions)
        return {"table": "Skill/DT_SkillData", "cloneFrom": donor_name, "set": settings, "effects": self.pack_effects(effects,8)+element_effects,
                **({'tagAttack':tag_binding} if tag_binding else {}),
                **({"multipleElements":element_binding} if element_binding else {}),
                **({"allTargeting":all_targeting} if all_targeting else {}),
                "owner": "equipping_actor", "sequence": {"fps":60,"hitFrames":frames,"hitWeights":ratios,
                    "components": groups, "applicationFrames": record.data.get("attack_frames"),
                    "requiresAnimationBinding": True},
                "wrapper": {"kind": "resonance" if record.kind == "lb" else "command", "sourceGaugeCost":result["costs"]["lb_cost"],
                            "requiresGaugeBinding": record.kind == "lb", "requiresCommandBinding": True},
                "general": {"equipperActionVisionSkills": record.kind != "enemy",
                            "additionalCostData":deepcopy(result["resourceCosts"]), "costCheckData":deepcopy(result["resourceCosts"])}}

    def pack_effects(self, effects, capacity):
        """Use native Bad Breath's four-child AddEffect row for bundle overflow.

        Only consecutive effects with identical recipients and application
        timing share a wrapper. Child chance/lifetime remains on each child.
        """
        if len(effects) <= capacity:
            return effects
        groups = []
        for effect in effects:
            if groups and len(groups[-1]) < 4 and all(effect.get(k) == groups[-1][0].get(k) for k in ("target","activeTiming","targetBinding")):
                groups[-1].append(effect)
            else:
                groups.append([effect])
        packed = []
        for group in groups:
            if len(group) == 1:
                packed.extend(group)
                continue
            wrapper = self.native.effect(1376, [0]+[-1]*4)
            wrapper["set"].update(applyTiming="AddEffect",proceedTiming="AddEffect",effectEndActionNum=1)
            wrapper.update(target=deepcopy(group[0]["target"]),component=group[0]["component"],
                           activeTiming=group[0].get("activeTiming","AfterDamageCalculation"),children=group)
            for key in ("targetBinding","targetBindingEvidence"):
                if key in group[0]:
                    wrapper[key] = deepcopy(group[0][key])
            packed.append(wrapper)
        if len(packed) > capacity:
            raise ValueError(f"Native bundle capacity still exceeded after same-target grouping ({len(packed)} > {capacity})")
        return packed

    def action_timing(self, record, actions, action):
        if "timing" in action:
            return deepcopy(action["timing"])
        frames = record.data.get("attack_frames") or []
        weights = record.data.get("attack_damage") or []
        count = len(record.data.get("effects_raw") or [])
        if frames and not isinstance(frames[0], list):
            frames = [frames]
        if weights and not isinstance(weights[0], list):
            weights = [weights]
        index = action["component"]
        layout = None
        if len(frames) == count:
            position = index
            layout = "component_aligned"
        elif len(frames) == len(actions) and len({a["component"] for a in actions}) == len(actions) and not any("timing" in a for a in actions):
            # FFBE also stores only the damaging/recovery portions, with no
            # empty placeholder for adjacent buffs or debuffs (e.g. Flood II).
            # Expanded child timelines are already explicit and cannot be
            # reinterpreted as this source's compact action array.
            position = next(i for i,a in enumerate(actions) if a is action)
            layout = "compact_actions"
        elif 0 < len(frames) < count and index < len(frames):
            # Raw FFBE timing can stop before the last effect. Both the
            # FFBE Equip parser and wiki parser use the raw component index
            # while it is in bounds; trailing support effects do not shift it.
            position = index
            layout = "component_prefix"
        elif (0 < len(frames) < count and all(group == frames[0] for group in frames)
              and (not weights or len(weights) == len(frames) and all(group == weights[0] for group in weights))):
            # The reference parsers disagree on general out-of-range timing
            # (last group versus wrapping). Identical groups are unambiguous
            # under either rule. Do not invent timing for an empty group.
            position = 0
            layout = "shared_identical"
        else:
            position = None
        return {"frames": deepcopy(frames[position]) if position is not None and position < len(frames) else [],
                "weights": deepcopy(weights[position]) if position is not None and position < len(weights) else [],
                "binding": {"layout":layout, "groupIndex":position, "componentIndex":index, "groupCount":len(frames)}}

    def timing(self, record, actions):
        jobs, hits = [], []
        total = sum(a["multiple"] for a in actions) or 1
        for a in actions:
            index = a["component"]
            timing = self.action_timing(record, actions, a)
            group, values = timing["frames"], timing["weights"]
            if not group:
                if a["kind"] == "damage":
                    raise ValueError(f"Missing or ambiguous hit frames for damage component {index}")
                group = [0]
            group = [integer(v, "hit frame", 0) for v in group]
            if values:
                if len(values) != len(group):
                    raise ValueError(f"Frame/weight count mismatch on component {index}")
                values = [number(v, "hit weight", 0) for v in values]
                if sum(values) <= 0:
                    raise ValueError("Hit weights must have positive total")
                values = [v/sum(values) for v in values]
            elif len(group) == 1:
                values = [1.]
            else:
                raise ValueError(f"Missing hit distribution for component {index}")
            share = a["multiple"]/total if a["kind"] == "damage" else 1/len(actions)
            jobs.append({"index": index, "order":list(execution_order(a)), "source":a.get("source", record.key),
                         "frames": group, "weights": values, "budgetShare": share,
                         "timingBinding":deepcopy(timing.get("binding"))})
            hits.extend((frame, weight*share, execution_order(a)) for frame, weight in zip(group, values))
        hits.sort(key=lambda h: (h[0], h[2]))
        return [h[0] for h in hits], [h[1] for h in hits], jobs


def execution_order(mechanic):
    return tuple(mechanic.get("order", [mechanic["component"]]))


class TableWriter:
    """Write the existing cloneFrom/set patch format with a persistent ID ledger.

    This produces mechanics rows, not cooked packages. String, command, gauge,
    sequencer, and equipping-actor bindings remain explicit integration jobs.
    """
    def __init__(self, native, ledger=None):
        from .skill_ids import ID_STARTS, validate_id
        self.native = native
        self.ledger = ledger if ledger is not None else {"skills":{},"passives":{},"effects":{}}
        if not isinstance(self.ledger, dict) or set(self.ledger) != set(ID_STARTS):
            raise ValueError("ID ledger requires skills, passives and effects dictionaries")
        self.used = {"skills":set(native.skill_ids), "passives":set(native.passive_ids), "effects":set(native.effects)}
        for kind, entries in self.ledger.items():
            if not isinstance(entries, dict) or any(not isinstance(key, str) or not key for key in entries):
                raise ValueError(f"Invalid {kind} ledger entries")
            values = list(entries.values())
            for value in values:
                validate_id(kind, value)
            if len(set(values)) != len(values) or self.used[kind].intersection(values):
                raise ValueError(f"Duplicate/colliding IDs in {kind} ledger")
            self.used[kind].update(values)
        self.tables = {}
        self.strings = {}
        self.bindings = []
        self.general = GeneralBindings(native)
        self.emitted = set()
        self.pending_skills = []
        # Scan free slots, including holes below a persisted high ID. Existing
        # keys keep their assignments; a sparse ledger cannot exhaust a bank.
        self.next_ids = dict(ID_STARTS)

    def allocate(self, kind, key):
        from .skill_ids import ID_RANGES
        if key not in self.ledger[kind]:
            value = self.next_ids[kind]
            start, stop = ID_RANGES[kind]
            while value < stop and value in self.used[kind]:
                value += 1
            if not start <= value < stop:
                raise ValueError(f"Native {kind} ID range exhausted ({start}..{stop-1})")
            self.ledger[kind][key] = value
            self.used[kind].add(value)
            self.next_ids[kind] = value+1
        return self.ledger[kind][key]

    def add(self, result):
        if not result["validation"]["tableCompatible"]:
            raise ValueError("Blocked entries cannot be exported as native table rows")
        native = result["native"]
        from .tag_attacks import validate as validate_tag
        validate_tag(self.native,result)
        from .multiple_elements import validate as validate_elements
        validate_elements(self.native,result)
        from .all_targets import validate as validate_all
        validate_all(self.native,native)
        from .random_effects import validate as validate_random
        from .reraise import validate as validate_reraise
        from .dispel import validate as validate_dispel
        from .stop import validate as validate_stop
        from .imbues import validate as validate_imbue
        from .delayed_actions import validate as validate_delayed
        from .automatic_passives import validate as validate_automatic, coverage as automatic_coverage
        for spec in native["effects"]:
            validate_automatic(self.native,spec)
            from .startup_recovery import valid as startup_recovery
            startup = startup_recovery(self.native, spec)
            if spec.get('passiveTiming') and (native['table']!='Skill/DT_PassiveSkillData'
                    or not startup and (not spec.get('automaticPassive') or spec['automaticPassive']['code']!=103
                    or spec['passiveTiming']!='BeginBattle')):
                raise ValueError('Passive event timing requires its complete source trigger binding')
            if spec.get('passiveTiming')=='BeginBattle' and native['set']['bBattleOnly'] is not False:
                raise ValueError('Battle-start passive must retain native startup availability')
            if automatic_coverage(spec) and native['table']!='Skill/DT_PassiveSkillData':
                raise ValueError('Automatic passive requires a native equippable passive owner')
            validate_delayed(self.native,spec)
            validate_random(spec,native=self.native)
            validate_reraise(self.native,spec)
            validate_dispel(self.native,spec)
            validate_stop(self.native,spec)
            validate_imbue(self.native,spec)
        if native.get("applications"):
            from .applications import validate
            validate(self.native, native)
        kind = "passives" if native["table"].endswith("DT_PassiveSkillData") else "skills"
        key = result["source"]["key"]
        if key in self.emitted:
            raise ValueError(f"Duplicate source identity: {key}")
        self.emitted.add(key)
        sid = self.allocate(kind, key)
        name = f"FFBE_{sid}"
        settings = deepcopy(native["set"])
        if native.get("general"):
            self.general.add(sid,native["general"])
        settings.update(ID=sid, SortId=sid)
        application_ids = {job["index"]:self.allocate("skills", f"{key}#application/{job['index']}")
                           for job in native.get("applications", [])}
        settings["effectBundleList"] = []
        for spec in native["effects"]:
            if 'tagAttack' in spec:
                spec=deepcopy(spec)
                indices=spec['tagAttack']['applicationIndices']
                spec['set']['ParamList'][1:1+len(indices)]=[application_ids[i] if i else sid for i in indices]
            if "skillElement" in spec:
                spec = deepcopy(spec)
                index = spec['skillElement'].get('applicationIndex', 0)
                spec["set"]["ParamList"][1] = application_ids[index] if index else sid
            if "applicationIndex" in spec:
                spec = deepcopy(spec)
                spec["set"]["ParamList"][0] = application_ids[spec["applicationIndex"]]
            eid = self.emit_effect(spec)
            target = spec["target"]
            settings["effectBundleList"].append({"effectId":eid,
                "TargetType":"SkillTarget" if spec.get("targetBinding") == "skill_selection" or target["shape"] in ("Single","Random") else target["shape"],
                "targetRelation":target["relation"], "activeSkillAddTiming":spec.get("activeTiming","AfterDamageCalculation"),
                "passiveSkillAddTiming":spec.get('passiveTiming','SpawnUnit') if kind == "passives" else "None", "conditionData":deepcopy(CONDITION)})
        prefix = "PassiveSkill" if kind == "passives" else "Skill"
        for field in ("Name", "Description"):
            table = f"/Game/Datatable/Strings/ST_Skill/ST_{prefix}{field}.ST_{prefix}{field}"
            string_key = f"{prefix}{field}{sid}"
            value = (result["name"] or result["source"]["id"]) if field == "Name" else self.description(result)
            # Literal FText is supported by ffr-dt and avoids dangling entries in
            # stock string tables. Companion strings remain available to Studio.
            settings[field] = value
            self.strings.setdefault(table, {})[string_key] = value
        self.tables.setdefault(native["table"], {"add":[]})["add"].append({"row":name,"cloneFrom":native["cloneFrom"],"set":settings})
        if self.pending_skills:
            self.tables.setdefault("Skill/DT_SkillData",{"add":[]})["add"].extend(self.pending_skills)
            self.pending_skills.clear()
        for job in native.get("applications", []):
            child_id = application_ids[job["index"]]
            child_settings = {**deepcopy(job["set"]), "ID":child_id, "SortId":child_id,
                              "Name":settings["Name"], "Description":settings["Description"]}
            self.tables[native["table"]]["add"].append({"row":f"FFBE_{child_id}", "cloneFrom":job["cloneFrom"], "set":child_settings})
        self.bindings.append({"source":key,"table":native["table"],"row":name,"id":sid,"owner":native["owner"],
                              "sequence":native["sequence"],"wrapper":native.get("wrapper"),
                              "general":deepcopy(native.get("general")),
                              "targetBindings":[{"component":e["component"], "binding":e["targetBinding"],
                                                  "evidence":deepcopy(e.get("targetBindingEvidence"))}
                                                for e in native["effects"] if e.get("targetBinding")],
                              "presentation":result["presentation"],"runtimeValidation":"not_run"})
        if application_ids:
            self.bindings[-1]["applications"] = [{"id":application_ids[job["index"]],
                "role":"private_appended_hit", "frame":job["frame"], "hitNumber":job["hitNumber"],
                "hitBudget":deepcopy(job["hitBudget"])} for job in native["applications"]]
        return sid

    def emit_effect(self, spec):
        if spec.get('orderedAilments'):
            from .ordered_ailments import expand
            return self.emit_effect(expand(spec,self.native))
        if spec.get('automaticPassive'):
            from .automatic_passives import emit
            return emit(self,spec)
        if spec.get('delayedAction'):
            from .delayed_actions import emit
            return emit(self,spec)
        if spec.get("reraise"):
            from .reraise import emit
            return emit(self,spec)
        settings = deepcopy(spec["set"])
        if spec.get("randomChoices"):
            children = [self.emit_effect(child) for child in spec["randomChoices"]]
            settings["ParamList"] = [0]+children+[-1]*(14-len(children))
        elif spec.get("children"):
            children = [self.emit_effect(child) for child in spec["children"]]
            if len(children) > 4:
                raise ValueError("AddEffect wrapper exceeds the four-child native template")
            settings["ParamList"] = [0]+children+[-1]*(14-len(children))
        self.native.validate_effect({"template":spec["template"],"set":settings})
        signature = json.dumps(settings,sort_keys=True,separators=(",",":"))
        effect_key = hashlib.sha256(signature.encode()).hexdigest()
        eid = self.allocate("effects",effect_key)
        if eid not in self.emitted:
            table = self.tables.setdefault("Skill/DT_SkillEffectData",{"add":[]})
            table["add"].append({"row":f"FFBE_effect_{eid}","cloneFrom":self.native.effect_names[spec["template"]],
                                 "set":{"ID":eid,**settings}})
            self.emitted.add(eid)
        return eid

    @staticmethod
    def description(result):
        return describe(result)

    def patch(self, out_root, legacy_root=ROOT/"extracted/legacy"):
        tables = dict(self.tables)
        if general := self.general.patch():
            tables[GENERAL_TABLE] = general
        return {"legacyRoot":str(legacy_root).replace("\\","/"),"outRoot":str(out_root).replace("\\","/"),
                "tables":[{"asset":"FFRS/Content/Datatable/"+table,**data} for table,data in tables.items()],
                "bindings":deepcopy(self.bindings),"runtimeValidation":"not_run"}


def describe(result):
    """Player-facing wording describes emitted mechanics, not conversion code."""
    native = result["native"]
    row = native["set"]
    parts = []
    for cost in result.get("resourceCosts", []):
        if cost["costType"] == "LB":
            parts.append(f"Consumes {cost['Cost']//100} resonance gauge{'s' if cost['Cost'] != 100 else ''}.")
    def recipient(t):
        if t["shape"] == "All":
            return "all allies and enemies"
        if t["shape"] == "Self":
            return "the user"
        group = t["shape"] == "Group"
        prefix = "all " if group else "one random " if t["shape"] == "Random" else "one "
        if t.get("ignoreSelf"):
            prefix += "other "
        noun = ("targets" if group else "target") if t.get("eitherSide") else ("enemies" if group else "enemy") if t["relation"] == "Enemies" else ("allies" if group else "ally")
        return prefix+noun+(" on the selected side" if group and t.get("eitherSide") else "")
    if row.get("magnification"):
        groups = {}
        for job in [native, *native.get("applications", [])]:
            action_row = job['set']
            who = recipient({"shape":action_row["TargetType"],"relation":action_row["defaultTargetRelation"],
                             "ignoreSelf":action_row.get("isTargetIgnoreSelf"),
                             "eitherSide":not action_row.get("isSameRelationTargetingDisabled") and not action_row.get("isHostilityRelationTargetingDisabled")})
            damage_element = '/'.join(job['multipleElements']['elements']) if job.get('multipleElements') else action_row['element']
            key = action_row["parameterVariationType"], action_row["DamageType"], damage_element, who, (job.get('tagAttack') or {}).get('bonusPercent',0)
            groups[key] = groups.get(key,0)+action_row["hitCount"]
        for (variation, damage_type, damage_element, who, stagger), count in groups.items():
            if variation == "Increase":
                parts.append(f"Restores HP to {who}.")
            else:
                element = damage_element+" " if damage_element != "None" else ""
                dtype = "physical" if damage_type == "Physic" else "magic" if damage_type == "Magic" else "fixed"
                extra=f', with {stagger}% more stagger power' if stagger else ''
                parts.append(f"Deals {count} hit{'s' if count != 1 else ''} of {element}{dtype} damage to {who}{extra}.")
    stats = {1:"maximum HP",2:"maximum MP",4:"resonance gain",5:"ATK",6:"DEF",7:"MAG",8:"SPR",9:"Agility"}
    statuses = {1:"Poison",2:"Blind",3:"Sleep",4:"Silence",5:"Paralysis",6:"Confusion",7:"Petrify",8:"Charm",9:"Stop",
                13:"instant death",15:"ATK down",16:"DEF down",17:"MAG down",18:"SPR down",24:"ATK up",25:"DEF up",26:"MAG up",27:"SPR up"}
    element_names = {v:k for k,v in ELEMENT_IDS.items()}
    def effect_text(effect):
        if effect.get('tagAttack'):
            return
        if removal := effect.get("removal"):
            who = recipient(effect["target"])
            if removal["mode"] == "buffs":
                parts.append(f"Removes dispellable buffs from {who}.")
            else:
                parts.append(f"Removes removable Slow, ATK/DEF/MAG/SPR penalties and stagger penalties from {who}.")
            return
        if automatic := effect.get('automaticPassive'):
            chance=effect['set']['activationProbability']
            chance_text=f'{chance}% chance to ' if chance!=100 else ''
            trigger={66:'At the start of each turn',103:'At battle start',104:'After revival'}[automatic['code']]
            child=automatic['child']
            parts.append(f"{trigger}, {chance_text}automatically use {child['name'] or child['source']['id']}: {describe(child)}")
            return
        if delayed := effect.get('delayedAction'):
            params=delayed['parameters'];turns=params[2]
            chance=f'{params[3]}% chance to ' if params[3]!=100 else ''
            child=delayed['child']
            parts.append(f"After {turns} turn{'s' if turns!=1 else ''}, {chance}automatically use {child['name'] or child['source']['id']}: {describe(child)}")
            return
        if reraise := effect.get("reraise"):
            turns = reraise["turns"]
            parts.append(f"Grants {recipient(effect['target'])} one automatic revival with {reraise['hpPercent']}% HP for {turns} turn{'s' if turns != 1 else ''}.")
            return
        if selection := effect.get("randomSelection"):
            names = {"Paralyzation":"Paralysis", "Stoned":"Petrify", "Disease":"Enfeebled (ATK and MAG down)"}
            pool = ", ".join(names.get(name,name) for name in selection["pool"])
            who = recipient(effect["target"])
            if selection["selection"] == "ordered_capped_outcomes":
                chances=", ".join(f"{names.get(name,name)} {chance:g}%" for name,chance in
                    zip(("Poison","Blind","Sleep","Silence","Paralyzation","Confusion","Disease","Stoned"),selection['sourceChances']) if chance)
                parts.append(f"Rolls ailments in order on {who}, stopping at {selection['count']}: {chances}. "
                    "FFR resistance applies afterward without retrying.")
            elif selection["selection"] == "one_uniform_outcome":
                parts.append(f"Attempts one randomly selected ailment on {who}: {pool}.")
            else:
                parts.append(f"Attempts these ailments on {who}: {pool}.")
            return
        if effect.get("children"):
            for child in effect["children"]:
                effect_text(child)
            return
        e = effect["set"]; p = e["ParamList"]; kind = e["EffectType"]; who = recipient(effect["target"])
        turns = e["effectEndActionNum"]
        duration = f" for {turns} turn{'s' if turns != 1 else ''}" if turns > 0 and e["proceedTiming"] in ("BeginTurn","EndTurn","ActionBegin","ActionEnd") else ""
        if kind == "ParameterContinuousVariation":
            text = f"{'Reduces' if p[2] == 3 else 'Raises'} {stats.get(p[1],'stats')} of {who} by {p[0]:g}%{duration}."
        elif kind == "CureStatusCondition":
            text = f"Removes {statuses.get(p[3],'the selected status')} from {who}."
        elif kind == "AddStatusConditionRegist":
            text = f"Grants {who} {p[1]:g}% resistance to {statuses.get(p[0],'status effects')}{duration}."
        elif kind == "AddElementResistance":
            category = {1:"weakness",2:"half damage",3:"immunity",4:"absorption"}.get(p[1],"resistance")
            text = f"Grants {who} {element_names.get(p[0],'elemental')} {category}{duration}."
        elif kind == "Revival":
            text = f"Revives {who} with {p[0]:g}% HP."
        elif kind == "ParameterVariation" and e["statusCondition"] != "Poison":
            unit = {1:"HP",2:"MP",4:"resonance gauge"}.get(p[1],"resource")
            periodic = " each turn" if e["applyTiming"] == "EndTurn" else ""
            text = f"Restores {p[0]:g}{'%' if p[2] == 2 else ''} {unit} to {who}{periodic}{duration}."
        elif kind == "Deffence":
            text = f"Reduces {'physical' if p[0] == 1 else 'magic'} damage taken by {who} by {p[1]:g}%{duration}."
        elif kind == "DmgMulElement":
            text = f"Raises {element_names.get(p[1],'elemental')} damage of {who} by {p[0]:g}%{duration}."
        elif kind == "AddElement" and not effect.get("skillElement"):
            text = f"Adds {element_names.get(p[0],'an element')} to attacks of {who}{duration}."
        elif kind == "CriticalRateVariation":
            text = f"Raises critical chance of {who} by {p[0]:g}%{duration}."
        elif kind == "BreakDamageVariation":
            text = f"Raises stagger damage of {who} by {p[0]:g}%{duration}."
        elif kind == "Avoidance":
            text = f"Grants {who} {p[0]:g}% {'physical' if p[1] == 1 else 'magic'} evasion{duration}."
        elif kind == "CostVariation":
            text = f"Reduces MP costs for {who} by {100-p[1]:g}%{duration}."
        elif kind == "Counter":
            text = f"Grants {who} a {e['activationProbability']:g}% chance to counter {'physical' if p[0] == 6 else 'magic'} attacks with a normal attack{duration}."
        elif kind in ("MoneyUp","ExperienceUp"):
            text = f"Increases {'gil' if kind == 'MoneyUp' else 'experience'} earned from battles by {p[0]-100:g}%."
        elif kind == "ItemDropUp":
            text = f"Increases item drop rates by {p[0]:g}%."
        elif kind == "EncountRatio":
            text = "Prevents random encounters." if p[0] == 0 else f"{'Reduces' if p[0] < 100 else 'Increases'} random encounter rate by {abs(100-p[0]):g}%."
        elif kind == "Preemtive":
            text = "Prevents enemy sneak attacks."
        elif e["statusCondition"] != "None":
            status = {"Charme":"Charm","Stoned":"Petrify","Paralyzation":"Paralysis"}.get(e["statusCondition"],e["statusCondition"])
            text = f"Applies {status} to {who}{duration}."
        else:
            text = {"Analyze":"Reveals enemy information.","InstantDeath":f"Attempts to defeat {who} instantly.",
                    "Escape":"Attempts to escape from battle.","Steal":"Attempts to steal an item.",
                    "StealRate":"Improves stealing success.",
                    "StealRareRate":"Improves rare-item stealing."}.get(kind,"")
        if text:
            if e["addProbability"] < 100:
                text = f"{e['addProbability']:g}% chance: "+text[0].lower()+text[1:]
            parts.append(text)
    for effect in native["effects"]:
        effect_text(effect)
    return " ".join(parts)
