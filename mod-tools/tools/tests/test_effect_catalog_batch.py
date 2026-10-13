"""Catalog scope, truthful partial results and checksum-verified resumption."""
from argparse import Namespace
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import convert_ffbe_effects as cli
from ffbe_effects import catalog_batch as batch
from tools.tests import test_convert_ffbe_effects as cli_tests


class CatalogBatch(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        self.catalog=self.root/'catalog.json'
        self.catalog.write_text(json.dumps([{'id':'10','forms':['1','2']},{'id':'20','forms':['3']}]))
        self.units=self.root/'units'
        self.units.mkdir()
        folder=self.root/'data/ffbe/native_kits'
        folder.mkdir(parents=True)
        for form in ('1','2','3'):
            (self.units/f'{form}.ffr').write_bytes(('original '+form).encode())
            (folder/f'{form}.json').write_text(json.dumps({'kit':{'entries':[
                {'sourceKey':form+'/a','kind':'ABILITY','status':'ready'},
                {'sourceKey':form+'/b','kind':'ABILITY','status':'held'}]}}))
        self.args=Namespace(forms=[],all=False,move=None,profile=None,unit=None,package_only=False,
            retain_prepared=False,rebuild_source=None,manifest_out=None,reports_from=None,
            limit_forms=None,catalog_index=self.catalog,unit_dir=self.units,resume=False,audit_only=False,
            out=self.root/'out',work=self.root/'work')
        self.calls=[]
        identity=patch.object(batch,'pipeline_identity',return_value={'sha256':'fixture-pipeline'})
        identity.start()
        self.addCleanup(identity.stop)
        import ffbe_effect_bundle
        compression_cache=patch.object(ffbe_effect_bundle,'COMPRESSION_CACHE',None)
        compression_cache.start()
        self.addCleanup(compression_cache.stop)

    def convert(self,args,form):
        self.calls.append(form)
        for suffix in ('ffr','ffr-effects'):
            (args.out/f'{form}.{suffix}').write_bytes(('converted '+form).encode())
        self.assertTrue(args.universal)
        self.assertTrue(args.allow_partial)
        self.assertTrue(args.no_previews)
        self.assertEqual(args.unit,self.units/f'{form}.ffr')
        self.assertTrue(args.manifest_out.is_relative_to(self.args.work))
        return {'form':form,'preparedMoves':[form+'/a'],'completeSourceMoves':[form+'/a'],
                'failedMoves':[],'unit':str(args.out/f'{form}.ffr')}

    def run_batch(self,converter=None):
        with patch.object(cli,'convert_form',side_effect=converter or self.convert),redirect_stdout(io.StringIO()):
            return batch.run(self.args,root=self.root)

    def test_all_catalog_forms_are_bundled_and_originals_unchanged(self):
        before={p.name:p.read_bytes() for p in self.units.iterdir()}
        report=self.run_batch()
        self.assertEqual(self.calls,['1','2','3'])
        self.assertEqual(report['summary']['visionsWithEveryFormBundled'],2)
        self.assertEqual(report['summary']['activeMoveMemberships'],6)
        self.assertEqual(report['summary']['completeSourceMoveMemberships'],3)
        self.assertIsNone(report['summary']['visualFidelity']['measuredPercent'])
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.units.iterdir()})

    def test_pilot_does_not_claim_a_multiform_vision_complete(self):
        self.args.limit_forms=1
        summary=self.run_batch()['summary']
        self.assertEqual(summary['status'],'pilot_complete')
        self.assertEqual(summary['catalogForms'],3)
        self.assertEqual(summary['visionsWithAnyBundle'],1)
        self.assertEqual(summary['visionsWithEveryFormBundled'],0)

    def test_missing_form_does_not_stop_other_forms_or_hide_failure(self):
        (self.units/'2.ffr').unlink()
        report=self.run_batch()
        self.assertEqual(self.calls,['1','3'])
        self.assertEqual(report['summary']['status'],'complete_with_gaps')
        self.assertEqual([e['form'] for e in report['errors']],['2'])
        self.assertEqual(report['summary']['visionsWithEveryFormBundled'],1)

    def test_resume_checks_output_bytes_and_source_archive_identity(self):
        self.run_batch()
        self.args.resume=True
        self.calls.clear()
        report=self.run_batch()
        self.assertEqual(self.calls,[])
        self.assertTrue(all(r['resumed'] for r in report['results']))
        (self.args.out/'2.ffr').write_bytes(b'changed')
        (self.units/'3.ffr').write_bytes(b'new source')
        self.run_batch()
        self.assertEqual(self.calls,['2','3'])

    def test_partial_form_retries_instead_of_freezing_its_gaps(self):
        def partial(args,form):
            result=self.convert(args,form)
            if form=='2':result['failedMoves']=[{'sourceKey':'2/b','error':'missing source'}]
            return result
        self.run_batch(partial)
        self.args.resume=True
        self.calls.clear()
        self.run_batch(partial)
        self.assertEqual(self.calls,['2'])

    def test_original_unit_directory_cannot_be_used_as_output(self):
        self.args.out=self.units
        with self.assertRaisesRegex(ValueError,'separate from original'):
            self.run_batch()
        self.assertEqual(self.calls,[])

    def test_locked_progress_report_does_not_abort_conversion(self):
        original=batch.write_json
        def write(path,document,**kwargs):
            if Path(path).name=='catalog-conversion.json' and document['summary']['status']=='running':
                raise PermissionError('status viewer lock')
            return original(path,document,**kwargs)
        with patch.object(batch,'write_json',side_effect=write):
            report=self.run_batch()
        self.assertEqual(self.calls,['1','2','3'])
        self.assertEqual(report['summary']['processedForms'],3)
        self.assertEqual(json.loads((self.args.out/'catalog-conversion.json').read_bytes())['summary'],report['summary'])

    def test_continue_pass_keeps_successes_and_failures_after_interruption(self):
        def interrupted(args,form):
            if form=='2':raise ValueError('known gap')
            if form=='3':raise KeyboardInterrupt()
            return self.convert(args,form)
        with self.assertRaises(KeyboardInterrupt):self.run_batch(interrupted)
        self.args.resume=True;self.args.continue_pass=True
        self.calls.clear()
        report=self.run_batch()
        self.assertEqual(self.calls,['3'])
        self.assertEqual(report['runtime']['carriedForwardForms'],2)
        self.assertEqual(report['runtime']['convertedThisRun'],1)
        self.assertEqual([e['form'] for e in report['errors']],['2'])
        self.assertEqual(report['summary']['processedForms'],3)

    def test_continue_pass_rejects_unreviewed_pipeline_change(self):
        self.run_batch()
        self.args.resume=True;self.args.continue_pass=True
        with patch.object(batch,'pipeline_identity',return_value={'sha256':'changed'}):
            with self.assertRaisesRegex(ValueError,'unreviewed compiler'):
                self.run_batch()

    def test_reviewed_io_compatibility_still_checks_output_and_source(self):
        first=self.run_batch()
        old=first['pipeline']['sha256']
        new=batch.encoded_hash({'compiler':'io-repair','playbackPolicy':'legacy'})
        (self.args.work/'pipeline-compatibility.json').write_text(json.dumps({
            'schema':'ffr-reviewed-io-recovery-1','oldPipeline':old,'newPipeline':new,
            'sourceInventoryUnchanged':True}))
        self.args.resume=True;self.calls.clear()
        with patch.object(batch,'pipeline_identity',return_value={'sha256':'io-repair'}):
            self.run_batch()
            self.assertEqual(self.calls,[])
            (self.args.out/'2.ffr').write_bytes(b'corrupt')
            (self.units/'3.ffr').write_bytes(b'changed source')
            self.run_batch()
        self.assertEqual(self.calls,['2','3'])

    def test_passive_only_and_held_only_forms_keep_exact_base_units(self):
        kits=self.root/'data/ffbe/native_kits'
        (kits/'1.json').write_text(json.dumps({'kit':{'entries':[
            {'sourceKey':'1/p','kind':'PASSIVE','status':'ready'}]}}))
        (kits/'2.json').write_text(json.dumps({'kit':{'entries':[
            {'sourceKey':'2/b','kind':'ABILITY','status':'held'}]}}))
        self.args.out.mkdir()
        (self.args.out/'1.ffr-effects').write_bytes(b'previous prepared output')
        report=self.run_batch()
        self.assertEqual(self.calls,['3'])
        self.assertEqual(report['summary']['baseOnlyForms'],2)
        self.assertEqual(report['summary']['visionsWithEveryFormBundled'],2)
        for form in ('1','2'):
            self.assertEqual((self.args.out/f'{form}.ffr').read_bytes(),(self.units/f'{form}.ffr').read_bytes())
            self.assertFalse((self.args.out/f'{form}.ffr-effects').exists())
            result=next(r for r in report['results'] if r['form']==form)
            self.assertEqual(result['preparedMoves'],[])
            self.assertIsNone(result['effects'])
        self.assertEqual(report['results'][1]['heldMoves'],['2/b'])
        self.assertEqual(Path(report['results'][0]['retiredOutputs'][0]).read_bytes(),b'previous prepared output')
        self.args.resume=True
        self.calls.clear()
        resumed=self.run_batch()
        self.assertEqual(self.calls,[])
        self.assertTrue(all(r['resumed'] for r in resumed['results']))

    def test_missing_native_kit_is_one_failure_not_a_batch_abort(self):
        (self.root/'data/ffbe/native_kits/2.json').unlink()
        report=self.run_batch()
        self.assertEqual(self.calls,['1','3'])
        self.assertEqual([e['form'] for e in report['errors']],['2'])
        self.assertEqual(report['summary']['unavailableCountForms'],['2'])

    def test_failed_pilot_reports_gaps(self):
        self.args.limit_forms=2
        (self.units/'2.ffr').unlink()
        summary=self.run_batch()['summary']
        self.assertEqual(summary['status'],'pilot_complete_with_gaps')
        self.assertEqual(summary['failedForms'],1)

    def test_empty_or_wrong_form_output_receipts_cannot_skip_a_conversion(self):
        self.run_batch()
        first=self.args.work/'form-receipts/1.json'
        receipt=json.loads(first.read_bytes())
        receipt['outputs']={}
        first.write_text(json.dumps(receipt))
        second=self.args.work/'form-receipts/2.json'
        receipt=json.loads(second.read_bytes())
        receipt['result']['form']='1'
        second.write_text(json.dumps(receipt))
        self.args.resume=True
        self.calls.clear()
        self.run_batch()
        self.assertEqual(self.calls,['1','2'])

    def test_receipt_storage_failure_keeps_verified_output_and_records_warning(self):
        original=batch.write_json
        def write(path,*args,**kwargs):
            if Path(path).parent.name=='form-receipts':
                raise PermissionError('cache location unavailable')
            return original(path,*args,**kwargs)
        with patch.object(batch,'write_json',side_effect=write):
            report=self.run_batch()
        self.assertEqual(report['errors'],[])
        self.assertEqual(report['summary']['bundledForms'],3)
        self.assertEqual(report['summary']['cacheWarnings'],3)
        self.assertEqual(json.loads((self.args.out/'catalog-conversion.json').read_bytes())['summary'],report['summary'])
        self.args.resume=True
        self.calls.clear()
        self.run_batch()
        self.assertEqual(self.calls,['1','2','3'])

    def test_all_failed_moves_remain_explicit_and_other_forms_continue(self):
        def convert(args,form):
            if form=='2':
                raise cli.MovePreparationError('2',[{'sourceKey':'2/a','error':'bad source'}],[])
            return self.convert(args,form)
        report=self.run_batch(convert)
        self.assertEqual(self.calls,['1','3'])
        self.assertEqual(report['summary']['failedMoveMemberships'],1)
        self.assertEqual(report['errors'][0]['moveErrors'][0]['sourceKey'],'2/a')

    def test_cli_returns_failure_after_partial_catalog_results_have_been_written(self):
        for summary in ({'failedForms':1},{'failedMoveMemberships':1}):
            with self.subTest(summary=summary),patch.object(batch,'run',return_value={'summary':summary}),\
                    patch('sys.stderr',new_callable=io.StringIO),self.assertRaises(SystemExit) as failed:
                cli.main(['--catalog'])
            self.assertEqual(failed.exception.code,1)


