"""Portable ordinary-command/passive bindings for Studio and the unit builder.

The snapshot contains structured source records, including resolved children.
Builds recompile those records; cached preview fields never replace mechanics.
"""
from copy import copy, deepcopy
from dataclasses import asdict
from functools import lru_cache
import math

from .catalog import record_scope, reference_scope
from .compiler import TableWriter
from .resonance import converter, materialize
from .sources import SourceRecord

SNAPSHOT_VERSION = "ffbe-ffr-source/1"
TICKS = 24000
# Match the previously corrected LB clearance (+Y is the party side). A small
# negative X puts the attacking sprite in front of its target, toward camera.
APPROACH_OFFSET = {'x': -80., 'y': 200., 'z': 0.}
APPROACH_FRAMES = 12


class SnapshotResolver:
    def __init__(self, snapshot):
        if snapshot.get("schemaVersion") != SNAPSHOT_VERSION:
            raise ValueError("Unsupported structured ability snapshot")
        self.records, self.index = {}, {}
        for payload in snapshot.get("records", []):
            record = SourceRecord(**deepcopy(payload))
            if record.key in self.records:
                raise ValueError(f"Duplicate snapshot identity {record.key}")
            self.records[record.key] = record
            key = record.source, record_scope(record.provenance()), record.id
            self.index.setdefault(key, []).append(record)
        if snapshot.get("root") not in self.records:
            raise ValueError("Structured ability snapshot has no root record")
        self.root = self.records[snapshot["root"]]

    def resolve(self, source, dependency):
        key = source["source"], reference_scope(source, dependency["kind"]), str(dependency["id"])
        candidates = self.index.get(key, [])
        if dependency["kind"] == "lb" and candidates:
            candidates = sorted(candidates, key=lambda r: int(r.level or 0), reverse=True)[:1]
        if len(candidates) != 1:
            raise ValueError(f"{'Missing' if not candidates else 'Ambiguous'} snapshot reference {'/'.join(key)}")
        return candidates[0]


class RecordingResolver:
    def __init__(self, root, resolver):
        self.records, self.resolver = {root.key: root}, resolver

    def resolve(self, source, dependency):
        if self.resolver is None:
            raise ValueError("Linked ability requires its structured source catalog")
        record = self.resolver.resolve(source, dependency)
        self.records[record.key] = record
        return record


def application_frames(result):
    """The native single-row sequencer can execute one timeline per command."""
    native = result["native"]
    actions = [a for c in result["components"] for a in c["actions"]]
    if actions:
        return native["sequence"]["hitFrames"]
    frames = []
    groups = result["presentation"].get("attack_frames") or []
    if groups and not isinstance(groups[0], list):
        groups = [groups]
    for component in result["components"]:
        if component["status"] == "noop":
            continue
        if component.get("expanded") and component['semantic'].get('mode')=='inline':
            frames.extend(application_frames(component["expanded"]))
            continue
        index = component["index"]
        group = groups[0] if len(groups) == 1 else groups[index] if len(groups) == len(result["components"]) else []
        if len(group) != 1:
            raise ValueError("Support components need one verified common application frame")
        frames.extend(group)
    if not frames or len(set(frames)) != 1:
        raise ValueError("Support components need one verified common application frame")
    return frames[:1]


@lru_cache(maxsize=2)
def damage_phase_evidence(variation="Decrease"):
    """Keep stock damage and recovery phase evidence separate.

    Both use DamageAndRecovery's bundle preparation, but an effect observed
    beside damage alone does not prove its behavior beside recovery.
    """
    if variation not in ("Decrease", "Increase"):
        raise ValueError("Phase evidence requires damage or recovery")
    native = converter().native
    found = {}
    for row in sorted(native.skills.values(), key=lambda row:row["ID"]):
        if row["skillEffectType"] != "DamageAndRecovery" or row["parameterVariationType"] != variation or row["magnification"] <= 0:
            continue
        for bundle in row["effectBundleList"]:
            effect = native.effects.get(bundle["effectId"])
            if effect is None:
                continue
            key = effect["EffectType"], bundle["activeSkillAddTiming"]
            found.setdefault(key,{"skillId":row["ID"], "effectId":bundle["effectId"]})
    return found


