"""Cast/follow, a 0.1-second hold, then a continuous target pan/zoom handoff."""
from copy import deepcopy

TICKS_PER_NATIVE_FRAME = 800
HOLD_TICKS = 2400
PAN_FRAMES = 6
ZOOM_FRAMES = 6
SETTLE_FRAMES = 0
TARGET_X, TARGET_Y, TARGET_HEIGHT = .38, .58, .60
MAX_TARGET_ZOOM = 2.2


def direct(plan, vision_id):
    plan = deepcopy(plan)
    events = plan['events']
    # The donor shell used a half-second empty lead. Retain 0.1 seconds for
    # setup; move cast, travel and action together, preserving source clocks.
    preparation = min(e['time'] for e in events if e['set']['EventType'] == 'UnitPlayAnimByName')
    lead = max(0, preparation - HOLD_TICKS)
    for event in events:
        if event['time'] >= preparation - 2:
            event['time'] -= lead
    plan['duration'] -= lead
    cameras = [e for e in events if e['set']['EventType'] == 'NativeParticipantCamera']
    if not cameras or any(e['set']['NativeParticipantCamera_Shot'] != 'caster' for e in cameras):
        raise ValueError('Target staging requires the completed caster-only camera plan')
    action = next(e['time'] for e in events if e['set']['EventType'] == 'UnitPlayAnimByName'
                  and e['set']['Unit_PlayAnimByName_AnimationName'] in ('LB1','attack_A','magic_attack'))
    # Move the action as a block so hit spacing and cleanup remain aligned.
    last_blend = max(e['time'] + e['set']['NativeParticipantCamera_Frame']*TICKS_PER_NATIVE_FRAME for e in cameras)
    # The checkpoint's action boundary ends its casting/preparation phase.
    # A camera blend alone is not the cast's end (especially for magic/LBs).
    cast_end = max(action, last_blend)
    target_start = cast_end + HOLD_TICKS
    zoom_start = target_start + PAN_FRAMES*TICKS_PER_NATIVE_FRAME
    ready = zoom_start + (ZOOM_FRAMES + SETTLE_FRAMES)*TICKS_PER_NATIVE_FRAME
    delay = max(0, ready-action)
    # Stationary casters remain part of the action composition. Decide from
    # actual travel events, including native fallbacks, rather than unit names.
    moving = any(e['time'] <= action and e['set']['EventType'] in
                 ('NativeGroundApproach', 'UnitMoveToTarget') for e in events)
    subject = 'targets' if moving else 'participants'
    for event in events:
        if event['time'] >= action and event['set']['EventType'] != 'NativeParticipantCamera':
            event['time'] += delay
    for tick,shot,frames in ((target_start,subject+'_pan',PAN_FRAMES),(zoom_start,subject+'_zoom',ZOOM_FRAMES)):
        events.append({'time': tick, 'set': {
            'EventType':'NativeParticipantCamera', 'NativeParticipantCamera_UnitId':vision_id,
            'NativeParticipantCamera_Frame':frames, 'NativeParticipantCamera_Shot':shot,
            'NativeParticipantCamera_CenterX':TARGET_X if moving else .5, 'NativeParticipantCamera_CenterY':TARGET_Y,
            'NativeParticipantCamera_HeightFraction':TARGET_HEIGHT, 'NativeParticipantCamera_ZoomFactor':MAX_TARGET_ZOOM}})
    plan['duration'] += delay
    plan['events'] = sorted(events,key=lambda e:e['time'])
    return plan
