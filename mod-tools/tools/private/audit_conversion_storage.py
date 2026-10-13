"""Measure shared payloads using archive manifests, without rereading textures."""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
DELIVERY=ROOT/'build/ffbe-all-animations/delivery'
OUT=ROOT/'build/animation-recovery'

def inspect(result):
    form=result['form']
    with zipfile.ZipFile(DELIVERY/(form+'.ffr')) as archive:
        index={i.filename:i for i in archive.infolist()}
        name=f'presentation/effects/{form}.json'
        if name not in index: return []
        manifest=json.loads(archive.read(name))
        return [(p,v['sha256'],v['size'],index[p].compress_size) for p,v in manifest['files'].items()]

def main():
    report=json.loads((DELIVERY/'catalog-conversion.json').read_bytes())
    unique={}; kinds=Counter(); sums=Counter(); duplicates=Counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n,entries in enumerate(pool.map(inspect,report['results']),1):
            for name,digest,size,packed in entries:
                kind=('audio' if name.startswith('audio/') else 'texture' if name.endswith(('.bgra','.bgra.z'))
                      else 'geometry' if name.endswith('/spec.json') else 'metadata')
                sums[kind]+=packed; duplicates[digest]+=1
                old=unique.get(digest)
                if old and old['size']!=size: raise ValueError('Checksum/size conflict')
                if old is None or packed<old['compressedBytes']:
                    unique[digest]={'size':size,'compressedBytes':packed,'kind':kind,'example':name}
            if n%250==0: print(f'Inspected {n}/{len(report["results"])} form manifests',flush=True)
    for item in unique.values(): kinds[item['kind']]+=item['compressedBytes']
    missing=Counter(len(r.get('failedMoves',[])) for r in report['results'])
    result={'currentArchiveBytes':sum((DELIVERY/(r['form']+'.ffr')).stat().st_size for r in report['results']),
            'payloadBytesAcrossArchives':dict(sums),'uniqueCompressedPayloadBytesEstimate':dict(kinds),
            'uniquePayloads':len(unique),'duplicateOccurrences':sum(n-1 for n in duplicates.values()),
            'exportedMissingMoveDistribution':dict(sorted(missing.items())),
            'exportsWithinThreeMissing':sum(n for missing,n in missing.items() if missing<=3),
            'exportsOverThreeMissing':sum(n for missing,n in missing.items() if missing>3),
            'measurement':'ZIP central directories and checksum manifests; unique compression estimate excludes unit sprites/ZIP metadata'}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'storage-audit.json').write_text(json.dumps(result,indent=2))
    (OUT/'payload-inventory.json').write_text(json.dumps(unique,separators=(',',':')))
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__': main()
