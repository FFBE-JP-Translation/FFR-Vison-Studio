"""Editable host presentation. Uses prepared media only, never FFBE decoders.

Source timelines use 60 Hz; native camera and movement durations use 30 Hz.
Offsets are SpriteStudio units, positive X right and positive Y up.
"""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = ROOT / 'data/ffbe/presentation/attack-settings.json'
SCHEMA = 'ffr-attack-director-1'
DEFAULTS = dict(castZoom=1.15, actionZoom=1.15, castX=.55, castY=.52,
                actionX=.5, actionY=.52, frameHeight=.6, panFrames=10,
                restoreFrames=10, camera=True, hideMovingAura=True,
                hideLbNonParticipants=True, backgroundMode='target',
                scale=1., offsetX=0., offsetY=0., backDepth=40., frontDepth=-40.,
                layers={})
RANGES = dict(castZoom=(.5,3.), actionZoom=(.5,3.), castX=(.15,.85),
              castY=(.2,.8), actionX=(.15,.85), actionY=(.2,.8),
              frameHeight=(.1,.75), panFrames=(1,120), restoreFrames=(1,120),
              scale=(.05,8), offsetX=(-2000,2000), offsetY=(-2000,2000),
              backDepth=(1,1000), frontDepth=(-1000,-1))
LAYER_RANGES = dict(scale=(.05,8), offsetX=(-2000,2000), offsetY=(-2000,2000), depth=(-1000,1000))


def validate(value, *, partial=False):
    if not isinstance(value, dict) or set(value)-set(DEFAULTS):
        raise ValueError('Unknown attack setting')
    out = deepcopy(value if partial else {**DEFAULTS, **value})
    for name, val in out.items():
        if name in RANGES:
            low, high = RANGES[name]
            if type(val) not in (int,float) or not math.isfinite(val) or not low <= val <= high:
                raise ValueError(f'{name} must be between {low} and {high}')
            if name.endswith('Frames') and type(val) is not int:
                raise ValueError(f'{name} must be a whole number')
        elif name in ('camera','hideMovingAura','hideLbNonParticipants'):
            if type(val) is not bool: raise ValueError(f'{name} must be true or false')
        elif name == 'backgroundMode':
            if val not in ('target','screen','hidden'): raise ValueError('Unknown background placement')
        elif name == 'layers':
            if not isinstance(val, dict) or len(val)>2048: raise ValueError('Invalid layer settings')
            for key, layer in val.items():
                if not isinstance(key,str) or len(key)>180 or not isinstance(layer,dict):
                    raise ValueError('Invalid layer identifier')
                if set(layer)-set(LAYER_RANGES)-{'enabled','anchor','order'}: raise ValueError('Unknown layer control')
                for field, number in layer.items():
                    if field in LAYER_RANGES:
                        lo,hi=LAYER_RANGES[field]
                        if type(number) not in (int,float) or not math.isfinite(number) or not lo<=number<=hi:
                            raise ValueError(f'Layer {field} must be between {lo} and {hi}')
                    elif field=='enabled' and type(number) is not bool: raise ValueError('Layer enabled must be boolean')
                    elif field=='anchor' and number not in ('source','caster','target','screen'): raise ValueError('Unknown layer anchor')
                    elif field=='order' and number not in ('source','back','front'): raise ValueError('Unknown layer order')
    return out


def read_settings(path=None):
    path=Path(path or os.environ.get('FFR_ATTACK_SETTINGS') or SETTINGS)
    if not path.is_file(): return {'schema':SCHEMA,'defaults':{},'moves':{}}
    doc=json.loads(path.read_text(encoding='utf-8-sig'))
    if doc.get('schema')!=SCHEMA or not isinstance(doc.get('moves'),dict): raise ValueError('Unsupported attack settings file')
    validate(doc.get('defaults',{}),partial=True)
    return doc


def resolve(form, key, entry=None, document=None):
    doc=read_settings() if document is None else document
    embedded=(entry or {}).get('reconstructionProfile',{}).get('attackDirector',{})
    chosen=doc.get('moves',{}).get(str(form),{}).get(key,{})
    # A bundle remains portable; explicit local choices win over its saved settings.
    return validate({**DEFAULTS, **embedded, **doc.get('defaults',{}), **chosen})


def layer_key(fx, index):
    return f"{fx.get('name','layer')}:{index}"


def configure(entry, settings):
    """Stage policy without rewriting source geometry, timings or provenance."""
    entry=deepcopy(entry)
    profile=entry.setdefault('reconstructionProfile',{})
    for field in ('resonanceCamera','resonanceMovement','screenPlacement','casterPlacement'):
        profile.pop(field,None)
    profile['attackDirector']=validate(settings)
    profile['preserveSourceColor']=True
    return entry


