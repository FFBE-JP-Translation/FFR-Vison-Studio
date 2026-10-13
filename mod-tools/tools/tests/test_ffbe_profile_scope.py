"""Cinematic staging stays opt-in and bound to one source form and move."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(TOOLS), str(TOOLS/'ffbe_effects'), str(TOOLS/'devui')]
import ffbe_presentation as presentation
import ffbe_resonance


def stage_events(plan):
    return [e for e in plan['events'] if e['set']['EventType'].startswith(
        ('Camera', 'BG', 'OtherChangeSubSpace', 'UnitSetVisibility', 'UnitSetHiddenInSceneCapture', 'NativeAuraVisibility'))]


class ProfileScope(unittest.TestCase):
    def test_unprofiled_screenless_moves_preserve_battlefield_after_cinematic(self):
        plan = ffbe_resonance.schedule(2., 1, 7, {'moveType': 1})
        placement = {'mode': 'target_stage', 'backdrop': 'native_subspace', 'sourceOffset': [-96, 84],
                     'camera': {'sourceCenter': [-96, 84], 'unitsPerPixel': 3.5, 'runtimeScale': .8, 'focalLength': 50}}
        cinematic = {'_hostResonance': True, 'visuals': [
            {'name': 'background', 'asset': '/Game/background', 'anchor': 'screen', 'placement': placement,
             'layer': 2, 'frame': 0, 'frames': 30},
            {'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster', 'layer': 1, 'frame': 0, 'frames': 30}],
            'reconstructionProfile': {'screenPlacement': placement, 'casterPlacement': 'approach_target'}}
        result = presentation.apply(plan, cinematic, [], 7)
        self.assertTrue(any(e['set']['EventType'] == 'BGChange' for e in result['events']))
        self.assertTrue(any(e['set']['EventType'] == 'CameraSetZoomInOut' for e in result['events']))
        from ability_converter import commands
        plan = commands.schedule({'supported': True, 'timeline': {'moveType': 4, 'hitFrames': [40]},
            'set': {'DamageType': 'Physic'}}, 8, 1., 'magic_attack', cast_frames=10, cast_motion='command')
        original = deepcopy(plan)
        for anchor in (None, 'caster', 'each_target', 'target_group'):
            visuals = [] if anchor is None else [{'name': 'ordinary', 'asset': '/Game/ordinary',
                'anchor': anchor, 'layer': 1, 'frame': 0, 'frames': 30}]
            with self.subTest(anchor=anchor):
                out = presentation.apply(plan, {'visuals': visuals}, [], 8)
                self.assertEqual(stage_events(plan), stage_events(out))
                self.assertFalse(any(e['set']['EventType'].startswith(('BG', 'OtherChangeSubSpace', 'UnitSetVisibility'))
                                     or e['set']['EventType'] == 'CameraSetZoomInOut' for e in out['events']))
                # The presentation appends FX controls only. It preserves every
                # original move/camera/grade/reaction event and mutates no input.
                self.assertEqual(plan['events'], [e for e in out['events'] if not e['set']['EventType'].startswith('SsActor')])
                self.assertEqual(original, plan)

    def test_screen_art_without_cinematic_profile_does_not_imply_background_or_zoom(self):
        plan = ffbe_resonance.schedule(2., 1, 7)
        entry = {'visuals': [{'name': 'space_named_source', 'asset': '/Game/space', 'anchor': 'screen',
                  'layer': 2, 'frame': 0, 'frames': 30,
                  'placement': {'mode': 'frozen_caster_plane', 'sourceOffset': [0, 0]}}]}
        out = presentation.apply(plan, entry, [], 7)
        self.assertEqual(stage_events(plan), stage_events(out))
        self.assertFalse(any(e['set']['EventType'] == 'SsActorMoveToTargetToSsID' for e in out['events']))

    def test_lookup_rejects_cross_form_or_move_profile_even_with_matching_source_hash(self):
        snapshot = {'root': 'GL/ability/1', 'records': [{'source': 'GL', 'kind': 'ability', 'id': '1', 'data': {}}]}
        entry = {'sourceKey': snapshot['root'], 'sourceSha256': presentation.source_fingerprint(snapshot),
                 'visuals': [], 'reconstructionProfile': {'form': '111', 'sourceKey': snapshot['root']}}
        bundle = {'schema': presentation.VERSION, 'form': '111', 'moves': {snapshot['root']: entry}}
        unit, skill = {'ffbe': {'id': 111}}, {'conversionSource': snapshot}
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation, 'BUNDLES', Path(folder)):
            path = Path(folder)/'111.json'
            path.write_text(json.dumps(bundle), encoding='utf8')
            selected = presentation.lookup(unit, skill)
            selected['reconstructionProfile']['form'] = 'other'
            self.assertEqual('111', presentation.lookup(unit, skill)['reconstructionProfile']['form'])
            cases = []
            bad = deepcopy(bundle); bad['form'] = '222'; cases.append(bad)
            bad = deepcopy(bundle); bad['moves'][snapshot['root']]['sourceKey'] = 'GL/ability/2'; cases.append(bad)
            bad = deepcopy(bundle); bad['moves'][snapshot['root']]['reconstructionProfile']['form'] = '222'; cases.append(bad)
            bad = deepcopy(bundle); bad['moves'][snapshot['root']]['reconstructionProfile']['sourceKey'] = 'GL/lb/111'; cases.append(bad)
            bad = deepcopy(bundle); bad['moves'][snapshot['root']]['reconstructionProfile'].pop('form'); cases.append(bad)
            for bad in cases:
                with self.subTest(bundle=bad):
                    path.write_text(json.dumps(bad), encoding='utf8')
                    with self.assertRaisesRegex(ValueError, 'different|does not match'):
                        presentation.lookup(unit, skill)
            # A second, unprofiled move in this same form cannot inherit the
            # first move's cinematic metadata, even with an identical record set.
            second = deepcopy(snapshot); second['root'] = 'GL/ability/2'
            bundle['moves'][second['root']] = {'sourceSha256': presentation.source_fingerprint(second), 'visuals': []}
            path.write_text(json.dumps(bundle), encoding='utf8')
            self.assertNotIn('reconstructionProfile', presentation.lookup(unit, {'conversionSource': second}))

    def test_aura_binding_uses_selected_host_vision_not_copied_bundle_id(self):
        snapshot = {'root': 'GL/lb/111', 'records': []}
        entry = {'sourceKey': snapshot['root'], 'sourceSha256': presentation.source_fingerprint(snapshot),
                 '_hostVisionUnitId': 99999, 'visuals': [],
                 'reconstructionProfile': {'form': '111', 'sourceKey': snapshot['root'],
                    'screenPlacement': {'hideNativeAuras': True}}}
        bundle = {'schema': presentation.VERSION, 'form': '111', 'moves': {snapshot['root']: entry}}
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation, 'BUNDLES', Path(folder)):
            Path(folder, '111.json').write_text(json.dumps(bundle), encoding='utf8')
            selected = presentation.lookup({'ffbe': {'id': 111}, 'id': 13503}, {'conversionSource': snapshot})
            self.assertEqual(13503, selected['_hostVisionUnitId'])
            for value in (None, True, 0, -1, '13503'):
                with self.subTest(hostId=value), self.assertRaises(ValueError):
                    presentation.lookup({'ffbe': {'id': 111}, 'id': value}, {'conversionSource': snapshot})

    def test_legacy_unprofiled_bundle_keeps_its_existing_lookup_contract(self):
        snapshot = {'root': 'GL/ability/1', 'records': []}
        entry = {'sourceSha256': presentation.source_fingerprint(snapshot), 'visuals': []}
        with tempfile.TemporaryDirectory() as folder, patch.object(presentation, 'BUNDLES', Path(folder)):
            Path(folder, '111.json').write_text(json.dumps({'schema': 'ffr-presentation-1',
                'moves': {snapshot['root']: entry}}), encoding='utf8')
            self.assertEqual(entry, presentation.lookup({'ffbe': {'id': 111}}, {'conversionSource': snapshot}))

    def test_prepare_rejects_profile_for_multiple_or_different_forms_and_moves_before_io(self):
        import prepare_vision
        profile = {'form': '111', 'sourceKey': 'GL/lb/111'}
        with tempfile.TemporaryDirectory() as folder, patch.object(prepare_vision, 'WORK', Path(folder)/'unused'):
            for forms, moves in ((['222'], ['GL/lb/111']), (['111', '222'], ['GL/lb/111']),
                                 (['111'], None), (['111'], ['GL/ability/1']),
                                 (['111'], ['GL/lb/111', 'GL/ability/1'])):
                with self.subTest(forms=forms, moves=moves), self.assertRaisesRegex(ValueError, 'single selected form and move'):
                    prepare_vision.prepare(forms, moves, profile)
            self.assertFalse((Path(folder)/'unused').exists())


if __name__ == '__main__':
    unittest.main()
