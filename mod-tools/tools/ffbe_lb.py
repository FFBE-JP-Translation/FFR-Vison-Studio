"""Resolve a form's LB presentation from FFBE's decoded master tables.

Attack-frame components follow effect_type, not animation frames: buff/debuff
components also contain a single 'hit'. Only supported damage components become
FFR damage reactions. Unsupported mechanics are reported for explicit review.
"""
from functools import lru_cache
from copy import deepcopy
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ELEMENTS = ("Fire", "Ice", "Thunder", "Water", "Wind", "Earth", "Light", "Dark")
ELEMENT_COLORS = {"Fire": "#EE5555", "Ice": "#00FFFF", "Thunder": "#FFFF00",
                  "Water": "#5588FF", "Wind": "#55CC88", "Earth": "#B88A55",
                  "Light": "#FFF2CC", "Dark": "#9955CC"}
NEUTRAL_COLOR = "#808080"
CLOUD_ID = 440110


def element_color(elements):
    """Equal RGB blend of distinct attack elements; absent elements are grey."""
    colors = [ELEMENT_COLORS[e] for e in dict.fromkeys(elements) if e != "None"]
    if not colors:
        return NEUTRAL_COLOR
    return "#" + "".join(f"{int(sum(int(c[i:i+2], 16) for c in colors) / len(colors) + .5):02X}"
                          for i in (1, 3, 5))


def move_offsets(value):
    """UnitMst stores normal and LB Vec2s, in that order (not two attack phases)."""
    if not value:
        return None
    pairs = [[float(n) for n in p.split(":")] for p in str(value).split(",")]
    if len(pairs) != 2 or any(len(p) != 2 for p in pairs):
        raise ValueError(f"Unrecognized FFBE MoveOffset: {value}")
    import math
    if any(not math.isfinite(n) for p in pairs for n in p):
        raise ValueError("FFBE movement offsets must be finite")
    return {"normal": pairs[0], "lb": pairs[1]}


@lru_cache(maxsize=1)
def cloud_reference():
    path = ROOT / "extracted/rows/Skill/DT_SkillData.json"
    return next(r for r in json.loads(path.read_text(encoding="utf-8-sig"))["rows"].values()
                if r["ID"] == CLOUD_ID)


