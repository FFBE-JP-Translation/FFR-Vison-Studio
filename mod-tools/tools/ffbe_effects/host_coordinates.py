"""Source rectangle geometry and an explicit FFR coordinate adapter.

This is an offline, engine-independent contract. It does not move a host actor,
attach to an animated socket, infer a camera, or simulate the source movement
state machine. The caller supplies the logical battle state *at group dispatch*.
Evidence: FFBEWW 9.1.0 ARM64 getSize(1), resetTouchRect, getEffectDispRect and
playBattleEffect; see build/effects-followup-20260913/source-placement-evidence.md.
"""
from copy import deepcopy
import csv
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .source_placement import NATIVE_CONTRACT, resolve_effect_position

VERSION = 1
_INT = re.compile(r'[+-]?\d+\Z', re.ASCII)
_FIELDS = {
    'touchRect': ('7KYufEd5', 'touch_rect', 'TouchRect'),
    'moveOffset': ('LBye01Wi', 'move_offset', 'MoveOffset'),
    'moveSpeed': ('rB70Ls63', 'move_speed', 'MoveSpeed'),
}


def _numbers(values, count, label, *, positive=False, nonnegative=False):
    if not isinstance(values, (list, tuple)) or len(values) != count:
        raise ValueError(f'{label} requires {count} numbers')
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
        raise ValueError(f'{label} requires finite numbers')
    if positive and min(values) <= 0 or nonnegative and min(values) < 0:
        raise ValueError(f'{label} has invalid dimensions')
    return tuple(float(v) for v in values)


def _integers(value, count, label):
    fields = value.split(':') if isinstance(value, str) else value
    if not isinstance(fields, (list, tuple)) or len(fields) != count:
        raise ValueError(f'{label} requires {count} colon-separated integers')
    if any(isinstance(v, bool) or not _INT.fullmatch(str(v)) for v in fields):
        raise ValueError(f'{label} requires integers')
    result = [int(v) for v in fields]
    if any(not -(2**31) <= v < 2**31 for v in result):
        raise ValueError(f'{label} exceeds native signed integer range')
    return result


def _csv_numbers(fields, label):
    try:
        values = [float(value) for value in fields]
    except (ValueError, TypeError) as error:
        raise ValueError(f'{label} requires finite numbers') from error
    if any(not math.isfinite(v) for v in values):
        raise ValueError(f'{label} requires finite numbers')
    return values


def _field(row, name):
    present = [(key, row[key]) for key in _FIELDS[name] if key in row]
    if not present:
        raise ValueError(f'Missing unit master {name}')
    if any(value != present[0][1] for _, value in present[1:]):
        raise ValueError(f'Conflicting unit master aliases for {name}')
    return present[0][1]


def parse_unit_geometry(row, animation_size, *, provenance=None):
    """Parse raw or decoded UnitMst fields; an absent LB pair stays zero.

    animation_size is the native getSize(1) result, not the current sprite's
    alpha bounds. Empty authored touch/movement strings retain native defaults;
    missing fields and malformed values are errors rather than guessed geometry.
    """
    size = _numbers(animation_size, 2, 'Animation-1 size', nonnegative=True)
    touch_raw, move_raw = _field(row, 'touchRect'), _field(row, 'moveOffset')
    touch = [0, 0, 0, 0] if touch_raw == '' else _integers(touch_raw, 4, 'TouchRect')
    if min(touch[2:]) < 0:
        raise ValueError('TouchRect dimensions must be nonnegative')
    pairs = [] if move_raw == '' else move_raw.split(',') if isinstance(move_raw, str) else None
    if pairs is None or len(pairs) > 2:
        raise ValueError('MoveOffset requires zero, one or two comma-separated pairs')
    offsets = [_integers(pair, 2, 'MoveOffset') for pair in pairs]
    offsets += [[0, 0] for _ in range(2 - len(offsets))]
    speed = _integers([_field(row, 'moveSpeed')], 1, 'MoveSpeed')[0]
    if not 0 <= speed <= 255:
        raise ValueError('MoveSpeed exceeds native byte range')
    result = {'version': VERSION, 'nativeContract': NATIVE_CONTRACT,
              'animationId': 1, 'animationSize': list(size), 'touchRect': touch,
              'moveOffset': offsets[0], 'moveOffsetLb': offsets[1], 'moveSpeed': speed,
              'raw': {'touchRect': touch_raw, 'moveOffset': move_raw, 'moveSpeed': _field(row, 'moveSpeed')}}
    if provenance is not None:
        result['provenance'] = deepcopy(provenance)
    return result


