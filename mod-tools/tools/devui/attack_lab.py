"""Advanced Studio attack editor, prepared previews and serialized build jobs."""
from copy import deepcopy
from functools import lru_cache
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from PIL import Image, ImageChops, ImageDraw
import ffbe_attack_director as director
import ffrenv

ROOT=director.ROOT
WORK=ROOT/'build/attack-lab'
STEM='zzzzzz_FFBE_Attack_Lab_P'
LOCK=threading.Lock()
router=APIRouter(prefix='/api/attack-lab')
host=None
job={'running':False,'stage':'Ready','log':[],'result':None}


def read(path): return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write(path,value):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    temporary.replace(path)


def form_id(form):
    if not isinstance(form,str) or not form.isdecimal() or len(form)>20: raise ValueError('Invalid vision form')
    return form


@lru_cache(maxsize=8)
def native_cached(path,mtime): return read(path)


def native(form):
    path=ROOT/'data/ffbe/native_kits'/f'{form_id(form)}.json'
    return native_cached(str(path),path.stat().st_mtime_ns)


def manifests(form):
    path=ROOT/'data/ffbe/presentation'/f'{form_id(form)}.json'
    candidates=[path] if path.is_file() else []
    candidates+=list((ROOT/'build').glob(f'ffbe-effects*/manifests/{form}.json'))
    candidates+=list(WORK.glob(f'*/{form}.json'))
    return sorted(set(candidates),key=lambda p:p.stat().st_mtime_ns,reverse=True)


def prepared(form,key):
    for path in manifests(form):
        doc=read(path)
        if key in doc.get('moves',{}): return doc['moves'][key],path
    return None,None


@router.get('/catalog')
def catalog():
    rows=read(ROOT/'build/devui/ffbe_index.json')
    imported={str(u.get('ffbe',{}).get('id')):u['key'] for u in host.load_spec()}
    return {'units':[{'id':u['id'],'name':u['name'],'forms':u['forms'],
                      'icon':u.get('iconForm',u['forms'][-1])} for u in rows],
            'imported':imported,'defaults':director.resolve('',''),
            'bulkAvailable':not ffrenv.FROZEN and (ROOT/'tools/convert_ffbe_effects.py').is_file()}


@router.get('/moves/{form}')
def moves(form:str):
    data=native(form)
    ready={}
    for path in reversed(manifests(form)): ready.update(read(path).get('moves',{}))
    return {'moves':[{**{k:e.get(k) for k in ('sourceKey','name','kind','status','issues','description')},
                      'prepared':e['sourceKey'] in ready} for e in data['kit']['entries'] if e['kind']!='PASSIVE']}


@router.get('/move')
def move(form:str,key:str):
    data=native(form)
    row=next((e for e in data['kit']['entries'] if e['sourceKey']==key and e['kind']!='PASSIVE'),None)
    if row is None: raise HTTPException(404,'Move does not belong to this form')
    entry,path=prepared(form,key)
    profile=data['profiles'][key]
    frames=(profile.get('timeline') or profile.get('conversion',{}).get('timeline') or {}).get('hitFrames',[])
    source=next((r.get('data',{}) for r in profile['snapshot']['records']
                 if '/'.join(str(r.get(k)) for k in ('source','kind','id'))==key.split('/level/')[0]),{})
    moving=source.get('move_type',source.get('moveType',0))==1
    # Native command translator owns the source movement interpretation.
    try:
        from ability_converter import commands
        resolved=profile if profile.get('timeline') else commands.from_snapshot(profile['snapshot'],reviewed=True)
        moving=resolved.get('timeline',{}).get('moveType')==1
        frames=resolved.get('timeline',{}).get('hitFrames',frames)
    except (AttributeError,ValueError,KeyError): pass
    return {'form':form,'key':key,'name':row['name'],'kind':row['kind'],'status':row['status'],
            'issues':row.get('issues',[]),'prepared':entry is not None,'moving':moving,
            'settings':director.resolve(form,key,entry),'hasOverride':key in director.read_settings().get('moves',{}).get(form,{}),
            'layers':[{ 'id':director.layer_key(fx,i),'name':fx['name'], 'anchor':fx['anchor'],
                        'order':'front' if fx['layer']==1 else 'back','frame':fx['frame'],
                        'frames':fx['frames'],'phase':fx.get('phase','action')}
                      for i,fx in enumerate((entry or {}).get('visuals',[]))],
            'durationFrames':max([60,*frames,*[fx['frame']+fx['frames'] for fx in (entry or {}).get('visuals',[])]]),
            'sounds':len((entry or {}).get('sounds',[])),'source':str(path) if path else None}


