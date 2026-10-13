"""Offline, source-backed scene classification and background-only cover fitting.

Anchor 4 means screen artwork, not necessarily a replacement battlefield.
Only a sustained, opaque, normally blended rear screen plate qualifies. Names,
unit IDs, rarity frames, foreground flashes and caster particles do not qualify.
The reference stage is a conversion coordinate convention, recorded in evidence;
it is not a claim to recover an arbitrary native viewport from a BMB container.
"""
from functools import lru_cache
import math

VERSION = 2


def _local_corners(sprite, rectangle, ppu):
    angle = math.radians(sprite.get('rot', 0))
    c, s = math.cos(angle), math.sin(angle)
    x, y = (v / ppu for v in sprite['pos'])
    left, bottom, right, top = rectangle
    return [((px-x)*c+(py-y)*s, -(px-x)*s+(py-y)*c)
            for px, py in ((left,bottom),(left,top),(right,bottom),(right,top))]


def cover_factor(sprite, rectangle, ppu):
    """Smallest uniform scale covering all four requested corners, even rotated."""
    w, h = sprite['uv'][2:]
    sx, sy = sprite['scale']
    hw, hh = abs(w*sx)/(2*ppu), abs(h*sy)/(2*ppu)
    if min(hw, hh) <= 0:
        return math.inf
    return max(max(abs(x)/hw, abs(y)/hh) for x,y in _local_corners(sprite, rectangle, ppu))


def classify(spawns, docs, load_texture, reference_stage=(320, 320), action_frames=None):
    width, height = reference_stage
    rectangle = [-width/2, -height/2, width/2, height/2]
    # Duration belongs to the action, not to an individual overlay. A late
    # 180-frame speed-line wipe must not turn an otherwise ordinary 340-frame
    # attack into an isolated background scene from its beginning.
    duration = action_frames or max((s['frame']+len(docs[s['file']]['frames']) for s in spawns
                                    if s.get('phase','action')=='action' and s['file'] in docs),default=1)

    @lru_cache(maxsize=512)
    def opaque(name, uv):
        # Inspect actual decoded texels, including native UV/material sampling.
        with load_texture(name) as image:
            x,y,w,h=uv
            alpha = image.convert('RGBA').getchannel('A').crop((x,y,x+w,y+h)).resize((32,32))
            pixels = alpha.tobytes()
        return sum(a >= 230 for a in pixels) / len(pixels) >= .95

    candidates = []
    for spawn in spawns:
        if (spawn.get('phase','action') != 'action' or
                spawn['anchor'] != 'screen' or spawn['layer'] != 2):
            continue
        doc = docs[spawn['file']]
        ppu = doc.get('pixelsPerUnit', 2.4)
        frames = []
        for fi, frame in enumerate(doc['frames']):
            # Spawn offsets/scales are part of source geometry, never labels.
            found = False
            for sprite in frame:
                if sprite.get('blend') != 'mix' or sprite.get('alpha',0) < .8:
                    continue
                placed = placed_sprite(sprite, spawn, ppu)
                if cover_factor(placed, rectangle, ppu) > 1.05:
                    continue
                if opaque(doc['textures'][sprite['tex']],tuple(sprite['uv'])):
                    found = True
                    break
            frames.append(found)
        longest = run = 0
        for found in frames:
            run = run + 1 if found else 0
            longest = max(longest, run)
        required = max(60, math.ceil(duration * .6))
        first_opaque = next((i for i,v in enumerate(frames) if v),len(frames)) + spawn['frame']
        if longest >= required and first_opaque <= duration*.2:
            candidates.append({'file':spawn['file'], 'groupId':spawn['groupId'],
                               'startFrame':spawn['frame'], 'opaqueFrames':sum(frames),
                               'firstOpaqueFrame':first_opaque,'longestOpaqueRun':longest, 'requiredRun':required})
    return {'version':VERSION, 'kind':'replacement_background' if candidates else
            'screen_overlay' if any(s['anchor']=='screen' for s in spawns) else 'battlefield',
            'referenceStage':list(reference_stage), 'actionFrames':duration, 'evidence':candidates,
            'rule':'action rear screen anchor + stage coverage + >=95% opaque texels + normal blending '
                   '+ >=60 frames and >=60% of action + onset within first20%'}


def placed_sprite(sprite, spawn, ppu):
    angle = math.radians(spawn.get('rotation',[0,0,0])[2])
    c, s = math.cos(angle), math.sin(angle)
    x, y = sprite['pos']
    return {**sprite, 'pos':[(x*c-y*s)*spawn['scale']+spawn['x']*ppu,
                            (x*s+y*c)*spawn['scale']-spawn['y']*ppu],
            'scale':[v*spawn['scale'] for v in sprite['scale']],
            'rot':sprite['rot']+math.degrees(angle)}


