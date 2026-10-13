"""Native camera interpolation stays separate from source art and hit clocks."""
from copy import deepcopy
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ffbe_presentation as presentation
import ffbe_resonance as resonance
import make_vision_mod as generator
import test_ffbe_native_aura as aura
from test_ffbe_target_registration import registered_fixture
from test_ffbe_target_stage import bytype, verify


def fixture():
    plan, entry = registered_fixture()
    placement = entry['reconstructionProfile']['screenPlacement']
    placement['hideNonParticipants'] = True
    placement['camera']['pan'] = [
        {'frame': 15, 'durationFrames': 20, 'sourceCenter': [-48, 160]},
        {'frame': 40, 'durationFrames': 30, 'sourceCenter': [-160, -20], 'focalLength': 32.5}]
    for fx in entry['visuals']:
        if fx['anchor'] == 'screen': fx['placement'] = deepcopy(placement)
    return plan, entry


class PanSchedule(unittest.TestCase):
    def test_native_pan_and_scoped_isolation_do_not_move_source_timeline(self):
        plan, entry = fixture()
        prior = deepcopy(entry)
        prior['reconstructionProfile']['screenPlacement']['camera'].pop('pan')
        prior['reconstructionProfile']['screenPlacement'].pop('hideNonParticipants')
        for fx in prior['visuals']:
            if fx['anchor'] == 'screen': fx['placement'] = deepcopy(prior['reconstructionProfile']['screenPlacement'])
        old = presentation.apply(plan, prior, [], 7)
        new = presentation.apply(plan, entry, [], 7)
        for kind in ('OtherReaction', 'UnitPlayAnimByName', 'UnitMoveToTarget', 'SsActorSpawnSpriteStudioActor',
                     'SsActorPlayAnimToSsID', 'SsActorMoveToTargetToSsID', 'SsActorDestroyToSsID'):
            self.assertEqual(bytype(old, kind), bytype(new, kind), kind)
        main = presentation.action_start(new)
        self.assertEqual([t for t, _ in bytype(new, 'NativeStageCamera')][1:], [main+15*400, main+40*400])
        self.assertEqual([e['NativeStageCamera_Frame'] for _, e in bytype(new, 'NativeStageCamera')[1:]], [10, 15])
        self.assertEqual(bytype(new, 'CameraSetZoomInOut')[-1][1]['Camera_SetZoomInOut_Frame'], 15)
        self.assertEqual(bytype(new, 'UnitSetVisibility'), [])
        self.assertTrue(verify(entry, new)['targetStageVerified'])
        for change in ('camera', 'restore'):
            bad = deepcopy(new)
            kind = 'NativeStageCamera' if change == 'camera' else 'NativeStageVisibility'
            bad['events'] = [e for e in bad['events'] if e['set']['EventType'] != kind]
            with self.assertRaises(AssertionError): verify(entry, bad)

    def test_pan_rejects_bad_centers_overlap_invalid_easing_and_cleanup_crossing(self):
        plan, entry = fixture()
        placement = entry['reconstructionProfile']['screenPlacement']
        camera = placement['camera']
        for patch in ({'frame': True}, {'frame': 0}, {'durationFrames': 0}, {'durationFrames': 35}, {'sourceCenter': [math.nan, 0]},
                      {'easing': 'Spline'}, {'focalLength': -1}, {'unexpected': 2}):
            bad = deepcopy(camera); bad['pan'][0].update(patch)
            with self.subTest(patch=patch), self.assertRaises(ValueError): presentation.camera_pan_keys(bad)
        bad = deepcopy(camera); bad['pan'][1]['frame'] = 20
        with self.assertRaises(ValueError): presentation.camera_pan_keys(bad)
        placement['camera']['pan'][-1]['durationFrames'] = 3600
        for fx in entry['visuals']:
            if fx['anchor'] == 'screen': fx['placement'] = deepcopy(placement)
        with self.assertRaisesRegex(ValueError, 'cleanup'): presentation.apply(plan, entry, [], 7)

    def test_single_target_override_keeps_original_source_scope(self):
        entry = {'reconstructionProfile': {'hostTargetType': 'Single'},
                 'provenance': [{'range': 2, 'target': 1}]}
        before = deepcopy(entry)
        self.assertEqual(presentation.host_target_settings(entry), {'TargetType': 'Single', 'targetRage': 'None'})
        self.assertEqual(entry, before)
        self.assertEqual(presentation.host_target_settings({}), {})
        with self.assertRaises(ValueError): presentation.host_target_settings({'reconstructionProfile': {'hostTargetType': 'Everyone'}})

    def test_screen_setup_preroll_moves_source_channels_together(self):
        plan = resonance.schedule(2, 1, 7, {'moveType': 0, 'hitFrames': [60]})
        placement = {'mode': 'frozen_caster_plane', 'backdrop': 'native_subspace', 'sourceOffset': [0, 0]}
        entry = {'reconstructionProfile': {'screenPlacement': placement}, 'visuals': [
            {'name': 'screen', 'asset': '/Game/screen', 'anchor': 'screen', 'placement': placement,
             'frame': -12, 'frames': 140, 'layer': 2}]}
        sound = {'frame': 60, 'bank': 'same_clock', 'cueName': 'impact', 'durationMs': 100}
        old_main = presentation.action_start(plan)
        out = presentation.apply(plan, entry, [sound], 7)
        main = presentation.action_start(out)
        self.assertGreater(main, old_main)
        self.assertEqual(bytype(out, 'OtherReaction')[0][0], main + 60*400)
        self.assertEqual(bytype(out, 'SoundPlayHitSound')[0][0], main + 60*400)
        self.assertGreater(bytype(out, 'SsActorSpawnSpriteStudioActor')[0][0],8002)


