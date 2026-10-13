"""Make the accepted four-unit media available to normal Studio rebuilds."""
from copy import deepcopy
import json
import hashlib
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ffbe_effects.playback_policy import configure


def main():
    work = ROOT / 'build/converted-moves-test'
    backup = work / 'before-presentation'
    backup.mkdir(parents=True, exist_ok=True)
    units = json.loads((ROOT / 'mods/EstherTsukiko/units.json').read_text())
    forms = {u['id']: u['ffbe']['id'] for u in units}
    jobs = json.loads((ROOT / 'build/effects-step4/plans.json').read_text())
    manifests = {}
    copied = {}
    for job in jobs:
        if not job.get('effectTrial'):
            continue
        form = forms[job['vision']]
        key = job['presentation']['sourceKey']
        # Start with the prepared source to retain cast particles/audio; apply
        # the reviewed placement corrections from the accepted final trial.
        original = json.loads((ROOT / 'build/effects-step3/presentation' / (form + '.json')).read_text())
        entry = deepcopy(original['moves'][key])
        entry['visuals'] = deepcopy(job['presentation']['visuals'])
        for visual in entry['visuals']:
            if visual['name'] in copied:
                visual.update(copied[visual['name']])
                continue
            source = ROOT / visual['spec']
            project = json.loads((source / 'spec.json').read_bytes())
            filenames = ['spec.json'] + [p.get('textureFile', 'tex' + (f'_{i}' if i else '') + '.bgra')
                for i, p in enumerate(project.get('cellmaps', [project]))]
            # Raw reviewed projects and compressed portable projects can share
            # an effect name. Preserve a separate immutable storage directory
            # so adding a converted unit cannot overwrite a reviewed spec.
            target = ROOT / 'data/ffbe/presentation/assets/reviewed' / visual['name']
            target.mkdir(parents=True, exist_ok=True)
            checksums = {}
            for filename in filenames:
                shutil.copy2(source / filename, target / filename)
                if filename == 'spec.json' and any(p.get('textureEncoding') == 'zlib' for p in project.get('cellmaps', [project])):
                    # Portable JSON sorts dictionaries. Restore the original
                    # exporter order so native property/name tables reproduce
                    # the reviewed cooked media byte for byte.
                    ordered = deepcopy(project)
                    for animation in ordered['animations']:
                        attrs = (['Cell', 'Posz', 'Sclx', 'Scly', 'Hide', 'PartsColor'] if animation.get('isSetup')
                                 else ['Cell', 'Posx', 'Posy', 'Sclx', 'Scly', 'Rotz', 'Alpha', 'Hide', 'Fliph', 'Flipv', 'Posz'])
                        parts = animation['parts']
                        restored = {}
                        for part in ordered['model']['parts']:
                            part_name = part['name']
                            if part_name not in parts: continue
                            order = ['Hide', 'Sclx', 'Scly', 'Posx'] if part_name == 'root' else attrs
                            restored[part_name] = {a: parts[part_name][a] for a in order if a in parts[part_name]}
                            restored[part_name].update({a: v for a, v in parts[part_name].items() if a not in restored[part_name]})
                        restored.update({k: v for k, v in parts.items() if k not in restored})
                        animation['parts'] = restored
                    assert ordered == project, 'Ordering recovery must not change any source value'
                    (target / filename).write_text(json.dumps(ordered, ensure_ascii=False, indent=1), encoding='utf-8')
                with (target / filename).open('rb') as stream:
                    checksums[filename] = hashlib.file_digest(stream, 'sha256').hexdigest()
            visual.update(spec=target.relative_to(ROOT).as_posix(), checksums=checksums)
            copied[visual['name']] = {'spec': visual['spec'], 'checksums': checksums}
        entry['reconstructionProfile'] = deepcopy(job['presentation']['reconstructionProfile'])
        entry = configure(entry, form, key)
        manifest = manifests.setdefault(form, {'schema': 'ffr-presentation-2', 'form': form, 'moves': {}})
        manifest['moves'][key] = entry
    for form, manifest in manifests.items():
        target = ROOT / 'data/ffbe/presentation' / (form + '.json')
        if target.exists() and not (backup / target.name).exists():
            shutil.copy2(target, backup / target.name)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    shutil.copy2(ROOT / 'mods/EstherTsukiko/units.json', work / 'units-before.json')
    print('Prepared ten accepted effects for normal Studio rebuilds; Raegen Blast keeps its camera-only path.')


if __name__ == '__main__':
    main()
