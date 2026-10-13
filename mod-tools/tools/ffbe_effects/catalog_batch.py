"""Resumable offline catalog conversion with one prepared unit file per form.

Counts describe artifact completeness, never a numerical visual-fidelity claim.
All output is staged; this module does not install a mod or publish a catalog.
"""
from copy import copy, deepcopy
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zlib
import time
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import redirect_stdout, redirect_stderr

from .atomic_files import write_json
from . import catalog_coverage

SCHEMA = 'ffr-effects-catalog-batch-1'


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def encoded_hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
                                     separators=(',',':'),allow_nan=False).encode()).hexdigest()


def pipeline_identity(root, *, compiler_files=None):
    """Content-version the compiler; also detect changes in the local dump.

    Source inventory is a change detector, not a claim of content hashing every
    unreferenced particle. Individual bake reports retain dependency hashes.
    """
    files=list((root/'tools/ffbe_effects').glob('*.py'))
    files += [root/'tools'/name for name in ('convert_ffbe_effects.py','ffbe_presentation.py','ffbe_effect_bundle.py',
              'ffbe_resonance.py','ffbe_attack_director.py','ffbe_target_camera.py','ffbe_cast_camera.py','make_vision_mod.py','ffbe_audio.py','devui/ffbe_catalog.py','release/unit_assets.py')]
    files += list((root/'tools/ffbe2ss6').glob('*.py'))
    files += list((root/'src/ffr-dt').glob('Kismet*.cs'))
    code={p.relative_to(root).as_posix():digest(p) for p in files if p.is_file()}
    if compiler_files is not None:
        # Used only by the explicit, hash-guarded performance receipt migration.
        code=dict(compiler_files)
    inputs=[]
    import ffbe_attack_director
    inputs.append(['attackDirector',encoded_hash(ffbe_attack_director.read_settings())])
    from .regional_assets import gl_root, index
    regional_root=gl_root()
    inputs.append(['regionalRoot',str(regional_root.resolve())])
    for paths in index(str(regional_root.resolve())).values():
        for path in paths:
            stat=path.stat()
            inputs.append([str(path.resolve()),stat.st_size,stat.st_mtime_ns])
    for folder in ('build/ffbe_cpk/effects_dec','build/devui/live_jp'):
        for path in sorted((root/folder).glob('*')):
            if path.is_file():
                stat=path.stat()
                inputs.append([path.relative_to(root).as_posix(),stat.st_size,stat.st_mtime_ns])
    geometry_roots=[root/'data/ffbe/sprites',root/'build/ffbe_cpk/jp_live_dec']
    # Respect the same ordered sprite roots used by anim_source, including the
    # external export. Inventory only geometry metadata, never multi-GB pixels.
    if root.resolve()==Path(__file__).resolve().parents[2]:
        from devui import ffbe_catalog
        geometry_roots=[Path(row[0]) for row in ffbe_catalog.SPRITE_ROOTS]
    seen=set()
    for folder in geometry_roots:
        if folder.resolve() in seen: continue
        seen.add(folder.resolve())
        inputs.append(['geometryRoot',str(folder.resolve()),folder.is_dir()])
        for directory,_,names in os.walk(folder):
            for name in names:
                lower=name.lower()
                if not (Path(lower).suffix in ('.cgg','.cgs') or
                        lower.endswith('.csv') and ('_cgg_' in lower or '_cgs_' in lower)): continue
                path=Path(directory)/name
                stat=path.stat()
                inputs.append([str(path.resolve()),stat.st_size,stat.st_mtime_ns])
    for folder in (root/'data/ffbe/audio',Path('S:/FFBE JP Data Export/public')):
        for name in ('SE.acb','System.acb'):
            path=folder/name
            if path.is_file():
                stat=path.stat()
                inputs.append([str(path.resolve()),stat.st_size,stat.st_mtime_ns])
    from . import catalog
    for folder in catalog.RAW_SOURCES.values():
        for name in ('F_ABILITY_MST','F_MAGIC_MST','F_LIMITBURST_MST','F_EFFECT_GROUP_MST','F_EFFECT_MST','F_UNIT_MST'):
            path=Path(folder)/(name+'.txt')
            if path.is_file():
                inputs.append([str(path.resolve()),digest(path)])
    fields=Path(catalog.ffbe_live.FIELDS)
    if fields.is_file():
        inputs.append([str(fields.resolve()),digest(fields)])
    for path in sorted((root/'data/ffbe/presentation/profiles').glob('*.json')):
        # Universal preparation retains only this gameplay preference, not the
        # old move-specific camera or offset calibrations. Hash opaque bytes so
        # a malformed profile is isolated by its form, not an inventory abort.
        inputs.append([path.relative_to(root).as_posix(),digest(path)])
    inputs.sort(key=lambda row:str(row[0]))
    return {'sha256':encoded_hash({'code':code,'sourceInventory':inputs}),
            'compilerFiles':code,'sourceInventoryEntries':len(inputs),
            'sourceInventoryPolicy':'path-size-mtime change detection; referenced bakes also hash source contents'}