def profile(source, cloud=None):
    """Shared build/Studio mechanics. No text matching or selected donor inference."""
    if not source:
        return {"supported": False, "issues": ["This form's LB source data is unavailable."]}
    import ffbe_lb_support
    if source.get("components") and all(c["type"] in ffbe_lb_support.TYPES for c in source["components"]):
        out = ffbe_lb_support.profile(source)
        out["fieldColor"] = element_color(source.get("elements", []))
        return out
    issues = list(source.get("issues", []))
    components = source.get("components", [])
    index = source.get("damageComponent")
    damage = components[index] if index is not None and index < len(components) else None
    elements = source.get("elements", [])
    out = {"lbId": source["lbId"], "name": source.get("name"), "elements": elements,
           "fieldColor": element_color(elements), "hits": len(source.get("hitFrames", [])),
           "movement": source.get("movement", {}),
           "availableLbIds": source.get("availableLbIds", []), "issues": issues}
    if not damage or not source.get("hitFrames"):
        issues.append("Automatic mechanics currently require one physical or magical damage component with at most 30 hits.")
    elif damage["target"] != 1 or damage["range"] not in (1, 2):
        issues.append("Automatic damage targeting currently supports one enemy or all enemies.")
    if len(elements) > 1:
        issues.append("The field blends all elements, but this FFR skill row accepts one damage element. Select custom mechanics to choose it.")
    if source.get("moveType") not in (0, 1, 4):
        issues.append(f"Movement type {source.get('moveType')} needs a movement adapter.")
    out["supported"] = not issues
    if damage:
        out["target"] = "One enemy" if damage["range"] == 1 else "All enemies" if damage["range"] == 2 else "Unresolved"
        out["damageType"] = "Physic" if damage["type"] == 1 else "Magic"
        out["sourceMultiplier"] = damage.get("multiplier")
    if not out["supported"]:
        return out
    cloud = cloud if cloud is not None else cloud_reference()
    # Retain Cloud's level scaling and critical bonus as well as its base total.
    # Matching displayed damage still depends on ATK/MAG, defence and resistance.
    names = ("skillAttrType", "skillEffectType", "parameterType", "parameterVariationType",
             "accuracy", "criticalHitRate", "Cost", "breakDamageValue", "effectBundleList")
    settings = {k: deepcopy(cloud[k]) for k in names}
    settings.update({"magnification": cloud["magnification"], "hitCount": out["hits"],
                     "hitDamageRatioList": [p / 100 for p in source["hitPercents"]] + [0.] * (30-out["hits"]),
                     "DamageType": out["damageType"], "damageCalcType": out["damageType"],
                     "TargetType": "Single" if damage["range"] == 1 else "Group", "targetRage": "None",
                     "defaultTargetRelation": "Enemies", "defaultTargetState": "Alive",
                     "isSameRelationTargetingDisabled": True, "isHostilityRelationTargetingDisabled": False,
                     "isReverseDamageToUndead": False, "totalDamageDisplayRule": "Default",
                     "element": elements[0] if elements else "None"})
    settings["SkillIcon.TagName"] = "UI.Skill.Action.Icon." + (elements[0] if elements else "Attack")
    out.update({"set": settings, "referenceSkillId": CLOUD_ID, "totalPower": cloud["magnification"],
                "description": f"{out['hits']} hits of {' / '.join(elements) or 'non-elemental'} "
                               f"{'physical' if out['damageType'] == 'Physic' else 'magic'} damage to {out['target'].lower()}."})
    return out


