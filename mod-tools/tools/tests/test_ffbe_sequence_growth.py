"""Large source presentations grow the native director beyond donor capacity."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools'))
import make_vision_mod as generator
import ffbe_resonance as resonance
import ffbe_presentation as presentation


class SequenceGrowth(unittest.TestCase):
    def test_full_rain_fina_camera_and_isolation_plan_cooks_with_bound_extra_functions(self):
        source = Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        bundle = ROOT/'data/ffbe/presentation/100032707.json'
        if not source.is_file() or not bundle.is_file(): self.skipTest('Prepared Rain/Fina and native donor required')
        entry = json.loads(bundle.read_text(encoding='utf-8'))['moves']['GL_2024/lb/100032707/level/40']
        entry['_hostVisionUnitId'] = 13503
        entry['_hostResonance'] = True
        raw = json.loads((ROOT/'units/ffbe/rainfina/raw/limitbursts.json').read_text())['100032707']
        sounds = [{'frame': s['frame'], 'bank': 'test_bank', 'cueName': f'cue_{i}', 'durationMs': 100}
                  for i, s in enumerate(entry['sounds'])]
        plan = resonance.schedule(313/60, 30, 444040,
                                  {'moveType': 1, 'hitFrames': raw['attack_frames'][2], 'opening': entry['opening']}, sounds)
        plan = presentation.apply(plan, entry, sounds, 444040, add_sounds=False)
        # Deliberately exceed even future expanded native donor pools.
        for i in range(80):
            plan['events'].append({'time': i+1, 'set': {'EventType': 'SoundPlayHitSound',
                'Sound_PlayHitSound_CueSheetName': 'growth_fixture', 'Sound_PlayHitSound_playLabel': f'cue{i}'}})
        plan['events'].sort(key=lambda e:e['time'])
        with tempfile.TemporaryDirectory(prefix='sequence-growth-', dir=ROOT/'build') as temp:
            work = Path(temp); asset = work/'shell.uasset'
            for suffix in ('.uasset','.uexp','.ubulk'):
                if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix),asset.with_suffix(suffix))
            def command(*args):
                result = subprocess.run([*generator.FFRDT,*map(str,args),'--usmap',generator.USMAP],capture_output=True,text=True,encoding='utf-8')
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            path = work/'asset.json'; command('tojson',asset,path)
            doc = json.loads(path.read_text(encoding='utf-8-sig')); original = len(doc['Exports'])
            operations = resonance.author(doc, plan)
            self.assertGreater(len(doc['Exports']),original)
            path.write_text(json.dumps(doc,ensure_ascii=False),encoding='utf-8')
            config = {'legacyRoot':str(work),'outRoot':str(work),'tables':[],
                'sequenceData':[{'asset':'shell','json':str(path)}],
                'bytecode':[{'asset':'shell',**op} for op in operations]}
            patch = work/'patch.json'; patch.write_text(json.dumps(config),encoding='utf-8'); command('patch',patch)
            out = work/'cooked.json'; command('tojson',asset,out)
            cooked = json.loads(out.read_text(encoding='utf-8-sig'))
            for export in cooked['Exports']:
                for channel in export.get('Data', []):
                    if channel['Name'] != 'EventChannel': continue
                    for event in resonance.child(channel['Value'], 'KeyValues'):
                        ptrs = resonance.child(event['Value'], 'Ptrs')
                        function_id = resonance.child(ptrs, 'Function')
                        bound = resonance.child(ptrs, 'BoundObjectProperty')
                        self.assertEqual(bound['ResolvedOwner'], function_id,
                                         'Native event argument must belong to the called function')
            fn_ids = {int(op['export']) for op in operations}
            for index in sorted(fn_ids):
                fn = cooked['Exports'][index-1]; owner = cooked['Exports'][fn['OuterIndex']-1]
                self.assertIn([fn['ObjectName'],index],owner['FuncMap'])
                self.assertIn(index,owner['Children'])
                def owners(value):
                    if isinstance(value,dict):
                        if value.get('Path') == [fn['LoadedProperties'][0]['Name']]: yield value['ResolvedOwner']
                        for item in value.values(): yield from owners(item)
                    elif isinstance(value,list):
                        for item in value:yield from owners(item)
                kind = next(op['set']['EventType'] for op in operations if int(op['export']) == index)
                self.assertEqual(set(owners(fn['ScriptBytecode'])), set() if kind == 'NativeAuraVisibility' else {index})
            dump = work/'events.json';command('seqdump',asset,dump)
            events = {int(k.split(':')[0]):v for k,v in json.loads(dump.read_text(encoding='utf-8-sig')).items()}
            for op in operations:
                event = events[int(op['export'])]
                self.assertEqual(event['EventType'], op['set']['EventType'])
                for key in ('Sound_PlayHitSound_CueSheetName', 'Sound_PlayHitSound_playLabel',
                            'NativeStageCamera_UnitId', 'NativeStageCamera_Frame',
                            'NativeStageVisibility_UnitId', 'NativeStageVisibility_Restore'):
                    if key in op['set']: self.assertEqual(event.get(key),op['set'][key])


if __name__=='__main__':unittest.main()
