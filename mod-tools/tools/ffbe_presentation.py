"""Play prepared FFBE presentations. No master-data lookup or particle bake at build time."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

import ffbe_audio

ROOT = Path(__file__).resolve().parents[1]
BUNDLES = ROOT / 'data/ffbe/presentation'
VERSION = 'ffr-presentation-2'  # Separate preparation/action phases require a new reader.
TICKS = 24000
NATIVE_SUBSPACE = '/Game/Map/Btl/99Aku/99Aku_60/BG/Btl_99Aku_60_BG0.Btl_99Aku_60_BG0'


def source_fingerprint(snapshot):
    # File paths and translator notes are not source identity.
    records = [{k: r.get(k) for k in ('source', 'kind', 'id', 'level', 'data')}
               for r in snapshot.get('records', [])]
    return hashlib.sha256(json.dumps(records, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def lookup(unit, skill):
    form = str(unit.get('ffbe', {}).get('id', ''))
    import os
    path = Path(os.environ.get('FFR_PRESENTATION_DIR') or BUNDLES) / f'{form}.json'
    if not path.is_file(): path = BUNDLES / f'{form}.json'
    if unit.get('presentationStep') in ('cast_camera', 'target_camera'):
        from ffbe_cast_camera import entry as camera_entry
        prepared = None
        if path.is_file():
            prepared = json.loads(path.read_text(encoding='utf-8'))['moves'].get(
                (skill.get('conversionSource') or {}).get('root'))
        # The old test roster can keep camera-only native moves (Raegen Blast)
        # while its reviewed FFBE moves use the portable effects compiler.
        if not prepared or prepared.get('reconstructionProfile', {}).get('cameraSequence') != 'cast_target':
            return camera_entry(unit, skill, prepared)
    if not path.is_file() or skill.get('ffbe_presentation') is False:
        return None
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if bundle.get('schema') not in ('ffr-presentation-1', VERSION):
        raise ValueError('Unsupported FFBE presentation bundle')
    if bundle.get('form') is not None and str(bundle['form']) != form:
        raise ValueError('FFBE presentation bundle belongs to a different form; prepare the vision again')
    snapshot = skill.get('conversionSource') or {}
    source_key = snapshot.get('root')
    entry = bundle['moves'].get(source_key)
    if not entry:
        return None
    if entry.get('sourceKey') is not None and entry['sourceKey'] != source_key:
        raise ValueError('FFBE presentation entry belongs to a different move; prepare the vision again')
    profile = entry.get('reconstructionProfile')
    if profile is not None and not isinstance(profile, dict):
        raise ValueError('FFBE reconstruction profile must be an object')
    if profile and (str(profile.get('form', '')) != form or profile.get('sourceKey') != source_key):
        # Shared ability records can have identical source hashes across forms.
        # A copied bundle must not transfer one form's cinematic staging to them.
        raise ValueError('FFBE reconstruction profile does not match the selected form and move; prepare the vision again')
    if entry['sourceSha256'] != source_fingerprint(snapshot):
        raise ValueError('FFBE presentation source changed; prepare the vision again')
    entry = deepcopy(entry)
    # Host command type is trusted only from the selected build skill. Source
    # metadata and a copied cinematic profile cannot turn an ability into a
    # Resonance or acquire permission to move the battle camera.
    entry.pop('_hostResonance', None)
    if skill.get('resonance') is True:
        entry['_hostResonance'] = True
    for fx in entry.get('visuals', []):
        plane = fx.get('placement', {})
        if fx.get('anchor') != 'screen' or plane.get('mode') != 'camera_plane':
            continue
        validate_screen_placement(plane)
        spec_path = ROOT / fx['spec'] / 'spec.json'
        spec = json.loads(spec_path.read_text(encoding='utf-8'))
        actual_scale = spec.get('runtimeScale', 1.)
        if isinstance(actual_scale, bool) or not isinstance(actual_scale, (int, float)) or actual_scale != plane['runtimeScale']:
            raise ValueError('Camera plane runtimeScale differs from the prepared animation root scale')
        if spec.get('runtimeViewport'):
            raise ValueError('Camera plane cannot combine an additional baked viewport transform')
    if any(fx.get('sourceCoordinates') for fx in entry.get('visuals', [])) or profile and (profile.get('resonanceCamera') is not None or profile.get('resonanceMovement') is not None
                    or profile.get('screenPlacement', {}).get('hideNativeAuras', False)
                    or profile.get('screenPlacement', {}).get('targetRegistration')
                    or profile.get('screenPlacement', {}).get('hideNonParticipants', False)):
        native_id = unit.get('id')
        if type(native_id) is not int or native_id <= 0:
            raise ValueError('Native presentation binding requires the selected host vision ID')
        # Bind to the selected imported vision, never a copied bundle ID.
        entry['_hostVisionUnitId'] = native_id
    import ffbe_attack_director as director
    native_id = unit.get('id')
    if type(native_id) is not int or native_id <= 0:
        raise ValueError('Attack director requires the selected host vision ID')
    entry['_hostVisionUnitId'] = native_id
    if entry.get('reconstructionProfile', {}).get('cameraSequence') == 'cast_target':
        # The portable policy keeps source screen/world geometry. Its camera is
        # completed before attaching artwork, exactly as in the accepted trial.
        return entry
    settings = director.resolve(form, source_key, entry)
    entry = director.materialize(entry, settings)
    return entry


def participant_camera(entry):
    """One host-space pan; source background classification is independent."""
    camera = entry.get('reconstructionProfile', {}).get('resonanceCamera')
    if camera is None:
        return None
    if entry.get('_hostResonance') is not True:
        raise ValueError('Camera movement and zoom require a Resonance')
    if not isinstance(camera, dict) or set(camera) != {'mode', 'panFrames', 'restoreFrames'} or camera.get('mode') != 'participants':
        raise ValueError('Resonance camera requires the shared participants mode and pan/restore durations')
    for field in ('panFrames', 'restoreFrames'):
        if type(camera[field]) is not int or not 1 <= camera[field] <= 120:
            raise ValueError('Resonance camera durations must be 1-120 native frames')
    native_id = entry.get('_hostVisionUnitId')
    if type(native_id) is not int or native_id <= 0:
        raise ValueError('Resonance camera requires the selected host vision ID')
    return camera


def ground_movement(entry):
    movement = entry.get('reconstructionProfile', {}).get('resonanceMovement')
    if movement is None:
        return None
    if movement != {'mode': 'ground_approach'}:
        raise ValueError('Resonance movement requires the shared ground_approach mode')
    if entry.get('_hostResonance') is not True:
        raise ValueError('Resonance ground approach requires a Resonance')
    if type(entry.get('_hostVisionUnitId')) is not int or entry['_hostVisionUnitId'] <= 0:
        raise ValueError('Resonance ground approach requires the selected host vision ID')
    profile = entry.get('reconstructionProfile', {})
    if profile.get('casterPlacement') is not None or profile.get('screenPlacement', {}).get('mode') == 'target_stage':
        raise ValueError('Shared ground approach cannot combine bespoke target-stage placement')
    return movement


def actor_root_snapshot(fx):
    """Source rectangles already baked relative to one dispatch-time actor root."""
    source = fx.get('sourceCoordinates')
    if source is None:
        return False
    if not isinstance(source, dict) or source.get('binding') != 'actor_root_snapshot' or source.get('offsetsApplied') is not True:
        raise ValueError('Source coordinates require an actor-root snapshot with applied offsets')
    expected_owner = 'caster' if fx.get('anchor') == 'caster' else 'target' if fx.get('anchor') in ('each_target', 'target_group') else None
    if source.get('owner') != expected_owner or expected_owner is None or fx.get('partName') != 'root':
        raise ValueError('Source actor-root snapshot owner or part differs from its anchor')
    if type(source.get('sampleFrame')) is not int or source['sampleFrame'] != fx.get('frame'):
        raise ValueError('Source actor-root snapshot must sample its declared dispatch frame')
    if not isinstance(source.get('rectangleMode'), str) or not source['rectangleMode'] or type(fx.get('frames')) is not int or fx['frames'] <= 2:
        raise ValueError('Source actor-root snapshot requires rectangle evidence and two hidden lead frames')
    return True


def action_start(plan):
    return next(e['time'] for e in plan['events'] if e['set'].get('Unit_PlayAnimByName_AnimationName')
                in ('attack_A', 'magic_attack', 'LB1'))


def phase_start(plan, phase='action'):
    if phase == 'action':
        return action_start(plan)
    if phase == 'cast':
        return next(e['time'] for e in plan['events']
                    if e['set'].get('Unit_PlayAnimByName_AnimationName') in ('magic_idle', 'command'))
    raise ValueError(f'Unsupported FFBE presentation phase {phase}')


def prepare_audio(unit, skill, entry, tables, plan=None):
    settings = {**skill, 'audio': 'native', 'audio_codec': 'host',
                'audio_bank': entry['audioBank'], 'lb_charge': False}
    # Ordinary moves never pass through the LB opening-sound wrapper.
    source = deepcopy(entry)
    if source.get('cast'):
        if plan is None:
            raise ValueError('Casting audio requires the action timeline')
        delta = phase_start(plan, 'cast') - action_start(plan)
        if delta % 400:
            raise ValueError('Casting audio must start on the source frame grid')
        source['cast']['frame'] += delta // 400
    system_sounds = [s for s in source.get('sounds', []) if s.get('sourceBank') == 'System']
    source['sounds'] = [s for s in source.get('sounds', []) if s.get('sourceBank', 'SE') == 'SE']
    bank, events = ffbe_audio.prepare_command(unit, settings, source, tables)
    if system_sounds:
        path = entry.get('audioBanks', {}).get('System')
        if not path:
            raise ValueError('System effect cues require an explicit prepared System bank')
        extra_bank, extra = ffbe_audio.prepare_command(unit, {**settings, 'audio_bank': path},
                                                      {'sounds': system_sounds}, tables)
        bank, events = ffbe_audio.combine(bank, events, extra_bank, extra)
    return bank, events


def has_target_visuals(entry):
    """Does the action supply its own hit presentation, at any source anchor?

    Caster-relative slashes can cross and strike a target. Their source anchor
    does not license mixing the donor's hit particles into those impacts.
    Casting-only art does not replace an otherwise absent action presentation.
    """
    return bool(entry and any(fx.get('phase', 'action') == 'action'
                              and fx.get('anchor') in ('caster', 'each_target', 'target_group', 'screen')
                              for fx in entry.get('visuals', [])))


def host_target_settings(entry):
    """An explicit host adaptation never changes the source snapshot."""
    target = (entry or {}).get('reconstructionProfile', {}).get('hostTargetType')
    if target is None:
        return {}
    if target not in ('Single', 'Group'):
        raise ValueError('Presentation hostTargetType must be Single or Group')
    return {'TargetType': target, 'targetRage': 'None'}


def validate_screen_placement(placement):
    if not isinstance(placement, dict) or placement.get('mode') not in ('frozen_caster_plane', 'target_stage', 'camera_plane'):
        raise ValueError('Screen effects require an explicit supported placement profile')
    if placement.get('backdrop') not in (None, 'native_subspace'):
        raise ValueError('Unsupported screen backdrop')
    if placement.get('backdropTiming', 'opening') not in ('opening', 'action'):
        raise ValueError('Unsupported screen backdrop timing')
    offset = placement.get('sourceOffset')
    if not isinstance(offset, list) or len(offset) != 2 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in offset):
        raise ValueError('Screen effect source offset must contain two finite coordinates')
    if placement['mode'] == 'camera_plane':
        allowed = {'mode', 'sourceOffset', 'referenceStage', 'runtimeScale', 'overscan', 'cameraDepth', 'backdrop', 'fit', 'backdropTiming'}
        if placement.get('fit', 'stretch') not in ('stretch', 'cover'):
            raise ValueError('Camera plane fit must be stretch or cover')
        if set(placement) - allowed or offset != [0, 0]:
            raise ValueError('Camera plane requires centered source coordinates and only camera-plane settings')
        for key, low, high in (('referenceStage', 1, 8192), ('overscan', 1, 2)):
            values = placement.get(key)
            if not isinstance(values, list) or len(values) != 2 or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                    or not low <= v <= high for v in values):
                raise ValueError('Camera plane '+key+' requires two finite values in its supported range')
        scale = placement.get('runtimeScale')
        if isinstance(scale, bool) or not isinstance(scale, (int, float)) or not math.isfinite(scale) or not .01 <= scale <= 100:
            raise ValueError('Camera plane runtimeScale must match the finite positive animation scale')
        depth = placement.get('cameraDepth')
        if not isinstance(depth, dict) or set(depth) != {'front', 'rearMargin'} or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                or not 1 <= v <= 10000 for v in depth.values()):
            raise ValueError('Camera plane cameraDepth requires finite positive front and rearMargin')
    if placement['mode'] == 'target_stage':
        if placement.get('backdrop') != 'native_subspace':
            raise ValueError('Target stage requires the native_subspace backdrop')
        if type(placement.get('hideNativeAuras', False)) is not bool:
            raise ValueError('Target stage hideNativeAuras must be boolean')
        for field in ('hideEnemies', 'hideNonParticipants'):
            if type(placement.get(field, False)) is not bool:
                raise ValueError('Target stage '+field+' must be boolean')
        if placement.get('hideEnemies') and placement.get('hideNonParticipants'):
            raise ValueError('Participant isolation must keep the selected enemy visible')
        if 'layerDepth' in placement:
            depths = placement['layerDepth']
            if not isinstance(depths, dict):
                raise ValueError('Target stage layerDepth requires back and front depths')
            for layer, sign in (('back', 1), ('front', -1)):
                value = depths.get(layer)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or sign * value <= 0:
                    raise ValueError('Target stage layerDepth requires finite back > 0 and front < 0')
        camera = placement.get('camera')
        if not isinstance(camera, dict):
            raise ValueError('Target stage requires an explicit camera profile')
        center = camera.get('sourceCenter')
        if not isinstance(center, list) or len(center) != 2 or any(
                isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in center):
            raise ValueError('Camera source center must contain two finite coordinates')
        for field in ('unitsPerPixel', 'runtimeScale', 'focalLength'):
            value = camera.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('Camera '+field+' must be finite and positive')
        registration = placement.get('targetRegistration')
        if registration is not None:
            if not isinstance(registration, dict) or registration.get('partName') != 'NULL_Center':
                raise ValueError('Target registration requires the native body center')
            impact = registration.get('sourceImpact')
            if not isinstance(impact, list) or len(impact) != 2 or any(
                    isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in impact):
                raise ValueError('Target source impact must contain two finite coordinates')
            if any(not math.isfinite(v * camera['unitsPerPixel'] * camera['runtimeScale']) for v in impact):
                raise ValueError('Target source impact conversion must be finite')
        factor = camera['unitsPerPixel'] * camera['runtimeScale']
        if not math.isfinite(factor) or any(not math.isfinite(v * factor) for v in center):
            raise ValueError('Camera source center conversion must be finite')
        camera_pan_keys(camera)
        if camera.get('pan') and not registration:
            raise ValueError('A native camera pan requires registered target staging')


def camera_pan_keys(camera):
    """Validate opt-in host camera keys without changing the source action clock."""
    pans = camera.get('pan', [])
    if not isinstance(pans, list):
        raise ValueError('Camera pan must be a list of source-frame keys')
    prior_end = 0
    for key in pans:
        if not isinstance(key, dict) or set(key) - {'frame', 'durationFrames', 'sourceCenter', 'focalLength', 'easing'}:
            raise ValueError('Camera pan key contains unsupported fields')
        frame, duration = key.get('frame'), key.get('durationFrames')
        if type(frame) is not int or frame <= 0 or type(duration) is not int or not 1 <= duration <= 3600 or frame < prior_end:
            raise ValueError('Camera pans need positive, non-overlapping source-frame intervals')
        if duration % 2:
            raise ValueError('Camera pan duration must use even source frames: native camera interpolation runs at 30 fps')
        center = key.get('sourceCenter')
        if not isinstance(center, list) or len(center) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in center):
            raise ValueError('Camera pan center must contain two finite coordinates')
        factor = camera['unitsPerPixel'] * camera['runtimeScale']
        if any(not math.isfinite(v * factor) for v in center):
            raise ValueError('Camera pan center conversion must be finite')
        if key.get('easing', 'EaseInOut') not in ('Linear', 'EaseInOut', 'EaseIn', 'EaseOut'):
            raise ValueError('Unsupported native camera pan easing')
        if 'focalLength' in key and (type(key['focalLength']) not in (int, float) or not math.isfinite(key['focalLength']) or key['focalLength'] <= 0):
            raise ValueError('Camera pan focalLength must be finite and positive')
        prior_end = frame + duration
    return pans


def motion_type(entry):
    if not entry:
        return None
    value = entry.get('motionType')
    if value is None:
        root = next((p for p in entry.get('provenance', [])
                     if p.get('source') == entry.get('sourceKey')), {})
        value = root.get('catalog', {}).get('motion')
    return int(value) if value is not None else None


def command_motion(skill, profile, entry):
    # FFBE BattleUnit::changeActionAnime maps getMotionType()==2 to CGS5,
    # magic_atk. Physical damage can use this casting motion (Sora is one case).
    # Studio persisted DamageType-derived defaults in `motion`; source playback
    # must supersede those. A dedicated presentation override stays explicit.
    if skill.get('presentation_motion'):
        return skill['presentation_motion']
    if motion_type(entry) == 2:
        return 'magic_attack'
    return skill.get('motion') or ('attack_A' if profile['set']['DamageType'] == 'Physic' else 'magic_attack')


def apply(plan, entry, sounds, skill_id, *, add_sounds=True):
    """Keep mechanics on their existing clock; extend only the visual tail."""
    if entry.get('reconstructionProfile', {}).get('cameraSequence') == 'cast_target':
        import ffbe_attack_director as director
        camera_entry=deepcopy(entry)
        camera_entry['visuals']=[]
        settings=director.resolve(entry['reconstructionProfile']['form'],entry['sourceKey'],{})
        settings['hideLbNonParticipants']=False
        camera_entry['reconstructionProfile']={'attackDirector':settings}
        camera_entry['_hostTargetCamera']=True
        base=apply(plan,camera_entry,sounds,skill_id,add_sounds=add_sounds)
        effect_entry=deepcopy(entry)
        for field in ('cameraSequence','attackDirector','resonanceCamera','resonanceMovement'):
            effect_entry['reconstructionProfile'].pop(field,None)
        return apply(base,effect_entry,[],skill_id,add_sounds=False)
    plan = deepcopy(plan)
    if entry.get('reconstructionProfile', {}).get('allTargetEffects'):
        entry = deepcopy(entry)
        visuals = []
        for fx in entry['visuals']:
            if fx['anchor'] == 'each_target' and entry.get('targetType') != 'Single':
                if not actor_root_snapshot(fx):
                    raise ValueError('Per-target effects need source actor-root coordinates')
                visuals.extend({**deepcopy(fx), '_targetIndex': i} for i in range(16))
            else: visuals.append(fx)
        entry['visuals'] = visuals
    start = action_start(plan)
    host_profile = entry.get('reconstructionProfile', {})
    vision_on_top = host_profile.get('visionOnTop', False)
    target_height = host_profile.get('targetHeightFraction')
    if target_height is not None and (type(target_height) not in (int, float)
            or not math.isfinite(target_height) or not 0 <= target_height <= 1):
        raise ValueError('targetHeightFraction must be a finite body-height fraction from zero to one')
    if vision_on_top and (type(entry.get('_hostVisionUnitId')) is not int or entry['_hostVisionUnitId'] <= 0):
        raise ValueError('Vision foreground order requires the selected host vision ID')
    placement = entry.get('reconstructionProfile', {}).get('screenPlacement', {})
    shared_camera = participant_camera(entry)
    shared_ground = ground_movement(entry)
    backdrop = placement.get('backdrop')
    target_stage = placement.get('mode') == 'target_stage'
    if shared_camera is not None and (target_stage or placement.get('camera')):
        raise ValueError('Shared participant camera cannot combine bespoke stage camera settings')
    if entry.get('_hostResonance') is not True and (
            target_stage or placement.get('camera') or any(
                fx.get('placement', {}).get('mode') == 'target_stage'
                or fx.get('placement', {}).get('camera') for fx in entry.get('visuals', []))):
        raise ValueError('Camera movement and zoom require a Resonance; ordinary abilities must use screen placement without a camera override')
    if backdrop is not None or target_stage:
        validate_screen_placement(placement)
        if not any(fx['anchor'] == 'screen' for fx in entry['visuals']):
            raise ValueError('Native subspace requires screen effects')
        if any(e['set']['EventType'] in ('BGChange', 'BGRevert') for e in plan['events']):
            raise ValueError('Native subspace cannot replace an existing background sequence')
    if backdrop == 'native_subspace':
        starts = [start + fx['frame'] * 400 - 800 for fx in entry['visuals']
                  if fx['anchor'] == 'screen' and fx.get('phase', 'action') == 'action']
        if starts:
            # Reserve native transition setup before the first action screen
            # layer. Move the whole command together, including preparation,
            # hit and audio events; never retime source channels separately.
            extra = max(0, math.ceil((8003 - min(starts)) / 400) * 400)
            if extra:
                for event in plan['events']: event['time'] += extra
                plan['duration'] += extra
                start += extra
    caster_placement = entry.get('reconstructionProfile', {}).get('casterPlacement')
    approach = None
    if target_stage and caster_placement != 'approach_target':
        raise ValueError('Target stage requires approach_target caster placement')
    if caster_placement is not None:
        if caster_placement != 'approach_target':
            raise ValueError('Unsupported caster placement')
        caster_visuals = [fx for fx in entry['visuals'] if fx['anchor'] == 'caster']
        moves = [e for e in plan['events'] if e['set']['EventType'] == 'UnitMoveToTarget'
                 and e['set'].get('Unit_MoveToTarget_IsVisionUnit') is True]
        if not caster_visuals or len(moves) != 1:
            raise ValueError('Caster target placement requires one vision approach and caster effects')
        move = moves[0]
        approach = move['set']
        frames = approach.get('Unit_MoveToTarget_Frame')
        first_caster = min(phase_start(plan, fx.get('phase', 'action')) + fx['frame'] * 400 - 800
                           for fx in caster_visuals)
        if type(frames) is not int or frames < 0 or move['time'] + frames * 400 > first_caster:
            raise ValueError('Vision approach must finish before caster effects spawn')
        offset = approach.get('Unit_MoveToTarget_AddLocation', {})
        if not isinstance(offset, dict) or any(isinstance(offset.get(k), bool) or
                not isinstance(offset.get(k), (int, float)) or not math.isfinite(offset[k]) for k in 'xyz'):
            raise ValueError('Vision approach requires a finite target offset')
        if not isinstance(approach.get('Unit_MoveToTarget_PartName'), str):
            raise ValueError('Vision approach requires a target part')
        # The vision and the effect must use the same target point. Native
        # combatant-clearance offsets apply to the unit move only, so suppress
        # that extra displacement for this explicit attachment mode.
        approach['Unit_MoveToTarget_IsDisableOffset'] = True
        registration = placement.get('targetRegistration') if target_stage else None
        if registration:
            # Register the whole authored stage to the selected body's native
            # socket, keeping the vision and every source effect together.
            factor = placement['camera']['unitsPerPixel'] * placement['camera']['runtimeScale']
            approach['Unit_MoveToTarget_PartName'] = registration['partName']
            approach['Unit_MoveToTarget_AddLocation'] = {
                'x': 0., 'y': -registration['sourceImpact'][0] * factor,
                'z': -registration['sourceImpact'][1] * factor}
    if entry.get('reconstructionProfile', {}).get('preserveSourceColor'):
        # A reference reconstruction supplies its own colored screen art.
        # The generic element-based field grade would recolor every source
        # texture (including blue light in a Fire LB) after compositing.
        plan['events'] = [e for e in plan['events'] if
                          e['set'].get('EventType') != 'PostSetColorGradingGlobalParameter']
    events = plan['events']
    original_events = list(events)
    tail = plan['duration']
    visual_end = 0
    first_spawn = None
    first_action_screen = None

    def at(t, kind, **fields):
        events.append({'time': t, 'set': {'EventType': kind, **fields}})

    if add_sounds:
        for sound in sounds:
            t = start + sound['frame'] * 400
            if t < 0: raise ValueError('Presentation needs additional pre-roll')
            at(t, 'SoundPlayHitSound', Sound_PlayHitSound_CueSheetName=sound['bank'],
               Sound_PlayHitSound_playLabel=sound['cueName'])
            tail = max(tail, t + round(sound['durationMs'] * 24) + 2400)
    for i, fx in enumerate(entry['visuals']):
        screen = fx['anchor'] == 'screen'
        root_snapshot = actor_root_snapshot(fx)
        if root_snapshot and target_stage:
            raise ValueError('Source actor-root snapshots cannot combine bespoke target-stage placement')
        caster_target = fx['anchor'] == 'caster' and approach is not None and not root_snapshot
        if screen:
            validate_screen_placement(fx.get('placement'))
            if (fx['placement']['mode'] == 'camera_plane' and placement
                    and {k: v for k, v in fx['placement'].items() if k not in ('backdrop','backdropTiming')} !=
                        {k: v for k, v in placement.items() if k not in ('backdrop','backdropTiming')}):
                raise ValueError('Camera plane visual must match its reconstruction profile')
            if (fx['placement']['mode'] == 'target_stage') != target_stage:
                raise ValueError('Screen effect placement must match the target stage profile')
            if target_stage and any(fx['placement'].get(k) != placement.get(k)
                                    for k in ('sourceOffset', 'backdrop', 'camera', 'layerDepth', 'hideEnemies', 'hideNonParticipants', 'hideNativeAuras', 'targetRegistration')):
                raise ValueError('Screen effect placement differs from the target stage profile')
        aid = f'FFBE_{skill_id}_{i}'
        t = phase_start(plan, fx.get('phase', 'action')) + fx['frame'] * 400
        if t < 0: raise ValueError('Presentation needs additional pre-roll')
        # Two hidden lead frames let placement and finite playback bind before
        # visible particles. All internal spawn times remain source-exact.
        # Source-root snapshots must sample the actor on the actual group
        # dispatch, including groups with delayed child particles. They need no
        # placement pre-roll: skip the exporter's two blank lead frames.
        spawn = t if root_snapshot else t - 800
        if spawn < 0: raise ValueError('Effect setup needs two pre-roll frames')
        first_spawn = spawn if first_spawn is None else min(first_spawn, spawn)
        if screen and fx.get('phase', 'action') == 'action':
            first_action_screen = spawn if first_action_screen is None else min(first_action_screen, spawn)
        depth = fx.get('_directorDepth', -8.0 if fx['layer'] == 1 else 8.0)
        if target_stage:
            depth = placement.get('layerDepth', {'back': 8.0, 'front': -8.0})[
                'front' if fx['layer'] == 1 else 'back']
        offset = {'x': depth, 'y': 0., 'z': 0.}
        if root_snapshot and (type(entry.get('_hostVisionUnitId')) is not int or entry['_hostVisionUnitId'] <= 0):
            raise ValueError('Source actor-root snapshot requires the selected host vision ID')
        at(spawn, 'SsActorSpawnSpriteStudioActor', SsActor_SsData={
            'spriteStudioID': aid, 'ssPlayerAsset': {'path': fx['asset'], 'class': 'Ss6Project'},
            'unitAssetID': -1, 'bCopyAnimPlayer': False, 'bCopyAllSide': False,
            'IsSynchronizeAnimation': False, 'AnimPackName': fx['name'], 'AnimationName': 'effect',
            'PartName': fx.get('partName', 'root' if screen else 'NULL_Center'),
            'bSpawnRelativeTarget': fx['anchor'] in ('each_target', 'target_group'),
            'addLocation': offset, 'startRotate': {'x': 0., 'y': 0., 'z': 0.},
            'Rotate': {'x': 0., 'y': 0., 'z': 0.}, 'rotateFrame': 0,
            'bDisableFollowing': screen or caster_target or root_snapshot, 'bHiddenInSceneCapture': False, 'bDisableSummons': False})
        if root_snapshot or (vision_on_top and not screen):
            at(spawn + 1, 'NativeActorRootSnapshot', NativeActorRootSnapshot_Id=aid,
               NativeActorRootSnapshot_UnitId=entry['_hostVisionUnitId'],
               NativeActorRootSnapshot_IsTarget=fx['anchor'] != 'caster', NativeActorRootSnapshot_Depth=depth,
               **({'NativeActorRootSnapshot_SortLayer': -1 if fx['layer'] == 1 else -2} if vision_on_top else {}),
               **({'NativeActorRootSnapshot_PreservePlacement': True} if not root_snapshot else {}),
               **({'NativeActorRootSnapshot_HeightFraction': target_height}
                  if target_height is not None and fx['anchor'] in ('each_target', 'target_group') and fx.get('phase', 'action') == 'action' else {}),
               **({'NativeActorRootSnapshot_TargetIndex': fx['_targetIndex']} if '_targetIndex' in fx else {}))
        at(spawn + (2 if root_snapshot or (vision_on_top and not screen) else 1), 'SsActorPlayAnimToSsID', SsActor_PlayAnim_ID=aid,
           SsActor_PlayAnim_AnimationName='effect', SsActor_PlayAnim_StartFrame=2 if root_snapshot else 0,
           SsActor_PlayAnim_LoopCount=1, SsActor_PlayAnim_PlayRate=1.)
        # Relative-target spawn attaches directly to the first selected target;
        # avoid the old delayed move-to-target behavior for each-target layers.
        if caster_target or (screen and target_stage):
            at(spawn + 2, 'SsActorMoveToTargetToSsID', SsActor_MoveToTarget_ID=aid,
               SsActor_MoveToTarget_targetPointID=-1, SsActor_MoveToTarget_frame=0,
               SsActor_MoveToTarget_partName=approach['Unit_MoveToTarget_PartName'],
               SsActor_MoveToTarget_plusOffset={k: approach['Unit_MoveToTarget_AddLocation'][k] + offset[k]
                                                for k in 'xyz'},
               SsActor_MoveToTarget_RelativeActionUnit=False, SsActor_MoveToTarget_Height=0.,
               SsActor_MoveToTarget_Length=0., SsActor_MoveToTarget_easingType='Linear',
               SsActor_MoveToTarget_EasingBlendExp=1., SsActor_MoveToTarget_EasingSteps=1)
        if fx['anchor'] == 'target_group' and not root_snapshot:
            at(spawn + 2, 'SsActorMoveToTargetToSsID', SsActor_MoveToTarget_ID=aid,
               SsActor_MoveToTarget_targetPointID=-1, SsActor_MoveToTarget_frame=0,
               SsActor_MoveToTarget_partName='NULL_Center', SsActor_MoveToTarget_plusOffset=offset,
               SsActor_MoveToTarget_RelativeActionUnit=False, SsActor_MoveToTarget_Height=0.,
               SsActor_MoveToTarget_Length=0., SsActor_MoveToTarget_easingType='Linear',
               SsActor_MoveToTarget_EasingBlendExp=1., SsActor_MoveToTarget_EasingSteps=1)
        end = spawn + (fx['frames'] - (2 if root_snapshot else 0)) * 400
        if screen and fx['placement']['mode'] == 'camera_plane':
            camera_plane = fx['placement']
            width, height = camera_plane['referenceStage']
            overscan_x, overscan_y = camera_plane['overscan']
            # Reuse one native function per screen layer. The camera component
            # follows every native transform tick; bounded 30 fps keys refresh
            # zoom/aspect and the rear plane's actual combatant support depth.
            for tick in range(spawn + 2, end, 800):
                at(tick, 'NativeScreenPlane', NativeScreenPlane_Id=aid,
                   NativeScreenPlane_SourceWidth=width, NativeScreenPlane_SourceHeight=height,
                   NativeScreenPlane_RuntimeScale=camera_plane['runtimeScale'],
                   NativeScreenPlane_OverscanX=overscan_x, NativeScreenPlane_OverscanY=overscan_y,
                   NativeScreenPlane_FrontDepth=camera_plane['cameraDepth']['front'],
                   NativeScreenPlane_RearMargin=camera_plane['cameraDepth']['rearMargin'],
                   NativeScreenPlane_IsRear=fx['layer'] != 1,
                   **({'NativeScreenPlane_VisionUnitId': entry['_hostVisionUnitId']} if vision_on_top else {}),
                   **({'NativeScreenPlane_ViewportRise': fx['viewportRise']} if 'viewportRise' in fx else {}),
                   **({'NativeScreenPlane_Cover': True} if camera_plane.get('fit') == 'cover' else {}))
        at(end, 'SsActorDestroyToSsID', SsActor_Destroy_ID=aid)
        visual_end = max(visual_end, end)
        tail = max(tail, end + 2400)
    cleanup = min((e['time'] for e in original_events if
                   e['set'].get('Unit_PlayAnimByName_AnimationName') in ('step_back', 'idle')), default=tail)
    # LB cleanup resets the camera/color one or two ticks before its idle key.
    # Move that entire cleanup group when imported art outlasts the actor motion.
    cleanup = min(cleanup, min((e['time'] for e in original_events if e['time'] > start
                  and e['set']['EventType'] in ('CameraSetDefault', 'PostSetDefaultColorGrading')), default=cleanup))
    if visual_end >= cleanup:
        delay = visual_end + 400 - cleanup
        for event in original_events:
            if event['time'] >= cleanup: event['time'] += delay
        tail = max(tail, plan['duration'] + delay)
    if target_stage:
        # These native controls frame a single world-space source stage. The
        # camera has no PartName field; SS placement retains the approach part.
        # Optics and category visibility are explicit, opt-in host settings.
        setup = first_spawn - 3
        if setup <= 8002 or move['time'] + frames * 400 > setup:
            raise ValueError('Vision approach and native backdrop must finish before target stage camera setup')
        camera = placement['camera']
        factor = camera['unitsPerPixel'] * camera['runtimeScale']
        center = dict(approach['Unit_MoveToTarget_AddLocation'])
        center['y'] += camera['sourceCenter'][0] * factor
        center['z'] += camera['sourceCenter'][1] * factor
        if not all(math.isfinite(v) for v in center.values()):
            raise ValueError('Target stage camera offset must be finite')
        if placement.get('targetRegistration'):
            native_id = entry.get('_hostVisionUnitId')
            if type(native_id) is not int or native_id <= 0:
                raise ValueError('Target registration requires the selected host vision ID')
            # Follow the completed shared stage once, so target height does not
            # move the composition within the approved source camera framing.
            at(setup, 'NativeStageCamera', NativeStageCamera_UnitId=native_id,
               NativeStageCamera_AddLocation={'x': 0.,
                   'y': camera['sourceCenter'][0] * factor,
                   'z': camera['sourceCenter'][1] * factor})
        else:
            at(setup, 'CameraSetLookAtTarget', Camera_SetLookAtTarget_Id=-1,
               Camera_SetLookAtTarget_AddLocation=center, Camera_SetLookAtTarget_Frame=0,
               Camera_SetLookAtTarget_EasingType='Linear', Camera_SetLookAtTarget_EasingBlendExp=1.,
               Camera_SetLookAtTarget_EasingSteps=1)
        at(setup + 1, 'CameraSetZoomInOut', Camera_SetZoomInOut_Value=camera['focalLength'],
           Camera_SetZoomInOut_RelativeValue=False, Camera_SetZoomInOut_Frame=0,
           Camera_SetZoomInOut_EasingType='Linear', Camera_SetZoomInOut_EasingBlendExp=1.,
           Camera_SetZoomInOut_EasingSteps=1)
        for pan in camera_pan_keys(camera):
            tick = start + pan['frame'] * 400
            if tick + pan['durationFrames'] * 400 >= visual_end:
                raise ValueError('Camera pan must finish before source effect cleanup')
            at(tick, 'NativeStageCamera', NativeStageCamera_UnitId=entry['_hostVisionUnitId'],
               NativeStageCamera_AddLocation={'x': 0., 'y': pan['sourceCenter'][0] * factor,
                                              'z': pan['sourceCenter'][1] * factor},
               # FFBE motion and keys use 60 fps; FFR camera Frame uses 30 fps.
               NativeStageCamera_Frame=pan['durationFrames'] // 2, NativeStageCamera_EasingType=pan.get('easing', 'EaseInOut'))
            if 'focalLength' in pan:
                at(tick + 1, 'CameraSetZoomInOut', Camera_SetZoomInOut_Value=pan['focalLength'],
                   Camera_SetZoomInOut_RelativeValue=False, Camera_SetZoomInOut_Frame=pan['durationFrames'] // 2,
                   Camera_SetZoomInOut_EasingType=pan.get('easing', 'EaseInOut'),
                   Camera_SetZoomInOut_EasingBlendExp=2., Camera_SetZoomInOut_EasingSteps=1)
        # Keep the entire friendly side visible: FriendUnits also gates the
        # acting vision. Only the explicitly requested enemy side is hidden.
        if placement.get('hideEnemies', False):
            categories = ('ActionUnit', 'TargetUnit', 'FriendUnits', 'EnemyUnits', 'VisionUnits', 'BeastUnits')
            at(setup + 2, 'UnitSetVisibility', **{'Unit_SetVisibility_Is'+k:
               k not in ('TargetUnit', 'EnemyUnits') for k in categories})
            at(visual_end + 400, 'UnitSetVisibility', **{'Unit_SetVisibility_Is'+k: True for k in categories})
        # Resonance's camera reset can precede the idle key by one tick. Keep
        # that cleanup after a longer effect tail without moving source hits.
        resets = [e for e in original_events if e['set']['EventType'] == 'CameraSetDefault' and e['time'] > start]
        for event in resets:
            event['time'] = max(event['time'], visual_end + 401)
            # Match the initial native reset constant, so the finite donor
            # shell can reuse its function while restoring the stage instantly.
            event['set'] = {'EventType': 'CameraSetDefault', 'Camera_SetDefault_Frame': 0,
                            'Camera_SetDefault_IsRotation': True, 'Camera_SetDefault_IsLocation': True,
                            'Camera_SetDefault_IsZoomInOut': True}
            tail = max(tail, event['time'] + 2400)
        if not resets:
            at(visual_end + 401, 'CameraSetDefault', Camera_SetDefault_Frame=0,
               Camera_SetDefault_IsRotation=True, Camera_SetDefault_IsLocation=True,
               Camera_SetDefault_IsZoomInOut=True)
        tail = max(tail, visual_end + 2801)
    if backdrop == 'native_subspace':
        # Native masters 412601/414091/414101 initialize the transition at 0,
        # start it at 3200, and load this shared subspace at 4000. The ground
        # control is enabled at 8000 in 414091. A black, unlit empty backdrop
        # lets the source-authored screen art supply its own environment.
        if first_action_screen is None or first_action_screen <= 8002:
            raise ValueError('Native subspace needs setup time before the first effect')
        # Keep cast/camera preparation in the current field when the imported
        # background belongs to the action. Preserve the native setup spacing.
        backdrop_start = ((first_action_screen - 8003) // 400 * 400
                          if placement.get('backdropTiming') == 'action' else 0)
        at(backdrop_start, 'OtherChangeSubSpaceInitialize')
        at(backdrop_start + 3200, 'OtherChangeSubSpace', Other_ChangeSubSpace_Scale={'X': 2.5, 'Y': 2.5})
        at(backdrop_start + 4000, 'BGChange', BG_Change_BackgroundLevel=NATIVE_SUBSPACE,
           BG_Change_IsChangeSubSpace=True)
        at(backdrop_start + 8000, 'OtherChangeSubSpaceGround', Other_ChangeSubSpaceGround_IsVisibility=False,
           Other_ChangeSubSpaceGround_IsParticleVisibility=False,
           Other_ChangeSubSpaceGround_IsFogVisibility=False)
        at(backdrop_start + 8001, 'OtherChangeSubSpaceColor',
           Other_ChangeSubSpaceColor_Color={'R': 0., 'G': 0., 'B': 0., 'A': 1.},
           Other_ChangeSubSpaceColor_Frame=0)
        at(backdrop_start + 8002, 'OtherChangeSubSpaceEmissive', Other_ChangeSubSpaceEmissive_Emissive=0.,
           Other_ChangeSubSpaceEmissive_frame=0)
        # Revert the stage only after every layer is destroyed. BGRevert is
        # the native cleanup operation, rather than re-enabling arbitrary
        # visibility flags on the previously active battlefield.
        restore = visual_end + 400
        at(restore, 'BGRevert', BG_Change_IsChangeSubSpace=True)
        tail = max(tail, restore + 2400)
    if placement.get('hideNativeAuras', False):
        if not target_stage or first_spawn is None:
            raise ValueError('Native aura suppression requires an explicit target stage')
        native_id = entry.get('_hostVisionUnitId')
        if type(native_id) is not int or native_id <= 0:
            raise ValueError('Native aura suppression requires the selected host vision ID')
        # Restore after every effect and the vision's native return movement.
        # Address the selected vision directly: the stock debug aura helper's
        # combatant list excludes summoned visions.
        returns = [e['time'] + e['set'].get('Unit_MoveToDefaultLocation_Frame', 0) * 400
                   for e in events if e['set']['EventType'] == 'UnitMoveToDefaultLocation']
        restore = max([visual_end + 400, *returns]) + 1
        at(first_spawn - 1, 'NativeAuraVisibility', NativeAura_IsVisible=False, NativeAura_UnitId=native_id)
        at(restore, 'NativeAuraVisibility', NativeAura_IsVisible=True, NativeAura_UnitId=native_id)
        tail = max(tail, restore + 2400)
    if placement.get('hideNonParticipants', False):
        native_id = entry.get('_hostVisionUnitId')
        if not target_stage or type(native_id) is not int or native_id <= 0:
            raise ValueError('Participant isolation requires a target stage and selected host vision')
        returns = [e['time'] + e['set'].get('Unit_MoveToDefaultLocation_Frame', 0) * 400
                   for e in events if e['set']['EventType'] == 'UnitMoveToDefaultLocation']
        restore = max([visual_end + 400, *returns]) + 2
        at(first_spawn - 1, 'NativeStageVisibility', NativeStageVisibility_UnitId=native_id,
           NativeStageVisibility_Restore=False)
        at(restore, 'NativeStageVisibility', NativeStageVisibility_UnitId=native_id,
           NativeStageVisibility_Restore=True)
        tail = max(tail, restore + 2400)
    if shared_camera is not None:
        # Resonance isolation is independent of source background replacement.
        # Resolve the vision and the action's entire selected target list in the
        # native helper; its paired cleanup restores only state it changed.
        cast_and_move = [e['time'] for e in original_events if
            e['set']['EventType'] == 'UnitMoveToTarget'
            or e['set'].get('Unit_PlayAnimByName_AnimationName') in ('command', 'magic_idle', 'LB1', 'attack_A', 'magic_attack')]
        isolate_at = max(0, min(cast_and_move, default=start) - 2)
        returns = [e['time'] + e['set'].get('Unit_MoveToDefaultLocation_Frame', 0) * 400
                   for e in events if e['set']['EventType'] == 'UnitMoveToDefaultLocation']
        restore_visibility = max([visual_end + 400, *returns, start + 400]) + 2
        at(isolate_at, 'NativeResonanceVisibility', NativeResonanceVisibility_UnitId=entry['_hostVisionUnitId'],
           NativeResonanceVisibility_Restore=False)
        if start - 3 > isolate_at:
            at(start - 3, 'NativeResonanceVisibility', NativeResonanceVisibility_UnitId=entry['_hostVisionUnitId'],
               NativeResonanceVisibility_Restore=False)
        at(restore_visibility, 'NativeResonanceVisibility', NativeResonanceVisibility_UnitId=entry['_hostVisionUnitId'],
           NativeResonanceVisibility_Restore=True)
        tail = max(tail, restore_visibility + 2400)
        # Follow the actual moving vision with non-overlapping short native
        # blends, then show the selected target set before the first impact.
        # Every sample uses current actor bounds; no source pixels become a
        # hardcoded world-space camera position.
        camera_start = isolate_at + 1
        first_hit = min((e['time'] for e in original_events if e['set']['EventType'] == 'OtherReaction'),
                        default=start + 30 * 400)
        target_start = max(start, first_hit - shared_camera['panFrames'] * 800)
        tick = camera_start
        while target_start - tick >= 800:
            frames = min(4, (target_start-tick)//800)
            at(tick, 'NativeParticipantCamera', NativeParticipantCamera_UnitId=entry['_hostVisionUnitId'],
               NativeParticipantCamera_Frame=frames, NativeParticipantCamera_Shot='caster',
               NativeParticipantCamera_CenterX=.55, NativeParticipantCamera_CenterY=.52,
               NativeParticipantCamera_HeightFraction=.52, NativeParticipantCamera_ZoomFactor=1.25)
            tick += frames * 800
        at(target_start, 'NativeParticipantCamera', NativeParticipantCamera_UnitId=entry['_hostVisionUnitId'],
           NativeParticipantCamera_Frame=shared_camera['panFrames'], NativeParticipantCamera_Shot='targets',
           NativeParticipantCamera_CenterX=.35, NativeParticipantCamera_CenterY=.56,
           NativeParticipantCamera_HeightFraction=.32, NativeParticipantCamera_ZoomFactor=1.05)
        camera_end = target_start + shared_camera['panFrames'] * 800
        # Stock schedules already have a reset after their action. Move it after
        # the longest prepared visual tail and retain a complete native blend.
        resets = [e for e in original_events if e['set']['EventType'] == 'CameraSetDefault' and e['time'] > start]
        restore = max([visual_end + 1, camera_end + 1, *(e['time'] for e in resets)], default=tail)
        if not resets:
            # A caller without a stock cleanup still gets a finite restore after
            # its declared action lifetime, not during an unobserved action.
            restore = max(restore, plan['duration'])
        events[:] = [e for e in events if e not in resets]
        at(restore, 'CameraSetDefault', Camera_SetDefault_Frame=shared_camera['restoreFrames'],
           Camera_SetDefault_IsRotation=True, Camera_SetDefault_IsLocation=True,
           Camera_SetDefault_IsZoomInOut=True)
        tail = max(tail, restore + shared_camera['restoreFrames'] * 800 + 1)
    if shared_ground is not None:
        # Do not invent approach motion for stationary source LBs. When an
        # approach exists, retain its time, target part and translated XY;
        # runtime socket compensation replaces only the vertical endpoint.
        moves = [e for e in events if e['set']['EventType'] == 'UnitMoveToTarget'
                 and e['set'].get('Unit_MoveToTarget_IsVisionUnit') is True]
        if len(moves) > 1:
            raise ValueError('Shared ground approach needs at most one source vision approach')
        for move in moves:
            fields = move['set']
            offset = fields.get('Unit_MoveToTarget_AddLocation', {})
            frames = fields.get('Unit_MoveToTarget_Frame')
            part = fields.get('Unit_MoveToTarget_PartName')
            if type(frames) is not int or not 1 <= frames <= 3600 or not isinstance(part, str) or not part:
                raise ValueError('Shared ground approach requires a finite native duration and target part')
            if not isinstance(offset, dict) or any(type(offset.get(k, 0)) not in (int, float)
                    or not math.isfinite(offset.get(k, 0)) for k in 'xyz'):
                raise ValueError('Shared ground approach requires a finite translated offset')
            move['set'] = {'EventType': 'NativeGroundApproach', 'NativeGroundApproach_UnitId': entry['_hostVisionUnitId'],
                'NativeGroundApproach_Frame': frames, 'NativeGroundApproach_PartName': part,
                'NativeGroundApproach_Offset': {'x': offset.get('x', 0), 'y': offset.get('y', 0), 'z': 0.}}
    plan['duration'] = tail
    plan['events'] = sorted(events, key=lambda e: e['time'])
    director_settings = entry.get('reconstructionProfile', {}).get('attackDirector')
    if director_settings is not None:
        import ffbe_attack_director as director
        cast_sound = next((s for s in sounds if s.get('role') in ('casting', 'lb_opening')), None)
        if cast_sound:
            entry = {**entry, '_castSoundTick': action_start(plan) + round(cast_sound['frame'] * 400)}
        plan = director.direct(plan, entry, director.validate(director_settings), visual_end)
        if entry.get('_hostTargetCamera') and director_settings.get('camera', True):
            import ffbe_target_camera
            plan = ffbe_target_camera.direct(plan, entry['_hostVisionUnitId'])
    return plan


def jobs(entry, donor):
    result = []
    for fx in entry['visuals']:
        folder = ROOT / fx['spec']
        for filename, digest in fx['checksums'].items():
            if hashlib.sha256((folder / filename).read_bytes()).hexdigest() != digest:
                raise ValueError(f'Prepared FFBE effect changed: {fx["name"]}/{filename}')
        result.append((fx['name'], fx['spec'], donor))
    return result
