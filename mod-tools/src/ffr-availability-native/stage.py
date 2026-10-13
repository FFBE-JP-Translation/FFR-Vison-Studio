"""Stage a disabled observer package only from a current verified native build."""
import hashlib
import json
from pathlib import Path
import shutil
from build import ROOT,OUT,HERE,SCRIPTS,fingerprint,imports

def main():
    report=json.loads((OUT/'native-bridge-validation.json').read_text())
    assert report['status']=='passed' and report['inputs']==fingerprint(),'Rebuild/retest changed native runtime inputs'
    binary=OUT/'native-bridge-build/Release/main.dll'
    assert report['dllSha256']==hashlib.sha256(binary.read_bytes()).hexdigest(),'Native DLL changed'
    assert report['ue4ssImports']==imports(binary),'UE4SS import set changed'
    assert report['sdkManifestSha256']==hashlib.sha256((OUT/'native-bridge-sdk/manifest.json').read_bytes()).hexdigest(),'SDK inputs changed'
    destination=OUT/'runtime-native/FFRAvailabilityRuntime'
    assert not (destination/'enabled.txt').exists(),'Staging directory was enabled; use a fresh disabled staging directory'
    (destination/'dlls').mkdir(parents=True,exist_ok=True)
    (destination/'Scripts').mkdir(parents=True,exist_ok=True)
    shutil.copyfile(binary,destination/'dlls/main.dll')
    for source,target in SCRIPTS.items():
        shutil.copyfile(ROOT/'tools/ability_converter/runtime'/source,destination/'Scripts'/target)
    shutil.copyfile(HERE/'README.md',destination/'README.md')
    licenses=destination/'licenses'; licenses.mkdir(exist_ok=True)
    for name,source in {'UE4SS.txt':'ue4ss-sdk-24b12662/LICENSE','MinHook.txt':'minhook-1.3.4/LICENSE.txt',
                        'Lua.txt':'ue4ss-sdk-24b12662/deps/first/LuaRaw/LICENSE','fmt.txt':'fmt-11.2.0/LICENSE'}.items():
        shutil.copyfile(ROOT/'build/tooling'/source,licenses/name)
    manifest={**report,'mode':'observe','enabled':False,'installed':False,
              'files':{p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(destination.rglob('*')) if p.is_file() and p.name!='manifest.json'}}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'staged','path':str(destination),'enabled':False,'installed':False,'mode':'observe'},indent=2))

if __name__=='__main__': main()
