"""Build and verify the native adapter outside the installed game."""
import hashlib
import json
from pathlib import Path
import subprocess
import os
import shutil
import sys
import pefile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'build/abilities'
SCRIPTS={'availability.lua':'availability.lua','native_host.lua':'native_host.lua',
         'native_main.lua':'main.lua','probe.lua':'availability_probe.lua','probe_main.lua':'availability_probe_main.lua'}

def fingerprint():
    sources=[HERE/name for name in ('CMakeLists.txt','bridge_core.cpp','bridge_core.hpp','query_bridge.cpp','query_bridge.hpp','mod.cpp','tests.cpp','query_tests.cpp','dependencies.json','bootstrap.py','build.py')]
    sources += [ROOT/'tools/ability_converter/runtime'/name for name in SCRIPTS]
    return {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}

def imports(binary):
    pe=pefile.PE(str(binary))
    assert pe.FILE_HEADER.Machine==0x8664
    exports={e.name.decode() for e in pe.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    assert exports=={'start_mod','uninstall_mod'},exports
    ue=pefile.PE(str(ROOT/'tools/UE4SS/ue4ss/UE4SS.dll'))
    available={e.name for e in ue.DIRECTORY_ENTRY_EXPORT.symbols if e.name}
    imported=[]
    for library in pe.DIRECTORY_ENTRY_IMPORT:
        if library.dll.lower()==b'ue4ss.dll':
            for symbol in library.imports:
                assert symbol.name in available, symbol.name
                imported.append(symbol.name.decode())
    assert imported
    return imported

def main():
    subprocess.run([sys.executable,'-X','utf8','-B',str(HERE/'bootstrap.py'),'--offline'],check=True)
    before=fingerprint()
    cmake=os.environ.get('FFR_CMAKE') or shutil.which('cmake')
    if not cmake:
        fallback=Path('C:/Program Files/Microsoft Visual Studio/2022/Community/Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe')
        if fallback.is_file(): cmake=str(fallback)
    if not cmake:
        raise ValueError('Install CMake with Visual Studio C++ tools, or set FFR_CMAKE')
    directory=OUT/'native-bridge-build'
    for name,args in (
        ('configure',['-S',str(HERE),'-B',str(directory),'-G','Visual Studio 17 2022','-A','x64']),
        ('build',['--build',str(directory),'--config','Release','--parallel','4'])):
        log=OUT/f'native-bridge-{name}.log'
        with log.open('w',encoding='utf8') as stream:
            result=subprocess.run([str(cmake),*args],stdout=stream,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'Native {name} failed; see {log}')
    executable=directory/'Release/bridge_tests.exe'
    result=subprocess.run([str(executable)],text=True,capture_output=True,check=True)
    (OUT/'native-bridge-tests.log').write_text(result.stdout+result.stderr,encoding='utf8')
    tests=json.loads(result.stdout)
    assert tests['status']=='passed'
    binary=directory/'Release/main.dll'
    sdk=OUT/'native-bridge-sdk/manifest.json'
    assert before==fingerprint(),'Sources changed while native build/tests ran'
    report={'status':'passed','inputs':before,'tests':tests,'ue4ssImports':imports(binary),
            'dllSha256':hashlib.sha256(binary.read_bytes()).hexdigest(),
            'testsExeSha256':hashlib.sha256(executable.read_bytes()).hexdigest(),
            'sdkManifestSha256':hashlib.sha256(sdk.read_bytes()).hexdigest(),
            'nativeGameHook':'not_installed','nativeBattle':'not_run','lifecycleBinding':'unbound',
            'queryTransport':'native_active_skill_set_v1'}
    (OUT/'native-bridge-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'passed','tests':tests,'ue4ssImports':len(report['ue4ssImports']),
                      'dll':str(binary),'nativeBattle':'not_run'},indent=2))

if __name__=='__main__': main()