def damage_phase_bindings(converted):
    actions = [a for c in converted["components"] for a in c["actions"]]
    effects = converted["native"]["effects"]
    if not actions or not effects:
        return []
    kinds = {a["kind"] for a in actions}
    if not kinds <= {"damage", "heal"} or len(kinds) > 1 and not converted["native"].get("applications"):
        raise ValueError("Mixed recovery and damage require separate command application jobs")
    variations = [("damage", "Decrease")] if kinds == {"damage"} else [("recovery", "Increase")] if kinds == {"heal"} else [("damage", "Decrease"), ("recovery", "Increase")]
    bindings = []
    for effect in effects:
        if 'tagAttack' in effect:
            from .tag_attacks import validate, EVIDENCE
            validate(converter().native,converted)
            bindings.append({'component':effect['component'],'effectType':'MulBaseBreakBySkill',
                'timing':'BeforeDamageCalculation','evidence':deepcopy(EVIDENCE),
                'tagApplications':effect['tagAttack']['applicationIndices']})
            continue
        if "skillElement" in effect:
            from .multiple_elements import validate, EVIDENCE
            validate(converter().native,converted)
            bindings.append({"component":effect["component"],"effectType":"AddElement",
                "timing":"BeforeDamageCalculation","evidence":deepcopy(EVIDENCE),
                "skillElement":effect["skillElement"]["element"]})
            if 'applicationIndex' in effect['skillElement']:
                bindings[-1]['elementApplicationIndex'] = effect['skillElement']['applicationIndex']
            continue
        kind, timing = effect["set"]["EffectType"], effect["activeTiming"]
        generated = "applicationIndex" in effect
        # Generated AppendDamage is a calculation job. Its child can Increase
        # or Decrease (stock 505090 -> 501530 demonstrates recovery). Ordinary
        # support around a mixed composition still needs BOTH phase contracts.
        phases = [("damage", "Decrease")] if generated else variations
        evidence = {}
        for phase_kind, variation in phases:
            available = damage_phase_evidence(variation)
            if (kind,timing) not in available:
                from .resistance_phases import evidence as resistance_evidence
                verified = resistance_evidence(converter().native,effect,variation)
                if verified is None:
                    raise ValueError(f"No stock {phase_kind}-phase binding for {kind}/{timing}; separate application jobs required")
                evidence[phase_kind] = verified
            else:
                evidence[phase_kind] = available[(kind,timing)]
        bindings.append({"component":effect["component"], "effectType":kind, "timing":timing,
                         "evidence":next(iter(evidence.values())) if len(evidence) == 1 else evidence})
        if generated:
            bindings[-1]["applicationIndex"] = effect["applicationIndex"]
            child = converted["native"]["applications"][effect["applicationIndex"]-1]
            bindings[-1]["calculation"] = child["set"]["parameterVariationType"]
            bindings[-1]["recipientEvidence"] = deepcopy(effect["targetBindingEvidence"])
            if child["set"]["parameterVariationType"] == "Increase":
                bindings[-1]["recoveryEvidence"] = {"skillId":505090,"effectId":1051,"childSkillId":501530,
                    "nativeCalculation":"0x144f6db90","nativeRecovery":"0x145227bc0"}
    return bindings