def _inside(root, value):
    path=(root/value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Catalog receipt dependency escaped the repository')
    return path


def _receipt_path(args, form, key):
    return args.work/'receipts'/form/(encoded_hash(key)+'.json')


def cached_move(args, form, key, snapshot):
    if not getattr(args,'resume',False):
        return None
    import ffbe_presentation
    receipt_path=_receipt_path(args,form,key)
    if not receipt_path.is_file() or not args.manifest_out.is_file():
        return None
    try:
        receipt=json.loads(receipt_path.read_bytes())
        if (receipt.get('schema')!=SCHEMA or receipt.get('form')!=form
                or receipt['pipeline'] not in {args.catalog_context['pipeline'], *args.catalog_context.get('compatiblePipelines', [])} or receipt['sourceKey']!=key
                or receipt['sourceSha256']!=ffbe_presentation.source_fingerprint(snapshot)):
            return None
        document=json.loads(args.manifest_out.read_bytes())
        if str(document.get('form'))!=form: return None
        entry=document['moves'][key]
        if encoded_hash(entry)!=receipt['entrySha256']:
            return None
        root=Path(args.catalog_context['root'])
        if _move_dependencies(root,entry)!=receipt['dependencies']:
            return None
        return receipt['reportSummary']
    except (OSError,ValueError,KeyError,TypeError):
        return None


def _move_dependencies(root, entry):
    """Hash the full prepared closure, including samples referenced by a bank."""
    dependencies={}
    for visual in entry.get('visuals',[]):
        for name,expected in visual.get('checksums',{}).items():
            path=(Path(visual['spec'])/name).as_posix()
            if digest(_inside(root,path))!=expected:
                raise ValueError('Prepared catalog dependency changed: '+path)
            dependencies[path]=expected
    bank_paths=set(entry.get('audioBanks',{}).values())
    if entry.get('audioBank'): bank_paths.add(entry['audioBank'])
    for bank_name in sorted(bank_paths):
        bank_path=_inside(root,bank_name)
        dependencies[bank_name]=digest(bank_path)
        bank=json.loads(bank_path.read_bytes())
        for wave in bank['waves'].values():
            path='data/ffbe/audio/samples/'+wave['sha256']+'.hca'
            actual=digest(_inside(root,path))
            if actual!=wave['sha256']:
                raise ValueError('Prepared catalog audio sample changed: '+path)
            dependencies[path]=actual
    return dependencies


def record_move(args, form, key, snapshot, audit):
    import convert_ffbe_effects as cli
    import ffbe_presentation
    entry=audit['forms'][form]['moves'][key]
    dependencies=_move_dependencies(Path(args.catalog_context['root']),entry)
    return _write_receipt(_receipt_path(args,form,key),{
        'schema':SCHEMA,'form':form,'pipeline':args.catalog_context['pipeline'],'sourceKey':key,
        'sourceSha256':ffbe_presentation.source_fingerprint(snapshot),
        'entrySha256':encoded_hash(entry),'dependencies':dependencies,
        'reportSummary':cli.report_summary(audit,form,key)})


def _write_receipt(path, document):
    try:
        write_json(path,document,ensure_ascii=False,separators=(',',':'))
    except OSError as error:
        return {'path':str(path),'errorType':type(error).__name__,'error':str(error),
                'impact':'Prepared output remains valid; this cache entry may need rebuilding on resume'}
    return None


def membership_counts(root, forms):
    """Use the deduplicated source database for counting, with a fixture fallback."""
    result={}
    database=root/'data/ability_converter/vision-kits.sqlite'
    if database.is_file():
        try:
            with closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True)) as db:
                for form,payload in db.execute('SELECT form,payload FROM kits'):
                    if form in forms:
                        try:
                            kit=json.loads(zlib.decompress(payload))
                            active=[entry for entry in kit['entries'] if entry['kind']!='PASSIVE']
                            result[form]={'active':len(active),'ready':sum(e['status']=='ready' for e in active)}
                        except (ValueError,KeyError,TypeError,zlib.error):
                            pass # Fall back to this form's native kit below.
        except (OSError,sqlite3.Error):
            pass
    for form in forms:
        if form not in result:
            try:
                document=json.loads((root/'data/ffbe/native_kits'/f'{form}.json').read_bytes())
                active=[entry for entry in document['kit']['entries'] if entry['kind']!='PASSIVE']
                result[form]={'active':len(active),'ready':sum(e['status']=='ready' for e in active)}
            except (OSError,ValueError,KeyError,TypeError):
                # The per-form runner records the concrete error and continues.
                result[form]={'active':0,'ready':0,'unavailable':True}
    return result