def materialize(entry, settings, root=ROOT):
    """Copy-on-write transforms of prepared SS projects; original art stays reusable."""
    entry=configure(entry,settings)
    visuals=[]
    for index, source in enumerate(entry.get('visuals',[])):
        fx=deepcopy(source)
        override=settings['layers'].get(layer_key(fx,index),{})
        if not override.get('enabled',True): continue
        order=override.get('order','source')
        fx['layer']={'back':2,'front':1}.get(order,fx['layer'])
        rear=fx['layer']!=1
        if rear and source['anchor']=='screen' and settings['backgroundMode']=='hidden': continue
        anchor=override.get('anchor','source')
        if anchor=='source':
            anchor='target' if source['anchor']=='screen' and rear and settings['backgroundMode']=='target' else source['anchor']
        fx['anchor']={'target':'target_group'}.get(anchor,anchor)
        plane=source.get('placement',{})
        if fx['anchor']=='screen':
            # Front flashes still fill the viewport; the battlefield never changes.
            fx['placement']={'mode':'camera_plane','sourceOffset':[0,0],
                'referenceStage':plane.get('referenceStage',[320,320]),
                'runtimeScale':plane.get('runtimeScale',1.),'overscan':[1.1,1.1],
                'cameraDepth':{'front':128.,'rearMargin':64.}}
            fx.pop('sourceCoordinates',None)
        else:
            fx.pop('placement',None)
            if fx['anchor'] != source['anchor']:
                fx['partName']='root'
                fx['sourceCoordinates']={'binding':'actor_root_snapshot','offsetsApplied':True,
                    'owner':'caster' if fx['anchor']=='caster' else 'target',
                    'sampleFrame':fx['frame'],'rectangleMode':'host_override'}
        fx['_directorDepth']=override.get('depth',settings['backDepth'] if rear else settings['frontDepth'])
        if fx['anchor']=='screen':
            # Screen planes are camera children: use the same depth adjustment
            # relative to their normal front distance / rear clearance. Scaling
            # to the viewport remains the native screen helper's responsibility.
            delta=fx['_directorDepth']-DEFAULTS['backDepth' if rear else 'frontDepth']
            fx['placement']['cameraDepth']['front']=max(64.,128.+delta)
            fx['placement']['cameraDepth']['rearMargin']=max(1.,64.+delta)
        factor=settings['scale']*override.get('scale',1.)
        dx=settings['offsetX']+override.get('offsetX',0.)
        dy=settings['offsetY']+override.get('offsetY',0.)
        folder=(root/source['spec']).resolve()
        if not folder.is_relative_to(root.resolve()): raise ValueError('Prepared effect path escapes the project')
        raw=(folder/'spec.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=source['checksums']['spec.json']: raise ValueError('Prepared effect spec changed')
        spec=json.loads(raw)
        # Remove historical screen stretching when returning a backdrop to world space.
        remove_viewport='runtimeViewport' in spec
        if fx['anchor']=='screen': fx['placement']['runtimeScale']=spec.get('runtimeScale',1.)
        if factor!=1 or dx or dy or remove_viewport:
            identity=hashlib.sha256(raw+json.dumps([factor,dx,dy,remove_viewport]).encode()).hexdigest()[:20]
            name='FFBE_Edit_'+identity
            dest=root/'data/ffbe/presentation/assets'/name
            dest.mkdir(parents=True,exist_ok=True)
            spec.pop('runtimeViewport',None)
            spec['animePackName']=name
            root_name=spec['model']['parts'][0]['name']
            for anim in spec['animations']:
                attrs=anim.setdefault('parts',{}).setdefault(root_name,{})
                # Set defaults only in Setup; transform any explicit action keys too.
                for field,mult,plus,default in (('Sclx',factor,0,1),('Scly',factor,0,1),('Posx',1,dx,0),('Posy',1,dy,0)):
                    if field in attrs or anim.get('isSetup'):
                        attrs[field]=[[t,v*mult+plus] for t,v in attrs.get(field,[[0,default]])]
            cooked=json.dumps(spec,ensure_ascii=False,separators=(',',':')).encode()
            checks={**source['checksums'],'spec.json':hashlib.sha256(cooked).hexdigest()}
            for filename in source['checksums']:
                target=(dest/filename).resolve(); src=(folder/filename).resolve()
                if not target.is_relative_to(dest.resolve()) or not src.is_relative_to(folder): raise ValueError('Invalid media path')
                if filename=='spec.json': continue
                if not target.exists():
                    try: os.link(src,target)
                    except OSError: shutil.copyfile(src,target)
            temp=dest/'spec.json.tmp'
            temp.write_bytes(cooked); temp.replace(dest/'spec.json')
            fx.update(name=name,spec=dest.relative_to(root).as_posix(),asset=f'/Game/Chara/effect/{name}/{name}',checksums=checks)
        visuals.append(fx)
    entry['visuals']=visuals
    return entry


def direct(plan, entry, settings, visual_end=0):
    """Cast focus and caster follow around an existing source action clock."""
    plan=deepcopy(plan); events=plan['events']; uid=entry['_hostVisionUnitId']
    action=next(e['time'] for e in events if e['set'].get('Unit_PlayAnimByName_AnimationName') in ('LB1','attack_A','magic_attack'))
    approaches=[e for e in events if e['set']['EventType']=='UnitMoveToTarget' and e['set'].get('Unit_MoveToTarget_IsVisionUnit')]
    if len(approaches)>1: raise ValueError('Attack director expects one approach per action')
    move=approaches[0] if approaches else None
    preparation=[e['time'] for e in events if e['set'].get('Unit_PlayAnimByName_AnimationName') in ('command','magic_idle','LB1_before','LB1_charge','step_front')]
    begin=max(3,min([action,*preparation,*(e['time'] for e in approaches)])-2)
    returns=[e['time']+e['set'].get('Unit_MoveToDefaultLocation_Frame',0)*800 for e in events if e['set']['EventType']=='UnitMoveToDefaultLocation']
    finish=max([visual_end+400,action+400,*returns,*(e['time'] for e in events if e['set'].get('Unit_PlayAnimByName_AnimationName')=='idle')])+2
    events[:]=[e for e in events if e['set']['EventType']!='CameraSetDefault' or e['time']<begin]
    def at(t,kind,**fields): events.append({'time':int(t),'set':{'EventType':kind,**fields}})
    if move and settings['hideMovingAura']:
        at(begin,'NativeAuraVisibility',NativeAura_UnitId=uid,NativeAura_IsVisible=False)
        at(finish,'NativeAuraVisibility',NativeAura_UnitId=uid,NativeAura_IsVisible=True)
    if entry.get('_hostResonance') and settings['hideLbNonParticipants']:
        # This helper changes only actors it tags. Aura is independently controlled.
        at(begin,'NativeResonanceVisibility',NativeResonanceVisibility_UnitId=uid,NativeResonanceVisibility_Restore=False,NativeResonanceVisibility_HideAura=False)
        at(finish+1,'NativeResonanceVisibility',NativeResonanceVisibility_UnitId=uid,NativeResonanceVisibility_Restore=True,NativeResonanceVisibility_HideAura=False)
    if settings['camera']:
        def camera(t,shot,zoom,x,y,frames,extra=None):
            at(t,'NativeParticipantCamera',NativeParticipantCamera_UnitId=uid,
               NativeParticipantCamera_Frame=frames,NativeParticipantCamera_Shot=shot,
               NativeParticipantCamera_CenterX=x,NativeParticipantCamera_CenterY=y,
               NativeParticipantCamera_HeightFraction=min(settings['frameHeight'],2*min(y-.05,.95-y)),
               NativeParticipantCamera_ZoomFactor=zoom,**(extra or {}))
        # Cast first, then follow the actual actor. A destination snapshot before
        # movement points at empty space and cannot follow the moving vision.
        cast_time=entry.get('_castSoundTick',begin+1)
        # Stationary attacks may begin while the opening sound is still
        # playing. Keep the gentle blend instead of snapping to fit a short
        # casting pose; only travel needs to take over the camera early.
        cast_end=move['time'] if move else cast_time+settings['panFrames']*800
        blend=max(1,min(settings['panFrames'],(cast_end-cast_time)//800))
        camera(cast_time,'caster',settings['castZoom'],settings['castX'],settings['castY'],blend)
        if move:
            # Native FFR movement, like camera blends, runs at 30 Hz. The
            # FFBE sprite/hit clock runs at 60 Hz. Mixing them stops the pan
            # halfway through the approach in an actual battle.
            arrival=move['time']+move['set']['Unit_MoveToTarget_Frame']*800
            # Each one-frame native blend measures the current actor again.
            # Include a final snapshot after arrival, including odd source-frame
            # durations. Never switch to a target/group shot during this step.
            tick=max(move['time'],cast_time+blend*800)
            while tick < arrival:
                camera(tick,'caster',settings['castZoom'],settings['castX'],settings['castY'],1)
                tick+=800
            camera(max(tick,arrival+1),'caster',settings['castZoom'],settings['castX'],settings['castY'],1)
        at(finish+2,'CameraSetDefault',Camera_SetDefault_Frame=settings['restoreFrames'],Camera_SetDefault_IsRotation=True,
           Camera_SetDefault_IsLocation=True,Camera_SetDefault_IsZoomInOut=True)
    if move:
        fields=move['set']
        move['set']={'EventType':'NativeGroundApproach','NativeGroundApproach_UnitId':uid,
            'NativeGroundApproach_Frame':fields['Unit_MoveToTarget_Frame'],
            'NativeGroundApproach_PartName':fields['Unit_MoveToTarget_PartName'],
            'NativeGroundApproach_Offset':{**fields['Unit_MoveToTarget_AddLocation'],'z':0.}}
    plan['duration']=max(plan['duration'],finish+settings['restoreFrames']*800+3)
    plan['events']=sorted(events,key=lambda e:e['time'])
    return plan