def cover_background(doc, detection, spawns, rectangle, load_texture):
    """Enlarge only opaque rear plates from detected source groups.

    Called before composition. UV motion, alpha, timing, front FX and the caster
    retain their source channels. Returns a copy and a measurable transform audit.
    """
    from copy import deepcopy
    if (not isinstance(rectangle,(list,tuple)) or len(rectangle)!=4 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in rectangle)
            or rectangle[0]>=rectangle[2] or rectangle[1]>=rectangle[3]):
        raise ValueError('Background cover rectangle requires finite left,bottom,right,top bounds')
    selected = {(e['file'],e['groupId'],e['startFrame']) for e in detection['evidence']}
    output, audit = dict(doc), {'rectangle':rectangle, 'spriteFrames':0, 'maxScale':1.0}
    ppu = doc.get('pixelsPerUnit', 2.4)
    source_width, source_height = detection['referenceStage']
    original = [-source_width/2,-source_height/2,source_width/2,source_height/2]
    relevant = [s for s in spawns if (s['file'],s['groupId'],s['frame']) in selected
                and s['anchor']=='screen' and s['layer']==2]
    if not relevant:
        return doc, audit

    @lru_cache(maxsize=512)
    def opaque(name, uv):
        with load_texture(name) as image:
            x,y,w,h=uv
            values = image.convert('RGBA').getchannel('A').crop((x,y,x+w,y+h)).resize((32,32)).tobytes()
        return sum(v>=230 for v in values)/len(values)>=.95

    output['frames'] = [deepcopy(frame) for frame in doc['frames']]
    for frame in output['frames']:
        for sprite in frame:
            if sprite.get('blend')!='mix' or not opaque(doc['textures'][sprite['tex']],tuple(sprite['uv'])):
                continue
            factor = 1.0
            for spawn in relevant:
                placed = placed_sprite(sprite, spawn, ppu)
                if cover_factor(placed, original, ppu)>1.05:
                    continue
                # Scaling about the local sprite center also preserves staging.
                factor=max(factor, cover_factor(placed,rectangle,ppu)*1.06)
            if factor>1:
                sprite['scale']=[v*factor for v in sprite['scale']]
                audit['spriteFrames']+=1
                audit['maxScale']=max(audit['maxScale'],factor)
    return output,audit


def cover_flat_flashes(doc, spawns, rectangle, load_texture, reference_stage=(320,320)):
    """Fit large solid-color flash plates while preserving their source channels.

    A source flash may be attached to any anchor and use additive blending. Only
    geometry that already covers the source stage, with an opaque and nearly
    constant-color UV cell, can grow. Textured art and smaller particles retain
    their dimensions. Call per spawn when one document is reused at many anchors.
    """
    from copy import deepcopy
    if (not isinstance(rectangle,(list,tuple)) or len(rectangle)!=4 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in rectangle)
            or rectangle[0]>=rectangle[2] or rectangle[1]>=rectangle[3]):
        raise ValueError('Flash cover rectangle requires finite left,bottom,right,top bounds')
    if (not isinstance(reference_stage,(list,tuple)) or len(reference_stage)!=2 or
            any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0
                for v in reference_stage)):
        raise ValueError('Flash reference stage requires finite positive width,height')
    ppu=doc.get('pixelsPerUnit',2.4)
    width,height=reference_stage
    original=[-width/2,-height/2,width/2,height/2]
    audit={'rectangle':list(rectangle), 'spriteFrames':0, 'maxScale':1.0}

    @lru_cache(maxsize=512)
    def flat_opaque(name, uv):
        x,y,w,h=uv
        if w<=0 or h<=0:
            return False
        # Inspect the complete selected cell. Downsampling could hide a ring,
        # small detail, or transparency that makes this a textured particle.
        with load_texture(name) as image:
            cell=image.convert('RGBA').crop((x,y,x+w,y+h))
            extrema=cell.getextrema()
            alpha=cell.getchannel('A').tobytes()
        return (bool(alpha) and sum(v>=230 for v in alpha)/len(alpha)>=.95
                and all(high-low<=3 for low,high in extrema[:3]))

    output={**doc, 'frames':[deepcopy(frame) for frame in doc['frames']]}
    for frame in output['frames']:
        for sprite in frame:
            factor=1.0
            for spawn in spawns:
                placed=placed_sprite(sprite,spawn,ppu)
                if cover_factor(placed,original,ppu)>1.05:
                    continue
                if not flat_opaque(doc['textures'][sprite['tex']],tuple(sprite['uv'])):
                    break
                factor=max(factor,cover_factor(placed,rectangle,ppu)*1.06)
            if factor>1:
                sprite['scale']=[v*factor for v in sprite['scale']]
                audit['spriteFrames']+=1
                audit['maxScale']=max(audit['maxScale'],factor)
    return output,audit


