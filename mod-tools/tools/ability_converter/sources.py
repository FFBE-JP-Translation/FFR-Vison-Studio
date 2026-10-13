"""Lossless readers for the sources used by the Build 16 effect inventory."""
from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT/"docs/build16" if (ROOT/"docs/build16").is_dir() else ROOT/"data/ability_converter"
DEFAULT_DATAMINE = Path("T:/Projects/ffbe/ffbe-wiki-tools/datamine")
ELEMENTS = ("Fire", "Ice", "Thunder", "Water", "Wind", "Earth", "Light", "Dark")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def scalar(value):
    value = value.strip()
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    if re.fullmatch(r"-?\d+\.\d+", value):
        return float(value)
    return value


def parameters(value):
    # Mirrors GameHelper::readParameters: ordered nested delimiters. Commas
    # always form a list; ';', '&', ':' only split when present. Preserve text.
    if not isinstance(value, str):
        return value
    def split(item, delimiter):
        if isinstance(item, list):
            return [split(v, delimiter) for v in item]
        return item.split(delimiter) if delimiter in item else item
    result = value.split(",")
    for delimiter in (";", "&", ":"):
        result = split(result, delimiter)
    def convert(item):
        return [convert(v) for v in item] if isinstance(item, list) else scalar(item)
    return convert(result)


@dataclass
class SourceRecord:
    source: str
    kind: str
    id: str
    data: dict
    path: str = ""
    level: str | None = None
    issues: list = field(default_factory=list)

    @property
    def namespace(self):
        return "field" if self.kind == "field" else "passive" if self.kind == "passive" else "active"

    @property
    def key(self):
        return f"{self.source}/{self.kind}/{self.id}" + (f"/level/{self.level}" if self.level is not None else "")

    def provenance(self):
        return {"key": self.key, "source": self.source, "kind": self.kind, "id": self.id,
                "level": self.level, "path": self.path}


def structured_records(data, source, table, path, all_levels=True):
    for sid, row in data.items():
        if not isinstance(row, dict):
            yield SourceRecord(source, table, str(sid), {"raw": row}, str(path),
                               issues=["Source record is not an object"])
            continue
        if table == "limitbursts":
            levels = row.get("levels") or {}
            if isinstance(levels, list):
                levels = {str(n): {"cost": v[0], "effects_raw": v[1]}
                          for n, v in enumerate(levels, 1)}
            if not levels:
                yield SourceRecord(source, "lb", str(sid), row, str(path), issues=["LB has no levels"])
            chosen = sorted(levels, key=lambda v: int(v))
            if not all_levels:
                chosen = chosen[-1:]
            for level in chosen:
                merged = {**{k: v for k, v in row.items() if k != "levels"}, **levels[level]}
                merged["lb_cost"] = merged.get("cost", 0)
                yield SourceRecord(source, "lb", str(sid), merged, str(path), str(level))
        else:
            kind = ("field" if table == "area_effects" else "enemy" if table == "monster_skills" else
                    "passive" if row.get("active") is False or table == "skills_passive" else
                    "magic" if row.get("type") == "MAGIC" or table == "skills_magic" else "ability")
            yield SourceRecord(source, kind, str(sid), row, str(path))


def master_record(row, table, known=None, path=""):
    idkey, kind = {"F_ABILITY_MST": ("ability_id", "ability"), "F_MAGIC_MST": ("magic_id", "magic"),
                   "F_LIMITBURST_MST": ("lb_id", "lb"), "F_FIELD_EFFECT_MST": ("area_effect_id", "field")}[table]
    sid = str(row[idkey])
    types = str(row.get("effect_type") or "").split("@")
    groups = str(row.get("effect_param") or "").split("@")
    issues = []
    if len(types) != len(groups):
        issues.append("Effect/parameter group count differs")
    if kind == "ability" and str(row.get("is_active")) == "1":
        kind = "passive"
    corrected = False
    if known and table == "F_ABILITY_MST" and "active" in known:
        vector = [str(e[2]) for e in known.get("effects_raw", []) if isinstance(e, list) and len(e) >= 4]
        if types == vector:
            new_kind = "ability" if known["active"] else "passive"
            corrected = new_kind != kind
            kind = new_kind
    ranges = str(row.get("target_range", "")).split("@")
    targets = str(row.get("target", "")).split("@")
    effects = []
    for i, code in enumerate(types):
        params = parameters(groups[i]) if i < len(groups) else None
        code = scalar(code)
        if kind == "field":
            effects.append([scalar(str(row.get("turns", ""))), code, params])
        else:
            effects.append([scalar(ranges[min(i, len(ranges)-1)]),
                            scalar(targets[min(i, len(targets)-1)]), code, params])
    timing, weights = [], []
    for group in str(row.get("attack_frames") or "").split("@"):
        pairs = [token.split(":") for token in group.split("-") if token]
        if pairs and all(len(p) >= 2 and re.fullmatch(r"\d+", p[0]) for p in pairs):
            timing.append([int(p[0]) for p in pairs])
            weights.append([scalar(p[1]) for p in pairs])
        else:
            timing.append([])
            weights.append([])
    flags = str(row.get("element_inflict") or "").split(",")
    data = {"name": row.get("name", row.get("explain_short")), "effects_raw": effects,
            "element_inflict": [e for e, v in zip(ELEMENTS, flags) if scalar(v) not in (0, "", -1)],
            "attack_frames": timing, "attack_damage": weights,
            "mp_cost": scalar(str(row.get("mp_cost", 0))),
            "lb_cost": scalar(str(row.get("lb_cost", row.get("cost", 0)))) if kind == "lb" else 0,
            "icon": row.get("icon_id"), "_master": row, "_activeFlagCorrected": corrected}
    return SourceRecord("JP_CLIENT", kind, sid, data, str(path)) if not issues else SourceRecord(
        "JP_CLIENT", kind, sid, data, str(path), issues=issues)


def iter_sources(datamine=DEFAULT_DATAMINE, client=ROOT/"build/devui/live_jp", archive=None,
                 sources=("gl", "jp", "client"), all_levels=True):
    datamine, client = Path(datamine), Path(client)
    jp_known = None
    for region in ("gl", "jp"):
        if region not in sources:
            continue
        for table in ("skills", "monster_skills", "limitbursts", "area_effects"):
            path = datamine/"data"/region/(table+".json")
            data = read(path)
            if region == "jp" and table == "skills":
                jp_known = data
            yield from structured_records(data, region.upper()+"_2024", table, path, all_levels)
    if "client" in sources:
        if jp_known is None and (datamine/"data/jp/skills.json").exists():
            jp_known = read(datamine/"data/jp/skills.json")
        for table in ("F_ABILITY_MST", "F_MAGIC_MST", "F_LIMITBURST_MST", "F_FIELD_EFFECT_MST"):
            path = client/(table+".json")
            for row in read(path)["rows"]:
                yield master_record(row, table, (jp_known or {}).get(str(row.get("ability_id"))), path)
    if archive:
        with zipfile.ZipFile(archive) as bundle:
            for region in ("GL", "JP"):
                for table in ("skills_ability", "skills_magic", "skills_passive", "limitbursts"):
                    member = f"ffbeEquip-master/tools/{region}/sources/{table}.json"
                    yield from structured_records(json.loads(bundle.read(member)), region+"_2022", table,
                                                  f"{archive}!{member}", all_levels)
