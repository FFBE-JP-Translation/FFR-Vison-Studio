"""Non-damaging LBs retain per-component targets and apply native effects once."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ffbe_lb as lb
import ffbe_lb_support as support
import ffbe_resonance as resonance
import make_vision_mod as generator
import test_ffbe_resonance as cooked_tests
from test_ffbe_resonance import number


def agnes():
    row = {'lb_id': '313000206', 'name': 'Divine Light', 'move_type': '1',
           'effect_type': '33@3@111', 'target': '1@2@2', 'target_range': '2@2@2',
           'effect_param': '0,0,0,0,0,0,-50,0,1,3@0,100,0,100,3,1@0,0,0,0,1,0',
           'attack_frames': '280:100:3:2', 'element_inflict': '0,0,0,0,0,0,0,0'}
    with patch.object(lb, 'table', return_value={'rows': [], 'file': 'fixture'}):
        return lb.from_master('313000206', {}, row, ['313000206'])


class SupportTests(unittest.TestCase):
    def test_agnes_has_four_native_effects_and_no_damage_or_healing(self):
        result = lb.profile(agnes())
        self.assertTrue(result['supported'], result['issues'])
        self.assertEqual(result['mode'], 'support')
        self.assertEqual(len(result['effects']), 4)
        settings = result['set']
        self.assertEqual((settings['magnification'], settings['breakDamageValue'], settings['criticalHitRate']), (0, 0, 0))
        for key in ('DamageType', 'damageCalcType', 'skillEffectType', 'parameterType'):
            self.assertEqual(settings[key], 'None')
        self.assertEqual(settings['effectBundleList'], [])  # no inherited Cloud damage buffs
        self.assertEqual(result['fieldColor'], '#808080')
        self.assertIn('Light weakness', result['description'])
        self.assertTrue(any('not reproduced exactly' in w for w in result['warnings']))
        imperil, defence, spirit, cure = result['effects']
        self.assertEqual((imperil['TargetType'], imperil['targetRelation'], imperil['set']['ParamList'][:2]), ('Group', 'Enemies', [7, 1]))
        self.assertEqual((defence['targetRelation'], defence['set']['ParamList'][:3]), ('Friendlies', [100, 6, 2]))
        self.assertEqual((spirit['targetRelation'], spirit['set']['ParamList'][:3]), ('Friendlies', [100, 8, 2]))
        self.assertEqual(cure['set']['ParamList'][3], 9)
        self.assertEqual(cure['targetRelation'], 'Friendlies')
        self.assertEqual([e['set']['effectEndActionNum'] for e in result['effects'][:3]], [3, 3, 3])

    def test_support_reaction_uses_source_frame_once_after_lb_start(self):
        source = agnes()
        plan = resonance.schedule(6, 1, 444010, source)
        reactions = [e for e in plan['events'] if e['set']['EventType'] == 'OtherReaction']
        self.assertEqual([e['time'] for e in reactions], [12000 + 280 * 400])
        self.assertEqual(reactions[0]['set']['Other_Reaction_Id'], 444010)

    def test_custom_hit_count_still_uses_its_own_fallback_timeline(self):
        plan = resonance.schedule(6, 10, 444010, agnes())
        self.assertEqual(sum(e['set']['EventType'] == 'OtherReaction' for e in plan['events']), 10)

    def test_unmapped_or_mistimed_support_does_not_silently_drop_components(self):
        for update in ({'supportFrames': [10, 20, 30]}, {'supportFrames': None}):
            self.assertFalse(lb.profile({**agnes(), **update})['supported'])
        source = agnes(); source['components'][2]['params'][0] = 1
        self.assertFalse(lb.profile(source)['supported'])
        source = agnes(); source['components'][0]['range'] = 1
        self.assertFalse(lb.profile(source)['supported'])
        source = agnes(); source['components'][0]['params'][6] = 50
        self.assertFalse(lb.profile(source)['supported'])

    def test_native_effect_ids_are_unique_and_target_relations_survive_materialization(self):
        tables = {}
        def tbl(rel): return tables.setdefault(rel, {'add': []})
        def row_by(rel, field, value): return (f'Template{value}', {})
        profile = lb.profile(agnes()); before = deepcopy(profile)
        one = support.materialize(profile, 444010, 'Agnes', tbl, row_by)
        two = support.materialize(profile, 444020, 'Other', tbl, row_by)
        ids = [e['effectId'] for e in one['effectBundleList'] + two['effectBundleList']]
        self.assertEqual(len(set(ids)), 8)
        self.assertEqual([e['targetRelation'] for e in one['effectBundleList']], ['Enemies', 'Friendlies', 'Friendlies', 'Friendlies'])
        self.assertEqual(profile, before)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            support.materialize(profile, 444010, 'Agnes', tbl, row_by)

    def test_support_timing_does_not_guess_partial_or_multi_application_layouts(self):
        self.assertEqual(support.application_frames({'effect_type': '33@3', 'attack_frames': '280:100'}), [280, 280])
        self.assertEqual(support.application_frames({'effect_type': '33@3', 'attack_frames': '200:100@280:100'}), [200, 280])
        self.assertIsNone(support.application_frames({'effect_type': '33@3@111', 'attack_frames': '200:100@280:100'}))
        self.assertIsNone(support.application_frames({'effect_type': '3', 'attack_frames': '200:50-280:50'}))

    def test_gl_support_can_reuse_only_matching_jp_presentation(self):
        forms = {'313000206': {'limitburst_id': [313000206]}}
        raw = agnes()['rawLb']
        components = agnes()['components']
        burst = {'move_type': 1, 'attack_frames': [[280]], 'attack_damage': [[100]],
                 'levels': {'1': {'effects_raw': [[c['range'], c['target'], c['type'], c['params']] for c in components]}}}
        master = {**raw, 'effect_frames': '0:1'}
        tables = {'F_UNIT_MST': [{'unit_evo_id': '313000206', 'lb_id': '313000206'}],
                  'F_LIMITBURST_MST': [master], 'F_EFFECT_GROUP_MST': [{'qIy86WvJ': '1', '1fVZ3rKd': '50:24'}]}
        with patch.object(lb, 'datamine', return_value=(forms, {'313000206': burst}, 'fixture')), \
                patch.object(lb, 'table', side_effect=lambda name: {'rows': tables[name], 'file': 'fixture'}):
            source = lb.from_datamine({'ffbe': {'id': '313000206', 'source': 'GL'}}, {})
            self.assertEqual(source['sounds'][0]['cueId'], 24)
            self.assertEqual(source['supportFrames'], [280, 280, 280])
            master['target'] = '2@2@2'
            self.assertEqual(lb.from_datamine({'ffbe': {'id': '313000206', 'source': 'GL'}}, {})['sounds'], [])


class CookedSupportTests(unittest.TestCase):
    run_dt = staticmethod(cooked_tests.CookedResonanceTests.run_dt)
    dump = classmethod(cooked_tests.CookedResonanceTests.dump.__func__)

    @classmethod
    def setUpClass(cls):
        if not Path(generator.LEGACY, resonance.SHELL + '.uasset').is_file():
            raise unittest.SkipTest('Extract the native resonance shell and skill/effect tables first')
        cls.temp = tempfile.TemporaryDirectory(prefix='support-lb-', dir=ROOT / 'build')
        cls.work = Path(cls.temp.name).resolve()
        assert cls.work.is_relative_to((ROOT / 'build').resolve())
        cls.addClassCleanup(cls.temp.cleanup)
        out = cls.work / 'assets'
        tables, clones, jobs = {}, [], []
        def tbl(rel): return tables.setdefault(rel, {'asset': generator.DT + rel, 'add': [], 'set': []})
        donor = generator.row_by('Skill/DT_SkillData', 'ID', 440110)[0]
        # Studio saves the preview's settings, including the empty effect-list
        # placeholder. Reproduce that JSON round trip before building the row.
        saved = json.loads(json.dumps(lb.profile(agnes())['set']))
        tbl('Skill/DT_SkillData')['add'].append({'row': 'SupportTest', 'cloneFrom': donor,
                                               'set': {'ID': 444010, **saved}})
        skill = {'jp': 'SupportTest', 'from': 440110, 'mechanics': 'ffbe', 'set': saved}
        with patch.object(generator, 'lb_motion_seconds', return_value=6), patch.object(lb, 'resolve', return_value=agnes()):
            generator.prepare_ffbe_resonance({'key': 'support-test', 'ffbe': {'id': '313000206'}}, skill, 444010, tbl, clones, jobs)
        path = cls.work / 'patch.json'
        path.write_text(json.dumps({'legacyRoot': generator.LEGACY, 'outRoot': str(out),
                                    'tables': list(tables.values()), 'clones': clones}), encoding='utf8')
        cls.run_dt([*generator.FFRDT, 'patch', str(path), '--usmap', generator.USMAP])
        job = jobs[0]
        resonance.build(job, out, cls.work, generator.FFRDT, generator.USMAP, cls.run_dt)
        cls.skill = cls.dump(out / (generator.DT + 'Skill/DT_SkillData.uasset'), 'rows')['rows']['SupportTest']
        cls.effects = cls.dump(out / (generator.DT + 'Skill/DT_SkillEffectData.uasset'), 'rows')['rows']
        cls.asset = cls.dump(out / (job['asset'] + '.uasset'), 'tojson')
        cls.functions = cls.dump(out / (job['asset'] + '.uasset'), 'seqdump')
        cls.plan = job['plan']

    def test_studio_saved_skill_cooks_effects_with_their_own_targets(self):
        self.assertEqual(self.skill['magnification'], 0)
        self.assertEqual(self.skill['DamageType'], 'None')
        self.assertEqual(self.skill['skillEffectType'], 'None')
        self.assertEqual(self.skill['defaultTargetRelation'], 'Friendlies')
        bundles = self.skill['effectBundleList']
        self.assertEqual(len(bundles), 4)
        self.assertEqual([b['targetRelation'] for b in bundles], ['Enemies', 'Friendlies', 'Friendlies', 'Friendlies'])
        self.assertTrue(all(b['TargetType'] == 'Group' for b in bundles))
        rows = [next(e for e in self.effects.values() if e['ID'] == b['effectId']) for b in bundles]
        self.assertEqual([e['EffectType'] for e in rows], ['AddElementResistance', 'ParameterContinuousVariation', 'ParameterContinuousVariation', 'CureStatusCondition'])
        self.assertEqual(rows[0]['ParamList'][:2], [7, 1])
        self.assertEqual(rows[1]['ParamList'][:3], [100, 6, 2])
        self.assertEqual(rows[2]['ParamList'][:3], [100, 8, 2])
        self.assertEqual(rows[3]['ParamList'][3], 9)
        self.assertEqual([e['effectEndActionNum'] for e in rows], [3, 3, 3, 1])

    def test_cooked_timeline_applies_once_and_restores_the_field(self):
        self.assets = [(self.asset, self.functions, self.plan)]
        cooked_tests.CookedResonanceTests.test_cooked_schedule_matches_channel(self)
        funcs = {int(k.split(':')[0]): v for k, v in self.functions.items()}
        events = []
        for export in self.asset['Exports']:
            for prop in export.get('Data', []):
                if prop['Name'] == 'EventChannel':
                    for time, value in zip(resonance.child(prop['Value'], 'KeyTimes'), resonance.child(prop['Value'], 'KeyValues')):
                        events.append((number(time), funcs[resonance.child(value['Value'], 'Ptrs', 'Function')]))
        self.assertEqual([t for t, e in events if e['EventType'] == 'OtherReaction'], [124000])
        self.assertEqual(events[-1][1]['EventType'], 'PostSetDefaultColorGrading')


if __name__ == '__main__':
    unittest.main()