def split_viewport_flashes(doc, spawn, load_texture, reference_stage=(320, 320)):
    """Separate source-sized solid flash plates from their actor's particles.

    A large quad can be embedded in a caster BMB. Its source color, alpha and
    clock survive, but its spatial role in a wide host viewport is a full-screen
    overlay. Rings, gradients, small squares and rear backgrounds stay put.
    This is an explicit host approximation, not a changed source anchor.
    """
    from copy import deepcopy
    width, height = reference_stage
    ppu = doc.get('pixelsPerUnit', 2.4)
    original, flashes = [], []
    audit = {'policy': 'large_uniform_front_plate_to_viewport_v1',
             'sourceAnchor': spawn['anchor'], 'sourceFrames': [], 'spriteFrames': 0,
             'referenceStage': list(reference_stage), 'textures': []}
    if spawn['layer'] != 1:
        return doc, None, audit

    @lru_cache(maxsize=512)
    def flat(name, uv):
        x, y, w, h = uv
        if w <= 0 or h <= 0:
            return False
        with load_texture(name) as image:
            cell = image.convert('RGBA').crop((x, y, x+w, y+h))
            ranges = cell.getextrema()
        # Every texel must be opaque. Tiny rings and nearly opaque gradients
        # must not become a uniform flash just because a thumbnail looks flat.
        return ranges[3][0] >= 250 and all(hi-lo <= 3 for lo, hi in ranges[:3])

    for fi, frame in enumerate(doc['frames']):
        keep, screen = [], []
        for sprite in frame:
            w, h = sprite['uv'][2:]
            spans = [abs(v*s)*abs(spawn['scale'])/ppu for v, s in zip((w, h), sprite['scale'])]
            texture = doc['textures'][sprite['tex']]
            if (min(spans[0]/width, spans[1]/height) < 1
                    or not flat(texture, tuple(sprite['uv']))):
                keep.append(sprite)
                continue
            plate = deepcopy(sprite)
            plate['pos'] = [0., 0.]
            plate['rot'] = 0.
            plate['scale'] = [width*ppu/w, height*ppu/h]
            screen.append(plate)
            audit['spriteFrames'] += 1
            if texture not in audit['textures']:
                audit['textures'].append(texture)
        if screen:
            audit['sourceFrames'].append(fi + spawn['frame'])
        original.append(keep)
        flashes.append(screen)
    if not audit['spriteFrames']:
        return doc, None, audit
    return {**doc, 'frames': original}, {**doc, 'frames': flashes}, audit


def default_profile(form, source_key, detection):
    """Shared host adapter; authored move profiles may refine its camera/impact."""
    profile = {'form':form, 'sourceKey':source_key, 'canonicalVariation':True,
               'seed':12345, 'particleBudget':4096,
               'export':{'scaleMult':1.0,'addGain':1.0,'maxUnits':65536,'maxCellSize':512,
                         'runtimeScale':.8}}
    if '/lb/' in source_key:
        # One shared host framing policy. Source background replacement is
        # classified independently and ordinary abilities keep their camera.
        profile['resonanceCamera']={'mode':'participants','panFrames':12,'restoreFrames':10}
        profile['resonanceMovement']={'mode':'ground_approach'}
    if detection['kind']=='battlefield':
        return profile
    # Screen artwork belongs to the rendered viewport. The native adapter
    # attaches its player component to the camera and derives the screen plane
    # from the actual FOV/aspect. The internal SS6 root multiplier is explicit
    # so it can be removed from that fit without changing prepared source art.
    placement={'mode':'camera_plane','sourceOffset':[0,0],
               'referenceStage':list(detection['referenceStage']),
               'runtimeScale':profile['export']['runtimeScale'],
               'overscan':[1.06,1.06],
               'cameraDepth':{'front':1000,'rearMargin':300}}
    if detection['kind']=='replacement_background':
        # Source screen art does not authorize inventing caster movement. Exact
        # target staging and pans belong to an independently calibrated profile.
        placement.update(backdrop='native_subspace')
        profile['preserveSourceColor']=True
    profile['screenPlacement']=placement
    return profile
