"""Prepare pinned public headers and the exact local UE4SS import library input.

This does not build UE4SS or require private Unreal headers. Its public mod
header includes an unused GUI implementation; replace only that include and
its nonvirtual callback alias with equivalent forward declarations/types.
The class fields, virtual methods and their order are preserved verbatim.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
UE4SS_HASH = '7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--ue4ss', type=Path, default=ROOT/'tools/UE4SS/ue4ss/UE4SS.dll')
    args = parser.parse_args()
    import pefile
    dll = args.ue4ss.read_bytes()
    if hashlib.sha256(dll).hexdigest() != UE4SS_HASH:
        raise ValueError('UE4SS DLL does not match the pinned public SDK revision/build')
    cache = ROOT/'build/tooling'
    cache.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((HERE/'dependencies.json').read_text())
    for name, dependency in manifest.items():
        archive_path = cache/(name+'.zip')
        if not archive_path.exists():
            if args.offline:
                raise ValueError(f'Missing cached source archive {archive_path}')
            raw = urllib.request.urlopen(dependency['url'], timeout=60).read()
        else:
            raw = archive_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != dependency['sha256']:
            raise ValueError(f'Source archive fingerprint mismatch: {name}')
        archive_path.write_bytes(raw)
        destination = (cache/name).resolve()
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                target = destination.joinpath(*Path(entry.filename).parts[1:]).resolve()
                if not target.is_relative_to(destination):
                    raise ValueError('Unsafe archive path')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(entry))
    sdk = cache/'ue4ss-sdk-24b12662'
    original = (sdk/'UE4SS/include/Mod/CppUserModBase.hpp').read_text()
    include = '#include <GUI/GUITab.hpp>'
    alias = 'GUI::GUITab::RenderFunctionType'
    assert original.count(include) == 1 and original.count(alias) == 1
    lean = original.replace(include, 'namespace RC { class CppUserModBase; namespace GUI { class GUITab; } }')
    lean = lean.replace(alias, 'void (*)(CppUserModBase*)')
    # Reversing these two substitutions must reproduce the complete source.
    assert lean.replace('namespace RC { class CppUserModBase; namespace GUI { class GUITab; } }', include).replace('void (*)(CppUserModBase*)', alias) == original
    generated = ROOT/'build/abilities/native-bridge-sdk'
    (generated/'include/Mod').mkdir(parents=True, exist_ok=True)
    (generated/'include/Mod/CppUserModBase.hpp').write_text(lean, encoding='utf8')
    pe = pefile.PE(data=dll, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    exports = sorted(e.name.decode('ascii') for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name)
    (generated/'UE4SS.def').write_text('LIBRARY UE4SS.dll\nEXPORTS\n'+'\n'.join(exports)+'\n', encoding='utf8')
    info = {'ue4ssSha256':UE4SS_HASH, 'dependencies':manifest,
            'publicHeaderSha256':hashlib.sha256(original.encode()).hexdigest(),
            'leanHeaderSha256':hashlib.sha256(lean.encode()).hexdigest(),
            'transformation':'GUI include replaced by forward declarations; nonvirtual GUI callback alias spelled as its exact function pointer type. No fields or virtual methods changed.',
            'exports':len(exports)}
    (generated/'manifest.json').write_text(json.dumps(info, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'status':'prepared','generated':str(generated),'exports':len(exports)}, indent=2))

if __name__ == '__main__':
    main()
