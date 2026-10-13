"""Finish the staged build using checksum-verified accepted effect geometry."""
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT / 'tools/private')]
import make_vision_mod as b
import cooked_effect_cache as cache


def main():
    old = ROOT / 'build/effects-step3'
    accepted = ROOT / 'build/effects-step4'
    sealed = ROOT / 'checkpoints/ffbe-effects-step3/source/src/ffr-dt/Ss6Builder.cs'
    if cache.digest(ROOT / 'src/ffr-dt/Ss6Builder.cs') != cache.digest(sealed):
        raise ValueError('Sprite/texture compiler changed since the accepted checkpoint')
    jobs = json.loads((accepted / 'plans.json').read_text())
    effects = {}
    forms = {u['id']: u['ffbe']['id'] for u in b.UNITS}
    for job in jobs:
        if not job.get('effectTrial'): continue
        manifest = json.loads((ROOT / 'data/ffbe/presentation' / (forms[job['vision']] + '.json')).read_text())
        entry = manifest['moves'][job['presentation']['sourceKey']]
        for name, spec, donor in b.ffbe_presentation.jobs(entry, job['donor']):
            effects.setdefault(name, (spec, donor))
    seeded = []
    for name, (spec, donor) in effects.items():
        marker = json.loads((old / 'effect-stamps' / (name + '.json')).read_text())
        for rel, checksum in marker['outputs'].items():
            if cache.digest(accepted / rel) != checksum:
                raise ValueError('Accepted cooked media changed: ' + rel)
        if marker['specSha256'] != cache.digest(ROOT / spec / 'spec.json'):
            # The portable importer may have switched a shared source spec to
            # lossless zlib storage. Prove identical cooked output before reuse.
            b.build_effect_project(name, spec, donor)
            for rel, checksum in marker['outputs'].items():
                if cache.digest(Path(b.BUILD) / rel) != checksum:
                    raise ValueError('Recooked portable project differs from accepted media: ' + name)
        key = cache.identity(ROOT, b.LEGACY, b.USMAP, b.FFRDT[-1], name, spec, donor, b.TEX_DONOR)
        source = accepted / 'assets/FFRS/Content/Chara/effect' / name
        cache.store(ROOT / 'build/cooked-effect-cache', key, source)
        b.build_effect_project(name, spec, donor)
        seeded.append(name)
    # The interrupted normal build already completed tables, timelines, audio,
    # and four unit sprite sets. Finish only the remaining icon/package stages.
    tables = {}
    def tbl(rel): return tables.setdefault(rel, {'asset': b.DT + rel, 'add': [], 'set': []})
    native = b.vision_icons.registry_rows(b.LEGACY, str(Path(b.BUILD) / 'native-command-tags.json'), b.FFRDT, b.USMAP, b.ffrenv.RETOC, b.ffrenv.detect_game())
    registry = b.vision_icons.registry_patch(b.UNITS, native)
    icons = b.skill_icons.prepare(b.UNITS, tbl, b.row_by, registry)
    b.skill_icons.build(icons, b.LEGACY, b.OUT, b.BUILD, b.FFRDT, b.USMAP, b.run)
    (Path(b.BUILD) / 'units-built.json').write_text(json.dumps(b.UNITS, ensure_ascii=False), encoding='utf-8')
    (ROOT / 'build/converted-moves-test/cooked-media-reuse.json').write_text(json.dumps({'compilerMatchesAccepted': True, 'effects': seeded}, indent=2))
    b.run(b.ffrenv.py(str(ROOT / 'tools/build_mod.py'), b.OUT, b.ffrenv.MOD_NAME))


if __name__ == '__main__': main()
