"""Author an FFBE LB sequence in the demo's cooked, event-only sequence shell.

The shell supplies the game's director and battle-event binding. Both the editor
channel and the cooked one-shot entity tree are rebuilt from the same schedule;
neither Cloud's Master, movie, sound sequence nor effect sequence is used.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import re
import uuid
import ffbe_lb

DEFAULT_FIELD_COLOR = ffbe_lb.NEUTRAL_COLOR
TICKS = 24000
SHELL = "FFRS/Content/Sequencer/Battle/Skill/440110/440111/Track/SEQ_Battle_440111_Cut_000"
DEFAULT_RIGHT_SHIFT = 200.0  # user-requested staging correction, separate from FFBE source offsets
CG_TEMPLATES = frozenset((440010, 440090, 440110))


def migrate_cg(unit):
    """Old imported visions must not enter a donor's CG sequence (Studio #1)."""
    skill = unit.get("lb_custom")
    if unit.get("ffbe") and skill and skill.get("visuals", skill.get("from")) in CG_TEMPLATES:
        if skill.get("presentation") != "ffbe":
            unit = deepcopy(unit)
            unit["lb_custom"]["presentation"] = "ffbe"
    return unit


def field_color(value=None):
    value = DEFAULT_FIELD_COLOR if value is None else value
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Resonance field colour must be a six-digit hex colour, e.g. #FFAA33")
    return value.upper()


def resolved_field_color(skill, source=None):
    if skill.get("field_color_mode", "element") == "custom":
        return field_color(skill.get("field_color"))
    elements = (source or {}).get("elements", [])
    if skill.get("mechanics") == "custom":
        elements = [skill.get("set", {}).get("element", "None")]
    return ffbe_lb.element_color(elements)


def uses_ffbe(unit, skill):
    mode = skill.get("presentation", "ffbe" if unit.get("ffbe") else "template")
    if mode not in ("ffbe", "template"):
        raise ValueError(f"Unknown Resonance presentation: {mode}")
    # Apply the same guard to specs built directly, without opening Studio.
    cg = unit.get("ffbe") and skill.get("visuals", skill.get("from")) in CG_TEMPLATES
    return bool(skill.get("resonance") and (mode == "ffbe" or cg))


def grading_row(skill_id, color, donor_name):
    """A private grading row; changing one vision never recolours a native skill.

    RGB gain blends the selected colour with neutral light to keep the battle
    readable. The picker represents the tint hue, not a literal screen colour.
    """
    color = field_color(color)
    rgb = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    st = {"ID": skill_id}
    for band in ("Global", "Highlights", "Shadows", "Midtones"):
        for control in ("Saturation", "Contrast", "Gamma", "Gain", "Offset"):
            st[f"bOverride_Color{control}{band}"] = band == "Global" and control in ("Gain", "Gamma", "Contrast")
    st.update({
        "colorGainGlobal": dict(zip("XYZW", [*(0.4 + 0.6 * c for c in rgb), 1.0])),
        "colorGammaGlobal": {"X": 1.0, "Y": 1.0, "Z": 1.0, "W": 0.9},
        "colorContrastGlobal": {"X": 1.15, "Y": 1.15, "Z": 1.15, "W": 1.0},
    })
    return {"row": f"FFBE_Field_{skill_id}", "cloneFrom": donor_name, "set": st}


def reaction_settings(skill_id):
    return {"ID": skill_id, "NormalEffectID": -1, "CriticalEffectID": -1,
            "WeaknessEffectID": -1, "MissEffectID": -1, "AdditionalEffectID": -1,
            "DeathEffectID": -1, "IsAdditionalEffect": False, "PlayShakeID": 1}


def opening_timing(source):
    """Optional measured/source-backed prelude; absent profiles keep their clock.

    The main LB sprite, hit list and effect groups all retain frame zero. A
    separate charge motion can occur within this prelude. This is deliberately
    metadata, because native cut-in waiting depends on the unit's own CGS.
    """
    opening = (source or {}).get("opening")
    if opening is None:
        return None
    if not isinstance(opening, dict):
        raise ValueError("FFBE LB opening timing must be an object")
    frames = opening.get("durationFrames")
    if type(frames) is not int or not 0 < frames <= 3600:
        raise ValueError("FFBE LB opening duration must be 1–3600 source frames")
    charge = opening.get("chargeFrame")
    if charge is not None:
        if type(charge) is not int or not 0 <= charge < frames:
            raise ValueError("FFBE LB charge frame must be within the opening")
        if opening.get("chargeMotion") != "LB1_charge":
            raise ValueError("FFBE LB charge needs the native LB1_charge motion")
    return opening


