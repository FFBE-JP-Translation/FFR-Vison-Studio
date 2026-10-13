"""Native row templates, bounded FFR power ladders, and table validation."""
from copy import deepcopy
from functools import lru_cache
import math

from .sources import ARTIFACTS, ROOT, read

CONDITION = {"Condition": "None", "param1": -1, "param2": -1, "param3": -1}
ELEMENT_IDS = dict(zip(("Fire", "Ice", "Wind", "Earth", "Thunder", "Water", "Light", "Dark"), range(1, 9)))
STATUS_IDS = {"Poison": 1, "Blind": 2, "Sleep": 3, "Silence": 4, "Paralyzation": 5,
              "Confusion": 6, "Stoned": 7, "Charme": 8, "Stop": 9}


class NativeCatalog:
    def __init__(self, directory=ARTIFACTS, rows=None):
        if rows is None:
            rows = ROOT/"extracted/rows"
            required = ("Skill/DT_SkillData.json", "Skill/DT_PassiveSkillData.json", "Skill/Other/DT_SkillGeneralData.json", "Skill/Other/DT_SkillTargetData.json")
            if not all((rows/name).is_file() for name in required) and all((directory/"rows"/name).is_file() for name in required):
                rows = directory/"rows"
        self.directory = directory
        self.reference_paths = {name:rows/name for name in
            ("Skill/DT_SkillData.json", "Skill/DT_PassiveSkillData.json", "Skill/Other/DT_SkillGeneralData.json", "Skill/Other/DT_SkillTargetData.json")}
        self.inventory = read(directory/"ffr-effects.json")
        self.types = {t["type"]: t for t in self.inventory["effectTypes"]}
        self.effects = {r["ID"]: {k: deepcopy(v) for k, v in r.items() if k not in ("row", "usedBy")}
                        for t in self.types.values() for r in t["effectRows"]}
        self.effect_names = {r["ID"]: r["row"] for t in self.types.values() for r in t["effectRows"]}
        self.skills = read(rows/"Skill/DT_SkillData.json")["rows"]
        self.passives = read(rows/"Skill/DT_PassiveSkillData.json")["rows"]
        self.target_policies = {r["ID"]:r for r in read(rows/"Skill/Other/DT_SkillTargetData.json")["rows"].values()}
        self.general_path = rows/"Skill/Other/DT_SkillGeneralData.json"
        general = read(self.general_path)["rows"]
        if len(general) != 1:
            raise ValueError("Expected one native skill general-settings row")
        self.general_name, self.general = next(iter(general.items()))
        self.skill_ids = {r["ID"]: name for name, r in self.skills.items()}
        self.passive_ids = {r["ID"]: name for name, r in self.passives.items()}
        self.cloud = next(r for r in self.skills.values() if r["ID"] == 440110)
        self.lb_cost_ladder = sorted({r["Cost"] for r in self.skills.values() if r["skillAttrType"] == "LimitBurst" and r["Cost"] > 0})
        self.ladders = {}
        for damage in ("Physic", "Magic"):
            self.ladders[damage] = sorted(set(r["magnification"] for r in self.skills.values()
                if r["DamageType"] == damage and r["parameterVariationType"] == "Decrease"
                and r["skillAttrType"] in ("Ability", "Magic") and 0 < r["magnification"] <= 200))

    def power(self, multiple, damage, lb=False):
        if multiple <= 0:
            return 0
        if lb:
            return self.cloud["magnification"]
        ladder = self.ladders[damage]
        # Monotone, independent of import order or a --limit subset. FFBE's
        # enormous modern modifiers compress onto the native playable ladder.
        position = min(1., max(0., math.log1p(multiple)/math.log1p(1000)))
        return ladder[min(len(ladder)-1, int(position*(len(ladder)-1)))]

    @lru_cache(maxsize=32)
    def filtered_selection_evidence(self, shape, relation, state, *, ignore_self=False, either_side=False):
        """Stock commands filter their selected list, then use SkillTarget."""
        for row in sorted(self.skills.values(), key=lambda r:r["ID"]):
            if (bool(row.get("isTargetIgnoreSelf")) == ignore_self and row["TargetType"] == shape
                    and row["defaultTargetRelation"] == relation and row["defaultTargetState"] == state
                    and (not either_side or not row["isSameRelationTargetingDisabled"] and not row["isHostilityRelationTargetingDisabled"])
                    and any(b["effectId"] >= 0 and b["TargetType"] == "SkillTarget" for b in row["effectBundleList"])):
                return {"skillId":row["ID"], "isTargetIgnoreSelf":ignore_self, "eitherSide":either_side,
                        "bundleTargetType":"SkillTarget"}
        raise ValueError(f"No stock selected-recipient binding for {shape}/{relation}/{state} (ignoreSelf={ignore_self}, eitherSide={either_side})")

    def effect(self, template, params=None, turns=None, chance=100, unremovable=False, status=None):
        row = deepcopy(self.effects[template])
        row.pop("ID")
        row.update(addProbability=int(round(chance)), activationProbability=100,
                   activationCondition=deepcopy(CONDITION), isUnremovable=unremovable)
        if params is not None:
            if len(params) > 15:
                raise ValueError("Native effects have fifteen parameter slots")
            # ParamList is an int32 array in the actual cooked table. Explicit
            # quantization prevents the patcher's implicit truncation changing
            # the reviewed effect (caught by the binary round-trip fixture).
            row["ParamList"] = [int(round(v)) for v in params] + [-1] * (15-len(params))
        if turns is not None:
            if turns == -1:
                row.update(effectEndActionNum=-1, proceedTiming="None")
            elif turns > 0:
                row.update(effectEndActionNum=turns, proceedTiming="BeginTurn")
            else:
                raise ValueError("Timed effect must have a positive lifetime")
        if status is not None:
            row["statusCondition"] = status
        return {"template": template, "set": row}

    def status_template(self, status):
        candidates = [r for r in self.effects.values() if r["statusCondition"] == status]
        if not candidates:
            raise ValueError(f"No native {status} effect template in the generated artifact")
        return min(candidates, key=lambda r: (-r["addProbability"], r["ID"]))["ID"]

    def validate_effect(self, spec):
        row = spec["set"]
        if spec["template"] not in self.effects:
            raise ValueError("Missing effect template")
        if row["EffectType"] not in self.types or not self.types[row["EffectType"]]["effectRows"]:
            raise ValueError("Effect has no native row evidence")
        if len(row["ParamList"]) != 15 or any(type(v) is not int or not -2147483648 <= v < 2147483647 for v in row["ParamList"]):
            raise ValueError("Invalid native effect parameters")
        if not 0 <= row["addProbability"] <= 100 or not 0 <= row["activationProbability"] <= 100:
            raise ValueError("Invalid native effect probability")
        if row["effectEndActionNum"] != -1 and row["effectEndActionNum"] <= 0:
            raise ValueError("Invalid effect lifetime")

    def validate_skill(self, row, *, hit_offset=0, budget_share=1.):
        checks = {"DamageType": "eSkillDamageType", "damageCalcType": "eSkillDamageCalcType",
                  "parameterType": "eUnitParameterType", "skillEffectType": "eSkillEffectType"}
        for key, enum in checks.items():
            if row[key] not in self.inventory["enums"][enum]:
                raise ValueError(f"Invalid {key}: {row[key]}")
        for key in ("TargetType", "defaultTargetRelation", "parameterVariationType"):
            if row[key] not in self.inventory["skillAxes"][key]:
                raise ValueError(f"Invalid {key}: {row[key]}")
        hits, weights = row["hitCount"], row["hitDamageRatioList"]
        if type(hits) is not int or not 1 <= hits < 2147483648:
            raise ValueError("Native hit count must be a positive int32")
        # The native Fixed calculation policy has doCalcHitNum=false. Its
        # damage kernel uses weight 1 for every reaction, regardless of the
        # array below. One row cannot encode separate fixed per-hit budgets.
        if row["damageCalcType"] == "Fixed" and row["parameterVariationType"] == "Decrease" and hits > 1:
            raise ValueError("Fixed damage bypasses native hit weights; multiple hits require separate damage budgets")
        if row["skillEffectType"] == "DamageAndRecovery" and row["parameterVariationType"] == "Increase" and hits > 1:
            raise ValueError("Recovery bypasses native hit weights; multiple hits require separate recovery budgets")
        if type(hit_offset) is not int or not 0 <= hit_offset < 2147483648:
            raise ValueError("Native hit offset must be a nonnegative int32")
        if type(budget_share) not in (int,float) or not math.isfinite(budget_share) or not 0 <= budget_share <= 1:
            raise ValueError("Native hit budget share must be between zero and one")
        if not isinstance(weights,list) or not hits+hit_offset <= len(weights) < 2147483648:
            raise ValueError("Native hit array must contain a weight for every hit")
        if any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in weights):
            raise ValueError("Hit weights must be finite nonnegative numbers")
        if any(weights[:hit_offset]) or any(weights[hit_offset+hits:]):
            raise ValueError("Unused native hit weight slots must be zero")
        if abs(sum(weights)-budget_share) > 1e-6:
            raise ValueError("Hit weights do not sum to one")
        # Native bundle preparation iterates TArray.Num (skill+0x188), not
        # a fixed eight-entry buffer. Appended hits each need their own bundle.
        if not isinstance(row["effectBundleList"],list) or len(row["effectBundleList"]) >= 2147483648:
            raise ValueError("Invalid native effect bundle array")
