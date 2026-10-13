"""Resume the effect-cooking phase without discarding verified candidate work."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json, os, shutil, subprocess, sys, threading
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step3'
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).parent)]
from prepare_step3_effects import read,write,sha
os.environ['FFR_UNIT_SPEC']=str(WORK/'units.json')
os.environ['FFR_PRESENTATION_DIR']=str(WORK/'presentation')
import make_vision_mod as b
b.BUILD=str(WORK);b.OUT=str(WORK/'assets')
assert Path(b.OUT).resolve()==(ROOT/'build/effects-step3/assets').resolve()
local=threading.local()
logs=WORK/'effect-logs';logs.mkdir(exist_ok=True)
def run(args):
    result=subprocess.run(list(map(str,args)),capture_output=True,text=True,encoding='utf-8')
    with (logs/(getattr(local,'name','finalize')+'.log')).open('a',encoding='utf-8') as f:
        f.write(result.stdout+result.stderr)
    if result.returncode: raise RuntimeError(result.stdout[-2000:]+result.stderr[-2000:])
b.run=run

def main():
    plans=read(WORK/'plans.json');assert len(plans)==14
    # The interrupted build must have completed tables, timelines, audio and sprites.
    prior=(WORK/'effects-resume-origin.log' if (WORK/'effects-resume-origin.log').exists() else ROOT/'build/effects-step3-build.log')
    text=prior.read_text(encoding='utf-8-sig').replace('\\','/').lower()
    assert '##stage building ffbe effect:' in text
    if not (WORK/'effects-resume-origin.log').exists():shutil.copy2(prior,WORK/'effects-resume-origin.log')
    effects={}
    for job in plans:
        for name,spec,donor in b.ffbe_presentation.jobs(job['presentation'],job['donor']):effects[name]=(spec,donor)
        for bank in b.ffbe_audio.banks(job.get('audio')):
            if not (WORK/'assets'/(bank['asset']+'.uasset')).exists():
                print('Cooking missing referenced sound bank', bank['name'], flush=True)
                b.ffbe_audio.build(bank,b.OUT,b.BUILD,b.FFRDT,b.USMAP,run,b.LEGACY)
    for u in b.UNITS:
        assert (WORK/f"assets/FFRS/Content/Chara/summon/summon{u['id']}/summon{u['id']}.uasset").exists()
    def cook(item):
        name,(spec,donor)=item; local.name=name
        marker=WORK/'effect-stamps'/(name+'.json')
        source=ROOT/spec/'spec.json';spec_hash=sha(source)
        if marker.exists():
            saved=read(marker)
            if saved['specSha256']==spec_hash and all((WORK/p).exists() and sha(WORK/p)==v for p,v in saved['outputs'].items()):
                print('Verified cached effect',name,flush=True);return
        data=read(source);pages=data.get('cellmaps',[data]);folder=Path(b.OUT)/'FFRS/Content/Chara/effect'/name
        suffix='_'+str(len(pages)-1) if len(pages)>1 else ''
        final=str(folder/(name+'_tex'+suffix+'.uasset')).replace('\\','/').lower()
        completed=any(('make-texture: '+final+' ') in line and 're-parse ok' in line for line in text.splitlines())
        if not completed:
            print('Cooking effect',name,flush=True);b.build_effect_project(name,spec,donor)
        else: print('Retained verified effect',name,flush=True)
        outputs={str(p.relative_to(WORK)):sha(p) for p in folder.iterdir() if p.suffix in ('.uasset','.uexp','.ubulk')}
        assert len(outputs)>=2*(len(pages)+1),(name,'incomplete cooked effect')
        marker.parent.mkdir(exist_ok=True)
        write(marker,{'specSha256':spec_hash,'outputs':outputs})
        print('Completed effect',name,flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(cook,effects.items()))
    tables={}
    def tbl(rel):return tables.setdefault(rel,{'asset':b.DT+rel,'add':[],'set':[]})
    native=b.vision_icons.registry_rows(b.LEGACY,str(WORK/'native-command-tags.json'),b.FFRDT,b.USMAP,b.ffrenv.RETOC,b.ffrenv.detect_game())
    registry=b.vision_icons.registry_patch(b.UNITS,native)
    icons=b.skill_icons.prepare(b.UNITS,tbl,b.row_by,registry)
    b.skill_icons.build(icons,b.LEGACY,b.OUT,b.BUILD,b.FFRDT,b.USMAP,run)
    write(WORK/'units-built.json',b.UNITS)
    import stage_cast_camera as stage
    stage.WORK=WORK;stage.ASSETS=Path(b.OUT);stage.stage()
    runtime=WORK/'runtime';runtime.mkdir(exist_ok=True)
    for name in ('run.ps1','main.lua','stage.lua'):shutil.copy2(ROOT/'build/target-camera-step2-retry/runtime'/name,runtime/name)
    from step3_runtime import configure
    configure(runtime)
    print('All effects cooked and the complete candidate staged.',flush=True)

if __name__=='__main__':main()
