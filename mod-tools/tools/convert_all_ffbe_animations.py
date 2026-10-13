"""Plan, then explicitly run a resumable catalog → forms → active moves conversion.

The default only writes an inventory. --execute prepares effects and merges them
into staged .ffr unit files; neither mode installs or publishes anything.
"""
import argparse, json
from pathlib import Path
import convert_ffbe_effects as converter
from ffbe_effects.catalog_coverage import load_catalog
from ffbe_effects.atomic_files import write_json

ROOT=Path(__file__).resolve().parents[1]

def plan(root, catalog_path, unit_dir, output):
    catalog=load_catalog(catalog_path)
    forms=[]
    for form in catalog['forms']:
        source=unit_dir/(form+'.ffr')
        destination=output/(form+'.ffr')
        if source.resolve()==destination.resolve(): raise ValueError('Output must be separate from source unit archives')
        native=root/'data/ffbe/native_kits'/(form+'.json')
        record={'form':form,'vision':catalog['owners'][form],'sourceUnit':str(source.resolve()),
                'sourceUnitAvailable':source.is_file(),'nativeKitAvailable':native.is_file(),
                'destination':str(destination.resolve()),'readyActiveMoves':[],'heldActiveMoves':[]}
        if native.is_file():
            data=json.loads(native.read_bytes())
            for entry in data['kit']['entries']:
                if entry['kind']=='PASSIVE':continue
                record['readyActiveMoves' if entry['status']=='ready' else 'heldActiveMoves'].append(entry['sourceKey'])
        forms.append(record)
    return {'schema':'ffr-animation-conversion-plan-1','operation':'inventory-only',
            'visions':len(catalog['units']),'forms':forms,'formCount':len(forms),
            'readyActiveMoveMemberships':sum(len(f['readyActiveMoves']) for f in forms),
            'heldActiveMoveMemberships':sum(len(f['heldActiveMoves']) for f in forms),
            'missingUnitArchives':sum(not f['sourceUnitAvailable'] for f in forms),
            'missingNativeKits':sum(not f['nativeKitAvailable'] for f in forms),
            'playbackPolicy':'cast-target','publication':'deferred; staged files only'}

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=ROOT/'build/devui/ffbe_index.json')
    parser.add_argument('--unit-dir',type=Path,default=ROOT/'build/native-editor/host/ffbe/units')
    parser.add_argument('--out',type=Path,default=ROOT/'build/ffbe-all-animations/delivery')
    parser.add_argument('--work',type=Path,default=ROOT/'build/ffbe-all-animations/work')
    parser.add_argument('--execute',action='store_true',help='Actually convert and bundle; omit to write the plan only')
    parser.add_argument('--pilot',type=int,help='Convert only the first N catalog forms; completion remains explicitly partial')
    parser.add_argument('--fresh',action='store_true',help='Ignore receipts; default resumes checksum-verified work')
    parser.add_argument('--workers',type=int,default=4,help='Parallel form workers, 1-8 (default 4)')
    parser.add_argument('--continue-pass',action='store_true',help='Resume an interrupted pass without retrying already reported gaps')
    args=parser.parse_args(argv)
    if args.pilot is not None and args.pilot<=0:parser.error('--pilot must be positive')
    if not 1<=args.workers<=8:parser.error('--workers must be between 1 and 8')
    report=plan(ROOT,args.catalog,args.unit_dir,args.out)
    args.out.mkdir(parents=True,exist_ok=True)
    write_json(args.out/'conversion-plan.json',report,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in report.items() if k!='forms'},indent=2),flush=True)
    if not args.execute:
        print('Inventory saved. Add --execute when ready; no effects converted or units deployed.')
        return
    # Use the existing tested recursive source closure and per-move/form
    # receipts. Failures remain visible and are retried on the next run.
    options=['--catalog','--catalog-index',str(args.catalog),'--unit-dir',str(args.unit_dir),
             '--out',str(args.out),'--work',str(args.work),'--playback-policy','cast-target','--workers',str(args.workers)]
    if not args.fresh:options.append('--resume')
    if args.continue_pass:options.append('--continue-pass')
    if args.pilot:options+=['--limit-forms',str(args.pilot)]
    converter.main(options)

if __name__=='__main__':main()
