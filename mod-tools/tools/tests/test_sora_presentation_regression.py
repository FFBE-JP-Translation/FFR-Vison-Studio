"""Ars Arcanum source, prepared media, and host action must share one clock."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import ffbe_audio
import ffbe_audio_assets
import ffbe_presentation
import make_vision_mod as generator
from ffbe_effects import acb_native, hca_host
from ffbe_effects.acb_cues import utf

FORM = '340000107'
SOURCE = 'GL_2024/lb/340000107/level/40'


class SoraPresentationRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        required = [ROOT / 'data/ffbe/native_kits' / (FORM + '.json'),
                    ROOT / 'data/ffbe/presentation' / (FORM + '.json'),
                    ROOT / 'extracted/rows/Skill/DT_SkillData.json']
        if not all(path.is_file() for path in required):
            raise unittest.SkipTest('Prepared Sora kit and native host tables required')
        kit = json.loads(required[0].read_text(encoding='utf-8'))
        profile = kit['profiles'][SOURCE]
        cls.unit = {'id': 13502, 'key': 'sora-regression', 'donor': 13125,
                    'ffbe': {'id': FORM, 'dir': 'units/ffbe/sora/sprites/' + FORM}}
        cls.skill = {'jp': 'SoraRegression', 'en': 'Ars Arcanum (KHIII)', 'from': 440110,
                     'mechanics': 'converted', 'effectPolicy': kit['studioPolicy'],
                     'conversionSource': profile['snapshot'], 'set': profile['set'],
                     'presentation': 'ffbe', 'resonance': True, 'ffbe_lb_id': FORM}
        cls.entry = ffbe_presentation.lookup(cls.unit, cls.skill)
        cls.tables = {}
        def tbl(rel):
            return cls.tables.setdefault(rel, {'asset': generator.DT + rel, 'add': [], 'set': []})
        tbl('Skill/DT_SkillData')['add'].append({
            'row': cls.skill['jp'], 'cloneFrom': generator.row_by('Skill/DT_SkillData', 'ID', 440110)[0],
            'set': {'ID': 444030}})
        jobs = []
        generator.prepare_ffbe_resonance(deepcopy(cls.unit), deepcopy(cls.skill), 444030, tbl, [], jobs)
        cls.job = jobs[0]
        cls.plan = cls.job['plan']
        cls.start = ffbe_presentation.action_start(cls.plan)
        cls.source = profile['snapshot']['records'][0]['data']

    def test_caster_authored_slashes_replace_donor_art_without_changing_mechanics(self):
        # The real source uses caster-relative KH stars and orange impacts.
        # An anchor-only gate formerly left donor normal/critical/additional art enabled.
        action_spawns = [v for v in self.entry['spawns'] if v.get('phase', 'action') == 'action']
        self.assertTrue(action_spawns)
        self.assertEqual({v['anchor'] for v in action_spawns if v['anchor']!='screen'}, {'caster'})
        self.assertTrue(any(v['file'] == 'KH_star_hit_eff_KingdomChain.bmb' for v in action_spawns))
        self.assertTrue(ffbe_presentation.has_target_visuals(self.entry))
        reaction = self.tables['Battle/Sequencer/DT_BtlHitEffectData']['add'][0]['set']
        for field in ('NormalEffectID', 'CriticalEffectID', 'AdditionalEffectID'):
            self.assertEqual(reaction[field], -1)
        self.assertFalse(reaction['IsAdditionalEffect'])
        source_hits = self.source['attack_frames'][0]
        actual_hits = [(e['time'] - self.start) // 400 for e in self.plan['events']
                       if e['set']['EventType'] == 'OtherReaction']
        self.assertEqual(actual_hits, source_hits)
        self.assertEqual(len(actual_hits), 13)
        self.assertEqual(actual_hits[-1], 293)
        skill = self.tables['Skill/DT_SkillData']['add'][0]['set']
        self.assertEqual(skill['TargetType'], 'Single')
        self.assertEqual(skill['hitCount'], 13)

    def test_finishing_sounds_survive_preparation_and_full_audio_tail(self):
        audio = self.job['audio']
        records = audio['recordings']
        by_label = {r['name']: r for r in records}
        sounds = [e for e in self.plan['events'] if e['set']['EventType'] == 'SoundPlayHitSound'
                  and e['set']['Sound_PlayHitSound_CueSheetName'] == audio['name']]
        actual = Counter(((e['time'] - self.start) // 400,
                          by_label[e['set']['Sound_PlayHitSound_playLabel']]['sourceCueId']) for e in sounds)
        self.assertEqual(actual, Counter((s['frame'], s['cueId']) for s in self.entry['sounds']))
        for event in ((293, 29), (293, 30), (303, 25)):
            self.assertEqual(actual[event], 1)
        self.assertEqual({r['sourceCueId']: r['samples'] for r in records if r['sourceCueId'] in (25, 29, 30)},
                         {25: 47981, 29: 40043, 30: 70031})
        for e in sounds:
            recording = by_label[e['set']['Sound_PlayHitSound_playLabel']]
            end = e['time'] + recording['durationMs'] * 24
            self.assertLess(end, self.plan['duration'])

    def test_finish_waveforms_are_retained_by_the_host_bank(self):
        # Exercise the actual bank writer with the final cues; checking event
        # labels alone cannot establish that their media made it into the ACB.
        audio = self.job['audio']
        manifest = audio['audioManifest']
        selected = [r for r in audio['recordings'] if r['sourceCueId'] in (25, 29, 30)]
        samples = ffbe_audio_assets.waves(audio['path'], manifest)
        host_path = Path(generator.LEGACY) / (ffbe_audio.SHELL + '.uexp')
        host = host_path.read_bytes()
        host = host[host.index(b'@UTF'):]
        host = host[:int.from_bytes(host[4:8], 'big') + 8]
        built = acb_native.build(b'', host, 'SoraFinishRegression', selected, raw_waves=samples)
        header = utf(built)[1][0]
        exported = acb_native.awb_files(header['AwbFile'])
        names = utf(header['CueNameTable'])[1]
        for index, rec in enumerate(selected):
            self.assertEqual(names[index]['CueName'], rec['name'])
            self.assertEqual(exported[index], samples[rec['sourceWaveId']])
            hca_host.validate_layout(exported[index])
        self.assertEqual(len(exported), 3)


if __name__ == '__main__':
    unittest.main()