@router.put('/settings')
async def settings(request:Request):
    body=await request.json()
    try:
        with LOCK:
            doc=director.read_settings()
            scope=body.get('scope')
            if scope=='defaults':
                values=director.validate(body['settings']); values['layers']={}
                doc['defaults']=values
            elif scope in ('move','reset'):
                form=form_id(body['form']); key=body['key']
                if key not in native(form)['profiles']: raise ValueError('Unknown move')
                target=doc['moves'].setdefault(form,{})
                if scope=='reset': target.pop(key,None)
                else: target[key]=director.validate(body['settings'])
            else: raise ValueError('Choose move settings or all-unit defaults')
            write(director.SETTINGS,doc)
        return {'ok':True}
    except (ValueError,KeyError,TypeError) as error: raise HTTPException(422,str(error)) from error


def last(keys,t,default):
    value=default
    for tick,item in keys:
        if tick>t: break
        value=item
    return value


@lru_cache(maxsize=8)
def spec_cached(path,stamp): return read(path)


@lru_cache(maxsize=6)
def atlas_cached(folder,filename,width,height,encoding,stamp):
    import zlib
    raw=(Path(folder)/filename).read_bytes()
    if encoding=='zlib': raw=zlib.decompress(raw)
    return Image.frombytes('RGBA',(width,height),raw,'raw','BGRA')


def layer_image(fx,frame):
    folder=(ROOT/fx['spec']).resolve()
    if not folder.is_relative_to((ROOT/'data/ffbe/presentation/assets').resolve()): raise ValueError('Invalid prepared path')
    path=folder/'spec.json'; spec=spec_cached(str(path),path.stat().st_mtime_ns)
    canvas=Image.new('RGBA',(800,800))
    if frame<0 or frame>=fx['frames']: return canvas
    anim=next(a for a in spec['animations'] if not a.get('isSetup'))
    setup=next((a['parts'] for a in spec['animations'] if a.get('isSetup')), {})
    pages=spec.get('cellmaps') or [spec]
    cells={c['name']:(i,c) for i,page in enumerate(pages) for c in page['cells']}
    parts={p['name']:p for p in spec['model']['parts']}
    # A fixed editor scale; game projection and enemy dimensions remain native.
    zoom=.32*spec.get('runtimeScale',1.)
    for name,attrs in anim['parts'].items():
        base=setup.get(name,{})
        def val(field,default): return last(attrs.get(field,base.get(field,[])),frame,default)
        if 'Cell' not in attrs or val('Hide',0)>=.5: continue
        found=cells.get(val('Cell',None))
        if not found: continue
        page_index,cell=found; page=pages[page_index]
        filename=page.get('textureFile', 'tex.bgra' if page_index==0 else f'tex_{page_index}.bgra')
        file=folder/filename
        width,height=map(int,page.get('pixelSize',spec['pixelSize']))
        atlas=atlas_cached(str(folder),filename,width,height,page.get('textureEncoding','raw'),file.stat().st_mtime_ns)
        x,y=cell['pos']; w,h=cell['size']
        im=atlas.crop((int(x),int(y),int(x+w),int(y+h)))
        sx=val('Sclx',1); sy=val('Scly',1)
        outw=max(1,min(2400,round(w*abs(sx)*zoom))); outh=max(1,min(2400,round(h*abs(sy)*zoom)))
        im=im.resize((outw,outh),Image.Resampling.NEAREST)
        if sx<0: im=im.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        if sy<0: im=im.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
        if val('Rotz',0): im=im.rotate(val('Rotz',0),expand=True)
        alpha=val('Alph',1)
        if alpha!=1: im.putalpha(im.getchannel('A').point(lambda a:round(a*max(0,min(1,alpha)))))
        px=400+val('Posx',0)*zoom-im.width/2; py=400-val('Posy',0)*zoom-im.height/2
        plane=Image.new('RGBA',canvas.size); plane.alpha_composite(im,(round(px),round(py)))
        if parts.get(name,{}).get('blend')=='Add':
            rgb=ImageChops.add(canvas.convert('RGB'),ImageChops.multiply(plane.convert('RGB'),plane.getchannel('A').convert('RGB')))
            rgb.putalpha(ImageChops.lighter(canvas.getchannel('A'),plane.getchannel('A'))); canvas=rgb
        else: canvas.alpha_composite(plane)
    return canvas


