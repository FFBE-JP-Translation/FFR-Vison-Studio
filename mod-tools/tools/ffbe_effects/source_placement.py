"""Interpret source placement fields without choosing a host playback adapter.

Evidence: FFBEWW 9.1.0 arm64 libgame.so, BattleUnit::playBattleEffect
(0x1ba8560) and GameUtils::playEffectWithGroupID (0x19f3944). See
build/effects-followup-20260913/source-placement-evidence.md.

``supported`` means the fields have a known source interpretation. It does
not mean a renderer implements it. Unknown inputs remain explicit failures;
raw values are retained, and no camera or actor-attachment policy is inferred.
"""
from copy import deepcopy
import math
import re

VERSION = 1
NATIVE_CONTRACT = 'ffbeww-9.1.0-arm64-placement-v1'
_INTEGER = re.compile(r'[+-]?\d+\Z', re.ASCII)


def _result(raw, key):
    return {'version': VERSION, 'nativeContract': NATIVE_CONTRACT,
            key: deepcopy(raw), 'supported': False, 'issues': []}


def _fields(raw, result, minimum, maximum):
    if isinstance(raw, str):
        values = raw.split(':')
    elif isinstance(raw, (list, tuple)):
        values = list(raw)
    else:
        result['issues'].append('Expected colon-separated text or a field list')
        return None
    if not minimum <= len(values) <= maximum:
        result['issues'].append(f'Expected {minimum}..{maximum} fields; got {len(values)}')
        return None
    return values


def _integer(value, label):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError(f'{label} must be an integer')
    if not _INTEGER.fullmatch(str(value)):
        raise ValueError(f'{label} must be an integer')
    number = int(value)
    if not -(2**31) <= number < 2**31:
        raise ValueError(f'{label} exceeds the native signed 32-bit range')
    return number


def _unit(owner, stored=False):
    return {'owner': owner, 'kind': 'unit_effect_rectangle',
            'mode': 'stored_touch_rect' if stored else 'logical_position',
            'getEffectDispRectArgument': stored,
            'unitStateMayPreserveStoredRect': not stored}


def normalize_skill_placement(flags):
    """Parse layer:anchor:extra after frame/group ID, preserving optional fields.

    The native default for an absent anchor is 1. For projectile anchors only,
    absent/empty extra means one second; explicit zero remains zero seconds.
    Rectangles and projectile destinations are sampled by playBattleEffect,
    not re-read from the current animated sprite on every particle frame.
    """
    out = _result(flags, 'rawFlags')
    fields = _fields(flags, out, 1, 3)
    if fields is None:
        return out
    try:
        layer = _integer(fields[0], 'Layer')
        anchor = _integer(fields[1], 'Anchor') if len(fields) > 1 else 1
        if layer not in (1, 2):
            raise ValueError(f'Unresolved draw layer {layer}')
        if anchor not in range(1, 10):
            raise ValueError(f'Unresolved anchor {anchor}')
        out['layer'] = {'sourceValue': layer, 'name': 'rear' if layer == 2 else 'front',
                        'gameLayer': 2 if layer == 2 else 3,
                        'zOrderBase': 50 if layer == 2 else 2000}
        out['anchorValue'] = anchor
        out['anchorDefaulted'] = len(fields) == 1
        out['coordinateSystem'] = 'source_field_x_right_y_down'
        out['temporalBinding'] = 'snapshot'
        out['instances'] = 'once' if anchor in (2, 3, 4, 7) else 'per_target'
        if anchor == 1:
            start = _unit('target')
        elif anchor == 2:
            start = {'owner': 'target_side', 'kind': 'field_half_rectangle'}
        elif anchor == 4:
            start = {'owner': 'field', 'kind': 'screen_rectangle', 'origin': [0, 0],
                     'size': 'BattleManager.getFieldRect.size'}
        elif anchor in (3, 5, 7, 8):
            start = _unit('caster', anchor in (7, 8))
        else:
            start = _unit('target')
        out['startRect'] = start
        extra = fields[2] if len(fields) > 2 else None
        if anchor in (5, 6, 8, 9):
            defaulted = len(fields) < 3 or extra == ''
            if not defaulted and (isinstance(extra, bool) or not isinstance(extra, (str, int, float))):
                raise ValueError('Travel frames must be a finite nonnegative number')
            frames = 60.0 if defaulted else float(extra)
            if not math.isfinite(frames) or frames < 0:
                raise ValueError('Travel frames must be a finite nonnegative number')
            out['temporalBinding'] = 'move_to_snapshot'
            out['destinationRect'] = (_unit('target') if anchor in (5, 8)
                                      else _unit('caster', anchor == 9))
            out['destinationPivot'] = [0.5, 0.5]
            out['travelFrames'] = frames
            out['travelSeconds'] = frames / 60.0
            out['travelDefaulted'] = defaulted
            out['extraMeaning'] = 'travel_duration_source_frames'
        else:
            out['extraMeaning'] = 'unused_by_inspected_nonprojectile_path'
        out['supported'] = True
    except (ValueError, OverflowError) as error:
        out['issues'].append(str(error))
    return out


