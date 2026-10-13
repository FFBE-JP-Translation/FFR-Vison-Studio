"""Regression for GL's bank selector: equal cue numbers are not equal sounds."""
from pathlib import Path
from unittest.mock import patch
import sys, unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'tools/devui'), str(ROOT/'tools/ffbe_effects')]
from ffbe_effects import prepare_vision
import ffbe_presentation
import ffbe_audio

class SoundRouting(unittest.TestCase):
    def test_nested_action_bank_survives_cast_bank_combination(self):
        action = {'name':'attack', 'additionalBanks':[{'name':'system95'}]}
        bank, _ = ffbe_audio.combine({'name':'cast'}, [], action, [])
        self.assertEqual(['cast','attack','system95'], [b['name'] for b in ffbe_audio.banks(bank)])
        self.assertEqual(['attack','system95'], [b['name'] for b in bank['additionalBanks']])
        # Existing saved plans may still contain the pre-flattening structure.
        old = {'name':'cast', 'additionalBanks':[action]}
        self.assertEqual(['cast','attack','system95'], [b['name'] for b in ffbe_audio.banks(old)])

    def test_real_sora_lb_95_uses_system(self):
        native = prepare_vision.native_kit('340000107')
        result = prepare_vision.timeline(native['profiles']['GL_2024/lb/340000107/level/40']['snapshot'],
                                         include_screen=True, source_matched=True)
        cues = [s for s in result['sounds'] if s['cueId'] == 95]
        self.assertEqual(12, len(cues))
        self.assertEqual({'System'}, {s['sourceBank'] for s in cues})
        self.assertEqual([63,72,82,91,107,129,171,206,217,222,227,232], [s['frame'] for s in cues])

    def test_equal_number_and_frame_in_different_banks_survive(self):
        entry = {'audioBank':'common.json', 'audioBanks':{'System':'system.json'},
                 'sounds':[{'cueId':95,'frame':5,'sourceBank':bank} for bank in ('SE','System')]}
        calls = []
        def prepare(unit, settings, source, tables):
            calls.append((settings['audio_bank'], source['sounds']))
            return {'name':settings['audio_bank']}, source['sounds']
        with patch('ffbe_presentation.ffbe_audio.prepare_command', side_effect=prepare):
            bank, events = ffbe_presentation.prepare_audio({}, {}, entry, None)
        self.assertEqual(['common.json','system.json'], [c[0] for c in calls])
        self.assertEqual(2, len(events))
        self.assertEqual('system.json', bank['additionalBanks'][0]['name'])

    def test_limit_burst_wrapper_also_routes_effect_banks(self):
        settings={'audio':'native','lb_charge':False,'audio_banks':{'SE':'common.json','System':'system.json'}}
        source={'sounds':[{'cueId':95,'frame':5,'sourceBank':bank} for bank in ('SE','System')]}
        paths=[]
        def prepare(unit, skill, data, tables):
            paths.append(skill['audio_bank']); return {'name':skill['audio_bank']}, data['sounds']
        with patch('ffbe_audio._prepare_bank',side_effect=prepare):
            _,events=ffbe_audio.prepare({},settings,source,None)
        self.assertEqual(['common.json','system.json'],paths)
        self.assertEqual(2,len(events))

if __name__ == '__main__': unittest.main()
