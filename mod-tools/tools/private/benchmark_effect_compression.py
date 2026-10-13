"""Bounded real-page benchmark; never changes prepared assets or delivered units."""
import hashlib, json, sys, time, zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
import ffbe_effect_bundle as bundle

def main():
    work=ROOT/'build/conversion-optimization-20260919'
    manifest=json.loads((ROOT/'build/ffbe-all-animations/work/100011805/package-manifest.json').read_bytes())
    chosen=[]
    for move in manifest['moves'].values():
        for visual in move['visuals']:
            folder=ROOT/visual['spec']
            spec=json.loads((folder/'spec.json').read_bytes())
            for page in spec.get('cellmaps',[spec]):
                path=folder/page.get('textureFile','tex.bgra')
                if path not in chosen: chosen.append(path)
    rows=[]
    bundle.COMPRESSION_CACHE=work/'compression-benchmark-cache'
    for path in sorted(chosen,key=lambda p:p.stat().st_size,reverse=True)[:4]:
        raw=path.read_bytes()
        start=time.perf_counter(); reference=zlib.compress(raw,level=9); baseline=time.perf_counter()-start
        start=time.perf_counter(); _,cold=bundle._compress_page(raw,{}); cold_seconds=time.perf_counter()-start
        start=time.perf_counter(); _,warm=bundle._compress_page(raw,{}); warm_seconds=time.perf_counter()-start
        assert reference==cold==warm and zlib.decompress(warm)==raw
        rows.append({'path':str(path.relative_to(ROOT)),'bytes':len(raw),'compressedBytes':len(warm),
                     'baselineSeconds':baseline,'coldSeconds':cold_seconds,'warmSeconds':warm_seconds,
                     'warmSpeedup':baseline/max(.000001,warm_seconds),'identicalBytes':True})
        print(json.dumps(rows[-1]),flush=True)
    (work/'compression-benchmark.json').write_text(json.dumps(rows,indent=2))

if __name__=='__main__': main()