def animation_geometry(cgg_path, animation_one_cgs_path, *, anime_scale=(1, 1)):
    """Exact getSize(1) union, without decoding any atlas pixels.

    Native 0x1eeab70 unions unrotated part [x,y,imgW,imgH] for every CGS
    referenced group, then applies EdgeAnime scaleX/Y. CGS offsets, opacity,
    rotations and alpha trimming do not participate in this native size query.
    The caller must identify animation 1; this function does not guess its name.
    """
    sx, sy = _numbers(anime_scale, 2, 'Source EdgeAnime scale', positive=True)
    paths = [Path(cgg_path), Path(animation_one_cgs_path)]
    groups = []
    with paths[0].open(encoding='utf-8-sig', newline='') as stream:
        for line, row in enumerate(csv.reader(stream), 1):
            while row and row[-1] == '':
                row.pop()
            if not row:
                groups.append([])
                continue
            if len(row) < 2:
                raise ValueError(f'CGG line {line} is incomplete')
            _, count = _integers(row[:2], 2, 'CGG header')
            if count < 0 or (count == 0 and len(row) != 2):
                raise ValueError(f'Invalid CGG part count on line {line}')
            if count and (len(row) - 2) not in (count * 10, count * 11):
                raise ValueError(f'Unsupported CGG part layout on line {line}')
            stride = (len(row) - 2) // count if count else 0
            parts = []
            for index in range(count):
                fields = _csv_numbers(row[2 + index * stride:2 + (index + 1) * stride], 'CGG part')
                x, y, width, height = fields[0], fields[1], fields[8], fields[9]
                if min(width, height) < 0:
                    raise ValueError('Negative CGG image size')
                parts.append((x, y, x + width, y + height))
            groups.append(parts)
    references = []
    with paths[1].open(encoding='utf-8-sig', newline='') as stream:
        for row in csv.reader(stream):
            while row and row[-1] == '':
                row.pop()
            if not row:
                continue
            if len(row) != 4:
                raise ValueError('CGS frame requires four fields')
            index, hold = _integers([row[0],row[3]], 2, 'CGS index/duration')
            _csv_numbers(row[1:3], 'CGS offsets')
            if not 0 <= index < len(groups) or hold < 0:
                raise ValueError('CGS references unavailable geometry or negative duration')
            references.append(index)
    parts = [part for index in references for part in groups[index]]
    bounds = ([min(p[0] for p in parts), min(p[1] for p in parts),
               max(p[2] for p in parts), max(p[3] for p in parts)] if parts else [0, 0, 0, 0])
    return {'animationId': 1, 'unscaledBounds': bounds, 'animeScale': [sx, sy],
            'size': [(bounds[2] - bounds[0]) * sx, (bounds[3] - bounds[1]) * sy],
            'cgsRows': len(references), 'referencedGroups': sorted(set(references)),
            'sources': [{'path': str(p.resolve()), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()} for p in paths]}


def load_unit_geometry(row, cgg_path, animation_one_cgs_path, *, anime_scale=(1, 1)):
    animation = animation_geometry(cgg_path, animation_one_cgs_path, anime_scale=anime_scale)
    return parse_unit_geometry(row, animation['size'], provenance={'animationGeometry': animation})


