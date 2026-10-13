"""Reconvert the existing FFBE source catalog and package FFR mechanics output.

No game launch, native-hook build, installation or network access is performed.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from ability_converter import Converter
from ability_converter.catalog import SourceCatalog
from ability_converter.cli import build_catalog
from ability_converter.runs import require_current_run
from ability_converter.sources import ARTIFACTS, ROOT, read


def write(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog',type=Path,default=ROOT/'build/abilities/v1',help='Completed source catalog to read without changing it')
    parser.add_argument('--out',type=Path,default=ROOT/'build/abilities/delivery',help='Delivery directory')
    parser.add_argument('--artifacts',type=Path,default=ARTIFACTS)
    args=parser.parse_args(argv)
    source=args.catalog.resolve();destination=args.out.resolve()
    if destination==source or destination in source.parents:
        parser.error('Delivery must not replace the input catalog or one of its parent directories')
    marker=destination/'delivery.json'
    if destination.exists() and any(destination.iterdir()) and not marker.is_file():
        parser.error('Refusing a nonempty output directory that is not a converter delivery')
    if marker.exists() and read(marker).get('schema')!='ffbe-ffr-delivery/1':
        parser.error('Output directory has an unrelated delivery marker')
    report=require_current_run(source,Converter(args.artifacts))
    for name,expected in report['sources'].items():
        path=Path(name)
        if not path.is_file():raise ValueError(f'Source file missing: {path}')
        with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if path.stat().st_size!=expected['bytes'] or digest!=expected['sha256']:
            raise ValueError(f'Source changed since indexing: {path}; rebuild the source catalog with tools/ability_import.py convert')
    if not (source/'source-index.sqlite').is_file():raise ValueError('Source catalog index is missing')
    destination.mkdir(parents=True,exist_ok=True)
    state={'schema':'ffbe-ffr-delivery/1','status':'running','scope':'FFR mechanics data and binding recipes; gameplay not verified',
           'startedUtc':datetime.now(timezone.utc).isoformat(),'sourceCatalog':str(source),'output':str(destination),
           'command':f'python -X utf8 -B "{Path(__file__).resolve()}" --catalog "{source}" --out "{destination}"',
           'gameTestsRun':False,'nativeHooksBuiltOrInstalled':False}
    write(marker,state)
    catalog_out=destination/'catalog';catalog_out.mkdir(exist_ok=True)
    # Preserve the validated category-correct IDs. The original ledger and
    # SQLite source are read-only; this invocation rebuilds only its own output.
    if not (catalog_out/'ids.json').exists():shutil.copyfile(source/'ids.json',catalog_out/'ids.json')
    options=report['options']
    conversion=SimpleNamespace(out=catalog_out,artifacts=args.artifacts,id=None,limit=None,strict=False,
        datamine=Path(options['datamine']),client=Path(options['client']),
        archive=None if options['archive']=='None' else Path(options['archive']),
        sources='gl,jp,client',max_level=options['all_levels']!='True')
    try:
        print(f'Reconverting the existing FFBE index into {catalog_out}',flush=True)
        with SourceCatalog.open_existing(source/'source-index.sqlite') as catalog:
            if catalog.count!=report['indexedRecords']:raise ValueError('Source index count does not match its completed report')
            if build_catalog(conversion,catalog):raise ValueError('Catalog conversion did not complete')
        sys.stdout.flush()
        subprocess.run([sys.executable,'-X','utf8','-B',str(Path(__file__).with_name('package_ability_delivery.py')),
                        '--out',str(destination),'--baseline',str(source),'--artifacts',str(args.artifacts)],check=True)
    except BaseException as error:
        state.update(status='failed',error=str(error));write(marker,state);raise
    return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print(f'Delivery failed: {error}',file=sys.stderr);raise SystemExit(2)
