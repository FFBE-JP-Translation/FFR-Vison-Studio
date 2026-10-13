"""Reproducible focused GL effect import; never changes the accepted checkpoint."""
from pathlib import Path
import sys, json, shutil, hashlib
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui'), str(ROOT/'tools/ffbe_effects')]
from ffbe_effects import prepare_vision as p

WORK = ROOT/'build/effects-step3'
SELECTED = {
    '401006807': ['GL_2024/lb/401006807/level/30'],
    '340000107': ['GL_2024/ability/513203', 'GL_2024/ability/237599', 'GL_2024/lb/340000107/level/40'],
    '100032707': ['GL_2024/ability/238671', 'GL_2024/ability/238673', 'GL_2024/lb/100032707/level/40'],
    '401007407': ['GL_2024/magic/20440', 'GL_2024/ability/913005', 'GL_2024/lb/401007407/level/30'],
}

def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path, doc): Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def sha(path):
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()

def main():
    WORK.mkdir(parents=True, exist_ok=True)
    sources = WORK/'regional-source'; sources.mkdir(exist_ok=True)
    audit = read(ROOT/'docs/discovery/ffbe-step3/media-audit.json')
    records = {}
    for row in audit['effects']:
        for resource in [row, *row.get('resources', [])]:
            assert resource['exists'], resource
            name = resource['file']; old = records.get(name)
            if old: assert old['sha256'] == resource['sha256'], name
            records[name] = resource
    for name, record in records.items():
        destination = sources/name
        if not destination.exists(): shutil.copy2(record['path'], destination)
        assert sha(destination) == record['sha256'], name
    write(WORK/'source-files.json', records)
    p.SOURCES = sources; p.catalog.EFFECTS_DIR = str(sources); p.catalog.clear_cache()
    p.to_ss6.EFFECTS = str(sources)
    p.CACHE = WORK/'decoded'
    manifests = WORK/'presentation'; manifests.mkdir(exist_ok=True)
    for form, keys in SELECTED.items():
        manifest = manifests/(form+'.json')
        if not manifest.exists(): write(manifest, {'schema':p.presentation.VERSION, 'form':form, 'moves':{}})
        for key in keys:
            if key in read(manifest)['moves']:
                print('Already prepared', key, flush=True); continue
            profile = p.scene.default_profile(form, key, {'kind':'screen_overlay', 'referenceStage':[320,320]})
            profile.pop('resonanceCamera', None); profile.pop('resonanceMovement', None)
            profile['preserveSourceColor'] = True
            profile['screenPlacement']['fit'] = 'cover'
            p.WORK = WORK/'prepare'/form/key.split('/')[2]; p.WORK.mkdir(parents=True, exist_ok=True)
            p.prepare([form], [key], profile, detect_scene=True, merge_existing=True,
                      manifest_out=manifest, make_previews=False, universal=True)
    write(WORK/'selected.json', SELECTED)
    print('Prepared all ten selected moves.', flush=True)

if __name__ == '__main__': main()
