"""Opcode adapters. Parameter positions come from the local Solaris formatters.

No effect is classified by its localized name, description, or proposal label.
An adapter can decode a mechanic without certifying that FFR can execute it.
"""
from copy import deepcopy
import math

from .native import ELEMENT_IDS, STATUS_IDS
from .sources import ELEMENTS

AILMENTS = ("Poison", "Blind", "Sleep", "Silence", "Paralyzation", "Confusion", "Disease", "Stoned")
STAT_IDS = (5, 6, 7, 8, 1, 2, 9)
STAT_UP = {5: "AttackUp", 6: "DeffenceUp", 7: "IntelligenceUp", 8: "MindUp", 9: "Haste"}
STAT_DOWN = {5: "AttackDown", 6: "DeffenceDown", 7: "IntelligenceDown", 8: "MindDown", 9: "Slow"}
RACE_THEMES = {
    1: ("Feral Heart", "stat", 5), 2: ("Skyborne Reflexes", "evasion", 1),
    3: ("Tidal Renewal", "regen", 2), 4: ("Abyssal Ward", "mitigation", 2),
    5: ("Duelist's Insight", "critical", 0), 6: ("Gearbreaker", "break", 0),
    7: ("Dragonhide", "stat", 1), 8: ("Arcane Grace", "stat", 7),
    9: ("Swarm Instinct", "stat", 9), 10: ("Stalwart Stones", "stat", 6),
    11: ("Verdant Renewal", "regen", 1), 12: ("Soulkeeper", "stat", 8),
}


def number(value, label="parameter", minimum=None, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number; got {value!r}")
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f"{label} is outside its decoded range: {value}")
    return value


def integer(value, label="parameter", minimum=None, maximum=None):
    value = number(value, label, minimum, maximum)
    if int(value) != value:
        raise ValueError(f"{label} must be an integer")
    return int(value)


def killer_entries(races, physical, magical):
    """FFBE Equip broadcasts scalar subtype bonuses across the race vector."""
    races = races if isinstance(races, list) else [races]
    races = [integer(race, "killer race", 0, 12) for race in races]
    subtypes = []
    for label, value in (("physical",physical), ("magical",magical)):
        values = value if isinstance(value, list) else [number(value, label+" killer bonus", 0)]*len(races)
        if len(values) != len(races):
            raise ValueError("Killer race and subtype arrays must align; only scalar bonuses broadcast")
        subtypes.append([number(amount, label+" killer bonus", 0) for amount in values])
    return [{"race":race,"physical":phys,"magical":magic}
            for race,phys,magic in zip(races,*subtypes)]


def target(raw, namespace):
    if namespace == "passive":
        return {"shape": "Self", "relation": "Friendlies", "owner": "equipping_actor", "state": "Alive"}
    if namespace == "field":
        return {"shape": "Group", "relation": None, "owner": "equipping_actor", "state": "Alive"}
    shape, side = raw[:2]
    if shape == 2 and side == 4:
        return {"shape":"All","relation":"Enemies","owner":"equipping_actor","state":"Alive",
                "ignoreSelf":False,"eitherSide":False}
    if shape == 0 and side in (0, 1, 3) or shape == 1 and side == 3:
        return {"shape": "Self", "relation": "Friendlies", "owner": "equipping_actor", "state": "Alive"}
    shapes = {1: "Single", 2: "Group", 3: "Random"}
    if shape not in shapes or side not in (1, 2, 5, 6):
        raise ValueError(f"Target range/side {shape}/{side} needs a native targeting adapter")
    return {"shape": shapes[shape], "relation": "Enemies" if side == 1 else "Friendlies",
            "owner": "equipping_actor", "state": "Alive", "ignoreSelf":side == 5, "eitherSide":side == 6}


