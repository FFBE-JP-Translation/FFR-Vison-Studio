"""Build the separate temporary battle-fixture DLL; do not install it."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=ROOT/'build/abilities'
spec=importlib.util.spec_from_file_location('native_build',HERE.parent/'build.py')
native=importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)
sources=[HERE/'CMakeLists.txt',HERE/'mod.cpp',Path(__file__),HERE.parent/'CMakeLists.txt',HERE.parent/'build.py',HERE.parent/'bridge_core.cpp',HERE.parent/'bridge_core.hpp',OUT/'native-bridge-sdk/manifest.json']
sources += [HERE.parent/'query_bridge.cpp',HERE.parent/'query_bridge.hpp']
inputs={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
cmake=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
directory=OUT/'native-fixture-build'
with (OUT/'native-fixture-build.log').open('w',encoding='utf8') as log:
    for args in (['-S',str(HERE),'-B',str(directory),'-G','Visual Studio 17 2022','-A','x64'],
                 ['--build',str(directory),'--config','Release','--target','FFRBattleFixture','--parallel','4']):
        subprocess.run([str(cmake),*args],stdout=log,stderr=subprocess.STDOUT,check=True)
binary=directory/'Release/main.dll'
report={'status':'built','scope':'temporary_test_fixture_only','inputs':inputs,
        'queryBinding':'production_runtime_active_skill_set',
        'dll':str(binary),'dllSha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
        'ue4ssImports':native.imports(binary),'nativeBattle':'not_run'}
(OUT/'native-fixture-build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
print(json.dumps({'status':'built','dll':str(binary),'imports':len(report['ue4ssImports'])}))