def normalize_effect_placement(raw_fields):
    """Parse one full F_EFFECT_GROUP_MST effect_frames colon item.

    Layout: frame:effectId:reverseEffectId:reserved:xMode:yMode:x:y[:reverseX:reverseY].
    Field 2 is not a loop count. A type-10 reverse effect is a flip instruction
    retaining the primary ID; other existing IDs select alternate effect art.
    Axis modes 1..3 add native jitter, 4..6 use the same alignments without it.
    """
    out = _result(raw_fields, 'rawFields')
    fields = _fields(raw_fields, out, 8, 10)
    if fields is None:
        return out
    try:
        frame, effect, reverse, reserved, xmode, ymode, x, y = (
            _integer(value, label) for value, label in zip(fields[:8],
                ('Frame', 'Effect ID', 'Reverse effect ID', 'Reserved field',
                 'X mode', 'Y mode', 'X offset', 'Y offset')))
        axes = {}
        for name, mode in (('x', xmode), ('y', ymode)):
            if mode not in range(1, 7):
                raise ValueError(f'Unresolved {name.upper()} alignment mode {mode}')
            index = (mode - 1) % 3
            axes[name] = {'sourceValue': mode, 'alignment': ('minimum', 'center', 'maximum')[index],
                          'fraction': (0.0, 0.5, 1.0)[index],
                          'jitter': {'enabled': mode <= 3, 'nativeRandomArguments': [-8, 8]}}
        reverse_offsets = []
        for index in (8, 9):
            value = fields[index] if len(fields) > index else 'none'
            reverse_offsets.append(None if value == 'none'
                                   else _integer(value, 'Reverse offset'))
        out.update(sourceFrame=frame, effectId=str(effect), reverseEffectId=str(reverse),
                   reservedField=reserved, reservedMeaning='unused_by_inspected_path',
                   axes=axes, offset=[x, y], reverseOffsets=reverse_offsets,
                   reverseOffsetDefaults=['negate_x', 'preserve_y'],
                   reverseEffectRule='type_10_flips_primary_other_existing_id_replaces_primary',
                   coordinateSystem='source_field_x_right_y_down',
                   temporalBinding='group_rectangle_snapshot', supported=True)
    except ValueError as error:
        out['issues'].append(str(error))
    return out


def resolve_effect_position(placement, rectangle, *, jitter=None, reverse=False):
    """Evaluate source axes with explicitly supplied native jitter samples.

    rectangle is x,y,width,height in the source field. This returns a logical
    position only; it never picks an effect ID, host coordinate scale or camera.
    Requiring samples avoids quietly replacing source randomness with zero.
    """
    if not placement.get('supported'):
        raise ValueError('Cannot resolve unsupported placement')
    if len(rectangle) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float))
                                 or not math.isfinite(v) for v in rectangle):
        raise ValueError('Rectangle requires four finite numbers')
    if min(rectangle[2:]) < 0:
        raise ValueError('Rectangle sizes must be nonnegative')
    axes = [placement['axes'][name] for name in ('x', 'y')]
    if jitter is None:
        if any(axis['jitter']['enabled'] for axis in axes):
            raise ValueError('Explicit source jitter samples are required')
        jitter = (0, 0)
    if len(jitter) != 2 or any(isinstance(v, bool) or not isinstance(v, int) or not -8 <= v <= 8
                               for v in jitter):
        raise ValueError('Jitter requires two integer samples within native call bounds')
    offsets = list(placement['offset'])
    if reverse:
        offsets = [(-offsets[0] if placement['reverseOffsets'][0] is None else placement['reverseOffsets'][0]),
                   (offsets[1] if placement['reverseOffsets'][1] is None else placement['reverseOffsets'][1])]
    return [rectangle[i] + rectangle[i+2] * axis['fraction'] + offsets[i]
            + (jitter[i] if axis['jitter']['enabled'] else 0)
            for i, axis in enumerate(axes)]