class PartialCatalogForm(unittest.TestCase):
    setUp=cli_tests.OfflineConversionCLI.setUp
    fixture=cli_tests.OfflineConversionCLI.fixture
    run_quiet=cli_tests.OfflineConversionCLI.run_quiet
    def test_partial_catalog_form_excludes_failed_stale_move(self):
        keys=self.fixture()
        self.args.package_only=False
        self.args.allow_partial=True
        from types import SimpleNamespace
        def prepare(forms,selected,profile,**options):
            if selected==[keys[0]]:raise ValueError('Unsupported source')
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        with patch.dict(sys.modules,{'prepare_vision':SimpleNamespace(prepare=prepare)}):
            result=self.run_quiet()[0]
        self.assertEqual(result['preparedMoves'],[keys[1]])
        self.assertEqual(result['failedMoves'][0]['sourceKey'],keys[0])
        import ffbe_effect_bundle
        files=ffbe_effect_bundle.read_archive(self.args.out/'1.ffr-effects')
        self.assertEqual(list(json.loads(files['presentation/1.json'])['moves']),[keys[1]])

    def test_move_receipt_write_failure_does_not_turn_a_prepared_move_into_a_gap(self):
        keys=self.fixture()
        self.args.package_only=False
        self.args.allow_partial=True
        self.args.catalog_context={'pipeline':'fixture','root':str(self.root)}
        self.args.manifest_out=self.root/'data/ffbe/presentation/1.json'
        document=json.loads(self.args.manifest_out.read_bytes())
        from types import SimpleNamespace
        def prepare(forms,selected,profile,**options):
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{},'forms':{'1':document}}
        with patch.dict(sys.modules,{'prepare_vision':SimpleNamespace(prepare=prepare)}),\
                patch.object(batch,'write_json',side_effect=PermissionError('cache unavailable')):
            result=self.run_quiet()[0]
        self.assertEqual(result['preparedMoves'],keys)
        self.assertEqual(result['failedMoves'],[])
        self.assertEqual(len(result['cacheWarnings']),2)
        self.assertTrue((self.args.out/'1.ffr-effects').exists())

    def test_universal_conversion_preserves_only_matching_host_target_preference(self):
        keys=self.fixture()
        self.args.package_only=False
        self.args.universal=True
        profile_path=self.root/'data/ffbe/presentation/profiles/1.json'
        profile_path.parent.mkdir()
        profile_path.write_text(json.dumps({'form':'1','sourceKey':keys[0],'hostTargetType':'Single',
            'camera':{'pan':'obsolete'},'screenPlacement':{'sourceOffset':[123,456]}}))
        from types import SimpleNamespace
        calls=[]
        def prepare(forms,selected,profile,**options):
            calls.append((selected,profile,options))
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        with patch.dict(sys.modules,{'prepare_vision':SimpleNamespace(prepare=prepare)}):
            self.run_quiet()
        self.assertIsNone(calls[0][1])
        self.assertEqual(calls[0][2]['host_preferences'],{'hostTargetType':'Single'})
        self.assertEqual(calls[0][2],{'detect_scene':True,'merge_existing':True,'universal':True,
                                    'host_preferences':{'hostTargetType':'Single'}})
        self.assertNotIn('host_preferences',calls[1][2])


