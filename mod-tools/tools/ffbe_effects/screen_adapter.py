"""Keep source screen framing on a declared native camera trajectory.

An adapter moves the original screen sprites; it never paints replacement art.
The camera and groups are explicit, auditable host layout data. Particle sources,
UVs, colors, opacity and event clocks remain unchanged.
"""
from copy import deepcopy
import math


def _point(value, label):
    if not isinstance(value,list) or len(value)!=2 or any(
            type(v) not in (int,float) or not math.isfinite(v) for v in value):
        raise ValueError(label+' must have two finite coordinates')
    return value


def _camera(camera):
    if not isinstance(camera,dict):
        raise ValueError('Screen camera must be a camera profile')
    _point(camera.get('sourceCenter'),'Screen camera source center')
    pans=camera.get('pan',[])
    if not isinstance(pans,list):
        raise ValueError('Screen camera pan must be a list')
    prior_end=0
    for pan in pans:
        if not isinstance(pan,dict) or set(pan)-{'frame','durationFrames','sourceCenter','focalLength','easing'}:
            raise ValueError('Screen camera pan contains unsupported fields')
        start,duration=pan.get('frame'),pan.get('durationFrames')
        if type(start) is not int or start<=0 or type(duration) is not int or not 1<=duration<=3600 or start<prior_end:
            raise ValueError('Screen camera pans require positive, ordered, non-overlapping intervals')
        _point(pan.get('sourceCenter'),'Screen camera pan center')
        if pan.get('easing','EaseInOut') not in ('Linear','EaseInOut','EaseIn','EaseOut'):
            raise ValueError('Unsupported screen camera interpolation')
        if 'focalLength' in pan and (type(pan['focalLength']) not in (int,float) or
                not math.isfinite(pan['focalLength']) or pan['focalLength']<=0):
            raise ValueError('Screen camera focal length must be finite and positive')
        prior_end=start+duration


def camera_center(camera, frame):
    center = list(camera['sourceCenter'])
    for pan in camera.get('pan', []):
        start, duration = pan['frame'], pan['durationFrames']
        if frame < start:
            break
        if frame >= start + duration:
            center = list(pan['sourceCenter'])
            continue
        alpha = (frame - start) / duration
        easing = pan.get('easing', 'EaseInOut')
        if easing == 'EaseInOut':
            alpha = 2*alpha*alpha if alpha < .5 else 1-2*(1-alpha)*(1-alpha)
        elif easing == 'EaseIn':
            alpha *= alpha
        elif easing == 'EaseOut':
            alpha = 1-(1-alpha)*(1-alpha)
        elif easing != 'Linear':
            raise ValueError('Unsupported camera interpolation '+str(easing))
        return [a+(b-a)*alpha for a,b in zip(center,pan['sourceCenter'])]
    return center


def resolve(config, spawns, placement, viewport):
    if config is None:
        return {}
    if not isinstance(config,list) or not config:
        raise ValueError('Screen camera groups require a nonempty adapter list')
    if not isinstance(placement,dict) or not placement.get('camera'):
        raise ValueError('Screen camera groups require a declared native camera')
    if placement.get('mode','target_stage')!='target_stage':
        raise ValueError('Screen camera groups require the native target stage camera')
    _point(placement.get('sourceOffset'),'Screen camera source offset')
    _camera(placement['camera'])
    if viewport is not None and not isinstance(viewport,dict):
        raise ValueError('Screen camera viewport must be a profile')
    stretch = viewport.get('stretchX') if viewport is not None else 1.
    if type(stretch) not in (float,int) or not math.isfinite(stretch) or stretch <= 0:
        raise ValueError('Screen camera stretch must be positive and finite')
    pivot=_point(viewport.get('center'),'Screen camera viewport center') if viewport is not None else placement['sourceOffset']
    retained = {s['groupId'] for s in spawns if s['anchor']=='screen'}
    output = {}
    for item in config:
        if not isinstance(item,dict) or set(item) != {'groupIds','sourceCenter','scale'}:
            raise ValueError('Screen camera group requires groupIds, sourceCenter and scale')
        ids, center, scale = item['groupIds'], item['sourceCenter'], item['scale']
        if not isinstance(ids,list) or not ids or any(not isinstance(v,str) or not v for v in ids):
            raise ValueError('Screen camera group IDs must be source group strings')
        if not isinstance(center,list) or len(center)!=2 or any(type(v) not in (float,int) or not math.isfinite(v) for v in center):
            raise ValueError('Screen camera source center must have two finite coordinates')
        if type(scale) not in (float,int) or not math.isfinite(scale) or scale<1:
            raise ValueError('Screen camera scale must be finite and at least one')
        for group in ids:
            if group not in retained or group in output or any(s['anchor']!='screen' for s in spawns if s['groupId']==group):
                raise ValueError('Screen camera group must identify one retained screen group')
            output[group] = {'sourceCenter':center,'scale':scale,
                             'camera':placement['camera'],'offset':placement['sourceOffset'],
                             'stretchX':stretch,'viewportCenter':pivot}
    return output


def transform(sprite, spawn, frame, adapter, ppu=2.4):
    """Run after source spawn placement, before the shared screen offset/stretch."""
    output=deepcopy(sprite)
    center=camera_center(adapter['camera'],frame)
    source=adapter['sourceCenter']
    scale=adapter['scale']
    # Runtime stretches X around the declared viewport center. Invert it so
    # the final screen center follows the actual camera rather than 1.5x its pan.
    pivot=adapter['viewportCenter']
    destination=[(center[0]-pivot[0])/adapter['stretchX']+(pivot[0]-adapter['offset'][0]),
                  center[1]-adapter['offset'][1]]
    angle=math.radians(spawn.get('rotation',[0,0,0])[2])
    c,s=math.cos(angle),math.sin(angle)
    origin=[(source[0]*c-source[1]*s)*spawn['scale']+spawn.get('x',0),
            (source[0]*s+source[1]*c)*spawn['scale']-spawn.get('y',0)]
    for axis in (0,1):
        output['pos'][axis]=(sprite['pos'][axis]-origin[axis]*ppu)*scale+destination[axis]*ppu
        output['scale'][axis]=sprite['scale'][axis]*scale
    return output
