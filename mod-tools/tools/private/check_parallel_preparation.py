"""Re-prepare four existing source moves concurrently and compare full metadata."""
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import json, sys, time
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))

def check(selection):
    import convert_ffbe_effects
    import prepare_vision as prepare
    from ffbe_effects.regional_assets import staged
    form,key=selection
    work=ROOT/'build/conversion-optimization-20260919/source-check'/form/key.replace('/','_')
    prepare.WORK=work
    prepare.CACHE=ROOT/'build/ffbe-all-animations/work/decoded'
    native=prepare.native_kit(form)
    expected=json.loads((ROOT/'build/ffbe-all-animations/work/manifests'/(form+'.json')).read_bytes())['moves'][key]
    start=time.perf_counter()
    with staged(prepare,native['profiles'][key]['snapshot'],work/'regional-source'):
        audit=prepare.prepare([form],[key],None,detect_scene=True,merge_existing=True,
                              make_previews=False,universal=True,manifest_out=work/'manifest.json')
    actual=audit['forms'][form]['moves'][key]
    assert actual==expected,(form,key,[k for k in actual.keys()|expected.keys() if actual.get(k)!=expected.get(k)])
    return {'form':form,'move':key,'identicalPreparedEntry':True,'seconds':time.perf_counter()-start}

def main():
    selections=[('100000103','GL_2024/magic/20010'),('100000103','GL_2024/magic/20080'),
                ('100000202','GL_2024/ability/200320'),('100000202','GL_2024/lb/100000202/level/5')]
    with ProcessPoolExecutor(max_workers=4) as pool: results=list(pool.map(check,selections))
    (ROOT/'build/conversion-optimization-20260919/source-comparison.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2),flush=True)

if __name__=='__main__':main()