class MoveReceipts(unittest.TestCase):
    setUp=cli_tests.OfflineConversionCLI.setUp
    fixture=cli_tests.OfflineConversionCLI.fixture

    def test_resumption_checks_audio_samples_and_exact_dependency_closure(self):
        keys=self.fixture()
        self.args.resume=True
        self.args.catalog_context={'pipeline':'fixture','root':str(self.root)}
        self.args.manifest_out=self.root/'data/ffbe/presentation/1.json'
        document=json.loads(self.args.manifest_out.read_bytes())
        samples=self.root/'data/ffbe/audio/samples'
        samples.mkdir(parents=True)
        sha=batch.hashlib.sha256(b'audio sample').hexdigest()
        sample=samples/(sha+'.hca')
        sample.write_bytes(b'audio sample')
        bank=samples.parent/'bank.json'
        bank.write_text(json.dumps({'waves':{'1':{'sha256':sha}}}))
        document['moves'][keys[0]]['audioBank']=bank.relative_to(self.root).as_posix()
        self.args.manifest_out.write_text(json.dumps(document))
        native=json.loads((self.root/'data/ffbe/native_kits/1.json').read_bytes())
        snapshot=native['profiles'][keys[0]]['snapshot']
        audit={'decoderFidelity':{},'assets':{},'soundOmissions':{},'forms':{'1':document}}
        batch.record_move(self.args,'1',keys[0],snapshot,audit)
        self.assertIsNotNone(batch.cached_move(self.args,'1',keys[0],snapshot))
        self.args.catalog_context.update(pipeline='io-repair',compatiblePipelines=['fixture'])
        self.assertIsNotNone(batch.cached_move(self.args,'1',keys[0],snapshot))
        receipt=batch._receipt_path(self.args,'1',keys[0])
        doc=json.loads(receipt.read_bytes())
        doc['dependencies']={}
        receipt.write_text(json.dumps(doc))
        self.assertIsNone(batch.cached_move(self.args,'1',keys[0],snapshot))
        batch.record_move(self.args,'1',keys[0],snapshot,audit)
        sample.write_bytes(b'corrupted audio')
        self.assertIsNone(batch.cached_move(self.args,'1',keys[0],snapshot))