def load_unit_geometry_from_folder(row, folder, unit_id, *, anime_scale=(1, 1), allow_fallback=True):
    """Load animation 1 (idle); record bounded catalog fallbacks explicitly.

    BattleUtils::getAnimeActionName(1) returns idle (0x1b44668). A missing idle
    may use standby, then authored touch extents; those are host approximations,
    not fabricated native getSize results. No unit identity changes the policy.
    """
    if not str(unit_id).isdecimal():
        raise ValueError('Unit ID must be decimal')
    folder = Path(folder) if folder is not None else None
    cgg = folder / f'unit_cgg_{unit_id}.csv' if folder else None
    issues = ['Native live EdgeAnime scale is unavailable; the recorded source scale is used']
    if cgg and cgg.is_file():
        for name in ('idle', 'standby') if allow_fallback else ('idle',):
            cgs = folder / f'unit_{name}_cgs_{unit_id}.csv'
            if cgs.is_file():
                geometry = load_unit_geometry(row, cgg, cgs, anime_scale=anime_scale)
                geometry['provenance']['animationName'] = name
                if name != 'idle':
                    issues.append('Source idle geometry missing; standby union approximates animation 1')
                geometry['approximations'] = issues
                return geometry
    if not allow_fallback:
        raise ValueError('Source animation-1 geometry unavailable')
    touch = _field(row, 'touchRect')
    values = [0, 0, 0, 0] if touch == '' else _integers(touch, 4, 'TouchRect')
    size = [max(1, values[i] + values[i + 2]) if values[i + 2] > 0 else 64 for i in range(2)]
    geometry = parse_unit_geometry(row, size, provenance={'animationName': None, 'fallback': 'authored_touch_extents_or_64'})
    geometry['approximations'] = issues + ['Source idle and standby geometry missing; authored touch extents or 64 source pixels approximate animation 1']
    return geometry


def movement_offset(geometry, *, limit_burst=False, reverse=False):
    """Authored approach offset only; not a complete movement destination/time."""
    x, y = geometry['moveOffsetLb' if limit_burst else 'moveOffset']
    return [-x if reverse else x, y]


def single_target_approach(geometry, *, target_position, target_animation_size,
                           target_effect_size, target_kind='monster', target_left=True,
                           caster_left=False, limit_burst=False, target_attack_offset=(0, 0)):
    """Recovered horizontal endpoint; Y remains a source RNG interval.

    This evaluates the single-target approach branch after its move-type/state
    guards, not those guards themselves. A ground host adapter can explicitly
    preserve its actor's elevation instead of simulating source screen-depth Y.
    """
    tx, ty = _numbers(target_position, 2, 'Target logical position')
    tw, _ = _numbers(target_animation_size, 2, 'Target animation size', nonnegative=True)
    _, th = _numbers(target_effect_size, 2, 'Target effect size', nonnegative=True)
    ax, ay = _numbers(target_attack_offset, 2, 'Target attack offset')
    if target_kind not in ('monster', 'character'):
        raise ValueError('Target kind must be monster or character')
    caster_width = stored_touch_rectangle(geometry, [0, 0])[2]
    pivot_x = tx + tw / 2 * (1 if target_kind == 'monster' or target_left else -1)
    edge = (caster_width / 2 - 8) * (1 if target_left else -1)
    mx, my = movement_offset(geometry, limit_burst=limit_burst, reverse=caster_left)
    return {'x': pivot_x + edge + mx + ax,
            'yRandomArguments': [math.trunc(ty - th / 4), math.trunc(ty)],
            'yAfterRandomOffset': my + ay,
            'targetPivot': [pivot_x, ty], 'casterWidthContribution': edge,
            'moveOffset': [mx, my], 'targetAttackOffset': [ax, ay]}


def stored_touch_rectangle(geometry, default_position, *, reverse=False):
    x, y = _numbers(default_position, 2, 'Default logical position')
    width, height = _numbers(geometry['animationSize'], 2, 'Animation size', nonnegative=True)
    tx, ty, tw, th = _numbers(geometry['touchRect'], 4, 'TouchRect')
    rw, rh = (tw if tw else width - tx), (th if th else height - ty)
    left = x - width / 2
    # resetTouchRect has a separate reversed zero-width branch.
    rx = (left + width - tx - tw if tw else left) if reverse else left + tx
    if min(rw, rh) < 0:
        raise ValueError('TouchRect fallback produces negative size')
    return [rx, y - height + ty, rw, rh]


