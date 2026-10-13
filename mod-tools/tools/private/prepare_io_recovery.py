"""Register the reviewed September 22 progress-file recovery without rewriting receipts.

Recompute the old identity with current source inventories, and refuse any
compiler change outside the IO/scheduling repair. All ordinary receipt content,
dependency and output checks remain in force. No game assets are changed.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
from ffbe_effects import catalog_batch as batch
from ffbe_effects.atomic_files import write_json

ALLOWED = {'tools/ffbe_effects/atomic_files.py',
           'tools/ffbe_effects/catalog_batch.py', 'tools/convert_ffbe_effects.py'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    old = json.loads(args.report.read_bytes())['pipeline']
    current = batch.pipeline_identity(ROOT)
    changed = {name for name in old['compilerFiles'].keys() | current['compilerFiles'].keys()
               if old['compilerFiles'].get(name) != current['compilerFiles'].get(name)}
    if not changed.issubset(ALLOWED):
        raise ValueError('Unreviewed compiler changes: '+str(changed-ALLOWED))
    legacy = batch.pipeline_identity(ROOT, compiler_files=old['compilerFiles'])
    legacy_hash = batch.encoded_hash({'compiler': legacy['sha256'], 'playbackPolicy': old['playbackPolicy']})
    if legacy_hash != old['sha256']:
        raise ValueError('Source inventory/settings changed; old receipts cannot be reused')
    new_hash = batch.encoded_hash({'compiler': current['sha256'], 'playbackPolicy': old['playbackPolicy']})
    evidence = {'schema': 'ffr-reviewed-io-recovery-1',
                'oldPipeline': old['sha256'], 'newPipeline': new_hash,
                'sourceInventoryUnchanged': True,
                'reviewedChanges': {name: {'before': old['compilerFiles'].get(name),
                                          'after': current['compilerFiles'].get(name)}
                                    for name in sorted(changed)}}
    if args.apply:
        if json.loads(args.evidence.read_bytes()) != evidence:
            raise ValueError('Code changed since recovery review')
        write_json(args.work/'pipeline-compatibility.json', evidence, indent=2)
    else:
        write_json(args.evidence, evidence, indent=2)
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == '__main__':
    main()
