"""Stage a move's GL particles/resources without overwriting the central JP dump."""
from contextlib import contextmanager
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
import hashlib, os, shutil, re
from .atomic_files import write_json

GL_DEFAULT=Path('T:/ffbe_patch/gl_extracted/common_lang/sd')

def gl_root():
    return Path(os.environ.get('FFR_GL_EFFECT_ROOT',str(GL_DEFAULT)))

def sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream,'sha256').hexdigest()

@lru_cache(maxsize=4)
def index(root):
    result=defaultdict(list)
    for folder in ('battleEffect','effectResource'):
        for path in (Path(root)/folder).rglob('*'):
            if path.is_file(): result[path.name.lower()].append(path)
    return result

def choose(name, regional, shared):
    if Path(name).name!=name or ':' in name or '\\' in name:
        raise ValueError('Unsafe source dependency name: '+name)
    candidates=regional.get(name.lower(),[])
    if candidates:
        hashes={sha(path) for path in candidates}
        if len(hashes)!=1:
            # The dump contains older revisions and separate tutorial / SG
            # packages. Unit battle effects use the ordinary common package.
            # Never settle a same-revision conflict by filesystem order.
            versions=[]
            for path in candidates:
                version=next((re.fullmatch(r'Ver(\d+)_(?:effectResource|battleEffect)\d*_common', part)
                              for part in path.parts if re.fullmatch(r'Ver(\d+)_(?:effectResource|battleEffect)\d*_common', part)), None)
                if version: versions.append((int(version.group(1)),path))
            if versions:
                latest=max(v for v,_ in versions)
                selected=[path for v,path in versions if v==latest]
                if len({sha(path) for path in selected})==1:
                    return selected[0], 'GL ordinary battle common; newest available revision (explicit export policy)'
            raise ValueError('Conflicting regional assets: '+name)
        return candidates[0], 'GL export'
    path=shared/name
    if not path.is_file(): raise FileNotFoundError('Missing particle dependency: '+name)
    return path, 'JP/shared fallback'

@contextmanager
def staged(prepare, snapshot, destination):
    if not snapshot['root'].startswith('GL_2024/'):
        yield
        return
    cat=prepare.catalog
    groups=[]
    profile=prepare.commands.from_snapshot(snapshot,reviewed=True)
    allowed={item.get('source') or snapshot['root'] for component in profile['conversion']['components']
             for item in component['actions']+component['effects']}
    for record in snapshot['records']:
        if record['kind'] not in ('ability','magic','lb'): continue
        key='/'.join([record['source'],record['kind'],str(record['id'])])
        if record.get('level') is not None:key+='/level/'+str(record['level'])
        if key not in allowed:continue
        source=record['source']
        if source!='GL_2024': raise ValueError('Mixed-region snapshot requires an explicit dependency mapping')
        own=prepare.commands.from_snapshot({**snapshot,'root':key},reviewed=True)
        retained={c['index'] for c in own['conversion']['components'] if c['actions'] or c['effects']}
        move=cat.skill_effects(record['kind'],record['id'],source=source)
        if move: groups.extend(row['group'] for row in move['groups'] if row.get('group') and row['component'] in retained)
    # Activation families are separate from the action graph. Resolve only the
    # selected school's pair; absent school metadata remains a reported gap.
    kind=snapshot['root'].split('/')[1]
    cast=['9000110','9000120'] if kind=='ability' else []
    if kind=='magic':
        record=next(r for r in snapshot['records'] if str(r['id'])==snapshot['root'].split('/')[2] and r['kind']=='magic')
        cast={'white':['9000030','9000040'],'black':['9000050','9000060'],
              'green':['9000070','9000080'],'blue':['9000090','9000100']}.get(str(record['data'].get('magic_type','')).lower(),[])
    groups.extend(group for gid in cast if (group:=cat.group_detail(gid,source='GL_2024')))
    names={e['file'] for g in groups for e in g['effects'] if e.get('effectType')=='5' and e['file'].lower().endswith('.bmb')}
    regional=index(str(gl_root().resolve()))
    shared=prepare.ROOT/'build/ffbe_cpk/effects_dec'
    records={}
    def collect(name):
        if name in records:return
        path,region=choose(name,regional,shared)
        records[name]={'path':str(path),'region':region,'sha256':sha(path)}
        if name.lower().endswith('.bmb'):
            parsed=prepare.ibmb.parse(str(path))
            for item,ext in [(s,'.png') for s in parsed.textures]+[(s,'.m3r') for s in parsed.models]:
                collect(item if Path(item).suffix else item+ext)
    for name in sorted(names):collect(name)
    destination=Path(destination);destination.mkdir(parents=True,exist_ok=True)
    for name,record in records.items():
        target=destination/name
        if not target.is_file() or sha(target)!=record['sha256']: shutil.copy2(record['path'],target)
        if sha(target)!=record['sha256']: raise ValueError('Source staging checksum mismatch: '+name)
    write_json(destination/'source-files.json',records,indent=2)
    previous=prepare.SOURCES,cat.EFFECTS_DIR,prepare.to_ss6.EFFECTS
    try:
        prepare.SOURCES=destination;cat.EFFECTS_DIR=str(destination);prepare.to_ss6.EFFECTS=str(destination)
        yield
    finally:
        prepare.SOURCES,cat.EFFECTS_DIR,prepare.to_ss6.EFFECTS=previous