def effect_rectangle(geometry, logical_position, stored_rectangle, *, stored=False, preserve_stored=False):
    """getEffectDispRect: source state decides whether false keeps stored data.

    preserve_stored must be supplied for state14/dead/special bad-state paths.
    Stored rectangles may have been reset at an active position; they must not
    be regenerated from an initial host actor transform at effect activation.
    """
    rectangle = list(_numbers(stored_rectangle, 4, 'Stored rectangle'))
    if min(rectangle[2:]) < 0:
        raise ValueError('Stored rectangle dimensions must be nonnegative')
    if stored or preserve_stored:
        return rectangle
    x, y = _numbers(logical_position, 2, 'Logical position')
    width, height = geometry['animationSize']
    tx, ty = geometry['touchRect'][:2]
    return [x - width / 2 + tx, y - height + ty, *rectangle[2:]]


def source_rectangle(descriptor, *, caster=None, target=None, field_rectangle=None, target_side=None):
    """Resolve a normalizer descriptor from a sampled source battle state.

    A unit snapshot contains geometry, logicalPosition, storedRectangle and
    preserveStoredRect. target_side is explicitly left/right, never inferred
    from living targets' positions. All values use source X-right/Y-down.
    """
    kind, owner = descriptor['kind'], descriptor['owner']
    if kind == 'unit_effect_rectangle':
        unit = {'caster': caster, 'target': target}.get(owner)
        if unit is None:
            raise ValueError(f'Missing {owner} source snapshot')
        if not isinstance(unit.get('preserveStoredRect'), bool):
            raise ValueError('Unit snapshot requires explicit preserveStoredRect state')
        if descriptor.get('mode') not in ('logical_position', 'stored_touch_rect'):
            raise ValueError('Unsupported source unit rectangle mode')
        return effect_rectangle(unit['geometry'], unit['logicalPosition'], unit['storedRectangle'],
                                stored=descriptor['mode'] == 'stored_touch_rect',
                                preserve_stored=unit['preserveStoredRect'])
    x, y, width, height = _numbers(field_rectangle, 4, 'Source field rectangle')
    if min(width, height) <= 0:
        raise ValueError('Source field must have positive dimensions')
    if kind == 'screen_rectangle' and owner == 'field':
        return [0, 0, width, height]
    if kind == 'field_half_rectangle' and owner == 'target_side':
        if target_side not in ('left', 'right'):
            raise ValueError('Target field side must be explicit left/right')
        return [x + (width / 2 if target_side == 'right' else 0), y, width / 2, height]
    raise ValueError(f'Unsupported source rectangle {kind}/{owner}')


@dataclass(frozen=True)
class HostScale:
    """Existing compose/export/native scale stages, each applied once."""
    document_pixels_per_source: float = 2.4
    export_scale: float = 1.0
    units_per_pixel: float = 3.5
    runtime_scale: float = 0.8

    def __post_init__(self):
        _numbers((self.document_pixels_per_source, self.export_scale,
                  self.units_per_pixel, self.runtime_scale), 4, 'Host scales', positive=True)

    def vector(self, source_delta):
        x, y = _numbers(source_delta, 2, 'Source delta')
        doc = [x * self.document_pixels_per_source, -y * self.document_pixels_per_source]
        ss6 = [v / self.document_pixels_per_source * self.export_scale for v in doc]
        return {'sourcePixels': [x, y], 'documentPixels': doc, 'ss6Pixels': ss6,
                'worldPlane': [v * self.units_per_pixel * self.runtime_scale for v in ss6]}


