"""Rebuild fourteen timelines, reusing the accepted effect/audio media unchanged."""
from copy import deepcopy
from pathlib import Path
import os, sys, shutil, argparse
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step4'
PREVIOUS=ROOT/'build/effects-step3'
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).parent)]
from prepare_step3_effects import read,write
os.environ['FFR_UNIT_SPEC']=str(WORK/'units.json')
import make_vision_mod as b
import ffbe_presentation as p
import ffbe_target_camera as camera
import ffbe_resonance as sequence
import stage_cast_camera as stage

def updated_camera(old, uid):
    plan=deepcopy(old)
    action=p.action_start(plan)
    target=[e for e in plan['events'] if e['set'].get('NativeParticipantCamera_Shot') in ('targets_pan','targets_zoom')]
    assert len(target)==2 and target[1]['time']==target[0]['time']+8*800
    assert action==target[1]['time']+10*800
    boundary=target[0]['time']-7200
    shift=action-boundary
    plan['events']=[e for e in plan['events'] if e not in target]
    for e in plan['events']:
        if e['time']>=action and e['set']['EventType']!='NativeParticipantCamera': e['time']-=shift
    plan['duration']-=shift
    return camera.direct(plan,uid)

def initialize():
    WORK.mkdir(exist_ok=True)
    for name in ('units.json','focused-selection.json','installation.json','patch.json','units-built.json'):
        path=PREVIOUS/name
        if path.is_file() and not (WORK/name).exists(): shutil.copy2(path,WORK/name)
    if not (WORK/'units-before.json').exists(): shutil.copy2(PREVIOUS/'units.json',WORK/'units-before.json')
    # Never hard-link mutable assets: the cooker can overwrite files in place.
    if not (WORK/'assets').exists():
        shutil.copytree(PREVIOUS/'assets',WORK/'assets')
    for path in PREVIOUS.glob('*.acb'):
        if not (WORK/path.name).exists(): shutil.copy2(path,WORK/path.name)
    runtime=WORK/'runtime'; runtime.mkdir(exist_ok=True)
    for name in ('run.ps1','main.lua','stage.lua'): shutil.copy2(PREVIOUS/'runtime'/name,runtime/name)
    lua=(runtime/'main.lua').read_text(encoding='utf-8-sig')
    lua=lua.replace('visible=player:IsVisible()', 'visible=player:IsVisible(),sortPriority=player.TranslucencySortPriority,renderMode=player.RenderMode')
    lua=lua.replace('sample.visible=not caster.bHidden', 'sample.visible=not caster.bHidden\n                        sample.casterSortPriority=caster.m_pSsPlayerComponent.TranslucencySortPriority\n                        sample.casterRenderMode=caster.m_pSsPlayerComponent.RenderMode')
    (runtime/'main.lua').write_text(lua,encoding='utf-8')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--no-stage',action='store_true');args=parser.parse_args()
    initialize()
    b.BUILD=str(WORK);b.OUT=str(WORK/'assets')
    jobs=read(PREVIOUS/'plans.json');old_bases={j['skill']:j['plan'] for j in read(PREVIOUS/'camera-plans.json')}
    bases=[]
    for job in jobs:
        sid=job['skill'];base=updated_camera(old_bases[sid],job['vision'])
        bases.append({'vision':job['vision'],'skill':sid,'asset':job['asset'],'plan':deepcopy(base)})
        job['plan']=base
        if job.get('effectTrial'):
            profile=job['presentation']['reconstructionProfile']
            profile['visionOnTop']=True
            if sid==485130:
                from ffbe_effects.playback_policy import configure
                adjusted=configure(job['presentation'],'401007407','GL_2024/magic/20440')
                job['presentation']['visuals']=adjusted['visuals']
            job['plan']=p.apply(base,job['presentation'],job['effectTrial']['sounds'],sid)
        clone=WORK/f'clone-{sid}.json'
        write(clone,{'legacyRoot':b.LEGACY,'outRoot':b.OUT,'clones':[{
            'from':sequence.SHELL,'to':job['asset'],
            'rename':[['SEQ_Battle_440111_Cut_000',Path(job['asset']).name]]}]})
        b.run([*b.FFRDT,'patch',str(clone),'--usmap',b.USMAP])
        sequence.build(job,b.OUT,b.BUILD,b.FFRDT,b.USMAP,b.run)
        print(f'Recooked {sid}',flush=True)
    write(WORK/'plans.json',jobs);write(WORK/'camera-plans.json',bases)
    if not args.no_stage:
        stage.WORK=WORK;stage.ASSETS=Path(b.OUT);stage.stage()

if __name__=='__main__':main()