class PanCooked(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY) / (resonance.SHELL + '.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-pan-', dir=ROOT / 'build'); cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name); cls.asset = cls.work / 'shell.uasset'
        cls.usmap = cls.work / 'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifier = next(k.split(':')[0] for k, v in cls.dump('seqdump').items()
                              if isinstance(v, dict) and v.get('$struct') == 'BTL_SEQUENCE_PARAMETER')
        cls.event = {'EventType': 'NativeStageCamera', 'NativeStageCamera_UnitId': 13503,
                     'NativeStageCamera_AddLocation': {'x': 0., 'y': -134.4, 'z': 448.},
                     'NativeStageCamera_Frame': 35, 'NativeStageCamera_EasingType': 'EaseInOut'}
        result = cls.patch([{'asset': 'shell', 'export': cls.identifier, 'set': cls.event}])
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def test_native_interpolation_fields_survive_cook(self):
        self.assertEqual(next(v for k, v in self.dump('seqdump').items() if k.split(':')[0] == self.identifier), self.event)
        fn = self.dump('tojson')['Exports'][int(self.identifier)-1]
        fields = fn['ScriptBytecode'][5]['Parameters'][1]['Value']
        self.assertEqual(fields[15]['Value'], 35)
        self.assertEqual(fields[17]['Value'], 2.0)
        self.assertEqual(fields[18]['Value'], 1)

    def test_bad_pan_input_is_cli_error_without_unhandled_crash(self):
        for patch in ({'NativeStageCamera_Frame': 0}, {'NativeStageCamera_Frame': True},
                      {'NativeStageCamera_EasingType': 'Unknown'}):
            event = {**self.event, **patch}
            result = self.patch([{'asset': 'shell', 'export': self.identifier, 'set': event}])
            self.assertEqual(result.returncode, 1)
            self.assertIn('NativeStageCamera', result.stderr)
            self.assertNotIn('Unhandled exception', result.stderr)


if __name__ == '__main__': unittest.main()