def schedule(seconds, hit_count, skill_id, source=None, sounds=None, movement=None):
    if seconds is None or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("The FFBE limit-burst motion is missing or empty; download the unit's sprites again")
    if type(hit_count) is not int or not 0 <= hit_count < 2147483648:
        raise ValueError("Resonance hit count must be a nonnegative int32")
    source = source or {}
    opening = opening_timing(source)
    opening_frames = opening["durationFrames"] if opening else 0
    # Tick times allow distinct, ordered events even in a very short LB.
    # Some FFBE LBs start a cue before frame zero. Reserve their pre-roll;
    # keep every hit and sound relative to LB1 rather than dropping the cue.
    earliest_sound = min((s['frame'] for s in (sounds or [])), default=0)
    start = max(TICKS // 2 + opening_frames * (TICKS // 60), -earliest_sound * (TICKS // 60) + 1)
    opening_start = start - opening_frames * (TICKS // 60) if opening else 801
    motion_end = start + math.ceil(seconds * TICKS)
    cleanup = motion_end + TICKS // 5
    events = []
    sounds = sounds or []
    movement = movement or {}
    move = movement.get("enabled", source.get("moveType") == 1)
    hit_frames = source.get("hitFrames")
    if hit_frames is None and hit_count == 1 and source.get("supportFrames") and len(set(source["supportFrames"])) == 1:
        hit_frames = sorted(set(source["supportFrames"]))
    if hit_frames is not None:
        if len(hit_frames) != hit_count or any(not isinstance(f, int) or f < 0 for f in hit_frames):
            raise ValueError("FFBE hit frames must match the resonance's damage hit count")
        motion_end = max(motion_end, start + max(hit_frames) * (TICKS // 60))
        cleanup = motion_end + TICKS // 5

    def at(tick, event, **params):
        events.append({"time": tick, "set": {"EventType": event, **params}})

    def animate(tick, name, loops=1):
        # The cooked shell's function defaults include both combatant sides.
        # Select the summoned vision explicitly, as converted commands do;
        # the Resonance's mechanical owner can remain the equipping actor.
        at(tick, "UnitPlayAnimByName", Unit_PlayAnimByName_AnimationName=name,
           Unit_PlayAnimByName_FirstDualcastAnimationName=name,
           Unit_PlayAnimByName_SecondDualcastAnimationName=name,
           Unit_PlayAnimByName_SkipDualcast=False, Unit_PlayAnimByName_AnimationID=-1,
           Unit_PlayAnimByName_InStartFrame=0, Unit_PlayAnimByName_InPlayRate=1.0,
           Unit_PlayAnimByName_InLoopCount=loops, Unit_PlayAnimByName_IsPlayFriend=True,
           Unit_PlayAnimByName_IsPlayEnemy=False, Unit_PlayAnimByName_IsOnlyVisionUnit=True)

    at(0, "PostSetDefaultColorGrading", Post_SetDefaultColorGrading_Frame=0)
    at(1, "CameraSetDefault", Camera_SetDefault_Frame=0,
       Camera_SetDefault_IsRotation=True, Camera_SetDefault_IsLocation=True, Camera_SetDefault_IsZoomInOut=True)
    at(2, "OtherSetGameSpeed", Other_SetGameSpeed_TimeDilation=1.0)
    at(opening_start - 1, "PostSetColorGradingGlobalParameter", Post_SetColorGradingGlobalParameter_Id=skill_id,
       Post_SetColorGradingGlobalParameter_Frame=10)
    initial_motion = "command" if opening and opening.get("chargeFrame") is not None else "LB1_before"
    animate(opening_start, initial_motion)
    if move:
        # FFBE ground Vec2 -> FFR ground plane: horizontal -> +Y, depth -> -X.
        # Retain FFR's runtime combatant clearance; X-only changes are depth.
        offset = movement.get("target_offset", (source.get("movement") or {}).get("ffrTargetOffset") or [0, 0, 0])
        if len(offset) != 3 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in offset):
            raise ValueError("LB target offset must contain three finite coordinates")
        shift = movement.get("right_shift", 0.0 if "target_offset" in movement else DEFAULT_RIGHT_SHIFT)
        if not isinstance(shift, (int, float)) or isinstance(shift, bool) or not math.isfinite(shift):
            raise ValueError("LB right shift must be finite")
        offset = [offset[0], offset[1] + shift, offset[2]]
        # Native loopMove completes the approach before the cut-in charge.
        at(opening_start + source.get('castBeforeMoveFrames', 0) * (TICKS // 60) + 1, "UnitMoveToTarget", Unit_MoveToTarget_Frame=12,
           Unit_MoveToTarget_PartName="Null_root", Unit_MoveToTarget_AddLocation=dict(zip("xyz", offset)),
           Unit_MoveToTarget_Height=0.0, Unit_MoveToTarget_EasingType="EaseOut",
           Unit_MoveToTarget_EasingBlendExp=1.5, Unit_MoveToTarget_EasingSteps=2,
           Unit_MoveToTarget_IsDisableOffset=False, Unit_MoveToTarget_IsVisionUnit=True)
    if opening and opening.get("chargeFrame") is not None:
        charge_start = opening_start + opening["chargeFrame"] * (TICKS // 60)
        if move and charge_start < opening_start + 1 + 12 * (TICKS // 60):
            raise ValueError("FFBE LB approach must finish before its charge motion")
        animate(charge_start, opening["chargeMotion"])
    animate(start, "LB1")
    # Keep the fallback for units whose LB master data is not installed yet.
    hit_times = ([start + frame * (TICKS // 60) for frame in hit_frames] if hit_frames is not None else
                 [start + round((motion_end - start) * (0.35 + 0.55 * i / max(1, hit_count - 1)))
                  for i in range(max(1, hit_count))])
    for t in hit_times:
        at(t, "OtherReaction", Other_Reaction_Id=skill_id, Otber_Reaction_ReactionNum=-1,
           Otber_Reaction_bReturnIdleMotion=True, Otber_Reaction_bChangeColor=False)
    audio_end = 0
    for sound in sounds:
        t = start + sound["frame"] * (TICKS // 60)
        if t < 0:
            raise ValueError("FFBE sound cue precedes the sequence")
        at(t, "SoundPlayHitSound", Sound_PlayHitSound_CueSheetName=sound["bank"],
           Sound_PlayHitSound_playLabel=sound["cueName"])
        audio_end = max(audio_end, t + math.ceil(sound["durationMs"] * TICKS / 1000))
    at(cleanup, "PostSetDefaultColorGrading", Post_SetDefaultColorGrading_Frame=10)
    at(cleanup + 1, "CameraSetDefault", Camera_SetDefault_Frame=10,
       Camera_SetDefault_IsRotation=True, Camera_SetDefault_IsLocation=True, Camera_SetDefault_IsZoomInOut=True)
    animate(cleanup + 2, "idle", 0)
    if move:
        at(cleanup + 3, "UnitMoveToDefaultLocation", Unit_MoveToDefaultLocation_Frame=12,
           Unit_MoveToDefaultLocationn_Height=0.0, Unit_MoveToDefaultLocation_EasingType="EaseOut",
           Unit_MoveToTargetMoveToDefaultLocation_EasingBlendExp=1.5,
           Unit_MoveToDefaultLocation_EasingSteps=2, Unit_MoveToDefaultLocation_IsAllSide=False,
           Unit_MoveToDefaultLocation_IsVision=True)
    # Leave a complete blend interval before the exclusive playback end. Do not
    # call OtherSkipResetParameter or release the battle job before cleanup.
    duration = max(cleanup + TICKS, audio_end + TICKS // 10)
    at(duration - TICKS // 10, "PostSetDefaultColorGrading", Post_SetDefaultColorGrading_Frame=0)
    return {"duration": duration, "events": sorted(events, key=lambda e: e["time"])}


def prop(data, name):
    return next(p for p in data if p.get("Name") == name)


def child(data, *names):
    for name in names:
        data = prop(data, name)["Value"]
    return data


def replace_array(p, items):
    p["Value"] = items
    for i, item in enumerate(items):
        item["Name"] = str(i)


def _frame(p, tick):
    if p["$type"].split(",")[0].endswith(".FrameNumberPropertyData"):
        p["Value"]["Value"] = tick
    elif isinstance(p.get("Value"), list):
        for c in p["Value"]:
            _frame(c, tick)


def author(asset, plan):
    """Modify a fresh Cut-shell JSON dump and return bytecode edits by export ID.

    Export numbers are deliberately preserved. Each event's original function
    and BoundObjectProperty travel together, so Unreal receives the battle actor.
    Unsupported shells fail instead of silently producing a partial timeline.
    """
    exps = asset["Exports"]
    imports = asset["Imports"]
    def cls(e):
        return imports[-e["ClassIndex"] - 1]["ObjectName"] if e["ClassIndex"] < 0 else ""
    def only(kind):
        found = [(i, e) for i, e in enumerate(exps, 1) if cls(e) == kind]
        if len(found) != 1:
            raise ValueError(f"FFBE sequence shell needs one {kind}, found {len(found)}")
        return found[0]
    _, root = only("LevelSequence")
    _, scene = only("MovieScene")
    _, compiled = only("MovieSceneCompiledData")
    if any(cls(e) in ("MovieSceneManaTrack", "MovieSceneAtomTrack", "MovieSceneSubTrack", "MovieSceneSpawnTrack") for e in exps):
        raise ValueError("FFBE sequence shell must contain only battle event tracks")
    bindings = child(scene["Data"], "ObjectBindings")
    if len(bindings) != 1:
        raise ValueError("FFBE sequence shell needs its single battle-event binding")
    track_ref = child(bindings[0]["Value"], "Tracks")[0]
    track = exps[track_ref["Value"] - 1]
    section_ref = child(track["Data"], "Sections")[0]
    section_id = section_ref["Value"]
    section = exps[section_id - 1]
    channel = child(section["Data"], "EventChannel")
    time_template = deepcopy(child(channel, "KeyTimes")[0])
    keys = {}
    for e in exps:
        for p in e.get("Data", []):
            if p.get("Name") != "EventChannel":
                continue
            for k in child(p["Value"], "KeyValues"):
                fn = child(k["Value"], "Ptrs", "Function")
                if fn > 0:
                    keys[fn] = deepcopy(k)
            replace_array(prop(p["Value"], "KeyTimes"), [])
            replace_array(prop(p["Value"], "KeyValues"), [])
    # A native donor's finite number of entry functions is a starting pool,
    # not a limit on source-authored cues, camera keys or effect layers.
    # Clone the bound event entry, register it with its existing director and
    # rebind only its own parameter-owner references.
    needed = len({json.dumps(e['set'], sort_keys=True) for e in plan['events']})
    if needed > 4096:
        raise ValueError('FFBE sequence exceeds 4096 distinct event payloads')
    if needed > len(keys):
        if not keys:
            raise ValueError('FFBE sequence shell has no bound event entry to extend')
        template_id = min(keys)
        template = exps[template_id-1]
        owner_id = template['OuterIndex']
        director = exps[owner_id-1] if owner_id > 0 else {}
        if (cls(template) != 'Function' or 'ClassExport' not in director.get('$type', '')
                or not isinstance(director.get('FuncMap'), list)
                or template_id not in director.get('Children', [])
                or not template.get('LoadedProperties')):
            raise ValueError('FFBE event-function growth requires a registered director function')
        template_key = deepcopy(keys[template_id])
        def rebind(value, old, new):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'ResolvedOwner' and item == old: value[key] = new
                    else: rebind(item, old, new)
            elif isinstance(value, list):
                for item in value: rebind(item, old, new)
        while len(keys) < needed:
            index = len(exps)+1
            name = f'FFBE_AuthoredEvent_{index}'
            if any(e['ObjectName'] == name and e.get('OuterIndex') == owner_id for e in exps):
                raise ValueError('FFBE generated event function name collision')
            copied = deepcopy(template)
            copied['ObjectName'] = name
            rebind(copied.get('ScriptBytecode', []), template_id, index)
            for field in ('SerializationBeforeSerializationDependencies', 'CreateBeforeSerializationDependencies',
                          'SerializationBeforeCreateDependencies', 'CreateBeforeCreateDependencies'):
                copied[field] = [index if v == template_id else v for v in copied.get(field, [])]
            for field in ('SerialSize', 'SerialOffset', 'ScriptSerializationStartOffset', 'ScriptSerializationEndOffset'):
                copied[field] = 0
            exps.append(copied)
            director['FuncMap'].append([name, index])
            director['Children'].append(index)
            director.setdefault('CreateBeforeSerializationDependencies', []).append(index)
            if name not in asset['NameMap']: asset['NameMap'].append(name)
            dependency_map = asset.get('DependsMap')
            if isinstance(dependency_map, list) and len(dependency_map) == index-1:
                dependency_map.append(deepcopy(dependency_map[template_id-1]))
            copied_key = deepcopy(template_key)
            prop(child(copied_key['Value'], 'Ptrs'), 'Function')['Value'] = index
            rebind(copied_key, template_id, index)
            keys[index] = copied_key
        asset['NamesReferencedFromExportDataCount'] = len(asset['NameMap'])
    unique = {}
    edits, times, values = [], [], []
    for event in plan["events"]:
        if not 0 <= event["time"] < plan["duration"]:
            raise ValueError("Event outside the authored playback range")
        key = json.dumps(event["set"], sort_keys=True)
        if key not in unique:
            fn = sorted(keys)[len(unique)]
            unique[key] = fn
            edits.append({"export": str(fn), "set": event["set"]})
        time = deepcopy(time_template)
        _frame(time, event["time"])
        times.append(time)
        values.append(deepcopy(keys[unique[key]]))
    replace_array(prop(channel, "KeyTimes"), times)
    replace_array(prop(channel, "KeyValues"), values)
    replace_array(prop(bindings[0]["Value"], "Tracks"), [track_ref])
    for e in exps:
        if "MovieSceneEventTrack" == cls(e) and e is not track:
            replace_array(prop(e["Data"], "Sections"), [])
    # This shell's event section and track evaluation entry are unbounded, so a
    # long LB only requires the root playback range and compiled tree to grow.
    playback = child(scene["Data"], "PlaybackRange")[0]["Value"]
    playback["LowerBound"].update(Type="Inclusive", Value={**playback["LowerBound"]["Value"], "Value": 0})
    playback["UpperBound"].update(Type="Exclusive", Value={**playback["UpperBound"]["Value"], "Value": plan["duration"]})
    field = child(compiled["Data"], "EntityComponentField")
    entities = prop(field, "Entities")
    template = deepcopy(entities["Value"][0])
    new_entities = []
    for i in range(len(times)):
        ent = deepcopy(template)
        prop(child(ent["Value"], "Key"), "EntityOwner")["Value"] = section_id
        prop(child(ent["Value"], "Key"), "EntityID")["Value"] = i
        prop(ent["Value"], "SharedMetaDataIndex")["Value"] = 0
        new_entities.append(ent)
    replace_array(entities, new_entities)
    meta = prop(field, "SharedMetaData")
    replace_array(meta, [meta["Value"][0]])
    tree = child(field, "OneShotEntityTree")[0]["Value"]["SerializedData"]
    groups = {}
    for i, event in enumerate(plan["events"]):
        groups.setdefault(event["time"], []).append(i)
    entry_template = deepcopy(tree["Data"]["Entries"][0])
    item_template = deepcopy(tree["Data"]["Items"][0])
    node_template = deepcopy(tree["ChildNodes"]["Items"][0])
    entries, items, nodes = [], [], []
    for tick, indices in groups.items():
        ent = deepcopy(entry_template)
        ent.update(StartIndex=len(items), Size=len(indices), Capacity=len(indices))
        entries.append(ent)
        for i in indices:
            item = deepcopy(item_template)
            item.update(EntityIndex=i, MetaDataIndex=-1)
            items.append(item)
        node = deepcopy(node_template)
        for bound in ("LowerBound", "UpperBound"):
            node["Range"][bound]["Type"] = "Inclusive"
            node["Range"][bound]["Value"]["Value"] = tick
        node["Parent"]["ChildrenHandle"]["EntryIndex"] = -1
        node["Parent"]["Index"] = 0
        node["ChildrenID"]["EntryIndex"] = -1
        node["DataID"]["EntryIndex"] = len(nodes)
        nodes.append(node)
    tree["Data"].update(Entries=entries, Items=items)
    root_entry = deepcopy(tree["ChildNodes"]["Entries"][0])
    root_entry.update(StartIndex=0, Size=len(nodes), Capacity=len(nodes))
    tree["ChildNodes"].update(Entries=[root_entry], Items=nodes)
    tree["RootNode"]["ChildrenID"]["EntryIndex"] = 0
    tree["RootNode"]["DataID"]["EntryIndex"] = -1
    signature = "{" + str(uuid.uuid4()).upper() + "}"
    for e in (root, scene, section, track):
        child(e["Data"], "Signature")[0]["Value"] = signature
    child(track["Data"], "EvaluationFieldGuid")[0]["Value"] = signature
    child(compiled["Data"], "CompiledSignature")[0]["Value"] = signature
    return edits


def build(job, out, work, command, usmap, run):
    """Write the authored schedule into a cloned shell, then its event constants."""
    path = Path(out) / (job["asset"] + ".uasset")
    dump = Path(work) / (path.stem + "-authored.json")
    run([*command, "tojson", str(path), str(dump), "--usmap", usmap])
    asset = json.loads(dump.read_text(encoding="utf-8-sig"))
    edits = author(asset, job["plan"])
    dump.write_text(json.dumps(asset, ensure_ascii=False), encoding="utf-8")
    patch = dump.with_name(path.stem + "-events.json")
    patch.write_text(json.dumps({"legacyRoot": str(out), "outRoot": str(out),
                                "sequenceData": [{"asset": job["asset"], "json": str(dump)}],
                                "bytecode": [{"asset": job["asset"], **e} for e in edits]}), encoding="utf-8")
    run([*command, "patch", str(patch), "--usmap", usmap])