@router.get('/layer')
def layer(form:str,key:str,index:int,frame:int=0):
    try:
        entry,_=prepared(form,key)
        if not entry or not 0<=index<len(entry['visuals']): raise ValueError('Prepared layer is unavailable')
        if not -3600<=frame<=36000: raise ValueError('Frame is outside preview range')
        image=layer_image(entry['visuals'][index],frame)
        out=io.BytesIO(); image.save(out,format='PNG')
        return Response(out.getvalue(),media_type='image/png',headers={'Cache-Control':'private, max-age=3600'})
    except (ValueError,OSError,KeyError) as error: raise HTTPException(422,str(error)) from error


def note(line):
    with LOCK:
        job['log'].append(line); job['log']=job['log'][-250:]
        if line.startswith('##stage '): job['stage']=line[8:]
        if job.get('folder'):
            with (Path(job['folder'])/'job.log').open('a',encoding='utf-8') as stream: stream.write(line+'\n')


def process(command,env):
    with subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0)) as child:
        job['pid']=child.pid
        for line in child.stdout: note(line.rstrip())
        if child.wait(): raise RuntimeError(f'{job["stage"]} failed. See the build log.')


def install(folder):
    if host.game_running(): raise ValueError('Close the game before installing. The completed build is saved.')
    destination=Path(ffrenv.game_paks())/'~mods'
    destination.mkdir(exist_ok=True)
    backup=folder/'previous-install'; backup.mkdir(exist_ok=True)
    sources={f'{STEM}.{ext}':ROOT/'build/out'/f'{STEM}.{ext}' for ext in ('pak','utoc','ucas')}
    for name,source in sources.items():
        if not source.is_file(): raise ValueError(f'Missing build file: {name}')
        if (destination/name).exists(): shutil.copy2(destination/name,backup/name)
    copied=[]
    try:
        for name,source in sources.items():
            shutil.copy2(source,destination/name); copied.append(name)
    except Exception:
        for name in copied:
            if (backup/name).exists(): shutil.copy2(backup/name,destination/name)
            else: (destination/name).unlink(missing_ok=True)
        raise
    write(folder/'installation.json',{'files':[str(destination/n) for n in sources], 'backup':str(backup)})
    note('Installed Attack Lab build. Launch the game to test the selected vision and move.')