class ComponentAdapter:
    def __init__(self, native, registry):
        self.native, self.registry = native, registry

    def convert(self, record, raw, index):
        result = {"index": index, "raw": deepcopy(raw), "namespace": record.namespace,
                  "status": "blocked", "effects": [], "actions": [], "dependencies": [],
                  "changes": [], "issues": [], "semantic": {}}
        try:
            size = 3 if record.namespace == "field" else 4
            if not isinstance(raw, list) or len(raw) != size:
                raise ValueError(f"Expected {size} fields in effects_raw")
            code = integer(raw[1 if record.namespace == "field" else 2], "opcode")
            key = f"{record.namespace}:{code}"
            policy = self.registry.get(key, {})
            result.update(key=key, code=code, family=policy.get("family"), policy=policy.get("strategy", "REVIEW"))
            if not isinstance(raw[-1], list):
                raise ValueError("Effect parameters must be a list")
            result["params"] = raw[-1]
            # Placeholders may carry intentionally empty/invalid targeting.
            if code in (-1, 0):
                result.update(status="noop", semantic={"kind": "placeholder"})
                return result
            result["target"] = target(raw, record.namespace)
            if result["target"]["shape"] == "All":
                result["changes"].append("All-unit targeting uses the native living selection across allies and enemies, including the caster.")
            context = Context(self.native, record, result)
            if record.namespace == "active":
                self.active(context)
            elif record.namespace == "passive":
                self.passive(context)
            else:
                self.field(context, raw[0])
            for effect in result["effects"]:
                self.native.validate_effect(effect)
            if not result["effects"] and not result["actions"] and not result["dependencies"] and not result["semantic"] and not result["issues"]:
                result.update(status="noop", semantic={"kind":"zero_magnitude"})
                return result
            if not result["issues"]:
                result["status"] = "replaced" if result.get("replacement") else "adapted" if result["changes"] else "converted"
        except (ValueError, TypeError, IndexError, KeyError) as ex:
            result["issues"].append(str(ex))
        return result

    def active(self, c):
        p, code = c.p, c.code
        if code in (22,23):
            if len(p) != 4:
                raise ValueError("Race-dependent damage requires four parameters")
            race = integer(p[0], "damage race", 1, 12)
            controls = [integer(p[i], "race-damage control", 0) for i in (1,2)]
            coefficient = number(p[3], "race damage coefficient", 0)
            c.r["semantic"] = {"kind":"race_dependent_damage", "race":race, "baseMultiple":1,
                "raceMultiple":coefficient/100, "sourceControls":controls,
                "nativeCandidate":"DmgVariationByRace", "runtimeValidation":"not_run"}
            if controls != [0,0]:
                c.hold("Unknown race-damage controls may change its base coefficient or condition")
                return
            if coefficient < 100:
                c.hold("Reduced damage against a race needs a conditional penalty, not a positive killer bonus")
                return
            # The FFBE Equip active parser and damage evaluator establish a
            # 1x base, REPLACED by Param[3]/100 only for the matching race.
            c.damage(1, "Physic" if code == 22 else "Magic")
            if coefficient > 100:
                c.r["actions"][-1]["raceBonus"] = {"race":race, "bonusPercent":coefficient-100,
                    "subtype":"physical" if code == 22 else "magic"}
                c.replace(RACE_THEMES[race][0], "The 1x base attack remains; its race-only coefficient becomes a pooled self benefit "
                    "using the killer themes. Offensive rewards apply before damage for two turns; defensive and recovery rewards apply afterward for one turn. "
                    "All race-dependent portions share one capped bonus, and the race check is removed.")
        elif code in (1, 15, 21, 40, 41, 43, 70, 72, 79, 80, 102, 103, 105, 124, 126, 169, 1007, 1024):
            if code == 1:
                c.damage(c.n(6)*(1+c.n(5)/100)/100, "Physic")
                if len(p) > 7 and c.n(7):
                    c.r["actions"][-1]["accuracy"] = min(100, 100+c.n(7))
            elif code == 15:
                c.damage(c.n(5)/100, "Magic")
            elif code == 40:
                c.damage((c.n(8)+c.n(9))/200, "Magic")
                c.replace("Hybrid to magic", "The average ATK/MAG multiplier becomes one magic damage budget.")
            elif code == 41:
                c.damage(c.n(0)/100, "Magic", calc="Fixed")
                c.change("Fixed damage normalized to FFR values without physical or magical multipliers.")
            elif code in (21, 70):
                c.damage(c.n(2)/100, "Physic" if code == 21 else "Magic")
                c.r["actions"][-1]["powerBoost"] = 1.15
                c.replace("Piercing Force", "DEF/SPR penetration becomes a bounded 15% power increase.")
            elif code == 43:
                c.damage(c.n(2)/100, "Physic")
                c.r["actions"][-1].update(criticalHitRate=100, accuracy=max(0, 100-c.n(3)))
            elif code in (79, 80):
                c.damage(c.n(7 if code == 79 else 6)/100, "Magic")
                c.replace("Evoke to magic", "Evoke scaling becomes a normalized magic attack.")
            elif code in (102, 103, 105):
                if code == 102 and len(p) > 3 and p[3] is not None:
                    c.effect(1007,[20,9,2,0,0,0],turns=3,status="Haste")
                    c.replace("Quickcast","The multicast variant of opcode 102 becomes a 20% Haste buff.")
                else:
                    c.damage(c.n(2)*c.n(0)/10000, "Physic" if code == 102 else "Magic")
                    c.replace("Alternate-stat damage", "DEF/SPR/MP scaling becomes the destination physical/magic formula.")
            elif code == 169:
                c.r["semantic"] = {"kind":"all_mp_damage","stat":p[0],"percentOfConsumedMP":c.n(1)}
                c.hold("Consumes all remaining MP; its resource cost and damage basis must be preserved together")
            elif code == 1024:
                c.damage((c.n(0)+c.n(1))/200, "Magic")
                c.replace("Evoke to magic", "Evoke and morale scaling become one fixed magic power tier.")
            elif code == 124:
                ratio = p[9]
                if not isinstance(ratio,list) or len(ratio) != 2 or sum(ratio) <= 0:
                    raise ValueError("Evoke stat ratio must contain two positive weights")
                c.damage((c.n(7)*number(ratio[0])+c.n(8)*number(ratio[1]))/(100*sum(ratio)),"Magic")
                c.replace("Evoke to magic", "Weighted MAG/SPR evoke multiplier becomes one magic damage budget.")
            else:
                pos = 3 if code == 126 else 2
                c.damage(c.n(pos)/100, "Magic" if code == 72 else "Physic")
                c.replace("Steady Force", "Uses the initial damage tier; repeated-use ramping is removed.")
        elif code == 42:
            c.r["semantic"] = {"kind": "random_repeat", "min": c.n(2), "max": c.n(3), "multiple": c.n(4)/100}
            c.hold("Random repeat count requires action scheduling and a shared total damage budget")
        elif code in (9, 39, 83):
            c.r["semantic"] = {"kind": "hp_damage", "basis": "target_current" if code == 9 else "caster_current" if code == 83 else "hp_sacrifice"}
            c.hold("HP-basis damage requires boss restrictions and lethal/nonlethal validation")
        elif code in (2, 16, 17, 26, 64, 65):
            if code == 2:
                c.heal(c.n(2), c.n(3)/100)
            elif code in (16, 17):
                c.recover(c.n(0), 1 if code == 16 else 2, ratio=False)
            elif code == 26:
                lo, hi, chance = c.n(0), c.n(1), c.n(2)
                c.recover((lo+hi)/2, 1, chance=chance)
                if lo != hi:
                    c.change("Random recovery range becomes its mean.")
            else:
                for i in range(2):
                    c.recover(c.n(i), i+1, ratio=code == 64)
        elif code == 38:
            base, multiple, chance = c.n(3), c.n(2)/100, c.percent(4)
            number(base, "base healing", 0); number(multiple, "healing multiplier", 0)
            if c.n(0) != 0 or c.n(1) != 0:
                raise ValueError("Unknown chance-healing formula flags")
            if not chance or not (base or multiple):
                return
            c.r["semantic"] = {"kind":"chance_healing", "base":base, "multiple":multiple, "chance":chance}
            if chance == 100:
                c.heal(base, multiple)
            else:
                c.recover(min(30, max(1, round(multiple*5+base/100))), 1, chance=chance)
                c.replace("Answered Prayer", "Chance healing becomes capped maximum-HP recovery; the source success chance is retained.")
        elif code in (8, 30, 56, 57, 131):
            turns = c.turn(3)
            resource = 2 if code in (30, 57, 131) else 1
            c.recover(5, resource, periodic=True, turns=turns)
            c.replace("Refresh" if resource == 2 else "Regeneration", "Source flat/scaled recovery becomes 5% maximum resource each turn.")
            if code in (56, 57):
                c.change("Song channeling becomes a timed effect.")
        elif code == 4:
            c.effect(1063, [c.percent(0)], state="Dead")
            c.r["semantic"] = {"kind": "revival", "hpPercent": c.percent(0)}
        elif code == 27:
            from .reraise import convert
            convert(c)
        elif code in (3, 24, 36, 58, 1028):
            if not any(c.n(i) for i in range(4)):
                return
            turns = c.turn(4)
            undispellable = bool(c.n(5)) if code == 1028 else len(p) > 6 and p[6] == 1
            for i, stat in enumerate(STAT_IDS[:4]):
                c.stat(-abs(c.n(i)) if code == 24 else c.n(i), stat, turns, undispellable)
            if code in (36, 58):
                c.replace("Inspiring Voice", "Singing becomes a timed stat buff without a channel lock.")
        elif code == 66:
            c.r["semantic"] = {"kind": "hp_barrier_or_hp_buff", "amount": c.n(0)}
            c.hold("Maximum HP effect lifetime is not established by this opcode")
        elif code in (18, 19, 101, 115, 116):
            turns = c.turn(2 if code in (115, 116) else 1)
            types = (1,) if code in (18, 115) else (2,) if code in (19, 116) else (1, 2)
            for damage in types:
                c.mitigation(c.n(0), damage, turns, len(p) > 3 and p[3] == 0)
        elif code in (33, 117, 1029, 1017):
            turns = c.turn(8 if code == 1017 else 9)
            for i, element in enumerate(ELEMENTS):
                amount = c.n(i)
                if amount:
                    category = 4 if code == 1017 else 1 if amount < 0 else 3 if amount >= 100 else 2
                    c.effect(1022, [ELEMENT_IDS[element], category], turns=turns, unremovable=code == 117)
            c.change("Element resistance percentages become native weakness/half/null/absorb categories.")
        elif code == 95:
            from .imbues import convert
            convert(c)
        elif code in (149, 1030):
            c.r["semantic"] = {"kind": "element_amplification", "damageSubtype": p[0]}
            if code == 1030:
                c.change("Stacking elemental amplification shares the ordinary amplification cap.")
            values = p[1] if isinstance(p[1], list) else [p[1]]
            for i, value in enumerate(values):
                if value:
                    c.effect(12955, [min(20, abs(number(value))/5), ELEMENT_IDS[ELEMENTS[i]]], turns=c.turn(3), unremovable=p[4] == 0)
            c.replace("Elemental Attunement", "Element-specific bonus is capped at 20%; physical/magic subtype becomes both damage types.")
        elif code in (5, 111, 148):
            if code == 5:
                names = [AILMENTS[integer(v, "ailment", 1, 8)-1] for v in p[:8] if v]
            elif code == 111:
                names = [name for name, value in zip(("AttackDown", "DeffenceDown", "IntelligenceDown", "MindDown", "Stop", "Charme"), p) if value]
            else:
                names = [name for name, value in zip(AILMENTS, p[0]) if value]
                if c.n(1):
                    names.append("Zombie")
            for name in names:
                c.cure(name)
        elif code == 141:
            selections = p[0] if isinstance(p[0], list) else [p[0]]
            if c.n(1) > 0:
                c.hold("Selective dispel count must be preserved")
            names = ["AttackUp", "DeffenceUp", "IntelligenceUp", "MindUp", "AttackDown", "DeffenceDown", "IntelligenceDown", "MindDown"]
            for selection in selections:
                if selection in range(1, 9):
                    c.cure(names[selection-1])
                else:
                    c.hold(f"Selective removal family {selection} needs effect-ID binding")
        elif code == 88:
            from .stop import convert
            convert(c)
        elif code in (6, 60, 144):
            if code == 6:
                for status, chance in zip(AILMENTS, p[:8]):
                    if chance:
                        c.inflict(status, number(chance, "chance", 0, 100))
            elif code == 60:
                c.inflict("Charme", c.percent(1), c.turn(0))
            else:
                for status, chance in zip(AILMENTS, p[0]):
                    if chance:
                        c.inflict(status, number(chance, "chance", 0, 100))
                c.inflict("Zombie", 100)
        elif code in (34, 146):
            from .random_effects import convert
            convert(c)
        elif code in (7, 89, 122, 145):
            if code == 89:
                names = ("AttackDown", "DeffenceDown", "IntelligenceDown", "MindDown", "Stop", "Charme")
                for name, amount in zip(names, p):
                    if amount:
                        c.resist(name, number(amount, "resistance", 0, 100), c.turn(6))
            elif code == 122:
                c.resist("InstantDeath", 100, c.turn(0))
            else:
                values = p[0] if code == 145 else p[:8]
                for name, amount in zip(AILMENTS, values):
                    if amount:
                        c.resist(name, number(amount, "resistance", 0, 100), c.turn(9))
        elif code == 59:
            from .dispel import convert
            convert(c)
        elif code == 35:
            c.effect(1046, chance=c.percent(0))
            c.r["semantic"] = {"kind": "instant_death", "chance": c.percent(0)}
        elif code in (112, 113):
            from .death_branches import convert
            convert(c)
        elif code in (91, 1001, 1002):
            c.r["semantic"] = {"kind": "death_branch_or_doom", "parameters": p}
            c.hold("Death fallback branches and delayed-death restrictions need a scheduled action")
        elif code == 61:
            c.effect(19000, [min(100, c.n(0))], turns=c.turn(1))
            c.change("Uses native targeting weight rather than FFBE draw-attack probability.")
        elif code in (96,118,142):
            self.cover(c)
        elif code == 54:
            if len(p) not in (2,3):
                raise ValueError("Unknown Mirage parameter layout")
            hits, turns = max(1, integer(p[0], "Mirage attack count", 0)), c.turn(1)
            c.r["semantic"] = {"kind":"mirage", "hits":hits, "turns":turns,
                                  "sourceControl":p[2] if len(p)>2 else None}
            if len(p)>2 and integer(p[2], "Mirage control flag", 0) != 0:
                c.hold("Nonzero Mirage control parameter needs a source removal/stacking rule")
                return
            amount = min(30, 10+5*hits)
            c.effect(1143, [amount,1], turns=turns)
            c.replace("Mirage Veil", "Guaranteed finite physical evades become a removable timed physical-evasion buff (15% for one attack, +5% per additional attack, capped at 30%); the source turn duration is retained and the hit counter is removed.")
        elif code == 86:
            c.r["semantic"] = {"kind": "reflect", "count": c.n(1), "turns": c.turn(2), "multiplier": c.n(0)}
            c.hold("Reflect needs both action-count and turn limits")
        elif code == 119:
            if len(p) not in (5,6) or p[4] != 1:
                raise ValueError("Unknown normal-counter grant schema")
            limit = integer(p[5], "counter limit", 0) if len(p) > 5 else 0
            c.normal_counter(c.percent(0), c.n(2), 1, c.turn(3),
                             maximum=0 if limit >= 999 else limit, stat=integer(p[1], "counter stat", 1, 4))
        elif code in (92, 93):
            entries = [v for v in p[:8] if v != -1]
            pairs = [(integer(v[0], "race", 0, 12), number(v[1], "killer", 0)) for v in entries if isinstance(v, list) and len(v) == 2]
            if len(pairs) != len(entries):
                raise ValueError("Killer race/amount pair is malformed")
            c.killers(pairs, c.turn(8), "physical" if code == 92 else "magic")
        elif code in (127, 1018):
            turns = c.turn(1 if code == 127 else 5)
            for damage in (1, 2):
                c.mitigation(10, damage, turns, scale=False)
            c.replace("Aegis", "HP barrier becomes 10% physical and magical mitigation.")
        elif code in (163, 1031):
            c.stat(-50, 6, c.turn(4 if code == 163 else 3))
            c.replace("Sunder Armor", "All weapon imperils share one bounded DEF reduction.")
        elif code in (44, 45, 97, 98, 168, 1006):
            turns_pos = {97: 3, 98: 4, 168: 6}
            turns = c.turn(turns_pos[code]) if code in turns_pos else 3
            c.effect(1007, [20, 9, 2, 0, 0, 0], turns=turns, status="Haste")
            c.replace("Quickcast", "Multicast becomes a 20% Haste buff; extra spell selections are removed.")
        elif code in (170, 1020):
            c.effect(1098, [2, 85, 0, -1, -1, -1, 0, -1, 0, -1], turns=3)
            c.replace("Focused Rhythm", "Cooldown/charge refill becomes 15% MP-cost relief for three turns.")
        elif code in (32, 1015, 1025):
            c.recover(5, 4)
            c.replace("Primal Focus" if code == 32 else "Fighting Spirit", "Source gauge system becomes 5% native resonance gauge gain.")
        elif code == 63:
            c.stat(c.n(0), 4, c.turn(1))
            c.change("Gauge fill-rate bonus uses native LB parameter gain scaling.")
        elif code == 125:
            c.recover(min(20, (c.n(0)+c.n(1))/200), 4)
            c.change("FFBE crystal units become a capped percentage of native gauge.")
        elif code in (10, 25, 31, 1003, 1010, 1012):
            c.r["semantic"] = {"kind": {10:"mp_drain",25:"hp_drain",31:"entrust",1003:"gauge_change",1010:"self_hp_loss",1012:"periodic_drain"}[code], "parameters": p}
            c.hold("Resource transfer/cost needs equipping-actor ownership and action timing")
        elif code in (47, 51, 37):
            template = {47: 1050, 51: 1000, 37: 1030}[code]
            # Select type by evidence, not an assumed adjacent row ID.
            type_name = {47:"Analyze",51:"Escape",37:"Steal"}[code]
            template = c.native.types[type_name]["effectRows"][0]["ID"]
            c.effect(template, chance=100 if code == 47 else c.percent(0))
            if code in (37, 51):
                c.change("Uses native encounter/loot rules.")
        elif code == 165:
            from .tag_attacks import convert
            convert(c)
        elif code == 132:
            from .delayed_actions import convert
            convert(c)
        elif code in (71, 99, 100, 130, 157, 160, 166, 167, 1014, 1026, 1027, 46, 29, 82):
            c.links()
        elif code in (128, 129, 162):
            value = c.n(0 if code == 162 else 1)
            c.effect(1275, [min(15, abs(value)/5), -1, 0], turns=c.turn(2))
            c.replace("Keen Focus", "Accuracy support becomes a bounded critical-rate bonus.")
        elif code == 1016:
            c.damage(c.n(0)/100,"Physic" if p[1] == 1 else "Magic")
            c.replace("Fighting Spirit","Morale-scaled damage becomes the base power tier; hybrid damage becomes magic.")
        elif code == 159:
            c.damage(c.n(3)/100,"Physic" if p[2] in (1,2) else "Magic")
            c.r["actions"][-1]["breakBonus"] = 10
            c.replace("Chaincraft","Weapon-dependent break damage becomes a bounded ten-point stagger bonus; alternate-stat scaling uses the normal damage formula.")
        elif code in (20, 90):
            c.stat(c.n(0), 5 if code == 20 else 7, 1)
            c.stat(-abs(c.n(2)), 6 if code == 20 else 8, 1)
            c.replace("Focused Strike" if code == 20 else "Focused Spell", "One-cast charge becomes a one-turn buff with its DEF/SPR penalty; charge stacking is removed.")
        elif code in (120, 136, 171, 176, 1022, 1023, 172):
            positions = {120:(0,1),136:(3,4),171:(3,4),176:(0,1),1022:(3,8),1023:(3,8),172:(0,2)}
            amount, turns = positions[code]
            c.stat(c.n(amount), 7, c.turn(turns))
            c.replace("Primal Attunement" if code == 172 else "Battle Focus", "Specialized damage boost becomes a bounded MAG bonus.")
        elif code in (140, 147, 1019):
            turns = c.turn(2 if code == 1019 else 9)
            c.stat(-50, 8, turns)
            c.replace("Sundered Will" if code != 1019 else "Grave Chill", "Status/healing resistance mechanic becomes a modest SPR reduction.")
        elif code == 139:
            c.inflict("Poison", 100, c.turn(4), unremovable=p[3] == 1)
            c.replace("Lingering Wound", "Damage over time becomes bounded native Poison; element, formula and immunity behavior change.")
        elif code in (153, 154):
            c.mitigation(10, 1 if code == 153 else 2, c.turn(7), scale=False)
            c.replace("Hunter's Ward", "Race-specific mitigation becomes 10% general mitigation of the same damage type.")
        else:
            c.hold(f"{c.r.get('family') or 'Unresolved opcode'} requires a validated parameter/behavior adapter")

    def cover(self, c, passive=False):
        """Decode the protector separately from the allies they intercept for.

        Native Cover's damage filter is not established. The approved fallback
        grants modest typed mitigation directly to the protected recipients.
        Reactive single-ally and passive cover still require an event binding.
        """
        p, code = c.p, c.code
        grant = deepcopy(c.r["target"])
        self_target = target([0,3], "active")
        controls = {}
        if passive:
            if len(p) != 5:
                raise ValueError("Passive cover needs its explicit activation chance and five parameters")
            gender = integer(p[0], "cover gender restriction", 0, 1)
            controls = {"unknown2":integer(p[1], "cover control", 0)}
            lo, hi, rate = c.percent(2), c.percent(3), c.percent(4)
            aoe, mode, turns, protector = 0, 1 if code == 8 else 2, -1, self_target
        elif code == 96:
            if len(p) not in (8,9):
                raise ValueError("Unknown active cover parameter layout")
            aoe = integer(p[0], "cover recipient range", 0, 1)
            gender = integer(p[1], "cover gender restriction", 0, 2)
            lo, hi, rate = c.percent(2), c.percent(3), c.percent(4)
            controls = {"unknown6":integer(p[5], "cover control", 0), "unknown8":integer(p[7], "cover control", 0)}
            mode, turns, protector = integer(p[8], "cover damage mode", 0, 2) if len(p)>8 else 1, c.turn(6), grant
        elif code == 118:
            if len(p) != 6:
                raise ValueError("Unknown targeted cover parameter layout")
            lo, hi, rate = c.percent(0), c.percent(1), c.percent(2)
            controls = {"unknown5":integer(p[4], "cover control", 0)}
            aoe, gender, mode, turns, protector = 0, 0, integer(p[5], "cover damage mode", 0, 2), c.turn(3), self_target
        else:
            if len(p) != 8:
                raise ValueError("Unknown monster cover parameter layout")
            aoe = integer(p[0], "cover recipient range", 0, 1)
            controls = {f"unknown{i+1}":integer(p[i], "cover control", 0) for i in (1,2,5,7)}
            lo, hi, rate, gender = 0, 0, c.percent(3), 0
            mode, turns, protector = integer(p[6], "cover damage mode", 0, 2), c.turn(4), grant
        if lo > hi:
            raise ValueError("Cover mitigation minimum exceeds maximum")
        protected = grant if code == 118 and not passive else {
            "selection":"all_other_allies_of_protector" if aoe else "attacked_ally_of_protector",
            "gender":("any","female","male")[gender]}
        damage_types = [1,2] if mode == 0 else [mode]
        c.r["semantic"] = {"kind":"cover", "protector":protector, "protected":protected,
            "damageTypes":["physical" if d == 1 else "magic" for d in damage_types],
            "chance":rate, "mitigationRange":[lo,hi], "turns":turns, "sourceControls":controls,
            "nativeCandidates":[19025,19026,19027]}
        expected = {"unknown2":100} if passive else {"unknown6":100,"unknown8":1} if code == 96 else {"unknown5":1} if code == 118 else {"unknown2":0,"unknown3":0,"unknown6":1,"unknown8":0}
        if controls != expected:
            c.hold("Cover control parameters differ from the established source layout")
            return
        if not rate:
            # A decoded zero-chance intercept has no gameplay effect. The raw
            # component remains available; the common adapter marks it a no-op.
            c.r["semantic"] = {}
            return
        if gender:
            c.hold("Gender-restricted cover needs the same protected-ally eligibility filter")
        if passive:
            c.hold("Passive cover needs per-hit ally selection and protector/recipient lifetime binding")
        elif code == 118:
            if grant["shape"] != "Single" or grant["relation"] != "Friendlies" or grant.get("eitherSide"):
                c.hold("Targeted cover needs one selected ally with the source recipient filter")
        elif protector["shape"] != "Self":
            c.hold("Cover granted to another unit needs that protector's ally and exclusion binding")
        elif not aoe:
            c.hold("Reactive single-ally cover cannot become an unconditional party ward")
        if c.r["issues"]:
            return
        recipients = grant if code == 118 else target([2,5], "active")
        # A base defensive benefit represents interception even with no damage
        # reduction. Chance and mean reduction set a bounded replacement budget.
        amount = min(25, max(1, round((10+(lo+hi)/10)*rate/100)))
        for damage in damage_types:
            c.mitigation(amount, damage, turns, scale=False)
            c.r["effects"][-1]["target"] = deepcopy(recipients)
        name = "Guardian Aegis" if mode == 0 else "Guardian Ward" if mode == 1 else "Spellguard Ward"
        c.replace(name, "Cover interception becomes removable mitigation on the protected allies, retaining damage type and duration. "
            "Hits are not redirected; chance and the random mitigation range become fixed strength: (10 + mean source mitigation / 5) "
            "times source chance, capped at 25% per damage type.")

    def passive_rates(self, c):
        p, code = c.p, c.code
        if code == 23:
            if len(p) != 2:
                raise ValueError("Vigilance requires its protection chance and mode")
            chance = c.percent(0)
            integer(p[1], "Vigilance mode", 1, 1)
            if not chance:
                return
            c.r["semantic"] = {"kind":"preemptive_protection","chance":chance,"mode":p[1]}
            if chance != 100:
                c.hold("Partial preemptive protection needs a native probability binding")
                return
            c.effect(1101, [1,0], turns=-1)
        elif code == 43:
            if len(p) != 1:
                raise ValueError("Encounter rate requires one signed percentage")
            change = integer(p[0], "encounter-rate change", -100)
            if not change:
                return
            remaining = min(150,100+change)
            c.r["semantic"] = {"kind":"encounter_rate","sourceChangePercent":change,"nativePercent":remaining}
            c.effect(71001, [remaining], turns=-1)
            if change > 50:
                c.change("Increased encounter frequency is capped at the native Enemy Lure rate of 150%.")
        elif code in (37,45):
            if len(p) != 1:
                raise ValueError("Reward bonuses require one percentage")
            bonus = integer(p[0], "reward bonus", 0)
            if not bonus:
                return
            percent = 100+min(100,bonus)
            c.r["semantic"] = {"kind":"reward_multiplier","reward":"gil" if code == 37 else "experience",
                                "sourceBonusPercent":bonus,"nativePercent":percent}
            c.effect(1121 if code == 37 else 1020, [percent], turns=-1)
            if bonus > 100:
                c.change("Battle reward bonuses are capped at +100%, matching native double-gil and double-EXP effects.")
        elif code == 16:
            if len(p) not in (1,2):
                raise ValueError("Steal-success bonuses require a percentage and optional control parameter")
            bonus = integer(p[0], "steal-success bonus", 0)
            control = integer(p[1], "steal-success control") if len(p)>1 else 0
            if control:
                c.r["semantic"] = {"kind":"steal_success_bonus","sourceBonusPercent":bonus,"sourceControl":control}
                c.hold("Nonzero steal-success control parameters need their source behavior decoded")
                return
            amount = min(50,bonus//2)
            if not amount:
                return
            c.r["semantic"] = {"kind":"steal_success_bonus","sourceBonusPercent":bonus,"nativeParameter":amount}
            c.effect(1129, [amount], turns=-1)
            c.change("Steal-success bonuses use half the source magnitude, capped at the stock Pickpocket's Prowess strength.")
        elif code == 46:
            if len(p) != 2:
                raise ValueError("Gil earned from stealing requires minimum and maximum percentages")
            minimum, maximum = c.percent(0), c.percent(1)
            if minimum > maximum:
                raise ValueError("Gil-steal minimum exceeds its maximum")
            if not maximum:
                return
            c.r["semantic"] = {"kind":"gil_on_item_steal","minimumPercent":minimum,"maximumPercent":maximum,
                                "trigger":"successful_item_steal"}
            c.hold("Gil earned after item theft needs a successful-steal trigger and remaining enemy-gil binding")
        elif code == 47:
            if len(p) not in (1,2):
                raise ValueError("Item-drop bonuses require common and optional rare percentages")
            common = integer(p[0], "common drop bonus", 0)
            rare = integer(p[1], "rare drop bonus", 0) if len(p)>1 else 0
            if not common and not rare:
                return
            c.r["semantic"] = {"kind":"item_drop_bonus","commonPercent":common,"rarePercent":rare}
            if common != rare:
                c.hold("Different common and rare drop bonuses require a native drop-category filter")
                return
            amount = min(25,common)
            c.r["semantic"]["nativeBonusPercent"] = amount
            c.effect(70000, [amount], turns=-1)
            if common > 25:
                c.change("The shared item-drop bonus is capped at the native Drop Rate Up strength of +25%.")

    def passive(self, c):
        p, code = c.p, c.code
        if code in (1, 89):
            for stat, value in zip(STAT_IDS[:6], p):
                if value:
                    c.stat(number(value), stat, -1, flat=code == 89)
            if len(p) > 6 and c.n(6):
                c.effect(1275, [min(15, c.n(6)/5), -1, 0], turns=-1)
                c.change("Critical chance is capped at 15%; this source slot is not Agility.")
        elif code == 2:
            for name, amount in zip(AILMENTS, p):
                if amount:
                    c.resist(name, number(amount, "resistance", 0, 100), -1)
        elif code in (3, 42):
            for element, value in zip(ELEMENTS, p):
                if value:
                    amount = number(value)
                    c.effect(1022, [ELEMENT_IDS[element], 4 if code == 42 else 1 if amount < 0 else 3 if amount >= 100 else 2], turns=-1)
            c.change("Element percentages become native resistance categories.")
        elif code in (11, 105):
            if code == 105:
                pairs = [(integer(p[0], "race", 0, 12), c.n(1))]
            else:
                if len(p) not in (3,4,6) or any(integer(value, "killer padding", 0, 0) != 0 for value in p[3:]):
                    raise ValueError("Passive killers require three bonus parameters with only known zero padding")
                entries = killer_entries(*p[:3])
                pairs = [(entry["race"],max(entry["physical"],entry["magical"])) for entry in entries]
            c.killers(pairs, -1, "physical_and_magic")
            if code == 11 and c.r["semantic"]:
                c.r["semantic"]["sourceEntries"] = entries
                if len(p)>3:
                    c.r["semantic"]["sourceControlParameters"] = deepcopy(p[3:])
        elif code == 7:
            c.r["semantic"] = {"kind": "race_presence_stats", "race": p[0], "stats": p[1:5]}
            c.hold("Race-presence stat bonus is conditional; it is not an unconditional killer")
        elif code in (8,59):
            self.cover(c, passive=True)
        elif code in (12,41):
            if not 1 <= len(p) <= 3:
                raise ValueError("Unknown normal-counter passive schema")
            c.normal_counter(c.percent(0), (c.n(1) or 100) if len(p)>1 else 100,
                             1 if code == 12 else 2, -1,
                             maximum=integer(p[2], "counter limit", 0) if len(p)>2 else 0)
        elif code in (22, 54):
            if code == 54 and c.n(0) > 0:
                c.hold("Limited magical evasion requires its activation cap")
            c.effect(1188 if code == 22 else 1189, [min(20, c.n(0 if code == 22 else 1)/5), 1 if code == 22 else 2], turns=-1)
            c.change("Permanent evasion is capped at 20% in the native balance scale.")
        elif code == 55:
            names = ("AttackDown", "DeffenceDown", "IntelligenceDown", "MindDown", "Stop", "Charme")
            for name, amount in zip(names, p):
                if amount:
                    c.resist(name, number(amount, "resistance", 0, 100), -1)
        elif code == 32:
            c.recover(min(5, c.n(0)), 2, periodic=True, turns=-1)
            c.change("Passive MP regeneration capped at 5% per turn.")
        elif code == 31:
            c.stat(c.n(0), 4, -1)
            c.change("Uses native LB gauge gain scaling.")
        elif code == 33:
            c.recover(min(5, c.n(0)/100), 4, periodic=True, turns=-1)
            c.change("Crystal units normalized to capped native gauge recovery.")
        elif code == 25:
            c.effect(19000, [min(50, c.n(0))], turns=-1)
            c.change("Draw-attack percentage becomes native targeting weight.")
        elif code == 24:
            c.effect(19007, turns=-1)
            c.change("Reduced targeting chance becomes native Camouflage.")
        elif code in (37, 45, 47, 16, 46, 23, 43):
            self.passive_rates(c)
        elif code in (81, 84, 85, 98, 106, 95):
            c.effect(1377, [10, 0, -1, 0, -1, -1, 0, 0], turns=-1)
            c.replace("Chaincraft", "Chain/tag/break enhancement becomes a shared 10% stagger bonus.")
        elif code in (52, 53, 102):
            c.effect(1007, [10, 9, 2, 0, 0, 0], turns=-1, status="None")
            c.replace("Quickcast", "Permanent multicast becomes 10% Agility.")
        elif code in (21, 61, 63, 64, 68, 73, 77, 17, 101):
            c.stat(50, 7, -1)
            c.replace("Primal Attunement" if code in (21,61,63,64) else "Battle Focus", "Specialized damage bonus becomes a modest permanent MAG bonus.")
        elif code in (9, 48):
            c.stat(50, 8, -1)
            c.replace("Field Medic" if code == 9 else "Inspiring Voice", "Item/song boost becomes a small SPR bonus.")
        elif code in (5, 6, 13, 14, 19, 69, 70, 74, 75, 76, 99, 10003, 10004):
            c.r["semantic"] = {"kind": "equipment_condition", "parameters": p}
            # The approved Weapon Mastery family permits smaller role bonuses
            # when native equipment conditions cannot be expressed. No new slot.
            if code in (5,14):
                c.stat(25,5,-1)
            elif code in (6,74):
                for stat,amount in zip(STAT_IDS[:6],p[1:7]):
                    c.stat(number(amount)/4,stat,-1)
            elif code in (13,19,70):
                c.stat(c.n(0)/4,7 if code == 70 else 5,-1)
            elif code in (69,99):
                stat_index = integer(p[0],"equipment stat",1,6)-1
                c.stat(c.n(1)/4,STAT_IDS[stat_index],-1)
            elif code in (10003,10004):
                values = p[:6] if code == 10003 else p[1:7]
                for stat,amount in zip((1,2,5,7,6,8),values):
                    c.stat(number(amount)/4,stat,-1)
            elif code == 75:
                if len(p) != 4:
                    raise ValueError("Equipment killers require equipment, race, physical and magical bonus parameters")
                entries = killer_entries(*p[1:])
                c.killers([(entry["race"],max(entry["physical"],entry["magical"])/4) for entry in entries],-1,"physical_and_magic")
                if c.r["semantic"]:
                    c.r["semantic"].update(sourceEntries=entries,equipmentCondition=deepcopy(p[0]),replacementScale=.25)
            else:
                # Unconditional element immunity is too large a replacement for
                # a conditional percentage; use a small defensive stat instead.
                c.stat(25,8,-1)
            c.replace("Weapon Mastery","Equipment/hand/weapon conditions and slot unlocks become quarter-strength self stat bonuses; the source condition is retained in the report.")
        elif code in (66,103,104):
            from .automatic_passives import convert
            convert(c)
        elif code in (35, 49, 50, 56, 72, 80, 97, 100, 10002, 10007):
            if code in (49,50) and len(p) in (3,4) and p[2] == 0:
                if p[1] != 1:
                    raise ValueError("Normal counter must target the single attacking unit")
                c.normal_counter(c.percent(0), 100, 1 if code == 49 else 2, -1,
                                 maximum=integer(p[3], "counter limit", 0) if len(p)>3 else 0)
            else:
                c.links()
        elif code in (109, 110, 111, 112, 113):
            c.r["semantic"] = {"kind": "boost_gated", "parameters": p}
            c.hold("BOOST activation/lifetime is required; gated refill must not become a permanent passive")
        elif code in (1001, 20001):
            for stat, amount in zip(STAT_IDS[:4], p):
                if code == 20001 and isinstance(amount,list):
                    amount = amount[0]
                c.stat(number(amount)/4, stat, -1)
            c.replace("Leader's Resolve", "Category party bonus becomes a smaller self bonus on the equipping actor.")
        elif code == 51:
            c.r["semantic"] = {"kind": "guts", "threshold": c.n(0), "chance": c.n(1), "lock": p[2], "uses": p[3]}
            c.hold("Fatal-survival threshold and finite-use limit require runtime state")
        elif code == 28:
            c.recover(2,1,periodic=True,turns=-1)
            c.replace("Guard Renewal","Guard-triggered healing becomes 2% HP regeneration each turn.")
        elif code in (18,29):
            c.resist("Poison",25,-1)
            c.replace("Trailkeeper","Exploration recovery becomes modest Poison protection.")
        elif code == 26:
            template = c.native.status_template("Berserk")
            c.effect(template,turns=-1 if c.n(1) >=999 else c.turn(1))
            c.change("Berserk uses native attack strength and retains the loss of action control.")
        elif code == 44:
            c.effect(1377,[10,0,-1,0,-1,-1,0,0],turns=-1)
            c.replace("Chaincraft","Additional normal-attack hits become a modest stagger bonus.")
        else:
            c.hold(f"{c.r.get('family') or 'Unresolved opcode'} requires a validated parameter/behavior adapter")

    def field(self, c, duration):
        c.r["semantic"] = {"kind": "field", "duration": duration, "parameters": c.p, "recipients":"referencing_action"}
        turns = integer(duration,"field duration",-1)
        if turns == 0:
            c.hold("Zero-duration field needs explicit lifetime semantics")
            return
        def value(index):
            v = c.p[index]
            if isinstance(v,list):
                if len(v) != 2:
                    raise ValueError("Field magnitude range must have two endpoints")
                c.change("Field magnitude range uses its mean.")
                return sum(number(x) for x in v)/2
            return number(v)
        if c.code == 1:
            for i,stat in enumerate(STAT_IDS[:4]):
                c.stat(value(i),stat,turns)
        elif c.code == 2:
            for i,element in enumerate(ELEMENTS):
                amount = value(i)
                if amount:
                    c.effect(1022,[ELEMENT_IDS[element],1 if amount < 0 else 3 if amount >=100 else 2],turns=turns)
            c.change("Field resistance percentages use native categories.")
        elif c.code == 3:
            for i in range(2):
                c.recover(value(i),i+1,ratio=False,periodic=True,turns=turns)
        elif c.code == 4:
            c.recover(min(5,value(2)/100),4,periodic=True,turns=turns)
            c.change("Field crystal units use capped native gauge recovery.")
        elif c.code == 5:
            c.effect(1188,[min(20,value(0)/5),1],turns=turns)
        elif c.code in (7,8,9,13):
            c.stat(value(0),5 if c.code in (7,13) else 7,turns)
            c.replace("Field Attunement","Specialized field damage bonus becomes a timed ATK/MAG bonus.")
        elif c.code in (10,11,12):
            for i,element in enumerate(ELEMENTS):
                amount = value(i)
                if amount:
                    c.effect(12955,[min(20,abs(amount)/5),ELEMENT_IDS[element]],turns=turns)
            c.replace("Elemental Field","Element bonuses keep their elements with a capped magnitude and broader damage subtype.")
        c.hold("Field recipient/side and aura removal must be bound by the referencing action")


class Context:
    def __init__(self, native, record, result):
        self.native, self.record, self.r = native, record, result
        self.p, self.code = result["params"], result["code"]

    def n(self, index):
        return number(self.p[index], f"parameter {index}")

    def percent(self, index):
        return number(self.p[index], f"chance {index}", 0, 100)

    def turn(self, index):
        return integer(self.p[index], "duration", 1)

    def hold(self, reason):
        self.r["issues"].append(reason)

    def change(self, message):
        if message not in self.r["changes"]:
            self.r["changes"].append(message)

    def replace(self, name, message):
        self.r["replacement"] = name
        self.change(message)

    def effect(self, template, params=None, turns=None, chance=100, unremovable=False, status=None, state="Alive", periodic=False):
        spec = self.native.effect(template, params, turns, chance, unremovable, status)
        if params and params != spec["set"]["ParamList"][:len(params)]:
            self.change("Fractional normalized parameters are rounded to the native table's integer slots.")
        spec.update(target={**self.r["target"], "state": state}, component=self.r["index"])
        if periodic:
            spec["set"].update(applyTiming="EndTurn", proceedTiming="EndTurn")
        self.r["effects"].append(spec)
        return spec

    def stat(self, amount, stat, turns, unremovable=False, flat=False):
        if not amount:
            return
        cap = 30 if turns == -1 else 50
        value = min(cap, max(1, round(abs(amount)/(100 if flat else 5))))
        status = (STAT_DOWN if amount < 0 else STAT_UP).get(stat, "None") if turns != -1 else "None"
        self.effect(16605, [value, stat, 3 if amount < 0 else 2, 0, 0, 0], turns=turns,
                    status=status, unremovable=unremovable)
        self.change("Stat magnitudes normalized to FFR: source percentage / 5 (flat / 100), capped at 30% passive or 50% timed.")

    def mitigation(self, amount, damage, turns, unremovable=False, scale=True):
        amount = max(0, min(30, round(amount/3))) if scale else amount
        if amount:
            # Defence damage type 1 = physical, 2 = magical, as in native Protect/Shell.
            self.effect(1042, [damage, amount, 0, 0], turns=turns, unremovable=unremovable, status="None")
        if scale:
            self.change("Mitigation is divided by three and capped at 30% per damage type.")

    def recover(self, amount, resource, ratio=True, chance=100, periodic=False, turns=None):
        number(amount, "recovery", 0)
        if not amount:
            return
        if not ratio:
            amount = max(1, round(amount/(10 if resource == 1 else 2)))
            self.change("Flat HP/MP recovery normalized to native scale (HP / 10, MP / 2).")
        amount = min(100, amount) if ratio else amount
        spec = self.effect(1019, [amount, resource, 2 if ratio else 0, -1, 0],
                           chance=chance, periodic=periodic, turns=turns)
        if not periodic:
            spec["set"].update(applyTiming="AddEffect", proceedTiming="AddEffect", effectEndActionNum=1)

    def heal(self, base, multiple):
        number(base, "base healing", 0)
        number(multiple, "healing multiplier", 0)
        if base == 0 and multiple == 0:
            return
        self.r["actions"].append({"kind": "heal", "multiple": multiple, "base": base,
                                  "damageType": "Magic", "target": deepcopy(self.r["target"]), "component": self.r["index"]})
        self.change("Scaled healing uses the native FFR recovery power ladder.")

    def normal_counter(self, chance, multiplier, incoming, turns, maximum=0, stat=1):
        number(multiplier, "counter multiplier", 0)
        self.r["semantic"] = {"kind":"normal_counter", "incoming":"physical" if incoming == 1 else "magic",
                              "chance":chance, "multiplier":multiplier/100, "maximumPerTurn":maximum,
                              "stat":stat, "turns":turns, "owner":"equipping_actor"}
        if maximum:
            self.hold("Counter activations per turn require a resettable use limit")
        if stat != 1 or multiplier != 100:
            self.hold("Counter scaling needs a separately bound child attack")
        if self.r["issues"]:
            return
        if not chance:
            self.r["semantic"] = {}
            return
        template, child = (1037,400120) if incoming == 1 else (1038,400130)
        if child not in self.native.skill_ids:
            raise ValueError("Native normal-counter child skill is absent")
        spec = self.effect(template, turns=turns)
        # Add probability grants the passive/buff. Activation probability is
        # the per-trigger roll; using addProbability would grant a 100% counter
        # permanently to only some users instead of rolling on each attack.
        spec["set"]["activationProbability"] = int(round(chance))
        spec["nativeSkillReferences"] = [child]
        self.change("Uses the native normal-attack counter with the source trigger chance and lifetime.")

    def damage(self, multiple, damage, calc=None):
        number(multiple, "damage multiplier", 0)
        self.r["actions"].append({"kind": "damage", "multiple": multiple, "damageType": damage,
                                  "calc": calc or damage, "target": deepcopy(self.r["target"]), "component": self.r["index"]})
        self.change("Damage normalized once onto native power tiers; LB damage shares Cloud's total budget.")

    def inflict(self, status, chance, turns=None, unremovable=False):
        if status in ("Disease", "Zombie"):
            for stat in ((5, 7) if status == "Disease" else (8,)):
                spec_start = len(self.r["effects"])
                self.stat(-50, stat, turns or 3, unremovable)
                for spec in self.r["effects"][spec_start:]:
                    spec["set"]["addProbability"] = chance
            self.replace("Enfeebled" if status == "Disease" else "Grave Chill", f"{status} becomes a modest stat reduction with the original application chance.")
        else:
            template = self.native.status_template(status)
            self.effect(template, turns=turns, chance=chance, unremovable=unremovable)
            if turns is None:
                self.change("Ailment duration uses the native status template where FFBE provides no per-effect duration.")

    def cure(self, status):
        if status == "Disease":
            for name in ("AttackDown", "IntelligenceDown"):
                self.cure(name)
            self.replace("Cure Enfeebled", "Cures the stat reductions used as the Disease replacement.")
            return
        if status == "Zombie":
            self.cure("MindDown")
            self.replace("Cure Grave Chill", "Cures the SPR reduction used as the Zombie replacement.")
            return
        status_id = self.native.inventory["enums"]["eUnitStatusCondition"][status]
        self.effect(1035, [0, 0, 0, status_id, 0, 0, 0, 0, 0, 1])

    def resist(self, status, amount, turns):
        if status == "Disease":
            for name in ("AttackDown", "IntelligenceDown"):
                self.resist(name, amount, turns)
            self.replace("Enfeebled Ward", "Disease resistance becomes resistance to its ATK/MAG reduction substitute.")
            return
        status_id = self.native.inventory["enums"]["eUnitStatusCondition"][status]
        self.effect(1096, [status_id, amount], turns=turns)

    def killers(self, pairs, turns, subtype):
        races = {}
        for race, amount in pairs:
            for selected in (range(1, 13) if race == 0 else [race]):
                if selected not in RACE_THEMES:
                    raise ValueError(f"Unknown killer race {selected}")
                if amount > 0:
                    races[selected] = max(races.get(selected, 0), amount)
        self.r["semantic"] = {"kind": "killer_replacement", "races": races, "subtype": subtype, "turns": turns}
        if not races:
            self.r["semantic"] = {}
            return
        budget = min(20, int(max(races.values())/10))
        if not budget:
            self.r["semantic"] = {}
            return
        if len(races) == 12:
            for i,stat in enumerate((5, 6, 7, 8)):
                amount = budget//4+(i < budget%4)
                if amount:
                    self.effect(16605, [amount, stat, 2, 0, 0, 0], turns=turns, status="None")
            self.replace("Myriad Mastery", "All-race killers share one capped ATK/MAG/DEF/SPR bonus.")
            return
        names = []
        for i,race in enumerate(sorted(races)):
            amount = budget//len(races)+(i < budget%len(races))
            if not amount:
                continue
            name, kind, parameter = RACE_THEMES[race]
            names.append(name)
            if kind == "stat":
                self.effect(16605, [amount, parameter, 2, 0, 0, 0], turns=turns, status="None")
            elif kind == "evasion":
                self.effect(1188, [min(10, amount), 1], turns=turns)
            elif kind == "regen":
                self.recover(min(3, amount/4), parameter, periodic=True, turns=turns)
            elif kind == "mitigation":
                self.mitigation(min(10, amount), parameter, turns, scale=False)
            elif kind == "critical":
                self.effect(1275, [min(10, amount), -1, 0], turns=turns)
            else:
                self.effect(1377, [amount, 0, -1, 0, -1, -1, 0, 0], turns=turns)
        self.replace(" / ".join(names), "Race themes split one capped 20% budget; physical and magical subtype remains in provenance.")

    def links(self):
        p, code = self.p, self.code
        namespace = self.record.namespace
        relations = []
        def add(value, relation="child", kind="skill", **condition):
            values = value if isinstance(value, list) else [value]
            for sid in values:
                sid = str(integer(sid, "referenced ID", 1))
                relations.append({"id": sid, "kind": kind, "relation": relation, "condition": condition})
        if namespace == "active":
            if code in (71, 130, 157, 1014, 46):
                add(p[1] if code == 46 else p[0], "cooldown" if code == 130 else "limited" if code in (157,1014) else "child")
                if code in (130,157,1014):
                    # A charge reference is availability metadata, not an
                    # instruction to recursively execute the referenced ID.
                    from .availability import decode
                    if code == 1014:
                        relations[-1]["relation"] = "charge_pool"
                    self.r["dependencies"] = relations
                    relations[-1]["condition"] = decode(code, p, self.record.id)
                elif code == 46:
                    relations[-1]["condition"] = {"levelMultiple":p[0]}
            elif code == 99:
                add(p[1], "prerequisite"); add(p[3], "enhanced"); add(p[5], "base")
            elif code in (100, 1027):
                add(p[1], "unlock")
            elif code == 1026:
                for sid in p[:3]:
                    if sid:
                        add(sid, "focus_variant")
            elif code in (160, 166, 167):
                add(p[1] if code == 166 else p[0], "field", "field")
            elif code in (29, 82):
                for pair in p:
                    if isinstance(pair, list) and len(pair) == 2:
                        if pair[0] and pair[1]:
                            add(pair[0], "random", chance=number(pair[1], "chance", 0, 100))
        else:
            if code in (49, 50):
                add(p[2], "counter", chance=p[0], maximum=p[3] if len(p)>3 else None)
            elif code == 97:
                add(p[2], "field", "field")
            elif code == 10002:
                add(p[2], "party_conditional", unitIds=p[0])
            else:
                add(p[0], "unlock" if code in (72,100) else "lb_variant" if code == 80 else "automatic", "lb" if code == 80 else "skill")
        self.r["dependencies"] = relations
        self.r["semantic"] = {"kind": "linked_action", "parameters": p}
        if namespace == "active" and code == 71:
            if len(p) != 2 or p[1] != 1 or len(relations) != 1:
                raise ValueError("Unknown immediate proxy schema")
            self.r["semantic"]["mode"] = "inline"
        else:
            self.hold("Linked action requires condition, cost, trigger and actor-lifetime binding before playable export")
