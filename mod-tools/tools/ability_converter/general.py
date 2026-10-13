"""Native skill costs and equipping-actor bindings outside the effect table."""
from copy import deepcopy

TABLE = "Skill/Other/DT_SkillGeneralData"


class GeneralBindings:
    def __init__(self, native):
        self.native = native
        self.additions = {}
        self.seen = {}

    def add(self, skill_id, specification):
        for field, entries in specification.items():
            if field == "equipperActionVisionSkills":
                values = [skill_id] if entries else []
            elif field in ("additionalCostData", "costCheckData"):
                values = [{"SkillId":skill_id, **entry} for entry in entries]
            else:
                raise ValueError(f"Unsupported general skill binding {field}")
            target = self.additions.setdefault(field, [])
            seen = self.seen.setdefault(field, set())
            for value in values:
                identity = repr(value)
                if identity not in seen:
                    target.append(value); seen.add(identity)

    def patch(self):
        settings = {field:deepcopy(self.native.general[field])+deepcopy(values)
                    for field,values in self.additions.items() if values}
        if not settings:
            return None
        return {"add":[], "set":[{"row":self.native.general_name, "set":settings}]}


def merge_patch(tbl, native, additions):
    """Append multiple converted skills to one shared native-table update.

    A unit build may already contain other general settings. Preserve them and
    the stock entries; never replace an earlier converted unit's binding list.
    """
    if not additions:
        return
    table = tbl(TABLE)
    row = next((r for r in table["set"] if r["row"] == native.general_name), None)
    if row is None:
        row = {"row":native.general_name,"set":{}}
        table["set"].append(row)
    for field, values in additions.items():
        current = row["set"].setdefault(field, deepcopy(native.general[field]))
        for value in values:
            if value not in current:
                current.append(deepcopy(value))