def profile(record, resolver=None, *, effect_choices=None, reviewed=False):
    recorded = RecordingResolver(record, resolver)
    if reviewed:
        from .reviewed import compiler as reviewed_compiler
        compiler = reviewed_compiler(recorded)
    else:
        compiler = copy(converter())
    compiler.resolver = recorded
    if effect_choices is not None and not reviewed:
        from .effect_policy import StudioAdapter
        compiler.adapters = StudioAdapter(compiler.native, compiler.registry, effect_choices)
    converted = compiler.convert(record)
    if effect_choices is not None and not reviewed:
        from .effect_policy import invocation_issues
        # Binding may append helpers after opcode conversion; check those too.
        extra = invocation_issues({"actions":[], "effects":(converted.get("native") or {}).get("effects", [])})
        converted["issues"].extend(i for i in extra if i not in converted["issues"])
    result = {"mode":"converted", "supported":False, "conversion":converted,
              "issues":list(converted["issues"]), "warnings":list(converted["changes"]),
              "runtimeValidation":"not_run", "snapshot":{"schemaVersion":SNAPSHOT_VERSION,
                  "root":record.key, "records":[asdict(r) for r in recorded.records.values()]}}
    if reviewed:
        from .reviewed import VERSION, fingerprint
        result['snapshot'].update(effectPolicy=VERSION, rulesSha256=fingerprint())
    if record.kind not in ("ability", "magic", "passive", *(('lb',) if reviewed else ())):
        result["issues"].append("Ordinary imports require an ability, magic or passive source")
    if not converted["validation"]["tableCompatible"] or result["issues"]:
        from .multicast import in_snapshot
        if in_snapshot(result['snapshot']) and not any(c['effects'] or c['actions'] for c in converted['components']):
            result['disabledBy'] = 'multicast'
        return result
    try:
        if record.kind != "passive":
            try:
                frames = application_frames(converted)
            except ValueError:
                if not reviewed: raise
                # Reviewed support is one application on use. Source animation
                # timestamps may contain separate buff cues, not repeated casts.
                frames = [0]
                result['warnings'].append('Support applies once when the vision starts its command motion.')
            if not frames or any(type(f) is not int or f < 0 for f in frames):
                raise ValueError("Command application frames must be nonnegative integers")
            move = record.data.get("move_type", 0)
            if move not in (None, 0, 1, 4):
                if not reviewed:
                    raise ValueError(f"Movement type {move} needs a command movement adapter")
                result['warnings'].append(f'Source movement type {move} uses a stationary vision motion for testing.')
                move = 0
            result["timeline"] = {"hitFrames":frames, "moveType":move or 0}
            if converted["native"]["sequence"].get("applicationKinds"):
                result["timeline"]["applicationKinds"] = list(converted["native"]["sequence"]["applicationKinds"])
            if reviewed:
                # Native bundles already carry their FFR before/after timing.
                # A stock example of every possible combination is not a
                # prerequisite for an explicitly experimental testing import.
                phases = [{'component': e['component'], 'effectType': e['set']['EffectType'],
                           'timing': e['activeTiming'], 'validation': 'awaiting_gameplay_test'}
                          for e in converted['native']['effects'] if e.get('set')]
            else:
                phases = damage_phase_bindings(converted)
            if phases:
                result["timeline"]["effectPhases"] = phases
                if any(phase['effectType']=='AddElementResistance' for phase in phases):
                    from .resistance_phases import CHANGE
                    result['warnings'].append(CHANGE)
                if any("applicationIndex" not in phase for phase in phases):
                    phase_kind = "recovery" if converted["native"]["set"]["parameterVariationType"] == "Increase" else "damage"
                    result["warnings"].append(f"Effects use FFR's native before/after {phase_kind} phases in source component order; separate source effect timestamps are not reproduced.")
        result.update(supported=True, set=deepcopy(converted["native"]["set"]),
                      description=converted.get('summary') or TableWriter.description(converted))
    except (ValueError, TypeError, KeyError, IndexError) as ex:
        result["issues"].append(str(ex))
    return result