def ground_approach_offset(geometry, *, limit_burst=False, scale=None):
    """Translate authored approach offsets to FFR's ground axes, once.

    An arbitrary host enemy uses the same 64x128 source proxy as target art.
    Source screen-depth Y maps to negative world X; horizontal X maps to world
    Y. Native extra clearance is disabled; elevation is preserved by the runtime
    adapter. Source battle-depth randomness is deliberately not replayed.
    """
    scale = scale or HostScale()
    x, y = movement_offset(geometry, limit_burst=limit_burst)
    factor = scale.export_scale * scale.units_per_pixel * scale.runtime_scale
    approach=single_target_approach(geometry,target_position=[0,0],
        target_animation_size=[64,128],target_effect_size=[64,128],limit_burst=limit_burst)
    return {'version': VERSION, 'sourceOffset': [x, y],
            'sourceEndpointX':approach['x'], 'casterWidthContribution':approach['casterWidthContribution'],
            'targetProxy':{'animationSize':[64,128],'effectSize':[64,128],'attackOffset':[0,0]},
            'ffrTargetOffset': [-y * factor, approach['x'] * factor, 0.0],
            'unitsPerSourcePixel': factor, 'preserveElevation': True,
            'useNativeSpacing': False, 'policy': 'source_approach_with_target_proxy'}


def binding_group_key(skill_placement, *, snapshot_frame, phase='action'):
    """Do not combine different rectangle sampling times or motion contracts."""
    if not skill_placement.get('supported'):
        raise ValueError('Cannot group unsupported source placement')
    frame = _numbers((snapshot_frame,), 1, 'Snapshot frame', nonnegative=True)[0]
    payload = {key: deepcopy(skill_placement.get(key)) for key in
               ('startRect', 'destinationRect', 'layer', 'instances', 'temporalBinding', 'travelFrames')}
    payload.update(phase=phase, snapshotFrame=frame)
    return json.dumps(payload, sort_keys=True, separators=(',', ':'), allow_nan=False)


def resolve_snapshot(skill_placement, effect_placement, *, snapshot_frame, caster=None,
                     target=None, field_rectangle=None, target_side=None, jitter=None,
                     reverse=False, scale=None):
    """Resolve one dispatched group entry and describe its host reference.

    Unit-relative vectors originate at the sampled *logical actor root*. They
    must be applied to a frozen host actor-root transform, not an animated
    socket. Field entries retain source UVs so a source-field plane/viewport
    adapter can use actual dimensions. This output does not claim native host
    application; the playback compiler is responsible for that operation.
    """
    key = binding_group_key(skill_placement, snapshot_frame=snapshot_frame)
    context = dict(caster=caster, target=target, field_rectangle=field_rectangle, target_side=target_side)
    rectangle = source_rectangle(skill_placement['startRect'], **context)
    start = resolve_effect_position(effect_placement, rectangle, jitter=jitter, reverse=reverse)
    owner = skill_placement['startRect']['owner']
    if owner in ('caster', 'target'):
        reference = list(_numbers(context[owner]['logicalPosition'], 2, 'Logical root'))
        binding = {'kind': 'actor_root_snapshot', 'owner': owner, 'sampleFrame': snapshot_frame,
                   'followActor': False, 'animatedSocket': False}
    else:
        field = source_rectangle({'kind': 'screen_rectangle', 'owner': 'field'}, **context)
        reference = [field[2] / 2, field[3] / 2]
        binding = {'kind': 'source_field_snapshot', 'owner': 'field', 'sampleFrame': snapshot_frame,
                   'fieldSize': field[2:], 'sourceUv': [start[0] / field[2], start[1] / field[3]],
                   'animatedSocket': False}
    scale = scale or HostScale()
    result = {'version': VERSION, 'nativeContract': NATIVE_CONTRACT, 'applied': False,
              'groupKey': key, 'sampleFrame': snapshot_frame, 'sourceRectangle': rectangle,
              'sourceStart': start, 'referenceSourcePosition': reference,
              'binding': binding, 'instances': skill_placement['instances'],
              'layer': deepcopy(skill_placement['layer']),
              'start': scale.vector([start[i] - reference[i] for i in range(2)])}
    if skill_placement['temporalBinding'] == 'move_to_snapshot':
        rect = source_rectangle(skill_placement['destinationRect'], **context)
        destination = [rect[i] + rect[i + 2] / 2 for i in range(2)]
        result['movement'] = {'kind': 'move_to_snapshot', 'destinationSource': destination,
                              'destination': scale.vector([destination[i] - reference[i] for i in range(2)]),
                              'travelFrames': skill_placement['travelFrames'],
                              'startAt': 'effect_activation_after_authored_wait'}
    return result