def summarize(catalog, forms, counts, results, errors, *, finished):
    completed={r['form'] for r in results}
    failed={r['form'] for r in errors}
    units=[]
    for unit in catalog['units']:
        done=[f for f in unit['forms'] if f in completed]
        units.append({'id':unit['id'],'forms':unit['forms'],'bundledForms':done,
                      'complete':len(done)==len(unit['forms'])})
    gaps=bool(errors or any(r.get('failedMoves') for r in results))
    status='pilot_complete' if len(forms)<len(catalog['forms']) else 'complete'
    return {'status':(status+'_with_gaps' if gaps else status)
                     if finished else 'running',
            'catalogVisions':len(catalog['units']),'catalogForms':len(catalog['forms']),
            'selectedForms':len(forms),'processedForms':len(completed|failed),
            'bundledForms':len(completed),'failedForms':len(failed),
            'visionsWithAnyBundle':sum(bool(u['bundledForms']) for u in units),
            'visionsWithEveryFormBundled':sum(u['complete'] for u in units),
            'activeMoveMemberships':sum(counts[f]['active'] for f in forms),
            'readyMoveMemberships':sum(counts[f]['ready'] for f in forms),
            'heldMoveMemberships':sum(counts[f]['active']-counts[f]['ready'] for f in forms),
            'unavailableCountForms':[f for f in forms if counts[f].get('unavailable')],
            'baseOnlyForms':sum(r.get('operation')=='preserve-base-unit' for r in results),
            'failedMoveMemberships':sum(len(r.get('failedMoves',[])) for r in results)+sum(len(e.get('moveErrors',[])) for e in errors),
            'cacheWarnings':sum(len(r.get('cacheWarnings',[])) for r in results),
            'preparedMoveMemberships':sum(len(r.get('preparedMoves',[])) for r in results+errors),
            'completeSourceMoveMemberships':sum(len(r.get('completeSourceMoves',[])) for r in results),
            'visualFidelity':{'target':'approximately 80%, allowing approximations',
                              'measuredPercent':None,'nativeValidation':'not established by catalog counts'},
            'units':units}


