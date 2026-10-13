"""One-time, guarded migration for the reviewed Sept 19 lossless speed changes.

Recomputes the OLD full pipeline identity using CURRENT source inventories;
only the explicitly reviewed code hashes may differ. Receipt content hashes,
source hashes and output hashes are retained and revalidated on normal resume.
No prepared animation, audio, source archive or delivered unit is rewritten.
"""
import argparse, json, shutil, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from ffbe_effects import catalog_batch as batch
from ffbe_effects.atomic_files import write_json

ALLOWED={'tools/ffbe_effects/conversion_io.py','tools/ffbe_effects/prepare_vision.py',
         'tools/ffbe_effects/render.py','tools/ffbe_effects/catalog_batch.py',
         'tools/ffbe_effects/hca_transcode.py','tools/release/unit_assets.py',
         'tools/convert_ffbe_effects.py','tools/ffbe_effect_bundle.py'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--work',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    old=json.loads(args.report.read_bytes())['pipeline']
    current=batch.pipeline_identity(ROOT)
    changed={n for n in old['compilerFiles'].keys()|current['compilerFiles'].keys()
             if old['compilerFiles'].get(n)!=current['compilerFiles'].get(n)}
    if not changed.issubset(ALLOWED):raise ValueError('Unreviewed compiler changes: '+str(changed-ALLOWED))
    legacy=batch.pipeline_identity(ROOT,compiler_files=old['compilerFiles'])
    legacy_hash=batch.encoded_hash({'compiler':legacy['sha256'],'playbackPolicy':old['playbackPolicy']})
    if legacy_hash!=old['sha256']:raise ValueError('Source inventory/settings changed; old receipts cannot be migrated')
    new_hash=batch.encoded_hash({'compiler':current['sha256'],'playbackPolicy':old['playbackPolicy']})
    evidence={'oldPipeline':old['sha256'],'newPipeline':new_hash,
              'reviewedChanges':{n:{'before':old['compilerFiles'].get(n),'after':current['compilerFiles'].get(n)} for n in sorted(changed)},
              'sourceInventoryUnchanged':True}
    if args.apply:
        expected=json.loads(args.evidence.read_bytes())
        if any(expected.get(k)!=v for k,v in evidence.items()):raise ValueError('Code changed since migration review')
        counts={'moves':0,'forms':0}
        backup=args.evidence.parent/'original-receipts'
        for kind,key in (('receipts','moves'),('form-receipts','forms')):
            for path in (args.work/kind).rglob('*.json'):
                document=json.loads(path.read_bytes())
                field=document if kind=='receipts' else document['inputs']
                if field.get('pipeline')!=old['sha256']:continue
                saved=backup/path.relative_to(args.work)
                saved.parent.mkdir(parents=True,exist_ok=True)
                if saved.exists():
                    if json.loads(saved.read_bytes())!=document:raise ValueError('Existing backup differs: '+str(saved))
                else:shutil.copy2(path,saved)
                field['pipeline']=new_hash
                write_json(path,document,ensure_ascii=False,separators=(',',':'))
                counts[key]+=1
        evidence['migratedReceipts']=counts
        write_json(args.evidence.with_name('migration-complete.json'),evidence,indent=2)
    else:write_json(args.evidence,evidence,indent=2)
    print(json.dumps(evidence,indent=2),flush=True)

if __name__=='__main__':main()