def from_snapshot(snapshot, *, effect_choices=None, reviewed=False):
    resolver = SnapshotResolver(snapshot)
    if reviewed:
        from .reviewed import fingerprint
        if snapshot.get('rulesSha256') and snapshot['rulesSha256'] != fingerprint():
            raise ValueError('The saved ability uses a different effect review; reimport its kit')
    return profile(resolver.root, resolver, effect_choices=effect_choices, reviewed=reviewed)


def from_spec(spec):
    from .effect_policy import VERSION
    from .reviewed import VERSION as REVIEWED_VERSION
    version = spec.get("effectPolicy")
    if version == REVIEWED_VERSION:
        return from_snapshot(spec.get('conversionSource') or {}, reviewed=True)
    if version and version != VERSION:
        raise ValueError(f"Unknown Studio effect policy {version!r}; review the ability before building")
    return from_snapshot(spec.get("conversionSource") or {},
                         effect_choices=spec.get("effectChoices", {}) if version else None)


def schedule(profile, skill_id, seconds, motion, cast_seconds=0.5, *, cast_frames=None, cast_motion='magic_idle'):
    """Author source-timed reactions without an LB animation or field change."""
    if not profile.get("supported") or "timeline" not in profile:
        raise ValueError("A held or passive ability cannot receive a command timeline")
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("The command's FFBE motion is missing or empty")
    if motion not in ("attack_A", "magic_attack"):
        raise ValueError(f"Unsupported converted command motion {motion}")
    frames = profile["timeline"]["hitFrames"]
    casting = motion == 'magic_attack'
    if cast_frames is not None and (type(cast_frames) is not int or cast_frames < 0):
        raise ValueError('Source casting duration must be a nonnegative frame count')
    if cast_motion not in ('command', 'magic_idle'):
        raise ValueError('Unsupported source preparation motion')
    source_cast = cast_frames is not None
    # FFBE initMove treats both move types 0 and 4 as stationary.
    moving = profile['timeline']['moveType'] == 1
    start = TICKS // 2 + (cast_frames * (TICKS//60) if source_cast else
                         round(max(0.25, min(cast_seconds or 0.5, 1.0))*TICKS) if casting else 0)
    approach = start if moving and source_cast else 800
    if moving and source_cast:
        # Native order is preparation, approach, action. One extra source frame
        # leaves the +1-tick movement event's full duration before action starts.
        start += (APPROACH_FRAMES+1)*(TICKS//60)
    end = start + max(math.ceil(seconds*TICKS), max(frames)*(TICKS//60))
    events = []
    def at(tick, event, **params):
        events.append({"time":tick, "set":{"EventType":event, **params}})
    def animate(tick, name, loops=1):
        at(tick, 'UnitPlayAnimByName', Unit_PlayAnimByName_AnimationName=name,
           Unit_PlayAnimByName_FirstDualcastAnimationName=name, Unit_PlayAnimByName_SecondDualcastAnimationName=name,
           Unit_PlayAnimByName_SkipDualcast=False, Unit_PlayAnimByName_AnimationID=-1,
           Unit_PlayAnimByName_InStartFrame=0, Unit_PlayAnimByName_InPlayRate=1., Unit_PlayAnimByName_InLoopCount=loops,
           Unit_PlayAnimByName_IsPlayFriend=True, Unit_PlayAnimByName_IsPlayEnemy=False,
           Unit_PlayAnimByName_IsOnlyVisionUnit=True)
    at(0, 'VisionStartFade', Vision_SpawnFade_bSpawnFade=True)
    if casting or source_cast:
        animate(TICKS//2 if moving or source_cast else 800, cast_motion if source_cast else 'magic_idle', 0)
    if moving:
        animate(approach, 'step_front', 0)
        at(approach+1, "UnitMoveToTarget", Unit_MoveToTarget_Frame=APPROACH_FRAMES,
           Unit_MoveToTarget_PartName="Null_root", Unit_MoveToTarget_AddLocation=deepcopy(APPROACH_OFFSET),
           Unit_MoveToTarget_Height=0., Unit_MoveToTarget_EasingType="EaseOut",
           Unit_MoveToTarget_EasingBlendExp=1.5, Unit_MoveToTarget_EasingSteps=2,
           Unit_MoveToTarget_IsDisableOffset=False, Unit_MoveToTarget_IsVisionUnit=True)
    animate(start, motion)
    recovery = (profile['set'].get('parameterVariationType') == 'Increase'
                and profile['set'].get('skillEffectType') == 'DamageAndRecovery')
    if recovery and profile['set'].get('parameterType') == 'HitPoint':
        aura = {
            'NiagaraID': f'FFR_Recovery_{skill_id}',
            'niagaraAsset': {'path':'/Game/Effect/03_SKL/skl210030/NS_EF_SKL210030_Root','class':'NiagaraSystem'},
            'friendNiagaraAsset': None, 'enemyNiagaraAsset': None,
            'Scale': {'x':1.,'y':1.,'z':1.}, 'PartName':'NULL_Center',
            'minRotate':{'x':0.,'y':0.,'z':0.}, 'maxRotate':{'x':0.,'y':0.,'z':0.},
            'minLocation':{'x':0.,'y':0.,'z':0.}, 'maxLocation':{'x':0.,'y':0.,'z':0.},
            'bHitEffect':False, 'bPlayOwnerUnit':False, 'bPlayVisionUnit':False,
            'bDisableFollowing':True, 'bDisableEnemyReverse':True, 'bLookAtTarget':False, 'LookAtTargetID':-1}
        # This event reads SpawnTarget_NiagaraData, not the generic NiagaraData.
        # Match Curaga's all-selected-targets event, including its target ID.
        at(start + min(frames)*(TICKS//60), 'EffectSpawnNiagaraAtTarget',
           Effect_NiagaraData=aura, Effect_SpawnTarget_NiagaraData=aura,
           Effect_SpawnTarget_bAllTarget=True, Effect_SpawnTarget_ID=-1)
    for frame in frames:
        at(start + frame*(TICKS//60), "OtherReaction", Other_Reaction_Id=skill_id,
           Otber_Reaction_ReactionNum=-1, Otber_Reaction_bReturnIdleMotion=not recovery, Otber_Reaction_bChangeColor=False)
    cleanup = end + TICKS//5
    animate(cleanup, 'step_back' if moving else 'idle', 0)
    if moving:
        at(cleanup+1, "UnitMoveToDefaultLocation", Unit_MoveToDefaultLocation_Frame=12,
           Unit_MoveToDefaultLocationn_Height=0., Unit_MoveToDefaultLocation_EasingType="EaseOut",
           Unit_MoveToTargetMoveToDefaultLocation_EasingBlendExp=1.5,
           Unit_MoveToDefaultLocation_EasingSteps=2, Unit_MoveToDefaultLocation_IsAllSide=False,
           Unit_MoveToDefaultLocation_IsVision=True)
        animate(cleanup+TICKS//4, 'idle', 0)
    at(cleanup+TICKS//2, 'VisionStartFade', Vision_SpawnFade_bSpawnFade=False)
    return {"duration":cleanup+TICKS, "events":sorted(events, key=lambda e:e["time"])}


def materialize_passive(profile, passive_id, row_name, tbl, row_by, name):
    if profile["conversion"]["source"]["kind"] != "passive":
        raise ValueError("A passive grant requires a passive source")
    table = profile["conversion"]["native"]["table"]
    if any(r["row"] == row_name or r["set"].get("ID") == passive_id for r in tbl(table)["add"]):
        raise ValueError(f"Duplicate converted passive ID {passive_id}")
    settings = materialize(profile, passive_id, row_name, tbl, row_by)
    native = profile["conversion"]["native"]
    tbl(native["table"])["add"].append({"row":row_name, "cloneFrom":native["cloneFrom"],
        "set":{"ID":passive_id, "SortId":passive_id, "Name":name, "Description":profile["description"], **settings}})
