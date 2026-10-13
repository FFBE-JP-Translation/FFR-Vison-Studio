"""Recover catalog gaps and publish small unit packs with shared effect blobs.

Existing successful source preparations are retained after source-fingerprint
and asset checks. This never installs a game mod or changes the user's roster.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import time
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/ffbe_effects')]
import ffbe_effect_bundle as old
import ffbe_effect_refs as refs
from ffbe_effects.conversion_io import file_lock


def now(): return datetime.now(timezone.utc).isoformat()


def coverage(active, prepared, failures, threshold):
    missing = [e['sourceKey'] for e in active if e['sourceKey'] not in prepared]
    held = [e['sourceKey'] for e in active if e['status'] != 'ready']
    acceptable = len(missing) <= threshold and (not active or bool(prepared))
    return {'coveragePolicyVersion': 2, 'missingMoveCount': len(missing), 'missingMoves': missing, 'heldMoveCount': len(held),
            'heldMoves': held, 'failedMoves': failures, 'missingMoveThreshold': threshold,
            'withinThreshold': acceptable,
            'coverageStatus': 'no_active_moves' if not active else 'ready' if not missing else 'accepted_with_gaps' if acceptable else 'needs_review'}


def process_form(settings, form, phase):
    work, delivery = Path(settings['work']), Path(settings['delivery'])
    logs = work/'logs'; logs.mkdir(parents=True, exist_ok=True)
    with file_lock(work/'locks'/(form+'.lock')), (logs/(form+'.log')).open('a', encoding='utf-8') as log, redirect_stdout(log), redirect_stderr(log):
        progress = work/'progress'/(form+'.json')
        def status(stage, **extra):
            refs.atomic(progress, old.encoded({'form': form, 'phase': phase, 'stage': stage, 'pid': os.getpid(), 'updatedUtc': now(), **extra}))
        started = time.time()
        status('reading prepared source')
        try:
            from ffbe_effects.shared_delivery import Publisher
            from ffbe_effects.playback_policy import configure
            import ffbe_presentation
            base = Path(settings['unit_dir'])/(form+'.ffr')
            native_path = ROOT/'data/ffbe/native_kits'/(form+'.json')
            if not native_path.is_file():
                with zipfile.ZipFile(base) as archive:
                    refs.atomic(native_path, archive.read(f'native_kits/{form}.json'))
            native = json.loads(native_path.read_bytes())
            active = [e for e in native['kit']['entries'] if e['kind'] != 'PASSIVE']
            eligible = {e['sourceKey']: e for e in active if e['status'] == 'ready'}
            staged = work/'manifests'/(form+'.json')
            source = staged if staged.is_file() else Path(settings['old_work'])/'manifests'/(form+'.json')
            document = json.loads(source.read_bytes()) if source.is_file() else {'schema': 'ffr-presentation-2', 'form': form, 'moves': {}}
            document['moves'] = {key: move for key, move in document['moves'].items() if key in eligible and
                move.get('sourceSha256') == ffbe_presentation.source_fingerprint(native['profiles'][key]['snapshot'])}
            refs.atomic(staged, old.encoded(document))
            missing = [key for key in eligible if key not in document['moves']]
            errors = {}
            old_result = settings.get('old_result', {})
            for failure in old_result.get('failedMoves', old_result.get('moveErrors', [])):
                errors[failure['sourceKey']] = failure
            publisher = Publisher(ROOT, delivery, Path(settings['old_work'])/'compressed-pages')
            if phase == 'repair':
                valid = {}
                for key, entry in document['moves'].items():
                    status('checking retained move', move=key)
                    try:
                        for visual in entry.get('visuals', []): publisher.project(visual)
                        banks = set(entry.get('audioBanks', {}).values())
                        if entry.get('audioBank'): banks.add(entry['audioBank'])
                        for bank in banks: publisher.bank(bank)
                        valid[key] = entry
                    except Exception as ex:
                        errors[key] = {'sourceKey': key, 'error': str(ex), 'errorType': type(ex).__name__}
                document['moves'] = valid
                refs.atomic(staged, old.encoded(document))
                missing = [key for key in eligible if key not in valid]
            retry_path = work/'attempts'/(form+'.json')
            attempted = json.loads(retry_path.read_bytes()) if retry_path.is_file() else {}
            # Count held mechanics too: the user's threshold refers to all
            # missing active moves. Held mechanics remain explicit, not retried.
            held_count = sum(e['status'] != 'ready' for e in active)
            allowance = max(0, settings['max_missing'] - held_count)
            if phase == 'repair' and (len(missing) > allowance or missing and not document['moves']):
                import prepare_vision as prepare
                from ffbe_effects.regional_assets import staged as regional_source
                prepare.CACHE = Path(settings['old_work'])/'decoded'
                for key in missing:
                    remaining = sum(k not in document['moves'] for k in eligible)
                    if document['moves'] and remaining <= allowance: break
                    if key in attempted and not settings.get('retry_errors'):
                        errors[key] = attempted[key]
                        continue
                    status('repairing move', move=key, missing=remaining, eligible=len(eligible))
                    prepare.WORK = work/'moves'/form/key.replace('/', '_')
                    prepare.WORK.mkdir(parents=True, exist_ok=True)
                    try:
                        with regional_source(prepare, native['profiles'][key]['snapshot'], prepare.WORK/'regional-source'):
                            prepare.prepare([form], [key], None, detect_scene=True, merge_existing=True, universal=True,
                                            make_previews=False, manifest_out=staged)
                        document = json.loads(staged.read_bytes())
                        errors.pop(key, None)
                    except Exception as ex:
                        errors[key] = {'sourceKey': key, 'error': str(ex), 'errorType': type(ex).__name__}
                        attempted[key] = errors[key]
                        traceback.print_exc()
                        refs.atomic(retry_path, old.encoded(attempted))
                    log.flush()
            shipped = {}
            for key, entry in document['moves'].items():
                if key not in eligible: continue
                status('sharing prepared files', move=key)
                try:
                    # Validate each move separately so one damaged project does
                    # not discard a whole form. Projects are shared and cached.
                    for visual in entry.get('visuals', []): publisher.project(visual)
                    banks = set(entry.get('audioBanks', {}).values())
                    if entry.get('audioBank'): banks.add(entry['audioBank'])
                    for bank in banks: publisher.bank(bank)
                    shipped[key] = configure(entry, form, key)
                    errors.pop(key, None)
                except Exception as ex:
                    errors[key] = {'sourceKey': key, 'error': str(ex), 'errorType': type(ex).__name__}
                    traceback.print_exc()
            status('writing small unit pack')
            report = coverage(active, shipped, [v for k,v in errors.items() if k not in shipped], settings['max_missing'])
            output = delivery/(form+'.ffr')
            result = publisher.pack({**document, 'moves': shipped}, base, output, report)
            result.update(form=form, localArchive=str(output.resolve()), phase=phase, seconds=round(time.time()-started, 2), completedUtc=now())
            refs.atomic(work/'results'/(form+'.json'), old.encoded(result))
            status('complete', prepared=len(shipped), missing=report['missingMoveCount'])
            return result
        except Exception as ex:
            traceback.print_exc()
            result = {'form': form, 'error': str(ex), 'errorType': type(ex).__name__, 'phase': phase}
            refs.atomic(work/'errors'/(form+'.json'), old.encoded(result))
            status('failed', error=str(ex))
            return result


def run(args):
    old_report = json.loads((args.old_work.parent/'delivery/catalog-conversion.json').read_bytes())
    baseline = json.loads(args.baseline.read_bytes())
    forms = list(dict.fromkeys(args.forms or old_report['requestedForms']))
    if not all(f.isdigit() and f in baseline['unitBundles'] for f in forms):
        raise ValueError('Choose catalog form IDs')
    args.work.mkdir(parents=True, exist_ok=True); args.delivery.mkdir(parents=True, exist_ok=True)
    fallback = args.work/'hosted-baseline.json'
    if not fallback.is_file():
        source = ROOT/'build/devui/ffbe_index_cache.json'
        refs.atomic(fallback, source.read_bytes() if source.is_file() else args.baseline.read_bytes())
    old_results = {row['form']: row for row in old_report['results'] + old_report['errors']}
    settings = {key: str(getattr(args,key)) for key in ('work','delivery','old_work','unit_dir')}
    settings.update(max_missing=args.max_missing, retry_errors=args.retry_errors)
    results, errors = {}, {}
    for path in (args.work/'results').glob('*.json'):
        row = json.loads(path.read_bytes())
        if not row.get('coveragePolicyVersion') and not row.get('preparedMoveCount') and row.get('missingMoveCount'):
            continue  # Re-evaluate old zero-animation successes with policy 2.
        output = args.delivery/(row['form']+'.ffr')
        if output.is_file() and output.stat().st_size == row['size']: results[row['form']] = row
    started, done_count = time.time(), 0
    phase = 'starting'
    def publish(active=(), finished=False):
        selected = [results[f] for f in forms if f in results]
        has_gaps = bool(errors or len(selected) != len(forms) or any(not r['withinThreshold'] for r in selected))
        summary = {'status': 'complete_with_gaps' if finished and has_gaps else 'complete' if finished else 'running',
                   'phase': phase, 'pid': os.getpid(), 'startedUtc': started_utc, 'heartbeatUtc': now(),
                   'requestedForms': len(forms), 'bundledForms': len(selected), 'failedForms': len(errors),
                   'withinThreshold': sum(r['withinThreshold'] for r in selected),
                   'aboveThreshold': sum(not r['withinThreshold'] for r in selected), 'maxMissingActiveMoves': args.max_missing,
                   'unitArchiveBytes': sum(r['size'] for r in selected), 'activeForms': list(active),
                   'completedJobsThisRun': done_count, 'elapsedSeconds': round(time.time()-started, 1),
                   'scope': 'active moves only; missing count includes held mechanics; no visual-fidelity percentage asserted'}
        report = {'schema': 'ffr-animation-recovery-1', 'summary': summary, 'requestedForms': forms,
                  'results': selected, 'errors': list(errors.values())}
        refs.atomic(args.work/'recovery.json', old.encoded(report))
        entries = {fid: {**baseline['unitBundles'][fid], **row} for fid,row in results.items()}
        manifest = {'schema': 'ffr-local-converted-units-1', 'delivery': str(args.delivery.resolve()),
                    'baseline': str(fallback.resolve()), 'summary': summary, 'unitBundles': entries}
        refs.atomic(args.work/'converted-units.json', old.encoded(manifest))
        return summary
    started_utc = now()
    phases = ['package','repair'] if args.phase == 'all' else [args.phase]
    with file_lock(args.work/'run.lock', blocking=False):
        for phase in phases:
            jobs = [f for f in forms if f not in results or args.repack and phase == 'package' or phase == 'repair' and
                    not results[f]['withinThreshold'] and results[f]['missingMoveCount'] > results[f]['heldMoveCount'] and
                    (results[f].get('phase') != 'repair' or args.retry_errors)]
            # Recover size-blocked forms early; successful old exports follow.
            failed_before = {e['form'] for e in old_report['errors']}
            jobs.sort(key=lambda f: (0 if f in failed_before else 1, f))
            iterator = iter(jobs)
            with ProcessPoolExecutor(max_workers=args.workers) as pool:
                active = {}
                def submit():
                    form = next(iterator, None)
                    if form is not None:
                        previous = old_results.get(form, {})
                        selected = {**settings, 'old_result': {'failedMoves': previous.get('failedMoves', previous.get('moveErrors', []))}}
                        active[pool.submit(process_form, selected, form, phase)] = form
                for _ in range(args.workers): submit()
                while active:
                    finished, _ = wait(active, timeout=10, return_when=FIRST_COMPLETED)
                    for future in finished:
                        form = active.pop(future)
                        try: row = future.result()
                        except Exception as ex: row = {'form': form, 'error': str(ex)}
                        if 'error' in row: errors[form] = row
                        else: results[form] = row; errors.pop(form, None)
                        done_count += 1
                        print(f"{phase}: {done_count} jobs finished; {form}: " + (row['error'] if 'error' in row else
                            f"{row['preparedMoveCount']} prepared, {row['missingMoveCount']} missing, unit {row['size']/1048576:.2f} MiB"), flush=True)
                        submit()
                    publish(active.values())
            publish()
        summary = publish(finished=True)
        print(json.dumps(summary, indent=2), flush=True)
        return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('forms', nargs='*')
    parser.add_argument('--phase', choices=['package','repair','all'], default='all')
    parser.add_argument('--workers', type=int, choices=range(1,9), default=4)
    parser.add_argument('--max-missing', type=int, default=3)
    parser.add_argument('--retry-errors', action='store_true')
    parser.add_argument('--repack', action='store_true')
    parser.add_argument('--old-work', type=Path, default=ROOT/'build/ffbe-all-animations/work')
    parser.add_argument('--work', type=Path, default=ROOT/'build/animation-recovery')
    parser.add_argument('--delivery', type=Path, default=ROOT/'build/ffbe-shared-delivery')
    parser.add_argument('--baseline', type=Path, default=ROOT/'build/native-editor/host/ffbe/index.json')
    parser.add_argument('--unit-dir', type=Path, default=ROOT/'build/native-editor/host/ffbe/units')
    args = parser.parse_args()
    if args.max_missing < 0: parser.error('--max-missing must be nonnegative')
    run(args)


if __name__ == '__main__': main()
