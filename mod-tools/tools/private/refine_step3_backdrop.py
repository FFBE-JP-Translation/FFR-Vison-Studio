"""Recook only the Rain/Fina timeline with action-timed backdrop activation."""
from pathlib import Path
import json, os, sys
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step3'
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).parent)]
from prepare_step3_effects import read,write
os.environ['FFR_UNIT_SPEC']=str(WORK/'units.json')
import make_vision_mod as b
import ffbe_presentation as p
import ffbe_resonance as sequence
import stage_cast_camera as stage
b.BUILD=str(WORK);b.OUT=str(WORK/'assets')

def main():
    jobs=read(WORK/'plans.json')
    job=next(j for j in jobs if j['skill']==444040)
    before=job['plan']
    job['presentation']['reconstructionProfile']['screenPlacement']['backdropTiming']='action'
    base=next(j['plan'] for j in read(WORK/'camera-plans.json') if j['skill']==444040)
    job['plan']=p.apply(base,job['presentation'],job['effectTrial']['sounds'],444040)
    setup=lambda e:e['set']['EventType'].startswith('OtherChangeSubSpace') or e['set']['EventType']=='BGChange'
    assert [e for e in before['events'] if not setup(e)]==[e for e in job['plan']['events'] if not setup(e)]
    clone=WORK/'rain-backdrop-clone.json'
    write(clone,{'legacyRoot':b.LEGACY,'outRoot':b.OUT,'clones':[{
        'from':sequence.SHELL,'to':job['asset'],
        'rename':[['SEQ_Battle_440111_Cut_000',Path(job['asset']).name]]}]})
    b.run([*b.FFRDT,'patch',str(clone),'--usmap',b.USMAP])
    sequence.build(job,b.OUT,b.BUILD,b.FFRDT,b.USMAP,b.run)
    write(WORK/'plans.json',jobs)
    stage.WORK=WORK;stage.ASSETS=Path(b.OUT);stage.stage()
    print('Rain/Fina background transition moved to action; every other event is unchanged.')

if __name__=='__main__':main()
