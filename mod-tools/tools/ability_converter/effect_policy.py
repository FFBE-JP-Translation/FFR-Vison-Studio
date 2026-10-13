"""Studio's small, shared effect policy. The research converter stays separate.

Entries are keyed by namespace/opcode, never ability name. A table row is not
invocation evidence. Unlisted native operations stay held, not declared absent.
"""
from copy import deepcopy
from .adapters import ComponentAdapter, Context

VERSION = "implemented-effects/1"
EVIDENCE = {
    "damage": "build/abilities/native-combat-validation.json; build/abilities/native-converted-fire-validation.json",
    "heal": "build/abilities/native-converted-cure-validation.json",
    "instant_recovery": "build/abilities/native-hit-evidence/application-pipeline.md: Recovery phases (Elixir 100060 / effect 21010)",
}
LABELS = {"converted": "direct", "adapted": "adaptation", "replaced": "replacement", "blocked": "unsupported", "noop": "no effect"}


def invocation_issues(component):
    issues = []
    if component.get("dependencies") or component.get("semantic", {}).get("mode"):
        issues.append("Linked, triggered and multicast actions are deferred in Studio; no new engine mechanics are enabled.")
    for action in component["actions"]:
        if action["kind"] not in ("damage", "heal") or action.get("damageType") not in ("Physic", "Magic") or action.get("calc") not in (None, "Physic", "Magic"):
            issues.append("This damage/recovery formula has no retained invocation evidence in the Studio policy.")
    for effect in component["effects"]:
        row = effect["set"]
        # This contract is deliberately narrower than the ParameterVariation enum.
        immediate = (row["EffectType"] == "ParameterVariation" and row["ParamList"][1] in (1, 2)
                     and row["ParamList"][2] in (0, 2) and row["ParamList"][3] == -1
                     and row["ParamList"][0] > 0 and row["applyTiming"] == "AddEffect"
                     and row["proceedTiming"] == "AddEffect" and row["effectEndActionNum"] == 1)
        if not immediate:
            issues.append(f"No retained invocation evidence for this {row['EffectType']} variant in Studio; table compatibility alone is insufficient.")
    return list(dict.fromkeys(issues))


class StudioAdapter(ComponentAdapter):
    def __init__(self, native, registry, choices):
        super().__init__(native, registry)
        if not isinstance(choices, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in choices.items()):
            raise ValueError("Effect choices must map opcode keys to replacement IDs")
        self.choices = choices

    def convert(self, record, raw, index):
        result = super().convert(record, raw, index)
        key = result.get("key", "malformed")
        original_status = result["status"]
        reasons = invocation_issues(result)
        options = []
        if original_status == "replaced" and not reasons and not result["issues"]:
            options.append({"id":"proposed", "label":result.get("replacement", "Suggested conversion"),
                            "changes":" ".join(result["changes"])})
        target = result.get("target", {})
        # Alternatives are explicit whole-component substitutions. Parameters and
        # raw source remain intact; malformed target data cannot be guessed.
        if record.namespace == "active" and target.get("relation") == "Friendlies":
            options += [{"id":"mp_restore", "label":"Restore 5% MP now", "changes":"One immediate 5% maximum-MP restore. Original effect, duration and repeated recovery are removed."},
                        {"id":"hp_restore", "label":"Restore 5% HP now", "changes":"One immediate 5% maximum-HP restore. Original effect and duration are removed."}]
        elif record.namespace == "active" and target.get("relation") == "Enemies":
            options += [{"id":"physical_damage", "label":"Physical damage", "changes":"Replace this component with a bounded 1x physical attack; retain source targets, element and available hit timing."},
                        {"id":"magic_damage", "label":"Magic damage", "changes":"Replace this component with a bounded 1x magic attack; retain source targets, element and available hit timing."}]
        selection = self.choices.get(key)
        if selection:
            selected = next((o for o in options if o["id"] == selection), None)
            if selected is None:
                result["issues"].append(f"Replacement {selection!r} is unavailable for {key}")
            elif selection != "proposed":
                result.update(effects=[], actions=[], dependencies=[], changes=[], issues=[], semantic={}, status="replaced")
                c = Context(self.native, record, result)
                if selection in ("mp_restore", "hp_restore"):
                    c.recover(5, 2 if selection == "mp_restore" else 1)
                else:
                    c.damage(1, "Physic" if selection == "physical_damage" else "Magic")
                c.replace(selected["label"], selected["changes"])
                reasons = invocation_issues(result)
        elif original_status == "replaced":
            result["issues"].append("Replacement requires your choice before import.")
        if key in ("active:30", "active:57", "active:131", "passive:32") and not selection:
            reasons.insert(0, "Imported MP regeneration was reported not working. Choose an immediate MP restore where offered.")
        if record.namespace == "passive" and any(e["set"]["applyTiming"] == "AddEffect" for e in result["effects"]):
            reasons.append("One-shot recovery cannot be attached as a permanent passive; an active-command replacement is not implemented.")
        result["issues"].extend(reasons)
        result["issues"] = list(dict.fromkeys(result["issues"]))
        if result["issues"]:
            result["status"] = "blocked"
        evidence = [EVIDENCE[a["kind"]] for a in result["actions"] if a["kind"] in EVIDENCE]
        if result["effects"] and not reasons:
            evidence.append(EVIDENCE["instant_recovery"])
        result["decision"] = {"key":key, "label":self.registry.get(key, {}).get("label", key),
            "class":LABELS[result["status"]], "candidateClass":LABELS[original_status],
            "selection":selection, "options":options,
            "suggestion":self.registry.get(key, {}).get("proposal"),
            "issues":list(result["issues"]), "evidence":[] if reasons else list(dict.fromkeys(evidence)),
            "gameplayValidation":"not_run"}
        return result


def decisions(profile):
    return [deepcopy(c["decision"]) for c in profile["conversion"]["components"] if "decision" in c]