def resolve_import(unit, skill):
    """Keep incomplete LBs buildable with an explicit neutral damage placeholder.

    profile() remains strict for coverage audits. Only Studio/import builds use
    this compatibility path; source mechanics are never labelled as supported.
    """
    from ability_converter.reviewed import VERSION as REVIEWED_VERSION
    if skill.get('effectPolicy') == REVIEWED_VERSION:
        from ability_converter.reviewed_lb import resolve as reviewed_resolve
        return reviewed_resolve(unit, skill)
    try:
        source = resolve(unit, skill)
        result = profile(source)
    except ValueError as ex:
        source = None
        result = {"supported": False, "issues": [str(ex)]}
    if result["supported"]:
        result = {**result, "sourceSupported": True, "animationIncomplete": True}
        return source, result
    reasons = result.get("issues", [])
    original = source or {}
    # Keep generic damage mechanics, but preserve the unit's known LB timing
    # and sound cues. Presentation does not certify unsupported effect types.
    frames = original.get("hitFrames") or original.get("presentationHitFrames") or []
    frames = sorted(set(f for f in frames if type(f) is int and f >= 0))
    if len(frames) > 30:
        frames = [frames[round(i * (len(frames) - 1) / 29)] for i in range(30)]
    count = len(frames) or 10
    weights = [100 // count + (i < 100 % count) for i in range(count)]
    synthetic = {"lbId": original.get("lbId"), "name": original.get("name"),
                 "availableLbIds": original.get("availableLbIds", []), "elements": [],
                 "moveType": 0, "movement": {"type": 0}, "damageComponent": 0,
                 "components": [{"index": 0, "type": 1, "target": 1, "range": 2}],
                 "hitFrames": frames or list(range(10)), "hitPercents": weights}
    fallback = profile(synthetic)
    fallback.update(mode="fallback", sourceSupported=False, animationIncomplete=True,
                    fallbackReasons=reasons, warnings=["This LB uses a generic damage resonance while its FFBE mechanics are being added."],
                    description=f"Temporary resonance: {count} hits of non-elemental physical damage to all enemies.")
    # Generic reactions are spread through the unit's own LB motion; these are
    # not the synthetic frames used to derive the normalized skill settings.
    timeline = {k: v for k, v in synthetic.items() if k not in ("hitFrames", "hitPercents", "damageComponent", "components")}
    timeline.update(sounds=original.get("sounds", []), warnings=original.get("warnings", []),
                    unitId=original.get("unitId"),
                    source={"presentation": "Source LB timing and sounds with generic damage mechanics"})
    if frames:
        timeline.update(hitFrames=frames, hitPercents=weights)
    if original.get("moveType") in (0, 1, 4):
        timeline.update(moveType=original["moveType"], movement=original.get("movement", {}))
    return timeline, fallback


@lru_cache(maxsize=None)
def table(name):
    for folder in (ROOT / "data/ffbe/master", ROOT / "build/devui/live_jp"):
        path = folder / (name + ".json")
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            data['_directory']=str(path.parent)
            return data
    return {"file": None, "rows": []}


_master_indexes = {}


def master_rows(name, key):
    data = table(name)
    cached = _master_indexes.get((name, key))
    if cached is None or cached[0] is not data:
        cached = (data, {str(r.get(key)): r for r in data["rows"]})
        _master_indexes[name, key] = cached
    return cached[1]


def presentation_frames(row):
    """All source application frames, independent of mechanics support."""
    frames = set()
    for group in (row.get("attack_frames") or "").split("@"):
        for hit in group.split("-"):
            if not hit:
                continue
            frame = hit.split(":")[0]
            if frame.isdigit():
                frames.add(int(frame))
    return sorted(frames)


def damage_timing(row):
    types = (row.get("effect_type") or "").split("@")
    components = (row.get("attack_frames") or "").split("@")
    # 1 = physical damage, 15 = magical damage in these FFBE master tables.
    # Multi-component damage needs power-weighted splits; do not guess those.
    damage = [i for i, kind in enumerate(types) if kind in ("1", "15")]
    if len(damage) != 1:
        return None
    # Older LBs share one hit sequence across their damage and side effects.
    # Newer records can store one sequence per effect, including buff entries.
    # Several groups with fewer entries than effects remain ambiguous: don't
    # shift their indexes or guess which omitted effect owns a sequence.
    if len(components) == len(types):
        sequence = components[damage[0]]
    elif len(components) == 1:
        sequence = components[0]
    else:
        return None
    if not sequence:
        return None
    hits = [part.split(":") for part in sequence.split("-")]
    if any(len(part) < 2 for part in hits):
        raise ValueError(f"Missing LB frame/weight pair for {row['lb_id']}")
    frames = [int(p[0]) for p in hits]
    percents = [int(p[1]) for p in hits]
    if len(hits) > 30:
        return None  # import the unit, then request custom mechanics in Studio.
    if frames != sorted(frames) or min(frames) < 0 or min(percents) < 0 or sum(percents) != 100:
        raise ValueError(f"Unsupported LB hit timing for {row['lb_id']}")
    return {"damageComponent": damage[0], "hitFrames": frames, "hitPercents": percents}


def effect_parameter(value):
    """Read scalar numbers; keep compound tokens and text for effect adapters.

    JP parameters can contain '&' lists, ':' pairs and literal text. Their
    meaning depends on the effect type, so retain the token and its position
    instead of flattening it or inventing a generic nested-list schema.
    """
    try:
        number = float(value)
    except ValueError:
        return value
    return number if math.isfinite(number) else value


def from_master(fid, form, row, variants):
    """Preserve each component's own target; ally buffs are not damage targets."""
    from devui import lb_names
    timing = damage_timing(row)
    import ffbe_lb_support
    support_frames = ffbe_lb_support.application_frames(row)
    types = row.get("effect_type", "").split("@")
    targets = row.get("target", "").split("@")
    ranges = row.get("target_range", "").split("@")
    params = row.get("effect_param", "").split("@")
    structured = row.get("effectParams")  # GL effects may contain nested ability lists.
    components = []
    for i, kind in enumerate(types):
        values = deepcopy(structured[i]) if structured is not None else [effect_parameter(p) for p in params[i].split(",")] if i < len(params) and params[i] else []
        power_index = {"1": 6, "15": 5}.get(kind)
        components.append({"index": i, "type": int(kind),
                           "target": int(targets[i]) if i < len(targets) and targets[i] else None,
                           "range": int(ranges[i]) if i < len(ranges) and ranges[i] else None,
                           "params": values,
                           "multiplier": values[power_index] / 100 if power_index is not None and len(values) > power_index and isinstance(values[power_index], (int, float)) else None})
    elements = [e for e, n in zip(ELEMENTS, (row.get("element_inflict") or "").split(",")) if n and float(n) != 0]
    return {"schema": 2, "unitId": fid, "lbId": str(row["lb_id"]), "availableLbIds": variants,
            "name": lb_names.english_name(row["lb_id"], row.get("name")) or row.get("name"),
            "jpname": row.get("name"), "fps": 60, "moveType": int(row.get("move_type") or 0),
            "rawAttackFrames": row.get("attack_frames"), "rawEffectType": row.get("effect_type"),
            "presentationHitFrames": presentation_frames(row), **(timing or {}),
            **({"supportFrames": support_frames} if support_frames else {}),
            "elements": elements, "components": components, **presentation(form, row),
            "rawLb": row,
            "source": {"unitTable": table("F_UNIT_MST")["file"], "lbTable": table("F_LIMITBURST_MST")["file"],
                       "effectGroups": table("F_EFFECT_GROUP_MST")["file"]}}


def presentation(form, row):
    """Movement and sound metadata are independent of regional skill mechanics."""
    offsets = move_offsets(form.get("MoveOffset"))
    groups = master_rows("F_EFFECT_GROUP_MST", "qIy86WvJ")
    sounds, effects, warnings = [], [], []
    primary, separator, _ = (row.get("effect_frames") or "").partition("@")
    if separator:
        warnings.append("Conditional LB effect groups need an adapter; only the primary group's sounds are used.")
    for entry in primary.split("&"):
        if not entry:
            continue
        offset, gid, *flags = entry.split(":")
        group = groups.get(gid)
        effects.append({"frame": int(offset), "groupId": gid, "flags": [int(f) for f in flags], "raw": group})
        if group is None:
            warnings.append(f"Missing effect group {gid}; sound/particle references are incomplete.")
            continue
        for sound in (group.get("1fVZ3rKd") or "").split(","):
            if sound:
                frame, cue, *sound_flags = sound.split(":")
                if not cue:
                    warnings.append(f"Missing sound cue ID in effect group {gid}: {sound!r}; entry omitted.")
                    continue
                sounds.append({"frame": int(offset) + int(frame), "cueId": int(cue), "groupId": gid,
                               "groupFrame": int(offset), "cueFrame": int(frame), "flags": sound_flags})
    return {"wait": row.get("wait"),
            "movement": {"type": int(row.get("move_type") or 0), "speed": form.get("MoveSpeed"),
                         "wait": row.get("wait"), "rawOffset": form.get("MoveOffset"),
                         "normalOffset": offsets["normal"] if offsets else None,
                         "lbOffset": offsets["lb"] if offsets else None,
                         "ffrTargetOffset": [-offsets["lb"][1], offsets["lb"][0], 0.] if offsets else None,
                         "useNativeSpacing": True},
            "sounds": sorted(sounds, key=lambda s: s["frame"]), "effectGroups": effects, "warnings": warnings,
            "rawUnit": form}


def resolve(unit, skill):
    """Saved schema-2 source, then decoded masters; upgrade old timing-only saves."""
    fid = str((unit.get("ffbe") or {}).get("id", ""))
    explicit = skill.get("ffbe_lb")
    bundled = ROOT / "data/ffbe/lb_profiles" / (fid + ".json")
    if not explicit and bundled.is_file():
        doc = json.loads(bundled.read_text(encoding="utf-8"))
        region = str(unit.get("ffbe", {}).get("source", "JP")).upper()
        variants = doc.get("regions", {}).get(region)
        if variants:
            selected = str(skill.get("ffbe_lb_id") or next(iter(variants)))
            if selected not in variants:
                raise ValueError(f"LB {selected} does not belong to FFBE form {fid}")
            entry = variants[selected]
            if entry.get("error"):
                raise ValueError(entry["error"])
            return entry.get("source")
    manifest = ROOT / explicit if explicit else ROOT / "data/ffbe/lb" / (fid + ".json")
    if explicit or manifest.exists():
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if data.get("schema") not in (1, 2) or str(data["unitId"]) != fid or data.get("fps") != 60:
            raise ValueError("LB manifest does not match the FFBE form or its frame rate")
        if "hitFrames" in data:
            frames, percents = data["hitFrames"], data["hitPercents"]
            if (not 1 <= len(frames) <= 30 or len(frames) != len(percents) or
                    any(type(v) is not int or v < 0 for v in frames + percents) or
                    frames != sorted(frames) or sum(percents) != 100):
                raise ValueError("Invalid FFBE LB frame timing or damage split in manifest")
        selected = str(skill.get("ffbe_lb_id", data["lbId"]))
        if selected not in data["availableLbIds"]:
            raise ValueError(f"LB {selected} does not belong to FFBE form {fid}")
        if data["schema"] == 2 and selected == data["lbId"]:
            return data
        # A schema-1 manifest has no targeting/elements or LB-specific offset.
        # Do not let it hide newer source data or ignore a changed LB variant.
        skill = {**skill, "ffbe_lb_id": selected}
    # The decoded masters are JP. Prefer the GL datamine for a GL selection;
    # identical form IDs do not imply identical regional LB mechanics.
    if str(unit.get("ffbe", {}).get("source", "JP")).upper().startswith("GL"):
        regional = from_datamine(unit, skill)
        if regional is not None:
            return regional
    units = table("F_UNIT_MST")
    form = master_rows("F_UNIT_MST", "unit_evo_id").get(fid)
    if not form or not form.get("lb_id"):
        return from_datamine(unit, skill)
    variants = form["lb_id"].split(",")
    selected = str(skill.get("ffbe_lb_id", variants[0]))
    if selected not in variants:
        raise ValueError(f"LB {selected} does not belong to FFBE form {fid}")
    lbs = table("F_LIMITBURST_MST")
    row = master_rows("F_LIMITBURST_MST", "lb_id").get(selected)
    if not row:
        return from_datamine(unit, skill)
    data=from_master(fid, form, row, variants)
    if directory:=lbs.get('_directory'):
        from ability_converter.lb_sources import FolderResolver,attach
        from ability_converter.sources import master_record
        return attach(data,master_record(row,'F_LIMITBURST_MST',path=str(Path(directory)/'F_LIMITBURST_MST.json')),
                      FolderResolver(directory,'JP_CLIENT',master=True))
    return data


@lru_cache(maxsize=2)
def datamine(region):
    for root in (ROOT / "data/ffbe/datamine", Path("T:/Projects/ffbe/ffbe-wiki-tools/datamine/data")):
        folder = root / region
        if (folder / "limitbursts.json").is_file() and (folder / "units.json").is_file():
            units = json.loads((folder / "units.json").read_text(encoding="utf-8-sig"))
            return {fid: row for u in units.values() for fid, row in u.get("entries", {}).items()}, \
                json.loads((folder / "limitbursts.json").read_text(encoding="utf-8-sig")), str(folder)
    return {}, {}, None


def from_datamine(unit, skill):
    fid = str(unit["ffbe"]["id"])
    preferred = "gl" if str(unit["ffbe"].get("source", "JP")).upper().startswith("GL") else "jp"
    for region in (preferred, "jp" if preferred == "gl" else "gl"):
        forms, lbs, path = datamine(region)
        form = forms.get(fid)
        if not form:
            continue
        variants = [str(v) for v in form.get("limitburst_id", [])]
        if not variants:
            continue
        selected = str(skill.get("ffbe_lb_id", variants[0]))
        if selected not in variants:
            raise ValueError(f"LB {selected} does not belong to FFBE form {fid}")
        lb = lbs.get(selected)
        if not lb or not lb.get("levels"):
            continue
        level_id=min(lb['levels'],key=int)
        level = lb["levels"][level_id]
        raw = level.get("effects_raw", [])
        frames, weights = lb.get("attack_frames", []), lb.get("attack_damage", [])
        if len(frames) != len(weights) or any(len(fs) != len(ps) for fs, ps in zip(frames, weights)):
            raise ValueError(f"LB {selected}: regional attack frames and damage weights have different lengths")
        elements = ["Thunder" if e == "Lightning" else e for e in (lb.get("element_inflict") or [])]
        row = {"lb_id": selected, "name": lb.get("name"), "move_type": lb.get("move_type", 0),"cost":level.get('cost',0),
               "effect_type": "@".join(str(c[2]) for c in raw),
               "target": "@".join(str(c[1]) for c in raw), "target_range": "@".join(str(c[0]) for c in raw),
               "effect_param": "@".join(",".join(str(v) for v in c[3]) for c in raw),
               "effectParams": [deepcopy(c[3]) for c in raw],
               "element_inflict": ",".join("1" if e in elements else "0" for e in ELEMENTS),
               "attack_frames": "@".join("-".join(f"{f}:{p}" for f, p in zip(fs, ps)) for fs, ps in zip(frames, weights))}
        data = from_master(fid, {}, row, variants)
        data["source"] = {"datamine": path}
        # Shared form/LB IDs alone do not prove that regional animations match.
        # Reuse JP presentation only when movement and damage timing also agree.
        jp_form = master_rows("F_UNIT_MST", "unit_evo_id").get(fid)
        if jp_form and selected not in (jp_form.get("lb_id") or "").split(","):
            jp_form = None
        jp_lb = master_rows("F_LIMITBURST_MST", "lb_id").get(selected) if jp_form else None
        try:
            jp_timing = damage_timing(jp_lb) if jp_lb else None
        except ValueError:
            jp_timing = None
        import ffbe_lb_support
        jp_support = ffbe_lb_support.application_frames(jp_lb) if jp_lb else None
        matching_applications = (jp_lb and presentation_frames(jp_lb) and
                                 presentation_frames(jp_lb) == presentation_frames(row) and
                                 jp_lb.get("effect_type") == row["effect_type"] and
                                 jp_lb.get("target") == row["target"] and
                                 jp_lb.get("target_range") == row["target_range"])
        timing_matches = matching_applications or (jp_timing and jp_timing["hitFrames"] == data.get("hitFrames")) or (
            jp_support and jp_support == data.get("supportFrames") and jp_lb.get("effect_type") == row["effect_type"]
            and jp_lb.get("target") == row["target"] and jp_lb.get("target_range") == row["target_range"])
        if timing_matches and int(jp_lb.get("move_type") or 0) == data["moveType"]:
            data.update(presentation(jp_form, jp_lb))
            data["source"]["presentation"] = "JP master data: matching form, LB, move type and hit frames"
            data["warnings"].append("Uses matching JP animation metadata for movement and sounds; the selected region's damage mechanics are preserved.")
        else:
            data["warnings"].append("No matching LB sound/offset metadata: only the common charging sound is available, with native spacing.")
        if region != preferred:
            data["warnings"].append(f"No {preferred.upper()} LB source is installed for this form; using {region.upper()} data.")
        from ability_converter.lb_sources import FolderResolver,attach
        from ability_converter.sources import structured_records
        revision=region.upper()+'_2024'
        record=next(structured_records({selected:{**lb,'levels':{level_id:level}}},revision,
                                       'limitbursts',Path(path)/'limitbursts.json'))
        return attach(data,record,FolderResolver(path,revision))
    return None
