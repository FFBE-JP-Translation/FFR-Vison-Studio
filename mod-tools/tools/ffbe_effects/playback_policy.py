"""Portable settings for the accepted cast → targets → source-effects sequence."""
from copy import deepcopy

def configure(entry, form, key):
    result=deepcopy(entry)
    profile=result.setdefault('reconstructionProfile',{})
    profile.update(form=str(form),sourceKey=key,cameraSequence='cast_target',
                   visionOnTop=True,allTargetEffects=True,preserveSourceColor=True)
    for field in ('attackDirector','resonanceCamera','resonanceMovement','casterPlacement'):
        profile.pop(field,None)
    if str(form)=='401007407' and key=='GL_2024/magic/20440':
        # Ultima's main blast is source frame 41, distinct from its frame-40
        # viewport flash and backdrop. Lift this art by 12% of viewport height.
        for fx in result.get('visuals',[]):
            if fx['anchor']=='screen' and fx['layer']==1 and fx['frame']==41:
                fx['viewportRise']=.12
    placement=profile.get('screenPlacement')
    if placement and placement.get('mode')=='camera_plane':
        placement['fit']='cover'
        if result.get('backgroundDetection',{}).get('kind')=='replacement_background':
            placement.update(backdrop='native_subspace',backdropTiming='action')
        for fx in result.get('visuals',[]):
            if fx.get('placement',{}).get('mode')=='camera_plane':
                fx['placement']['fit']='cover'
    return result