class PipelineIdentity(unittest.TestCase):
    def test_geometry_and_runtime_changes_invalidate_resume_without_reading_pixels(self):
        from ffbe_effects import catalog
        with tempfile.TemporaryDirectory() as folder,patch.object(catalog,'RAW_SOURCES',{}),\
                patch.object(catalog.ffbe_live,'FIELDS',str(Path(folder)/'missing-fields')):
            root=Path(folder)
            sprite=root/'data/ffbe/sprites/1'
            sprite.mkdir(parents=True)
            cgs=sprite/'unit_idle_cgs_1.csv'
            cgs.write_bytes(b'geometry')
            png=sprite/'unit_1.png'
            png.write_bytes(b'pixels')
            runtime=root/'tools/ffbe_resonance.py'
            runtime.parent.mkdir()
            runtime.write_text('runtime v1')
            before=batch.pipeline_identity(root)['sha256']
            png.write_bytes(b'irrelevant pixel inventory change')
            self.assertEqual(before,batch.pipeline_identity(root)['sha256'])
            stat=cgs.stat()
            os.utime(cgs,ns=(stat.st_atime_ns,stat.st_mtime_ns+1000000000))
            geometry_changed=batch.pipeline_identity(root)['sha256']
            self.assertNotEqual(before,geometry_changed)
            runtime.write_text('runtime v2')
            self.assertNotEqual(geometry_changed,batch.pipeline_identity(root)['sha256'])
            profile=root/'data/ffbe/presentation/profiles/1.json'
            profile.parent.mkdir(parents=True)
            profile.write_text('{"hostTargetType":"Single"}')
            preference=batch.pipeline_identity(root)['sha256']
            profile.write_text('{broken profile')
            self.assertNotEqual(preference,batch.pipeline_identity(root)['sha256'])


if __name__=='__main__':unittest.main()
