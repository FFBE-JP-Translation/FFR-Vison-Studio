"""Collect the local JP/GL skill icon collection and exact client icon-ID aliases."""
import json
from pathlib import Path
import shutil
import sys
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import skill_icons


def main():
    icons = skill_icons.ICONS; icons.mkdir(parents=True, exist_ok=True)
    aliases = {str(r['icon_id']): r['file_name'] for r in json.loads(
        (ROOT/'build/devui/live_jp/F_ICON_MST.json').read_text(encoding='utf-8'))['rows']}
    needed = set()
    for bundle in (ROOT/'data/ffbe/native_kits').glob('*.json'):
        doc = json.loads(bundle.read_text(encoding='utf-8'))
        needed.update(aliases.get(str(e['icon']), str(e['icon'])) for e in doc['kit']['entries'] if e.get('icon'))
    sources = [Path(r'T:\ffbe_patch\jp_extracted\on_demand_asset2'),
               Path(r'T:\ffbe_patch\gl_extracted\common_lang\sd\item')]
    found = {}
    for source in sources:
        for p in sorted(source.rglob('*.png')):
            if p.name.startswith(('ability_', 'global_ability_')) or p.name in needed:
                found.setdefault(p.name, p)
    for name, source in found.items():
        with Image.open(source) as image: image.verify()
        shutil.copy2(source, icons/name)
    (icons/'aliases.json').write_text(json.dumps({k:v for k,v in aliases.items() if (icons/v).is_file()}, sort_keys=True), encoding='utf-8')
    missing = sorted(n for n in needed if not (icons/n).is_file())
    report = {'icons': len(list(icons.glob('*.png'))), 'referenced': len(needed), 'missing': missing,
              'sources': {n:str(p) for n,p in found.items()}}
    target = ROOT/'build/ability-icon-fix/icon-coverage.json'; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='sources'}))
    if missing: raise ValueError('Some native icon images are still missing')


if __name__ == '__main__': main()