def run(body,folder,document):
    env=dict(os.environ,PYTHONIOENCODING='utf-8',PYTHONUNBUFFERED='1',FFR_ATTACK_SETTINGS=str(folder/'settings.json'))
    try:
        write(folder/'settings.json',document)
        if body['scope']=='all':
            job['stage']='Converting all abilities, magic and LBs'
            output=ROOT/'build/ffbe-effects-attack-lab'
            job['catalog']=str(output/'catalog-conversion.json')
            process(ffrenv.py(str(ROOT/'tools/convert_ffbe_effects.py'),'--catalog','--resume','--out',str(output),
                              '--work',str(ROOT/'build/ffbe-effects-catalog-work')),env)
            job['message']=f'Catalog build finished: {output}'
        else:
            form=body['form']; key=body['key']
            entry,manifest=prepared(form,key)
            if entry is None:
                if ffrenv.FROZEN: raise ValueError('This move needs prepared effects from the offline converter.')
                job['stage']='Preparing the selected move'
                process(ffrenv.py(str(ROOT/'tools/convert_ffbe_effects.py'),form,'--move',key,'--universal',
                        '--manifest-out',str(folder/f'{form}.json'),'--work',str(folder/'prepare'),'--out',str(folder/'effects')),env)
                manifest=folder/f'{form}.json'
            units=host.load_spec()
            unit=next((u for u in units if str(u.get('ffbe',{}).get('id'))==form),None)
            import ffbe_catalog, vision_import
            if unit is None:
                owner=next(u for u in ffbe_catalog.load_index() if form in u['forms'])
                detail=ffbe_catalog.unit_detail(owner['id'])
                unit=host.default_spec(detail,form,'attacklab_'+form,owner['name'],units)
                units.append(unit)
                destination=ROOT/unit['ffbe']['dir']; destination.mkdir(parents=True,exist_ok=True)
                for path in ffbe_catalog.sprite_files(form): shutil.copy2(path,destination/Path(path).name)
            vision_import.hydrate(unit)
            vision_import.equip(unit,key)
            # Stage one complete mod snapshot, preserving other authored units.
            # Build scripts and verification both read this immutable selection.
            write(folder/'units.json',units)
            env['FFR_UNIT_SPEC']=str(folder/'units.json'); env['FFR_MOD_STEM']=STEM
            manifest_dir=folder/'presentations'; manifest_dir.mkdir(exist_ok=True)
            for u in units:
                fid=str(u.get('ffbe',{}).get('id',''))
                if not fid: continue
                combined={}
                base=None
                for path in reversed(manifests(fid)):
                    base=read(path); combined.update(base.get('moves',{}))
                if fid==form:
                    base=read(manifest); combined.update(base['moves'])
                if base: write(manifest_dir/f'{fid}.json',{**base,'moves':combined})
            env['FFR_PRESENTATION_DIR']=str(manifest_dir)
            job['stage']='Building the selected attack in your mod'
            process(ffrenv.py(str(ROOT/'tools/make_vision_mod.py'),'--no-install'),env)
            job['stage']='Verifying the built mod'
            process(ffrenv.py(str(ROOT/'tools/verify_mod.py')),env)
            if body.get('install'):
                job['stage']='Installing'; install(folder)
            job['message']='Installed. Launch FFR and use the selected move.' if body.get('install') else 'Build complete. Game files were not changed.'
            job['builtUnit']=unit['en']; job['output']=str(ROOT/'build/out'/f'{STEM}.utoc')
        job['result']='complete'
    except Exception as error:
        note(str(error)); job.update(result='failed',message=str(error))
    finally:
        with LOCK:
            job.update(running=False,ended=time.time(),stage='Finished' if job['result']=='complete' else 'Needs attention')
            host.state['running']=False
            write(folder/'job.json',job)


@router.post('/build')
async def build(request:Request):
    body=await request.json()
    try:
        if body.get('scope') not in ('move','all'): raise ValueError('Choose a move or all units')
        if body['scope']=='all' and ffrenv.FROZEN: raise ValueError('Build all requires the standalone offline converter on this computer.')
        if body['scope']=='move':
            body['form']=form_id(body['form']); native(body['form'])
            if body['key'] not in native(body['form'])['profiles']: raise ValueError('Unknown move')
        if body.get('install') and host.game_running(): raise ValueError('Close the game before building and installing.')
        with LOCK:
            if job['running'] or host.state['running']: raise HTTPException(409,'A build is already running')
            folder=WORK/time.strftime('%Y%m%d-%H%M%S'); folder.mkdir(parents=True,exist_ok=True)
            document=director.read_settings()
            job.clear(); job.update(running=True,stage='Starting',result=None,log=[],started=time.time(),
                                     folder=str(folder),scope=body['scope'])
            host.state['running']=True
        threading.Thread(target=run,args=(deepcopy(body),folder,deepcopy(document)),daemon=True).start()
        return {'ok':True}
    except (ValueError,KeyError,TypeError) as error: raise HTTPException(422,str(error)) from error


@router.get('/progress')
def progress():
    with LOCK: result=deepcopy(job)
    catalog=result.get('catalog')
    if catalog and Path(catalog).is_file():
        try:
            data=read(catalog); result['counts']={k:v for k,v in data.get('summary',{}).items() if not isinstance(v,(dict,list))}
            result['failures']=data.get('errors',[])[-8:]
        except (ValueError,OSError): result['checkpointPending']=True
    result['gameRunning']=host.game_running()
    return result


def register(app,module):
    global host
    host=module
    # Finished receipts remain visible after reopening Studio. Running work is
    # owned by this server process and is never inferred from a recycled PID.
    for receipt in sorted(WORK.glob('*/job.json'),key=lambda p:p.stat().st_mtime_ns,reverse=True)[:1]:
        try:
            previous=read(receipt)
            if previous.get('running') is False: job.update(previous)
        except (ValueError,OSError): pass
    app.include_router(router)