def _valid_form_receipt(path, stamp, output, form, compatible=()):
    if not path.is_file():
        return None
    try:
        receipt=json.loads(path.read_bytes())
        result=receipt['result']
        inputs=dict(receipt['inputs'])
        if inputs.get('pipeline') in compatible: inputs['pipeline']=stamp['pipeline']
        expected_outputs={f'{form}.ffr'}
        if result.get('operation')!='preserve-base-unit': expected_outputs.add(f'{form}.ffr-effects')
        if (receipt.get('schema')!=SCHEMA or inputs!=stamp or result['form']!=form
                or result.get('failedMoves') or set(receipt['outputs'])!=expected_outputs):
            return None
        for name,expected in receipt['outputs'].items():
            target=(output/name).resolve()
            if not target.is_relative_to(output.resolve()) or digest(target)!=expected:
                return None
        return result
    except (OSError,ValueError,KeyError,TypeError):
        return None


def _base_only(source, output, form, expected_sha):
    """Keep a no-ready-move form in the catalog without inventing effects."""
    target=output/f'{form}.ffr'
    descriptor,temporary=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.tmp',dir=output)
    try:
        with os.fdopen(descriptor,'wb') as dest,source.open('rb') as src:
            shutil.copyfileobj(src,dest)
            dest.flush()
            os.fsync(dest.fileno())
        if digest(temporary)!=expected_sha:
            raise ValueError('Original unit changed while it was being copied')
        os.replace(temporary,target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    effects=output/f'{form}.ffr-effects'
    retired=[]
    if effects.exists():
        previous=effects.with_name(effects.name+'.previous-'+digest(effects))
        os.replace(effects,previous)
        retired.append(str(previous.resolve()))
    return {'form':form,'operation':'preserve-base-unit','unit':str(target.resolve()),'effects':None,
            'moves':0,'preparedMoves':[],'completeSourceMoves':[],'failedMoves':[],
            'reason':'No eligible active moves in this form; original unit retained without an effects archive',
            'retiredOutputs':retired}


def worker_progress(args, form, phase, move=None):
    if not getattr(args, 'catalog_context', None): return
    try:
        write_json(args.work/'progress'/(form+'.json'), {
            'form':form, 'phase':phase, 'move':move, 'processId':os.getpid(),
            'updatedUtc':datetime.now(timezone.utc).isoformat()})
    except OSError:
        pass  # A progress display failure must never discard prepared work.


def _convert_one(args, root, form, owner, pipeline, catalog_identity):
    import convert_ffbe_effects as cli
    import ffbe_effect_bundle
    from .conversion_io import file_lock
    started=time.perf_counter()
    source=args.unit_dir/f'{form}.ffr'
    native=root/'data/ffbe/native_kits'/f'{form}.json'
    receipt_path=args.work/'form-receipts'/f'{form}.json'
    try:
        with file_lock(args.work/'.form-locks'/(form+'.lock')):
            stamp={'pipeline':pipeline,'catalog':catalog_identity,
                   'unitSha256':digest(source),'nativeKitSha256':digest(native)}
            document=json.loads(native.read_bytes())
            active=[entry for entry in document['kit']['entries'] if entry['kind']!='PASSIVE']
            ready=[entry for entry in active if entry['status']=='ready']
            held=[entry['sourceKey'] for entry in active if entry['status']!='ready']
            cached=_valid_form_receipt(receipt_path,stamp,args.out,form,getattr(args,'compatible_pipelines',())) if args.resume else None
            if cached is not None:
                return {'result':{**cached,'resumed':True},'seconds':time.perf_counter()-started}
            selected=copy(args)
            selected.unit=source
            selected.manifest_out=args.work/'manifests'/f'{form}.json'
            selected.universal=True
            selected.allow_partial=True
            selected.no_previews=True
            selected.catalog_context={'pipeline':pipeline,'root':str(root.resolve()),
                                      'compatiblePipelines':getattr(args,'compatible_pipelines',[])}
            ffbe_effect_bundle.COMPRESSION_CACHE=args.work/'compressed-pages'
            worker_progress(selected,form,'preparing')
            result=(cli.convert_form(selected,form) if ready else
                    _base_only(source,args.out,form,stamp['unitSha256']))
            result['catalogVision']=owner
            result['heldMoves']=held
            outputs={f'{form}.ffr':digest(args.out/f'{form}.ffr')}
            if ready: outputs[f'{form}.ffr-effects']=digest(args.out/f'{form}.ffr-effects')
            if not result.get('failedMoves'):
                warning=_write_receipt(receipt_path,{'schema':SCHEMA,'inputs':stamp,'outputs':outputs,'result':result})
                if warning: result.setdefault('cacheWarnings',[]).append(warning)
            worker_progress(selected,form,'finished')
            return {'result':result,'seconds':time.perf_counter()-started}
    except Exception as error:
        failure={'form':form,'catalogVision':owner,'errorType':type(error).__name__,'error':str(error)}
        if isinstance(error,cli.MovePreparationError):
            failure.update(moveErrors=error.move_errors,preparedMoves=error.prepared_moves)
        return {'error':failure,'seconds':time.perf_counter()-started}


def _worker(args, root, form, owner, pipeline, catalog_identity):
    log=args.work/'logs'/(form+'.log')
    log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('a',encoding='utf-8',buffering=1) as stream, redirect_stdout(stream), redirect_stderr(stream):
        print('Started',datetime.now(timezone.utc).isoformat(),form,flush=True)
        return _convert_one(args,root,form,owner,pipeline,catalog_identity)


def run(args, *, root):
    from .conversion_io import file_lock
    with file_lock(args.work/'.conversion.lock', blocking=False):
        return _run(args, root=root)


def _run(args, *, root):
    import convert_ffbe_effects as cli
    root=Path(root)
    if args.forms or args.all or args.move or args.profile or args.unit or args.package_only:
        raise ValueError('--catalog selects the full catalog; use --limit-forms for a bounded pilot')
    if args.retain_prepared or args.rebuild_source or args.manifest_out or args.reports_from:
        raise ValueError('--catalog uses its own staged manifests and --resume receipts')
    if args.limit_forms is not None and args.limit_forms<=0:
        raise ValueError('--limit-forms must be positive')
    catalog_path=args.catalog_index or root/'build/devui/ffbe_index.json'
    catalog=catalog_coverage.load_catalog(catalog_path)
    unit_dir=args.unit_dir or root/'build/native-editor/host/ffbe/units'
    args.out.mkdir(parents=True,exist_ok=True)
    args.work.mkdir(parents=True,exist_ok=True)
    if args.audit_only:
        census=catalog_coverage.build_census(root,catalog_path=catalog_path,unit_dir=unit_dir)
        write_json(args.out/'source-coverage.json',census,ensure_ascii=False,indent=2)
        print('Source census saved to '+str(args.out/'source-coverage.json'),flush=True)
        return census
    forms=catalog['forms'][:args.limit_forms] if args.limit_forms else catalog['forms']
    for form in forms:
        source=unit_dir/f'{form}.ffr'
        destination=args.out/f'{form}.ffr'
        if source.resolve()==destination.resolve():
            raise ValueError('Catalog output must be separate from original unit archives')
    counts=membership_counts(root,set(forms))
    pipeline=deepcopy(pipeline_identity(root))
    pipeline['playbackPolicy']=getattr(args,'playback_policy','legacy')
    pipeline['sha256']=encoded_hash({'compiler':pipeline['sha256'],'playbackPolicy':pipeline['playbackPolicy']})
    args=copy(args)
    args.compatible_pipelines=[]
    compatibility=args.work/'pipeline-compatibility.json'
    if compatibility.is_file():
        transition=json.loads(compatibility.read_bytes())
        if (transition.get('schema')=='ffr-reviewed-io-recovery-1'
                and transition.get('newPipeline')==pipeline['sha256']
                and transition.get('sourceInventoryUnchanged') is True):
            args.compatible_pipelines=[transition['oldPipeline']]
    results,errors=[],[]
    previous_path=args.out/'catalog-conversion.json'
    if getattr(args,'continue_pass',False):
        if not args.resume or not previous_path.is_file():
            raise ValueError('--continue-pass requires --resume and an existing catalog report')
        previous=json.loads(previous_path.read_bytes())
        if (previous.get('schema')!=SCHEMA or previous.get('catalog',{}).get('sha256')!=catalog['identity']['sha256']
                or previous.get('requestedForms')!=forms
                or Path(previous['sourceUnitDirectory']).resolve()!=unit_dir.resolve()
                or previous.get('pipeline',{}).get('sha256') not in {pipeline['sha256'], *args.compatible_pipelines}):
            raise ValueError('Previous pass has different catalog, sources or unreviewed compiler changes')
        results=previous['results']; errors=previous['errors']
        completed=[r['form'] for r in results+errors]
        if len(set(completed))!=len(completed) or not set(completed).issubset(forms):
            raise ValueError('Previous report has duplicate or unknown forms')
    carried={r['form'] for r in results+errors}
    remaining_forms=[form for form in forms if form not in carried]
    report={'schema':SCHEMA,'catalog':catalog['identity'],'pipeline':pipeline,
            'requestedForms':forms,'sourceUnitDirectory':str(unit_dir.resolve()),
            'results':results,'errors':errors}
    last_warning=-float('inf')
    def checkpoint(finished=False):
        nonlocal last_warning
        report['summary']=summarize(catalog,forms,counts,results,errors,finished=finished)
        try:
            write_json(args.out/'catalog-conversion.json',report,ensure_ascii=False,indent=2)
        except PermissionError:
            if finished: raise
            # Per-move/form receipts remain durable. A locked status display
            # must not unwind the process pool or stop scheduling new work.
            if time.monotonic()-last_warning>=60:
                print('Progress file is temporarily locked; conversion continues and will retry.',flush=True)
                last_warning=time.monotonic()
    checkpoint()
    args=copy(args)
    args.unit_dir=unit_dir
    workers=getattr(args,'workers',1)
    if not 1<=workers<=8: raise ValueError('workers must be between 1 and 8')
    run_start=time.perf_counter()
    report['runtime']={'processId':os.getpid(),'startedUtc':datetime.now(timezone.utc).isoformat(),
                       'workers':workers,'activeForms':[],'completedThisRun':0,'convertedThisRun':0,
                       'carriedForwardForms':len(carried)}
    def accept(outcome):
        if 'result' in outcome: results.append(outcome['result'])
        else: errors.append(outcome['error'])
        report['runtime']['completedThisRun']+=1
        if not outcome.get('result',{}).get('resumed'):
            report['runtime']['convertedThisRun']+=1
        report['runtime']['elapsedSeconds']=time.perf_counter()-run_start
        done=len(results)+len(errors)
        print(f'[{done}/{len(forms)}] {100*done/len(forms):.1f}% | {len(results)} exported | {len(errors)} failed | '
              f"last form {outcome.get('result',outcome.get('error'))['form']}: {outcome['seconds']:.1f}s",flush=True)
        checkpoint()
    if workers==1:
        for form in remaining_forms:
            report['runtime']['activeForms']=[form]
            checkpoint()
            accept(_convert_one(args,root,form,catalog['owners'][form],pipeline['sha256'],catalog['identity']['sha256']))
    else:
        iterator=iter(remaining_forms)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            pending={}
            def fill():
                while len(pending)<workers:
                    form=next(iterator,None)
                    if form is None: break
                    future=pool.submit(_worker,args,root,form,catalog['owners'][form],pipeline['sha256'],catalog['identity']['sha256'])
                    pending[future]=form
                report['runtime']['activeForms']=list(pending.values())
            fill(); checkpoint()
            while pending:
                finished,_=wait(pending,timeout=10,return_when=FIRST_COMPLETED)
                for future in finished:
                    pending.pop(future)
                    accept(future.result())
                fill()
                report['runtime']['heartbeatUtc']=datetime.now(timezone.utc).isoformat()
                report['runtime']['elapsedSeconds']=time.perf_counter()-run_start
                checkpoint()
    report['runtime']['activeForms']=[]
    checkpoint(True)
    print(json.dumps({k:v for k,v in report['summary'].items() if k!='units'},ensure_ascii=False),flush=True)
    return report
