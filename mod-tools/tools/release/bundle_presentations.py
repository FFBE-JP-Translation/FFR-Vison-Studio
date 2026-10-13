"""Bundle independently prepared effects .ffr files with portable unit archives.

No FFBE source conversion happens here. Existing callers may package an already
prepared presentation; --effects-dir consumes the offline compiler's artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ffbe_effect_bundle as effects


def bundle(source, out, forms, *, effects_dir=None):
    source, out = Path(source), Path(out)
    index = json.loads((source / 'ffbe/index.json').read_text(encoding='utf-8'))
    entries = {}
    for form in forms:
        form = effects.form_id(form)
        unit = source / 'ffbe/units' / (form + '.ffr')
        catalog = index['unitBundles'][form]
        raw = unit.read_bytes()
        if len(raw) != catalog['size'] or hashlib.sha256(raw).hexdigest() != catalog['sha256']:
            raise ValueError(f'{form}: source unit does not match its catalog checksum')
        if effects_dir is None:
            artifact = out / 'ffbe/effects' / (form + '.ffr')
            effects.pack(ROOT / 'data/ffbe/presentation' / (form + '.json'), artifact)
        else:
            artifact = Path(effects_dir) / (form + '.ffr-effects')
            if not artifact.is_file():
                artifact = Path(effects_dir) / (form + '.ffr')
        info = effects.merge(unit, artifact, out / 'ffbe/units' / (form + '.ffr'))
        entries[form] = {**catalog, **info, 'url': f'ffbe/units/{form}.ffr'}
        print(form, info, flush=True)
    # A review fragment, never an implicit replacement for a published catalog.
    out.mkdir(parents=True, exist_ok=True)
    (out / 'presentation-bundles.json').write_bytes(effects.encoded({'schema': effects.VERSION, 'unitBundles': entries}))
    return entries


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('forms',nargs='+')
    parser.add_argument('--source',type=Path,default=ROOT/'build/multicast-fix/host')
    parser.add_argument('--out',type=Path,default=ROOT/'build/prepared-effects/host')
    parser.add_argument('--effects-dir',type=Path,help='Offline compiler output containing <form>.ffr-effects files')
    args=parser.parse_args();bundle(args.source,args.out,args.forms,effects_dir=args.effects_dir)