def adapt_timeline(data, geometry, *, reference_stage=(320, 320), seed=12345):
    """Apply one documented, generic source-to-host approximation policy.

    Caster placement uses that unit's source rectangle. Arbitrary host enemies
    have no FFBE MonsterPartsMst identity, so target rectangles use a fixed
    64x128 source proxy; target-side artwork uses a half-field proxy centered
    on the selected target. Screen alignment uses the supplied source stage.
    These approximations are recorded and never presented as source snapshots.
    Raw x/y, flags, source records, timing and sound events remain unchanged.
    """
    width, height = _numbers(reference_stage, 2, 'Source reference stage', positive=True)
    issues = list(geometry.get('approximations', []))
    count = 0
    for spawn in data['spawns']:
        skill, effect = spawn.get('sourceSkillPlacement'), spawn.get('sourceEffectPlacement')
        if not skill or not effect or not skill.get('supported') or not effect.get('supported'):
            if spawn.get('phase', 'action') != 'cast':
                issues.append('Some source placement fields are unresolved; their legacy offsets are retained')
            continue
        owner = skill['startRect']['owner']
        if owner == 'caster':
            rectangle = stored_touch_rectangle(geometry, [0, 0])
            if skill['startRect']['mode'] == 'logical_position':
                rectangle = effect_rectangle(geometry, [0, 0], rectangle)
            reference, host_owner = [0, 0], 'caster'
        elif owner == 'target':
            rectangle, reference, host_owner = [-32, -128, 64, 128], [0, 0], 'target'
            issues.append('Target geometry uses a 64x128 source-pixel proxy at the host actor root')
        elif owner == 'target_side':
            rectangle, reference, host_owner = [-width / 4, -height / 2, width / 2, height], [0, 0], 'target'
            issues.append('Target-side field art uses a half-field proxy centered on the first selected target')
        elif owner == 'field':
            rectangle, reference, host_owner = [0, 0, width, height], [width / 2, height / 2], 'field'
            issues.append('Screen alignment uses the shared source reference stage and native viewport adaptation')
        else:
            issues.append(f'Unresolved rectangle owner {owner}; legacy offset retained')
            continue
        identity = json.dumps([seed, spawn.get('source'), spawn.get('groupId'),
                               spawn.get('sourceGroupFrame'), effect['rawFields']], sort_keys=True)
        entropy = hashlib.sha256(identity.encode()).digest()
        jitter = [entropy[0] % 17 - 8, entropy[1] % 17 - 8]
        position = resolve_effect_position(effect, rectangle, jitter=jitter)
        sample_frame = spawn['sourceGroupFrame']
        spawn['hostCoordinates'] = {
            'version': VERSION, 'sourceRectangle': rectangle, 'sourcePosition': position,
            'sourceOffset': [position[i] - reference[i] for i in range(2)],
            'binding': 'source_field_snapshot' if host_owner == 'field' else 'actor_root_snapshot',
            'owner': host_owner, 'sampleFrame': sample_frame,
            'rectangleMode': skill['startRect'].get('mode', skill['startRect']['kind']),
            'groupKey': binding_group_key(skill, snapshot_frame=sample_frame, phase=spawn.get('phase', 'action')),
            'offsetsApplied': True, 'reverseSide': False,
            'jitter': jitter, 'jitterPolicy': 'deterministic_hash_not_native_rng',
        }
        count += 1
    if count:
        issues += ['Source placement jitter uses deterministic bounded samples; native RNG sequence is not reproduced',
                   'Source state is approximated as active; stored-rectangle state changes and reversed-party art selection are not replayed']
    placement = data.setdefault('sourcePlacement', {})
    placement.update(hostAdapter='logical_rectangle_to_root_v1', applied=bool(count),
                     appliedSpawns=count, sourceUnitGeometry=deepcopy(geometry),
                     approximations=sorted(set(issues)))
    data['issues'] = [issue for issue in data['issues'] if not issue.startswith(
        'Source rectangle alignment, per-spawn jitter and reverse-side selection are recorded;')]
    data['issues'].extend(placement['approximations'])
    return data
