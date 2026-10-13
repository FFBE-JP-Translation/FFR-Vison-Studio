"""Host Resonance selection controls camera motion independently of source BG."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ffbe_presentation as presentation
from ability_converter import commands
from tools.tests.test_ffbe_target_stage import fixture
from tools.tests.test_ffbe_camera_plane import placement


class CameraPolicy(unittest.TestCase):
    def test_ordinary_background_replacement_fits_effects_without_moving_camera(self):
        plan = commands.schedule({'supported': True, 'timeline': {'moveType': 4, 'hitFrames': [40]},
            'set': {'DamageType': 'Magic'}}, 8, 1., 'magic_attack')
        plane = {**placement(), 'backdrop': 'native_subspace'}
        entry = {'reconstructionProfile': {'screenPlacement': plane}, 'visuals': [
            {'name': 'meteor', 'asset': '/Game/meteor', 'anchor': 'screen', 'placement': deepcopy(plane),
             'layer': 2, 'frame': 0, 'frames': 90}]}
        before = deepcopy((plan, entry))
        out = presentation.apply(plan, entry, [], 8)
        events = [e['set']['EventType'] for e in out['events']]
        self.assertIn('BGChange', events)
        self.assertIn('BGRevert', events)
        self.assertIn('NativeScreenPlane', events)
        self.assertFalse(any(e.startswith('Camera') or e == 'NativeStageCamera' for e in events))
        self.assertEqual((plan, entry), before)
        self.assertEqual([e['time'] - presentation.action_start(out) for e in out['events']
                          if e['set']['EventType'] == 'OtherReaction'], [40 * 400])

    def test_cinematic_profile_requires_explicit_host_resonance(self):
        plan, entry = fixture()
        for invalid in (None, False, 1, 'true'):
            candidate = deepcopy(entry)
            if invalid is None: candidate.pop('_hostResonance')
            else: candidate['_hostResonance'] = invalid
            with self.subTest(value=invalid), self.assertRaisesRegex(ValueError, 'require a Resonance'):
                presentation.apply(plan, candidate, [], 7)
        self.assertTrue(any(e['set']['EventType'] == 'CameraSetZoomInOut'
                            for e in presentation.apply(plan, entry, [], 7)['events']))

    def test_source_bundle_cannot_grant_camera_permission_to_an_ordinary_skill(self):
        plan, entry = fixture()
        snapshot = {'root': 'GL/ability/123', 'records': []}
        entry['sourceSha256'] = presentation.source_fingerprint(snapshot)
        entry['reconstructionProfile'].update(form='123', sourceKey=snapshot['root'])
        unit = {'ffbe': {'id': 123}}
        skill = {'conversionSource': snapshot}
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation, 'BUNDLES', Path(folder)):
            Path(folder, '123.json').write_text(json.dumps({'schema': presentation.VERSION,
                'moves': {snapshot['root']: entry}}), encoding='utf-8')
            ordinary = presentation.lookup(unit, skill)
            self.assertNotIn('_hostResonance', ordinary)
            with self.assertRaisesRegex(ValueError, 'require a Resonance'):
                presentation.apply(plan, ordinary, [], 7)
            resonance = presentation.lookup(unit, {**skill, 'resonance': True})
            self.assertIs(resonance['_hostResonance'], True)
            self.assertTrue(any(e['set']['EventType'] == 'CameraSetZoomInOut'
                                for e in presentation.apply(plan, resonance, [], 7)['events']))


if __name__ == '__main__': unittest.main()
