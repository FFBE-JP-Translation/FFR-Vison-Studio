"""Offline FFBE -> portable FFR sound and particle effects.

This developer command is deliberately excluded from Vision Studio. Studio
consumes the prepared archive; it never needs FFBE master tables or BMB files.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'),str(ROOT/'tools/ffbe_effects')]


class ConversionBatchError(ValueError):
    """Failures are reported only after the remaining selected forms run."""
    def __init__(self, results, errors):
        self.results, self.errors = results, errors
        super().__init__(f'{len(errors)} form(s) failed; {len(results)} completed. '
                         'See conversion.json for each result.')


class MovePreparationError(ValueError):
    """A form remains unpublished, but its successful preparations can resume."""
    def __init__(self, form, errors, prepared_moves):
        self.move_errors, self.prepared_moves = errors, prepared_moves
        super().__init__(f'{form}: {len(errors)} move(s) failed; '
                         f'{len(prepared_moves)} prepared. No archive published for this form.')


def report_summary(audit, form, key):
    move=audit.get('forms',{}).get(form,{}).get('moves',{}).get(key,{})
    return {
        'decoderFidelity':audit['decoderFidelity'],
        'assets':audit['assets'],'soundOmissions':audit['soundOmissions'],
        'retainedLegacyVisuals':move.get('retainedLegacyVisuals'),
        'rebuiltPreparedVisuals':move.get('rebuiltPreparedVisuals')}


def reuse_preparation_report(directory, form, key, entry):
    """Reuse an audit only when it describes the exact prepared move being shipped."""
    path=directory/form/key.replace('/','_')/'report.json'
    payload=path.read_bytes()
    audit=json.loads(payload)
    recorded=audit.get('forms',{}).get(form,{}).get('moves',{}).get(key)
    if recorded!=entry:
        raise ValueError(f'{form}: preparation report does not match prepared move {key}: {path}')
    summary=report_summary(audit,form,key)
    summary['preparationReport']={'path':str(path.resolve()),
                                  'sha256':hashlib.sha256(payload).hexdigest(),
                                  'validation':'exact prepared move equality before portable encoding'}
    return summary


def selected_entries(root, form, moves=None):
    path=root/'data/ffbe/native_kits'/f'{form}.json'
    native=json.loads(path.read_text(encoding='utf-8'))
    entries={e['sourceKey']:e for e in native['kit']['entries']
             if e['kind']!='PASSIVE' and e['status']=='ready'}
    if moves:
        absent=set(moves)-set(entries)
        if absent:
            raise ValueError(f'{form}: moves are not ready in this form: {sorted(absent)}')
        entries={key:entries[key] for key in moves}
    if not entries:
        raise ValueError(f'{form}: no ready active moves')
    return native,entries


def validate_rebuild_selection(args, forms):
    """Catch misspelled repair selectors before publishing any selected form."""
    requested=getattr(args,'rebuild_source',None)
    if not requested:
        return
    if not getattr(args,'retain_prepared',False):
        raise ValueError('--rebuild-source requires --retain-prepared')
    if any(not isinstance(name,str) or '/' in name or '\\' in name or ':' in name
           or not name.lower().endswith('.bmb') or len(name)<=4 for name in requested):
        raise ValueError('--rebuild-source requires source BMB basenames, without directories')
    found=set()
    for form in forms:
        _,entries=selected_entries(ROOT,form,args.move)
        staged=getattr(args,'manifest_out',None)
        path=staged if staged is not None and staged.is_file() else ROOT/'data/ffbe/presentation'/f'{form}.json'
        if not path.is_file():
            continue # The normal per-form retention error is recorded by run().
        doc=json.loads(path.read_text(encoding='utf-8'))
        for key in entries:
            for spawn in doc.get('moves',{}).get(key,{}).get('spawns',[]):
                if isinstance(spawn.get('file'),str): found.add(spawn['file'].casefold())
    missing=[name for name in requested if name.casefold() not in found]
    if missing:
        raise ValueError('Rebuild sources do not occur in the selected prepared moves: '+', '.join(missing))


def convert_form(args, form):
    import ffbe_effect_bundle
    native,entries=selected_entries(ROOT,form,args.move)
    reports={}
    cache_warnings=[]
    if not args.package_only:
        import prepare_vision
        # Bake identity includes the source dependencies, seed, and decoder.
        # Share this cache across moves/forms; reports retain separate folders.
        prepare_vision.CACHE=args.work/'decoded'
        preparation_errors, prepared_moves = [], []
        for key in entries:
            try:
                if getattr(args,'catalog_context',None):
                    from ffbe_effects.catalog_batch import worker_progress
                    worker_progress(args,form,'preparing',key)
                profile_path=args.profile or ROOT/'data/ffbe/presentation/profiles'/f'{form}.json'
                stored_profile=json.loads(profile_path.read_text(encoding='utf-8')) if profile_path.is_file() else None
                profile=stored_profile if args.profile or not getattr(args,'universal',False) else None
                if profile and profile.get('sourceKey')!=key:
                    if args.profile:
                        raise ValueError('Explicit profile belongs to a different move')
                    profile=None
                prepare_vision.WORK=args.work/form/key.replace('/','_')
                options={'detect_scene':True,'merge_existing':True}
                if getattr(args,'no_previews',False): options['make_previews']=False
                if getattr(args,'universal',False): options['universal']=True
                if (getattr(args,'universal',False) and not args.profile and stored_profile
                        and str(stored_profile.get('form'))==form and stored_profile.get('sourceKey')==key
                        and 'hostTargetType' in stored_profile):
                    # An explicit gameplay target preference is independent of
                    # historical camera/offset calibration and source geometry.
                    options['host_preferences']={'hostTargetType':stored_profile['hostTargetType']}
                if getattr(args,'retain_prepared',False): options['retain_prepared']=True
                if getattr(args,'rebuild_source',None): options['rebuild_sources']=args.rebuild_source
                if getattr(args,'manifest_out',None): options['manifest_out']=args.manifest_out
                context=getattr(args,'catalog_context',None)
                if context:
                    from ffbe_effects import catalog_batch
                    cached=catalog_batch.cached_move(args,form,key,native['profiles'][key]['snapshot'])
                    if cached is not None:
                        reports[key.replace('/','_')+'.json']=cached
                        prepared_moves.append(key)
                        continue
                if getattr(args,'playback_policy','legacy')=='cast-target':
                    from ffbe_effects.regional_assets import staged
                    with staged(prepare_vision,native['profiles'][key]['snapshot'],prepare_vision.WORK/'regional-source'):
                        audit=prepare_vision.prepare([form],[key],profile,**options)
                else:
                    audit=prepare_vision.prepare([form],[key],profile,**options)
                if context:
                    warning=catalog_batch.record_move(args,form,key,native['profiles'][key]['snapshot'],audit)
                    if warning: cache_warnings.append({'sourceKey':key,**warning})
            except Exception as error:
                # Finish inspecting the selected source set. An unresolved move
                # must not silently skip the rest of its form, or cause an old
                # prepared copy of that move to be published as fresh output.
                failure={'sourceKey':key,'error':str(error),'errorType':type(error).__name__}
                preparation_errors.append(failure)
                print(json.dumps({'form':form,**failure},ensure_ascii=False),flush=True)
                continue
            prepared_moves.append(key)
            reports[key.replace('/','_')+'.json']=report_summary(audit,form,key)
        if preparation_errors and (not getattr(args,'allow_partial',False) or not prepared_moves):
            raise MovePreparationError(form,preparation_errors,prepared_moves)
        if preparation_errors:
            entries={key:entry for key,entry in entries.items() if key in prepared_moves}
    manifest=getattr(args,'manifest_out',None) or ROOT/'data/ffbe/presentation'/f'{form}.json'
    doc=json.loads(manifest.read_text(encoding='utf-8'))
    if str(doc.get('form'))!=form:
        raise ValueError(f'{form}: prepared manifest belongs to another form')
    import ffbe_presentation
    shipped={}
    for key in entries:
        entry=doc['moves'].get(key)
        if not entry:
            raise ValueError(f'{form}: missing prepared move {key}; run conversion first')
        snapshot=native['profiles'][key]['snapshot']
        if entry['sourceSha256']!=ffbe_presentation.source_fingerprint(snapshot):
            raise ValueError(f'{form}: stale prepared move {key}; run conversion first')
        import ffbe_attack_director as director
        if getattr(args,'playback_policy','legacy')=='cast-target':
            from ffbe_effects.playback_policy import configure
            shipped[key]=configure(entry,form,key)
        else:
            shipped[key]=director.configure(entry,director.resolve(form,key,entry))
        shipped[key]['reconstructionProfile'].update(form=form,sourceKey=key)
        if getattr(args,'reports_from',None):
            reports[key.replace('/','_')+'.json']=reuse_preparation_report(args.reports_from,form,key,entry)
    # The working manifest may include older moves and other manual selections.
    # Package exactly this request, without mutating that reusable preparation.
    selected_manifest=args.work/form/'package-manifest.json'
    selected_manifest.parent.mkdir(parents=True,exist_ok=True)
    selected_manifest.write_text(json.dumps({**doc,'moves':shipped},ensure_ascii=False,
                                           separators=(',',':')),encoding='utf-8')
    output=args.out/f'{form}.ffr-effects'
    if getattr(args,'catalog_context',None):
        from ffbe_effects.catalog_batch import worker_progress
        worker_progress(args,form,'packaging')
    info=ffbe_effect_bundle.pack(selected_manifest,output,root=ROOT,reports=reports)
    ffbe_effect_bundle.verify(output,expected_form=form)
    result={'form':form,'effects':str(output.resolve()),'metadata':info,
            'operation':'package-prepared' if args.package_only else 'convert-source',
            'rebuildSourceFiles':getattr(args,'rebuild_source',None) or [],
            'preparationReports':{name:report['preparationReport'] for name,report in reports.items()
                                  if 'preparationReport' in report},
            'moves':len(shipped),'sceneKinds':{k:v.get('backgroundDetection',{}).get('kind','legacy_unclassified')
                                             for k,v in shipped.items()}}
    if getattr(args,'allow_partial',False):
        failures=[] if args.package_only else preparation_errors
        complete=[key for key,entry in shipped.items() if
                  entry.get('visualCoverage',{}).get('complete') is True and
                  not any(str(sound['cueId']) in entry.get('soundOmissions',{}) for sound in entry.get('sounds',[]))]
        result.update(failedMoves=failures,preparedMoves=list(shipped),completeSourceMoves=complete,
                      approximationPolicy='Known particle approximations retained and reported; no native visual accuracy percentage asserted')
    if cache_warnings: result['cacheWarnings']=cache_warnings
    if args.unit:
        unit_output=args.out/f'{form}.ffr'
        result['unitBundle']=ffbe_effect_bundle.merge(args.unit,output,unit_output)
        result['unit']=str(unit_output.resolve())
    return result


def run(args):
    forms=list(dict.fromkeys(args.forms))
    if args.all:
        forms=sorted(p.stem for p in (ROOT/'data/ffbe/native_kits').glob('*.json'))
    if not forms:
        raise ValueError('Select at least one form, or --all')
    if any(not f.isdecimal() for f in forms):
        raise ValueError('Form IDs must be decimal digits')
    if args.unit and len(forms)!=1:
        raise ValueError('--unit merges one selected form at a time')
    if getattr(args,'manifest_out',None) and len(forms)!=1:
        raise ValueError('--manifest-out stages one selected form at a time')
    if getattr(args,'retain_prepared',False) and args.package_only:
        raise ValueError('--retain-prepared enriches source groups; omit --package-only')
    if getattr(args,'reports_from',None) and not args.package_only:
        raise ValueError('--reports-from reuses existing audits and requires --package-only')
    if args.profile and (len(forms)!=1 or not args.move or len(args.move)!=1):
        raise ValueError('--profile requires one form and one exact --move')
    if args.profile and not args.profile.is_file():
        raise FileNotFoundError(f'Explicit conversion profile not found: {args.profile}')
    validate_rebuild_selection(args,forms)
    args.out.mkdir(parents=True,exist_ok=True)
    args.work.mkdir(parents=True,exist_ok=True)
    results,errors=[],[]
    for form in forms:
        print(f'Processing form {form}',flush=True)
        try:
            result=convert_form(args,form)
        except Exception as error:
            # One bad source must not prevent the rest of a catalog batch from
            # producing reviewable results. Interrupts still stop immediately.
            failure={'form':form,'error':str(error),'errorType':type(error).__name__}
            if isinstance(error,MovePreparationError):
                failure.update(moveErrors=error.move_errors,preparedMoves=error.prepared_moves)
            errors.append(failure)
            print(json.dumps(failure,ensure_ascii=False),flush=True)
        else:
            results.append(result)
            print(json.dumps(result,ensure_ascii=False),flush=True)
        (args.out/'conversion.json').write_text(json.dumps({'schema':'ffr-effects-conversion-1','forms':results,
                                                          'errors':errors,'requestedForms':forms,
                                                          'status':('running' if len(results)+len(errors)<len(forms)
                                                                    else 'failed' if errors else 'complete')},
                                                        indent=2,ensure_ascii=False),encoding='utf-8')
    if errors:
        raise ConversionBatchError(results,errors)
    return results


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('forms',nargs='*',help='Prepared native-kit form IDs; converts every ready active ability/magic/LB')
    parser.add_argument('--all',action='store_true',help='Convert every local native-kit form')
    parser.add_argument('--universal',action='store_true',help='Use the shared source-coordinate adapter for selected forms and moves')
    parser.add_argument('--move',action='append',help='Exact source key; repeat to select several moves')
    parser.add_argument('--profile',type=Path,help='Optional reviewed source/host calibration for one exact move')
    parser.add_argument('--out',type=Path,default=ROOT/'build/ffbe-effects-delivery')
    parser.add_argument('--work',type=Path,default=ROOT/'build/ffbe-effects-offline')
    parser.add_argument('--package-only',action='store_true',help='Verify source fingerprints and package existing prepared effects')
    parser.add_argument('--reports-from',type=Path,help='Include existing per-move preparation reports from this work directory, requiring exact prepared-entry matches (--package-only)')
    parser.add_argument('--retain-prepared',action='store_true',help='Preserve byte-verified source-identical prepared groups; convert only missing groups and report legacy settings')
    parser.add_argument('--rebuild-source',action='append',metavar='FILE.bmb',help='With --retain-prepared, rebuild complete groups containing this source file; repeat for several files')
    parser.add_argument('--manifest-out',type=Path,help='Write/read a staged prepared manifest instead of changing the reusable project manifest (one form)')
    parser.add_argument('--unit',type=Path,help='Merge finished effects into this portable .ffr unit archive')
    parser.add_argument('--catalog',action='store_true',help='Process every vision/form in the catalog and merge effects into its unit archive')
    parser.add_argument('--catalog-index',type=Path,help='Vision catalog JSON (defaults to the local 1,295-vision catalog)')
    parser.add_argument('--unit-dir',type=Path,help='Directory of source .ffr unit archives for --catalog')
    parser.add_argument('--audit-only',action='store_true',help='Read all catalog source dependencies without rendering or publishing')
    parser.add_argument('--resume',action='store_true',help='Resume verified catalog preparations and completed archives')
    parser.add_argument('--workers',type=int,default=1,help='Independent catalog form processes (1-8); source caches are protected by locks')
    parser.add_argument('--continue-pass',action='store_true',help='Keep prior reported outcomes and resume only forms not yet processed; failed forms remain reported for a later repair pass')
    parser.add_argument('--limit-forms',type=int,help='Bound a catalog pilot; its report never claims full catalog completion')
    parser.add_argument('--playback-policy',choices=('legacy','cast-target'),default='legacy',help='Bundle the refined cast/target framing, foreground vision order and uniform screen cover')
    args=parser.parse_args(argv)
    if not 1<=args.workers<=8: parser.error('--workers must be between 1 and 8')
    # Fresh source conversion uses the shared adapter. Retention and an
    # explicitly requested historical profile keep their recorded contract.
    args.universal=not (args.retain_prepared or args.profile)
    if args.all and args.forms:
        parser.error('Choose form IDs or --all')
    try:
        if args.catalog:
            from ffbe_effects import catalog_batch
            report=catalog_batch.run(args,root=ROOT)
            summary=report.get('summary',{})
            if not args.audit_only and (summary.get('failedForms') or summary.get('failedMoveMemberships')):
                raise ValueError('Catalog finished with unresolved conversions; see catalog-conversion.json. '
                                 'Successful artifacts remain available and --resume retries the gaps.')
        else:
            if args.audit_only or args.resume or args.catalog_index or args.unit_dir or args.limit_forms is not None:
                parser.error('Catalog audit/resume options require --catalog')
            run(args)
    except (ValueError,FileNotFoundError) as error:
        parser.exit(1,str(error)+'\n')


if __name__=='__main__':
    main()
