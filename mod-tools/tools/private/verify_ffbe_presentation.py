"""Read cooked SFX/VFX events and ensure their referenced assets are packaged."""
from collections import Counter
import argparse
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import ffbe_presentation as presentation
import ffbe_resonance as sequence
import ffbe_audio
import ffbe_lb
import ffrenv
from ability_converter import commands
from make_vision_mod import lb_id
from ffbe_effects.acb_cues import cues



def verify_host_placement(entry, events, sid, duration):
    """Check opt-in host controls independently of the presentation builder."""
    bytype = lambda kind: [(t, e) for t, e in events if e['EventType'] == kind]
    profile = entry.get('reconstructionProfile', {})
    placement = profile.get('screenPlacement', {})
    backdrop = placement.get('backdrop') == 'native_subspace'
    target_stage = placement.get('mode') == 'target_stage'
    caster_target = profile.get('casterPlacement') == 'approach_target'
    expected_planes = []
    for i, fx in enumerate(entry.get('visuals', [])):
        plane = fx.get('placement', {})
        if fx.get('anchor') != 'screen' or plane.get('mode') != 'camera_plane':
            continue
        presentation.validate_screen_placement(plane)
        aid = f'FFBE_{sid}_{i}'
        spawns = [(t, e) for t, e in bytype('SsActorSpawnSpriteStudioActor')
                  if e['SsActor_SsData']['spriteStudioID'] == aid]
        assert len(spawns) == 1, 'Camera plane needs one native actor'
        start = spawns[0][0]
        end = start + fx['frames'] * 400
        assert start >= 0 and end < duration
        fields = {'EventType': 'NativeScreenPlane', 'NativeScreenPlane_Id': aid,
                  'NativeScreenPlane_SourceWidth': plane['referenceStage'][0],
                  'NativeScreenPlane_SourceHeight': plane['referenceStage'][1],
                  'NativeScreenPlane_RuntimeScale': plane['runtimeScale'],
                  'NativeScreenPlane_OverscanX': plane['overscan'][0],
                  'NativeScreenPlane_OverscanY': plane['overscan'][1],
                  'NativeScreenPlane_FrontDepth': plane['cameraDepth']['front'],
                  'NativeScreenPlane_RearMargin': plane['cameraDepth']['rearMargin'],
                  'NativeScreenPlane_IsRear': fx['layer'] != 1}
        expected_planes.extend((t, fields) for t in range(start + 2, end, 800))
    assert sorted(bytype('NativeScreenPlane'), key=lambda p: (p[0], p[1]['NativeScreenPlane_Id'])) == sorted(
        expected_planes, key=lambda p: (p[0], p[1]['NativeScreenPlane_Id'])), 'Camera plane projection settings or bounded refresh cadence differ'
    camera_verified = bool(expected_planes)
    shared = presentation.participant_camera(entry)
    participant_verified = shared is not None
    if shared is not None:
        assert not target_stage, 'Shared camera combined with bespoke stage'
        main = next(t for t, e in bytype('UnitPlayAnimByName')
                    if e.get('Unit_PlayAnimByName_AnimationName') in ('LB1', 'attack_A', 'magic_attack'))
        camera = bytype('NativeParticipantCamera')
        movement = bytype('UnitMoveToTarget') + bytype('NativeGroundApproach')
        casting = [(t, e) for t, e in bytype('UnitPlayAnimByName') if e.get('Unit_PlayAnimByName_AnimationName')
                   in ('command', 'magic_idle', 'LB1', 'attack_A', 'magic_attack')]
        isolate_at = max(0, min((t for t, _ in movement + casting), default=main) - 2)
        first_hit = min((t for t, _ in bytype('OtherReaction')), default=main + 12000)
        target_at = max(main, first_hit - shared['panFrames'] * 800)
        casters = [(t, e) for t, e in camera if e.get('NativeParticipantCamera_Shot') == 'caster']
        targets = [(t, e) for t, e in camera if e.get('NativeParticipantCamera_Shot') == 'targets']
        assert len(camera) == len(casters) + len(targets) and len(targets) == 1, 'Shared camera requires caster follow and one target shot'
        assert targets[0][0] == target_at, 'Target framing misses the source impact transition'
        expected_start = isolate_at + 1
        for index, (t, fields) in enumerate(casters):
            frames = fields.get('NativeParticipantCamera_Frame')
            assert t == expected_start and type(frames) is int, 'Caster framing is not a continuous finite blend chain'
            assert frames == min(4, (target_at-t)//800), 'Caster framing duration or cadence changed'
            assert frames >= 1 and t + frames * 800 <= target_at, 'Caster camera blend overlaps target framing'
            expected_start = t + frames * 800
        assert 0 <= target_at - expected_start < 800, 'Caster tracking has an unexplained gap'
        for t, fields in camera:
            shot = fields['NativeParticipantCamera_Shot']
            x, y, height, lens = (.55, .52, .52, 1.25) if shot == 'caster' else (.35, .56, .32, 1.05)
            expected = {'EventType': 'NativeParticipantCamera', 'NativeParticipantCamera_UnitId': entry['_hostVisionUnitId'],
                        'NativeParticipantCamera_Frame': fields['NativeParticipantCamera_Frame'],
                        'NativeParticipantCamera_Shot': shot, 'NativeParticipantCamera_CenterX': x,
                        'NativeParticipantCamera_CenterY': y, 'NativeParticipantCamera_HeightFraction': height,
                        'NativeParticipantCamera_ZoomFactor': lens}
            assert fields == expected and 0 <= t < duration, 'Shared camera framing settings or selected vision changed'
        assert targets[0][1]['NativeParticipantCamera_Frame'] == shared['panFrames']
        assert not any(bytype(kind) for kind in ('NativeStageCamera', 'CameraSetLookAtTarget', 'CameraSetLookAtSelf',
                       'CameraSetViewLocation', 'CameraSetViewTarget', 'CameraSetZoomInOut')), 'Shared camera has competing position or lens controls'
        resets = [(t, e) for t, e in bytype('CameraSetDefault') if t > main]
        assert len(resets) == 1, 'Shared camera lacks one finite restoration'
        tick, fields = resets[0]
        assert fields.get('Camera_SetDefault_Frame') == shared['restoreFrames']
        assert fields.get('Camera_SetDefault_IsRotation') and fields.get('Camera_SetDefault_IsLocation')
        assert fields.get('Camera_SetDefault_IsZoomInOut', False), 'Shared camera must restore the original lens'
        assert tick > max([target_at + shared['panFrames'] * 800, *(t for t, _ in bytype('SsActorDestroyToSsID'))]), 'Shared camera restores before presentation ends'
        assert tick + shared['restoreFrames'] * 800 < duration, 'Shared camera restoration is truncated'
        visibility = bytype('NativeResonanceVisibility')
        hides = [isolate_at] + ([main - 3] if main - 3 > isolate_at else [])
        returns = [t + e.get('Unit_MoveToDefaultLocation_Frame', 0) * 400 for t, e in bytype('UnitMoveToDefaultLocation')]
        final_visual = max((t for t, _ in bytype('SsActorDestroyToSsID')), default=0)
        restore_visibility = max([final_visual + 400, main + 400, *returns]) + 2
        expected_visibility = [(t, {'EventType': 'NativeResonanceVisibility',
                               'NativeResonanceVisibility_UnitId': entry['_hostVisionUnitId'],
                               'NativeResonanceVisibility_Restore': False}) for t in hides]
        expected_visibility.append((restore_visibility, {'EventType': 'NativeResonanceVisibility',
                                    'NativeResonanceVisibility_UnitId': entry['_hostVisionUnitId'],
                                    'NativeResonanceVisibility_Restore': True}))
        assert visibility == expected_visibility, 'Resonance isolation has wrong owners, hide retry or restoration'
        assert restore_visibility < duration, 'Resonance visibility cleanup is truncated'
    else:
        assert not bytype('NativeParticipantCamera'), 'Unrequested shared camera override'
        assert not bytype('NativeResonanceVisibility'), 'Unrequested resonance visibility override'
    grounded = presentation.ground_movement(entry)
    ground_moves = bytype('NativeGroundApproach')
    if grounded is not None:
        assert len(ground_moves) <= 1, 'Shared grounding invented multiple approaches'
        assert not any(e.get('Unit_MoveToTarget_IsVisionUnit', False) for _, e in bytype('UnitMoveToTarget')), 'Native and grounded vision approaches compete'
        for tick, move in ground_moves:
            assert 0 <= tick < duration
            assert move.get('NativeGroundApproach_UnitId') == entry['_hostVisionUnitId']
            assert type(move.get('NativeGroundApproach_Frame')) is int and 1 <= move['NativeGroundApproach_Frame'] <= 3600
            assert isinstance(move.get('NativeGroundApproach_PartName'), str) and move['NativeGroundApproach_PartName']
            offset = move.get('NativeGroundApproach_Offset', {})
            assert set(offset) == {'x', 'y', 'z'} and offset['z'] == 0, 'Ground approach adds a vertical displacement'
            assert all(type(v) in (int, float) and math.isfinite(v) for v in offset.values())
            assert any(t > tick and e.get('Unit_MoveToDefaultLocation_IsVision', False)
                       for t, e in bytype('UnitMoveToDefaultLocation')), 'Ground approach lacks native return'
    else:
        assert not ground_moves, 'Unrequested ground approach'
    expected_roots = []
    for i, fx in enumerate(entry.get('visuals', [])):
        if not presentation.actor_root_snapshot(fx):
            continue
        aid = f'FFBE_{sid}_{i}'
        tick, spawn = next((t, e) for t, e in bytype('SsActorSpawnSpriteStudioActor')
                           if e['SsActor_SsData']['spriteStudioID'] == aid)
        expected_roots.append((tick + 1, {'EventType': 'NativeActorRootSnapshot',
            'NativeActorRootSnapshot_Id': aid, 'NativeActorRootSnapshot_UnitId': entry['_hostVisionUnitId'],
            'NativeActorRootSnapshot_IsTarget': fx['anchor'] != 'caster',
            'NativeActorRootSnapshot_Depth': -8. if fx['layer'] == 1 else 8.}))
        assert any(t == tick + 2 and e.get('SsActor_PlayAnim_ID') == aid and e.get('SsActor_PlayAnim_StartFrame') == 2
                   for t, e in bytype('SsActorPlayAnimToSsID')), 'Root snapshot must precede visible playback'
    assert sorted(bytype('NativeActorRootSnapshot'), key=lambda p: (p[0], p[1]['NativeActorRootSnapshot_Id'])) == sorted(
        expected_roots, key=lambda p: (p[0], p[1]['NativeActorRootSnapshot_Id'])), 'Missing or incorrect selected-actor root binding'
    if target_stage:
        assert backdrop and caster_target, 'Target stage lacks native backdrop or completed approach mode'
        presentation.validate_screen_placement(placement)
    if not (backdrop or caster_target):
        return {'nativeBackdropVerified': False, 'casterTargetPlacementVerified': False, 'targetStageVerified': False,
                'cameraPlaneVerified': camera_verified, 'participantCameraVerified': participant_verified,
                'groundApproachVerified': bool(ground_moves), 'actorRootSnapshotsVerified': len(expected_roots)}
    assert all(isinstance(t, (int, float)) and 0 <= t < duration for t, _ in events), 'Host event outside finite playback'
    spawns = bytype('SsActorSpawnSpriteStudioActor')
    destroys = bytype('SsActorDestroyToSsID')
    if backdrop:
        expected = [
            ('OtherChangeSubSpaceInitialize', 0), ('OtherChangeSubSpace', 3200),
            ('BGChange', 4000), ('OtherChangeSubSpaceGround', 8000),
            ('OtherChangeSubSpaceColor', 8001), ('OtherChangeSubSpaceEmissive', 8002)]
        for kind, time in expected:
            assert len(bytype(kind)) == 1 and bytype(kind)[0][0] == time, 'Native backdrop event order changed: '+kind
        action_screen_ids = {f'FFBE_{sid}_{i}' for i, fx in enumerate(entry['visuals'])
                             if fx['anchor'] == 'screen' and fx.get('phase', 'action') == 'action'}
        assert action_screen_ids and 8002 < min(t for t, e in spawns if e['SsActor_SsData']['spriteStudioID'] in action_screen_ids), 'Backdrop setup overlaps source screen effects'
        change = bytype('BGChange')[0][1]
        assert change.get('BG_Change_BackgroundLevel') == 'soft:'+presentation.NATIVE_SUBSPACE, 'Wrong native backdrop level'
        assert change.get('BG_Change_IsChangeSubSpace', False), 'Background bypasses native SubSpace'
        scale = bytype('OtherChangeSubSpace')[0][1]['Other_ChangeSubSpace_Scale']
        assert scale.get('X') == scale.get('Y') == 2.5, 'Native SubSpace transition scale changed'
        ground = bytype('OtherChangeSubSpaceGround')[0][1]
        assert not any(ground.get('Other_ChangeSubSpaceGround_'+k, False) for k in
                       ('IsVisibility', 'IsParticleVisibility', 'IsFogVisibility')), 'Backdrop geometry obscures source art'
        color = bytype('OtherChangeSubSpaceColor')[0][1]
        rgba = color['Other_ChangeSubSpaceColor_Color']
        assert all(rgba.get(k, 0) == 0 for k in 'RGB') and rgba.get('A') == 1, 'Backdrop is not opaque black'
        assert color.get('Other_ChangeSubSpaceColor_Frame', 0) == 0
        emissive = bytype('OtherChangeSubSpaceEmissive')[0][1]
        assert emissive.get('Other_ChangeSubSpaceEmissive_Emissive', 0) == 0, 'Backdrop emissive competes with source art'
        assert emissive.get('Other_ChangeSubSpaceEmissive_frame', 0) == 0
        revert = bytype('BGRevert')
        assert len(revert) == 1 and revert[0][0] == max(t for t, _ in destroys)+400, 'Battlefield restored before visual cleanup'
        assert revert[0][1].get('BG_Change_IsChangeSubSpace', False)
    if caster_target:
        moves = [(t, e) for t, e in bytype('UnitMoveToTarget') if e.get('Unit_MoveToTarget_IsVisionUnit', False)]
        assert len(moves) == 1, 'Caster attachment lacks one vision approach'
        move_time, move = moves[0]
        assert move.get('Unit_MoveToTarget_IsDisableOffset', False), 'Unit clearance offsets separate caster and effect'
        registration = placement.get('targetRegistration')
        if registration:
            assert move.get('Unit_MoveToTarget_PartName') == registration['partName'], 'Stage uses the enemy root instead of body center'
            factor = placement['camera']['unitsPerPixel'] * placement['camera']['runtimeScale']
            expected_offset = dict(zip('xyz', (0., -registration['sourceImpact'][0]*factor, -registration['sourceImpact'][1]*factor)))
            actual_offset = move.get('Unit_MoveToTarget_AddLocation', {})
            assert all(math.isclose(actual_offset.get(k, 0), v, abs_tol=1e-5) for k, v in expected_offset.items()), 'Authored impact is not registered to body center'
        attached_count = 0
        for i, fx in enumerate(entry['visuals']):
            if fx['anchor'] != 'caster' and not (target_stage and fx['anchor'] == 'screen'):
                continue
            aid = f'FFBE_{sid}_{i}'
            found = [(t, e) for t, e in spawns if e['SsActor_SsData']['spriteStudioID'] == aid]
            assert len(found) == 1
            spawn_time, spawn = found[0]
            assert move_time+move.get('Unit_MoveToTarget_Frame', 0)*400 <= spawn_time, 'Caster effect precedes completed approach'
            assert spawn['SsActor_SsData'].get('bDisableFollowing', False), 'Caster effect follows equipper after target placement'
            attached = [(t, e) for t, e in bytype('SsActorMoveToTargetToSsID') if e.get('SsActor_MoveToTarget_ID') == aid]
            assert len(attached) == 1 and attached[0][0] == spawn_time+2, 'Caster placement clock differs from source setup'
            fields = attached[0][1]
            assert fields.get('SsActor_MoveToTarget_targetPointID') == -1
            assert fields.get('SsActor_MoveToTarget_frame', 0) == 0
            assert fields.get('SsActor_MoveToTarget_partName') == move['Unit_MoveToTarget_PartName'], 'Caster effect uses a different target part'
            assert not fields.get('SsActor_MoveToTarget_RelativeActionUnit', False)
            assert fields.get('SsActor_MoveToTarget_Height', 0) == fields.get('SsActor_MoveToTarget_Length', 0) == 0
            assert fields.get('SsActor_MoveToTarget_easingType') == 'Linear'
            offset = fields.get('SsActor_MoveToTarget_plusOffset', {})
            unit_offset = move.get('Unit_MoveToTarget_AddLocation', {})
            depth_x = -8 if fx['layer'] == 1 else 8
            if target_stage:
                depth_x = placement.get('layerDepth', {'back': 8, 'front': -8})[
                    'front' if fx['layer'] == 1 else 'back']
                assert spawn['SsActor_SsData'].get('addLocation', {}).get('x', 0) == depth_x, 'Stage spawn depth differs from profile'
            for k in 'xyz':
                depth = depth_x if k == 'x' else 0
                assert offset.get(k, 0) == unit_offset.get(k, 0)+depth, 'Caster effect offset differs from vision approach'
            play = [(t, e) for t, e in bytype('SsActorPlayAnimToSsID') if e.get('SsActor_PlayAnim_ID') == aid]
            assert len(play) == 1 and play[0][0] == spawn_time+1
            assert play[0][1].get('SsActor_PlayAnim_LoopCount') == 1
            attached_count += 1
        assert attached_count, 'Caster target profile has no caster effects'
    if target_stage:
        first = min(t for t, _ in spawns)
        last = max(t for t, _ in destroys)
        assert move_time + move.get('Unit_MoveToTarget_Frame', 0)*400 <= first-3, 'Approach overlaps stage camera setup'
        assert first-3 > 8002, 'Stage camera overlaps backdrop setup'
        registered = bool(placement.get('targetRegistration'))
        look = bytype('NativeStageCamera' if registered else 'CameraSetLookAtTarget')
        assert not bytype('CameraSetLookAtTarget' if registered else 'NativeStageCamera'), 'Competing root and stage camera controls'
        zoom = bytype('CameraSetZoomInOut')
        camera = placement['camera']
        pans = camera.get('pan', [])
        assert len(look) == 1 + len(pans) and len(zoom) == 1 + sum('focalLength' in p for p in pans), 'Target stage has competing camera controls'
        assert look[0][0] == first-3 and zoom[0][0] == first-2, 'Stage camera setup clock changed'
        camera = placement['camera']
        fields = look[0][1]
        factor = camera['unitsPerPixel'] * camera['runtimeScale']
        if registered:
            assert type(entry.get('_hostVisionUnitId')) is int and entry['_hostVisionUnitId'] > 0
            assert fields.get('NativeStageCamera_UnitId') == entry['_hostVisionUnitId'], 'Stage camera follows a different vision'
            expected = {'x': 0., 'y': camera['sourceCenter'][0] * factor, 'z': camera['sourceCenter'][1] * factor}
            actual = fields.get('NativeStageCamera_AddLocation', {})
        else:
            assert fields.get('Camera_SetLookAtTarget_Id') == -1
            assert fields.get('Camera_SetLookAtTarget_Frame', 0) == 0
            assert fields.get('Camera_SetLookAtTarget_EasingType') == 'Linear'
            expected = dict(move['Unit_MoveToTarget_AddLocation'])
            expected['y'] = expected.get('y', 0) + camera['sourceCenter'][0] * factor
            expected['z'] = expected.get('z', 0) + camera['sourceCenter'][1] * factor
            actual = fields.get('Camera_SetLookAtTarget_AddLocation', {})
        assert all(math.isclose(actual.get(k, 0), expected.get(k, 0), abs_tol=1e-5) for k in 'xyz'), 'Camera center differs from shared source stage'
        fields = zoom[0][1]
        assert math.isclose(fields.get('Camera_SetZoomInOut_Value', 0), camera['focalLength'], abs_tol=1e-5)
        assert not fields.get('Camera_SetZoomInOut_RelativeValue', False), 'Stage lens became relative'
        assert fields.get('Camera_SetZoomInOut_Frame', 0) == 0
        assert fields.get('Camera_SetZoomInOut_EasingType') == 'Linear'
        main = next(t for t, e in bytype('UnitPlayAnimByName')
                    if e.get('Unit_PlayAnimByName_AnimationName') in ('LB1', 'attack_A', 'magic_attack'))
        lens_index = 1
        for index, pan in enumerate(pans, 1):
            tick, fields = look[index]
            assert tick == main + pan['frame'] * 400, 'Camera pan action clock changed'
            assert fields.get('NativeStageCamera_UnitId') == entry['_hostVisionUnitId']
            assert fields.get('NativeStageCamera_Frame') * 800 == pan['durationFrames'] * 400, 'Native 30 fps pan duration differs from source 60 fps duration'
            assert fields.get('NativeStageCamera_EasingType') == pan.get('easing', 'EaseInOut')
            expected = dict(zip('xyz', (0, pan['sourceCenter'][0] * factor, pan['sourceCenter'][1] * factor)))
            actual = fields.get('NativeStageCamera_AddLocation', {})
            assert all(math.isclose(actual.get(k, 0), expected[k], abs_tol=1e-5) for k in 'xyz'), 'Camera pan leaves the authored stage'
            assert tick + pan['durationFrames'] * 400 < last
            if 'focalLength' in pan:
                lens_tick, lens = zoom[lens_index]; lens_index += 1
                assert lens_tick == tick + 1
                assert math.isclose(lens.get('Camera_SetZoomInOut_Value', 0), pan['focalLength'], abs_tol=1e-5)
                assert lens.get('Camera_SetZoomInOut_Frame', 0) * 800 == pan['durationFrames'] * 400
                assert lens.get('Camera_SetZoomInOut_EasingType') == pan.get('easing', 'EaseInOut')
                assert not lens.get('Camera_SetZoomInOut_RelativeValue', False)
        visibility = bytype('UnitSetVisibility')
        if placement.get('hideEnemies', False):
            assert len(visibility) == 2 and [t for t, _ in visibility] == [first-1, last+400]
            for category in ('ActionUnit', 'TargetUnit', 'FriendUnits', 'EnemyUnits', 'VisionUnits', 'BeastUnits'):
                key = 'Unit_SetVisibility_Is'+category
                assert visibility[0][1].get(key, False) == (category not in ('TargetUnit', 'EnemyUnits')), 'Enemy-only visibility policy changed'
                assert visibility[1][1].get(key, False), 'Enemy visibility must restore after the effect'
        else:
            assert not visibility, 'Target stage must preserve native combatant visibility'
        isolation = bytype('NativeStageVisibility')
        if placement.get('hideNonParticipants', False):
            returns = [t + e.get('Unit_MoveToDefaultLocation_Frame', 0) * 400
                       for t, e in bytype('UnitMoveToDefaultLocation')]
            expected_restore = max([last + 400, *returns]) + 2
            assert len(isolation) == 2 and [t for t, _ in isolation] == [first - 1, expected_restore]
            assert [e.get('NativeStageVisibility_Restore') for _, e in isolation] == [False, True]
            assert all(e.get('NativeStageVisibility_UnitId') == entry['_hostVisionUnitId'] for _, e in isolation)
        else:
            assert not isolation, 'Unrequested participant isolation'
        auras = bytype('NativeAuraVisibility')
        if placement.get('hideNativeAuras', False):
            returns = [t + e.get('Unit_MoveToDefaultLocation_Frame', 0) * 400
                       for t, e in bytype('UnitMoveToDefaultLocation')]
            expected_restore = max([last + 400, *returns]) + 1
            assert len(auras) == 2 and [t for t, _ in auras] == [first - 1, expected_restore], 'Ambient aura hide/restore clock changed'
            assert auras[0][1].get('NativeAura_IsVisible') is False, 'Ambient aura must hide before effects'
            assert auras[1][1].get('NativeAura_IsVisible') is True, 'Ambient aura must restore after return movement'
            assert type(entry.get('_hostVisionUnitId')) is int and entry['_hostVisionUnitId'] > 0
            assert all(e.get('NativeAura_UnitId') == entry['_hostVisionUnitId'] for _, e in auras), 'Aura override must address the selected vision'
        else:
            assert not auras, 'Unrequested ambient aura override'
        resets = bytype('CameraSetDefault')
        assert any(t > last for t, _ in resets), 'Cinematic camera lacks default cleanup'
        for t, reset in resets:
            if t > last:
                assert reset.get('Camera_SetDefault_Frame', 0) == 0, 'Cinematic camera restore must be instant'
                assert all(reset.get('Camera_SetDefault_'+k, False) for k in ('IsRotation', 'IsLocation', 'IsZoomInOut'))
        assert not any(first <= t <= last for t, _ in resets), 'Camera restored while source effects remain active'
    return {'nativeBackdropVerified': backdrop, 'casterTargetPlacementVerified': caster_target,
            'targetStageVerified': target_stage, 'targetBodyRegistrationVerified': bool(placement.get('targetRegistration')),
            'cameraPlaneVerified': camera_verified, 'participantCameraVerified': participant_verified,
            'groundApproachVerified': bool(ground_moves), 'actorRootSnapshotsVerified': len(expected_roots)}


def verify(work=None):
    work=work or ROOT/'build/sora-presentation/cooked';work.mkdir(parents=True,exist_ok=True)
    usmap = work / 'Mappings.usmap'
    if not usmap.exists(): shutil.copy2(ROOT/'extracted/Mappings.usmap', usmap)
    assets=ROOT/'build/visions_mod/assets'
    units=json.loads((assets.parent/'units-built.json').read_text(encoding='utf-8'))
    def dump(path,verb):
        out=work/(path.stem+'-'+verb+'.json')
        p=subprocess.run([*ffrenv.FFRDT,verb,str(path),str(out),'--usmap',str(usmap)],capture_output=True,text=True)
        if p.returncode:raise RuntimeError(p.stdout+p.stderr)
        return json.loads(out.read_text(encoding='utf-8-sig'))
    results=[]
    for unit in units:
        selected=[(int(sid),s) for sid,s in unit.get('skills',{}).items()]
        if unit.get('lb_custom'):selected.append((lb_id(unit['id']),{**unit['lb_custom'],'resonance':True}))
        for sid,skill in selected:
            entry=presentation.lookup(unit,skill)
            if not entry:continue
            path=assets/f'FFRS/Content/Sequencer/Battle/Skill/{sid}/{sid+1}/SEQ_Battle_{sid+1}_Master.uasset'
            doc,funcs=dump(path,'tojson'),dump(path,'seqdump')
            funcs={int(k.split(':')[0]):v for k,v in funcs.items()}
            events=[]
            for export in doc['Exports']:
                for prop in export.get('Data',[]):
                    if prop['Name']!='EventChannel':continue
                    for time,key in zip(sequence.child(prop['Value'],'KeyTimes'),sequence.child(prop['Value'],'KeyValues')):
                        while not isinstance(time,(int,float)):time=time[0] if isinstance(time,list) else time['Value']
                        function_id = sequence.child(key['Value'],'Ptrs','Function')
                        bound = sequence.child(key['Value'],'Ptrs','BoundObjectProperty')
                        assert bound['ResolvedOwner'] == function_id, 'Native event argument belongs to another function'
                        events.append((time,funcs[function_id]))
            main=next(t for t,e in events if e['EventType']=='UnitPlayAnimByName'
                      and e.get('Unit_PlayAnimByName_AnimationName') in ('LB1','magic_attack','attack_A'))
            cast = entry.get('cast')
            cast_start = (next(t for t,e in events if e['EventType']=='UnitPlayAnimByName'
                              and e.get('Unit_PlayAnimByName_AnimationName') == cast.get('motion', 'magic_idle'))
                          if cast else None)
            if cast:
                moving=commands.from_spec(skill)['timeline']['moveType']==1
                assert main-cast_start == (cast['durationFrames']+(commands.APPROACH_FRAMES+1 if moving else 0))*400
            if presentation.motion_type(entry) == 2 and not skill.get('presentation_motion'):
                assert any(t == main and e.get('Unit_PlayAnimByName_AnimationName') == 'magic_attack'
                           for t,e in events), 'Source casting motion replaced by damage-type default'
            bytype=lambda kind:[(t,e) for t,e in events if e['EventType']==kind]
            if skill.get('resonance'):
                for _, motion in bytype('UnitPlayAnimByName'):
                    name = motion['Unit_PlayAnimByName_AnimationName']
                    assert motion.get('Unit_PlayAnimByName_IsOnlyVisionUnit', False), 'LB animates the equipper instead of its vision'
                    assert motion.get('Unit_PlayAnimByName_IsPlayFriend', False), 'LB excludes its friendly vision'
                    assert not motion.get('Unit_PlayAnimByName_IsPlayEnemy', False), 'LB animation leaks to enemies'
                    assert motion.get('Unit_PlayAnimByName_AnimationID') == -1
                    assert motion.get('Unit_PlayAnimByName_FirstDualcastAnimationName') == name
                    assert motion.get('Unit_PlayAnimByName_SecondDualcastAnimationName') == name
            source_hits = None
            if skill.get('resonance') and entry.get('reconstructionProfile'):
                source_hits = ffbe_lb.resolve(unit, skill)['hitFrames']
                assert Counter(t for t,e in bytype('OtherReaction')) == Counter(
                    main+frame*400 for frame in source_hits), 'LB damage frames differ from the source action clock'
            if entry.get('reconstructionProfile', {}).get('preserveSourceColor'):
                assert not bytype('PostSetColorGradingGlobalParameter'), 'Generic field tint recolors source art'
            spawn=bytype('SsActorSpawnSpriteStudioActor');destroy=bytype('SsActorDestroyToSsID');play=bytype('SsActorPlayAnimToSsID')
            assert len(spawn)==len(destroy)==len(play)==len(entry['visuals'])
            for i,fx in enumerate(entry['visuals']):
                aid=f'FFBE_{sid}_{i}'
                t,e=next((t,e) for t,e in spawn if e['SsActor_SsData']['spriteStudioID']==aid)
                origin = cast_start if fx.get('phase') == 'cast' else main
                assert origin is not None
                root_snapshot = presentation.actor_root_snapshot(fx)
                assert t==origin+fx['frame']*400-(0 if root_snapshot else 800)
                assert fx['name'] in str(e['SsActor_SsData']['ssPlayerAsset'])
                assert e['SsActor_SsData'].get('bSpawnRelativeTarget',False)==(fx['anchor'] in ('each_target','target_group'))
                if fx['anchor'] == 'screen':
                    assert e['SsActor_SsData']['bDisableFollowing'], 'Screen plane follows moving caster'
                    assert e['SsActor_SsData']['PartName'] == 'root'
                playing = next(e for _,e in play if e['SsActor_PlayAnim_ID']==aid)
                assert playing['SsActor_PlayAnim_LoopCount']==1
                assert playing.get('SsActor_PlayAnim_StartFrame', 0) == (2 if root_snapshot else 0)
                if root_snapshot:
                    assert e['SsActor_SsData']['bDisableFollowing'] and e['SsActor_SsData']['PartName'] == 'root'
                    assert not any(m.get('SsActor_MoveToTarget_ID') == aid for _, m in bytype('SsActorMoveToTargetToSsID')), 'Source offsets applied twice'
                assert next(t1 for t1,e1 in destroy if e1['SsActor_Destroy_ID']==aid)==t+(fx['frames']-(2 if root_snapshot else 0))*400
                for suffix in ('.uasset','.uexp','_tex.uasset','_tex.uexp'):
                    assert (assets/f'FFRS/Content/Chara/effect/{fx["name"]}/{fx["name"]}{suffix}').is_file()
            scene = next(e for e in doc['Exports'] if e['ObjectName'] == 'MovieScene_0')
            duration = sequence.child(scene['Data'], 'PlaybackRange')[0]['Value']['UpperBound']['Value']['Value']
            host_placement = verify_host_placement(entry, events, sid, duration)
            audio_doc=json.loads((ROOT/entry['audioBank']).read_text())
            expected=Counter(main+s['frame']*400 for s in entry['sounds'] if str(s['cueId']) not in audio_doc['omitted'])
            expected_labels=Counter((main+s['frame']*400, audio_doc['cues'][str(s['cueId'])]['name'])
                                    for s in entry['sounds'] if str(s['cueId']) not in audio_doc['omitted'])
            if cast:
                expected[cast_start+cast['frame']*400] += 1
                expected_labels[(cast_start+cast['frame']*400, cast['cueName'])] += 1
            opening = entry.get('opening')
            if opening and opening.get('chargeFrame') is not None:
                charge = main + (opening['chargeFrame']-opening['durationFrames'])*400
                expected[charge] += 1
                expected_labels[(charge, audio_doc['cues']['647']['name'])] += 1
                assert any(t == charge and e.get('Unit_PlayAnimByName_AnimationName') == opening['chargeMotion']
                           for t,e in events), 'LB charge pose and cue clocks differ'
            sounds=bytype('SoundPlayHitSound')
            ordinary=[]; actual_labels=[]
            for t,sound in sounds:
                name=sound['Sound_PlayHitSound_CueSheetName'];label=sound['Sound_PlayHitSound_playLabel']
                if label.startswith(ffbe_audio.LB_OPENING_CUE):
                    assert skill.get('resonance'), 'LB opening leaked into an ordinary command'
                    if opening:
                        assert t == main-opening['durationFrames']*400, 'LB opening cue lost its prelude'
                else:
                    ordinary.append(t)
                    base, marker, variant = label.rpartition('__v')
                    actual_labels.append((t, base if marker and variant.isdigit() else label))
                bank=assets/f'FFRS/Content/Sound/FFBE/{name}'
                assert bank.with_suffix('.uasset').is_file()
                data=bank.with_suffix('.uexp').read_bytes()
                assert b'@UTF' in data
                source=assets.parent/(name+'.acb')
                assert label in {c['name'] for c in cues(str(source)).values()}
            assert Counter(ordinary)==expected,(sid,'sound timing mismatch')
            assert Counter(actual_labels)==expected_labels,(sid,'sound cue identity mismatch')
            if presentation.has_target_visuals(entry):
                rows=dump(assets/'FFRS/Content/Datatable/Battle/Sequencer/DT_BtlHitEffectData.uasset','rows')['rows']
                reaction=next(r for r in rows.values() if r['ID']==sid)
                assert all(reaction[f] == -1 for f in ('NormalEffectID','CriticalEffectID','AdditionalEffectID'))
                assert not reaction['IsAdditionalEffect'], 'Donor hit flashes overlap FFBE target art'
            results.append({'vision':unit['en'],'skill':skill['en'],'id':sid,
                            'soundEvents':len(sounds),'effectActors':len(spawn),'finitePlaybackAndCleanup':True,
                            'nativeMotionType':presentation.motion_type(entry),'castPhaseVerified':bool(cast),
                            'openingPhaseVerified':bool(opening), 'sourceHitTimesVerified':len(source_hits) if source_hits is not None else None,
                            'sourceTargetArtReplacesDonorFlashes':presentation.has_target_visuals(entry), **host_placement})
    assert results,'No prepared presentations found'
    (work.parent/'presentation-verification.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work',type=Path,help='Isolated cooked readback directory')
    verify(parser.parse_args().work)
