"""Compare lossless compression on representative existing prepared files."""
import json, sys, time, zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
manifest=json.loads((ROOT/'build/ffbe-all-animations/work/manifests/100000107.json').read_bytes())
projects={ROOT/v['spec'] for m in manifest['moves'].values() for v in m.get('visuals',[])}
spec=max((p/'spec.json' for p in projects),key=lambda p:p.stat().st_size)
texture=max((p for folder in projects for p in folder.glob('*.bgra')),key=lambda p:p.stat().st_size)
rows=[]
for path in (spec,texture):
    raw=path.read_bytes()
    for level in (1,3,6,9):
        start=time.perf_counter(); packed=zlib.compress(raw,level); seconds=time.perf_counter()-start
        assert zlib.decompress(packed)==raw
        row={'file':str(path.relative_to(ROOT)),'bytes':len(raw),'level':level,'packedBytes':len(packed),'seconds':round(seconds,3)}
        rows.append(row);print(json.dumps(row),flush=True)
(ROOT/'build/animation-recovery/compression-benchmark.json').write_text(json.dumps(rows,indent=2))
