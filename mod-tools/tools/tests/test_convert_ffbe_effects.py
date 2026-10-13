"""Offline CLI selection and resumable batch behavior without particle baking."""
from argparse import Namespace
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import convert_ffbe_effects as cli
import ffbe_effect_bundle as bundle
import ffbe_presentation


class OfflineConversionCLI(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patch=patch.object(cli,'ROOT',self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.args=Namespace(forms=['1'],all=False,move=None,profile=None,unit=None,
                            out=self.root/'out',work=self.root/'work',package_only=True)

    def fixture(self, form='1', stale=None):
        keys=[f'JP/ability/{form}01',f'JP/ability/{form}02']
        snapshots={key:{'root':key,'records':[{'source':'JP','kind':'ability','id':key.rsplit('/',1)[1],
                                             'data':{'name':'Ability '+key}}]} for key in keys}
        native={'kit':{'entries':[{'sourceKey':key,'kind':'ABILITY','status':'ready'} for key in keys]},
                'profiles':{key:{'snapshot':snapshot} for key,snapshot in snapshots.items()}}
        doc={'schema':'ffr-presentation-2','form':form,'moves':{
            key:{'sourceKey':key,'sourceSha256':('0'*64 if key==stale else ffbe_presentation.source_fingerprint(snapshot)),
                 'visuals':[],'sounds':[],'status':'ready'} for key,snapshot in snapshots.items()}}
        for folder,value in [('native_kits',native),('presentation',doc)]:
            path=self.root/'data/ffbe'/folder/(form+'.json')
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(value),encoding='utf-8')
        return keys

    def run_quiet(self):
        with redirect_stdout(io.StringIO()):
            return cli.run(self.args)

    def test_selected_move_excludes_stale_unselected_preparation(self):
        keys=self.fixture(stale='JP/ability/102')
        self.args.move=[keys[0]]
        result=self.run_quiet()
        self.assertEqual(result[0]['moves'],1)
        packed=bundle.read_archive(self.args.out/'1.ffr-effects')
        self.assertEqual(list(json.loads(packed['presentation/1.json'])['moves']),[keys[0]])
        original=json.loads((self.root/'data/ffbe/presentation/1.json').read_text())
        self.assertEqual(list(original['moves']),keys)

    def test_every_shipped_move_is_checked_before_publication(self):
        self.fixture(stale='JP/ability/102')
        with self.assertRaises(cli.ConversionBatchError) as failed:
            self.run_quiet()
        self.assertIn('stale prepared move JP/ability/102',failed.exception.errors[0]['error'])
        self.assertFalse((self.args.out/'1.ffr-effects').exists())

    def test_catalog_batch_continues_and_reports_failed_and_completed_forms(self):
        self.fixture('1',stale='JP/ability/102')
        self.fixture('2')
        self.args.forms=[]
        self.args.all=True
        with self.assertRaises(cli.ConversionBatchError) as failed:
            self.run_quiet()
        self.assertEqual([r['form'] for r in failed.exception.results],['2'])
        self.assertEqual([r['form'] for r in failed.exception.errors],['1'])
        summary=json.loads((self.args.out/'conversion.json').read_text())
        self.assertEqual(summary['status'],'failed')
        self.assertEqual(summary['requestedForms'],['1','2'])
        bundle.verify(self.args.out/'2.ffr-effects',expected_form='2')

    def test_shared_source_cache_survives_separate_move_report_folders(self):
        self.fixture('1')
        self.fixture('2')
        self.args.forms=['1','2']
        self.args.package_only=False
        calls=[]
        fake=SimpleNamespace()
        def prepare(forms,keys,profile,**options):
            calls.append((fake.CACHE,fake.WORK,forms,keys,options))
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        fake.prepare=prepare
        with patch.dict(sys.modules,{'prepare_vision':fake}):
            self.run_quiet()
        self.assertEqual(len(calls),4)
        self.assertEqual({c[0] for c in calls},{self.args.work/'decoded'})
        self.assertEqual(len({c[1] for c in calls}),4)
        self.assertTrue(all(c[4]=={'detect_scene':True,'merge_existing':True} for c in calls))

    def test_cli_exits_nonzero_after_a_recorded_failure(self):
        self.fixture(stale='JP/ability/102')
        with redirect_stdout(io.StringIO()),patch('sys.stderr',new_callable=io.StringIO),self.assertRaises(SystemExit) as failed:
            cli.main(['1','--package-only','--out',str(self.args.out),'--work',str(self.args.work)])
        self.assertEqual(failed.exception.code,1)
        self.assertTrue((self.args.out/'conversion.json').is_file())

    def test_failed_source_move_does_not_skip_later_moves_or_publish_old_preparation(self):
        keys=self.fixture()
        self.args.package_only=False
        calls=[]
        fake=SimpleNamespace()
        def prepare(forms,selected,profile,**options):
            calls.extend(selected)
            if selected==[keys[0]]:
                raise ValueError('Unresolved source emitter')
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        fake.prepare=prepare
        with patch.dict(sys.modules,{'prepare_vision':fake}),self.assertRaises(cli.ConversionBatchError):
            self.run_quiet()
        self.assertEqual(calls,keys)
        self.assertFalse((self.args.out/'1.ffr-effects').exists())
        result=json.loads((self.args.out/'conversion.json').read_text())
        self.assertEqual(result['status'],'failed')
        failure=result['errors'][0]
        self.assertEqual(failure['preparedMoves'],[keys[1]])
        self.assertEqual(failure['moveErrors'],[{
            'sourceKey':keys[0],'error':'Unresolved source emitter','errorType':'ValueError'}])

    def test_retained_conversion_packages_staged_manifest_without_replacing_project_data(self):
        keys=self.fixture()
        self.args.move=[keys[0]]
        self.args.package_only=False
        self.args.retain_prepared=True
        self.args.manifest_out=self.root/'staged/1.json'
        original_path=self.root/'data/ffbe/presentation/1.json'
        original=original_path.read_bytes()
        calls=[]
        fake=SimpleNamespace()
        def prepare(forms,selected,profile,**options):
            calls.append(options)
            doc=json.loads(original)
            doc['moves'][selected[0]]['backgroundDetection']={'kind':'screen_overlay'}
            options['manifest_out'].parent.mkdir(parents=True)
            options['manifest_out'].write_text(json.dumps(doc))
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        fake.prepare=prepare
        with patch.dict(sys.modules,{'prepare_vision':fake}):result=self.run_quiet()
        self.assertTrue(calls[0]['retain_prepared'])
        self.assertEqual(calls[0]['manifest_out'],self.args.manifest_out)
        self.assertEqual(original_path.read_bytes(),original)
        self.assertEqual(result[0]['sceneKinds'][keys[0]],'screen_overlay')
        packed=bundle.read_archive(self.args.out/'1.ffr-effects')
        self.assertEqual(json.loads(packed['presentation/1.json'])['moves'][keys[0]]['backgroundDetection']['kind'],'screen_overlay')

    def test_retained_mode_cannot_be_silently_skipped_by_package_only(self):
        self.args.retain_prepared=True
        with self.assertRaisesRegex(ValueError,'omit --package-only'):self.run_quiet()

    def report_fixtures(self):
        keys=self.fixture()
        doc=json.loads((self.root/'data/ffbe/presentation/1.json').read_text())
        self.args.reports_from=self.root/'prepared-reports'
        for key in keys:
            path=self.args.reports_from/'1'/key.replace('/','_')/'report.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'forms':{'1':{'moves':{key:doc['moves'][key]}}},
                                        'decoderFidelity':{'version':15},'assets':{},'soundOmissions':{}}))
        return keys

    def test_package_only_retains_exact_preparation_audits_with_provenance(self):
        keys=self.report_fixtures()
        result=self.run_quiet()[0]
        self.assertEqual(result['operation'],'package-prepared')
        self.assertEqual(len(result['preparationReports']),2)
        archive=bundle.read_archive(self.args.out/'1.ffr-effects')
        for key in keys:
            name=key.replace('/','_')+'.json'
            report=json.loads(archive['presentation/reports/1/'+name])
            self.assertEqual(report['decoderFidelity'],{'version':15})
            self.assertEqual(len(report['preparationReport']['sha256']),64)
            self.assertEqual(report['preparationReport'],result['preparationReports'][name])

    def test_stale_or_missing_audit_prevents_publication(self):
        keys=self.report_fixtures()
        path=self.args.reports_from/'1'/keys[0].replace('/','_')/'report.json'
        report=json.loads(path.read_text())
        report['forms']['1']['moves'][keys[0]]['issues']=['Different prepared content']
        path.write_text(json.dumps(report))
        with self.assertRaises(cli.ConversionBatchError) as failed:self.run_quiet()
        self.assertIn('preparation report does not match',failed.exception.errors[0]['error'])
        self.assertFalse((self.args.out/'1.ffr-effects').exists())
        path.unlink()
        with self.assertRaises(cli.ConversionBatchError) as missing:self.run_quiet()
        self.assertEqual(missing.exception.errors[0]['errorType'],'FileNotFoundError')
        self.assertFalse((self.args.out/'1.ffr-effects').exists())

    def test_report_reuse_requires_package_only(self):
        self.args.package_only=False
        self.args.reports_from=self.root/'reports'
        with self.assertRaisesRegex(ValueError,'requires --package-only'):self.run_quiet()

    def test_rebuild_selector_preflight_and_staged_fallback(self):
        keys=self.fixture()
        self.args.package_only=False
        self.args.retain_prepared=True
        self.args.rebuild_source=['star.bmb']
        self.args.manifest_out=self.root/'new-staged/1.json'
        with self.assertRaisesRegex(ValueError,'do not occur'):self.run_quiet()
        self.assertFalse(self.args.out.exists())
        path=self.root/'data/ffbe/presentation/1.json'
        doc=json.loads(path.read_text())
        doc['moves'][keys[0]]['spawns']=[{'file':'STAR.bmb'}]
        path.write_text(json.dumps(doc))
        cli.validate_rebuild_selection(self.args,['1'])
        self.args.move=[keys[1]]
        with self.assertRaisesRegex(ValueError,'do not occur'):cli.validate_rebuild_selection(self.args,['1'])

    def test_rebuild_sources_reach_each_preparation_without_changing_original_manifest(self):
        keys=self.fixture()
        self.args.package_only=False
        self.args.retain_prepared=True
        self.args.rebuild_source=['star.bmb']
        path=self.root/'data/ffbe/presentation/1.json'
        doc=json.loads(path.read_text())
        doc['moves'][keys[0]]['spawns']=[{'file':'star.bmb'}]
        path.write_text(json.dumps(doc))
        original=path.read_bytes()
        calls=[]
        fake=SimpleNamespace()
        def prepare(forms,selected,profile,**options):
            calls.append(options)
            return {'decoderFidelity':{},'assets':{},'soundOmissions':{}}
        fake.prepare=prepare
        with patch.dict(sys.modules,{'prepare_vision':fake}):result=self.run_quiet()
        self.assertEqual(len(calls),2)
        self.assertTrue(all(call['rebuild_sources']==['star.bmb'] for call in calls))
        self.assertEqual(result[0]['rebuildSourceFiles'],['star.bmb'])
        self.assertEqual(path.read_bytes(),original)

    def test_rebuild_sources_require_retention_and_basenames(self):
        self.args.rebuild_source=['star.bmb']
        with self.assertRaisesRegex(ValueError,'requires --retain-prepared'):self.run_quiet()
        self.args.retain_prepared=True
        self.args.package_only=False
        self.args.rebuild_source=['../star.bmb']
        with self.assertRaisesRegex(ValueError,'basenames'):self.run_quiet()


if __name__=='__main__':
    unittest.main()
