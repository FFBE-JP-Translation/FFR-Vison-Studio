"""Cooked regressions for body framing, native default lens and stable pan.

The real SpriteStudio culling boxes in the rejected v5 shot were 2–3k units
high. They must never change the new close-camera lens or position.
"""
from copy import deepcopy
from pathlib import Path
import math
import shutil
import struct
import sys
import tempfile
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from tools.tests import test_ffbe_native_participant_framing as framing
from tools.tests.fixtures.participant_camera_vm import CameraVM, vector
import ffbe_resonance as resonance
import make_vision_mod as generator


def xyz(value): return dict(zip(('X', 'Y', 'Z'), value))


def unit(feet=(0, 0, 0), height=400, radius=80, canvas=(300, 1500, 1490), sockets=True):
    head = vector(feet) + [0, 0, height]
    return {'location': xyz(feet), 'm_pSsPlayerComponent': {
        'origin': xyz(feet), 'extent': xyz(canvas),
        'sockets': {'NULL_Head': xyz(head)} if sockets else {}},
        'm_pRootCapsuleComponent': {'radius': radius, 'halfHeight': height/2}}


def camera(default=32.5):
    return {'location': xyz((-2800, 0, 800)), 'defaultFocal': default,
        'defaultTransform': {'location': xyz((-2800, 0, 800)),
            'rotation': {'Pitch': -10.5, 'Yaw': 0, 'Roll': 0}, 'scale': xyz((1, 1, 1))},
        'Cine': {'location': xyz((-2800, 0, 800)),
            'rotation': {'Pitch': -6.83, 'Yaw': -6.15, 'Roll': 0}, 'CurrentFocalLength': default,
            'Filmback': {'SensorWidth': 23.76},
            'LensSettings': {'MinFocalLength': 4., 'MaxFocalLength': 200.}}}


class NativeParticipantFocus(unittest.TestCase):
    command = classmethod(framing.NativeParticipantFraming.command.__func__)
    dump = classmethod(framing.NativeParticipantFraming.dump.__func__)
    patch = classmethod(framing.NativeParticipantFraming.patch.__func__)
    kind = staticmethod(framing.NativeParticipantFraming.kind)
    walk = staticmethod(framing.NativeParticipantFraming.walk)
    vm_size = classmethod(framing.NativeParticipantFraming.vm_size.__func__)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-participant-focus-', dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup); cls.work = Path(cls.temp.name); cls.asset = cls.work/'shell.uasset'
        cls.usmap = cls.work/'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifiers = [key.split(':')[0] for key, value in cls.dump('seqdump').items()
                           if isinstance(value, dict) and value.get('$struct') == 'BTL_SEQUENCE_PARAMETER'][:2]
        cls.events = [{'EventType': 'NativeParticipantCamera', 'NativeParticipantCamera_UnitId': 7777,
            'NativeParticipantCamera_Frame': 4 if shot == 'caster' else 12,
            'NativeParticipantCamera_Shot': shot, 'NativeParticipantCamera_CenterX': x,
            'NativeParticipantCamera_CenterY': y, 'NativeParticipantCamera_HeightFraction': height,
            'NativeParticipantCamera_ZoomFactor': zoom}
            for shot, x, y, height, zoom in [('caster', .55, .52, .52, 1.25), ('targets', .35, .56, .32, 1.05)]]
        cls.ops = [{'asset': 'shell', 'export': identifier, 'set': event} for identifier, event in zip(cls.identifiers, cls.events)]
        # The live upgrade starts from the rejected v5 two-native-call camera,
        # rather than from a fresh one-event stock donor.
        old_ops = deepcopy(cls.ops)
        for op in old_ops:
            op['set'].pop('NativeParticipantCamera_ZoomFactor')
            op['set']['NativeParticipantCamera_MaxFocalLength'] = 52. if op['set']['NativeParticipantCamera_Shot'] == 'caster' else 32.5
        result = cls.patch(old_ops)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)
        cls.before = cls.dump('tojson')
        result = cls.patch(cls.ops)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)
        cls.document = cls.dump('tojson')

    def test_upgrade_of_validated_v5_preserves_all_other_function_bodies_and_channels(self):
        selected = set(map(int, self.identifiers))
        for index, (before, after) in enumerate(zip(self.before['Exports'], self.document['Exports']), 1):
            self.assertEqual(before.get('Data'), after.get('Data'))
            if index not in selected: self.assertEqual(before.get('ScriptBytecode'), after.get('ScriptBytecode'))

    def evaluate(self, index, caster, targets, cam=None, viewport=(1280, 720)):
        fn = self.document['Exports'][int(self.identifiers[index])-1]
        vm = CameraVM(self.document, fn, self.vm_size, caster, targets, cam or camera(), viewport)
        return vm.run(), vm

    def test_native_roundtrip_uses_versioned_focus_and_no_dolly_or_culling_bounds(self):
        decoded = self.dump('seqdump')
        for identifier, event in zip(self.identifiers, self.events):
            self.assertEqual(next(v for k, v in decoded.items() if k.startswith(identifier+':')), event)
            fn = self.document['Exports'][int(identifier)-1]; code = fn['ScriptBytecode']
            names = [self.document['Imports'][-n['StackNode']-1]['ObjectName'] for n in self.walk(code) if 'StackNode' in n]
            self.assertNotIn('GetComponentBounds', names); self.assertNotIn('GetAllActorsOfClass', names)
            self.assertIn('GetDefaultCameraTransform', names); self.assertIn('GetDefaultCurrentFocalLength', names)
            self.assertIn('GetSocketLocation', names); self.assertIn('GetScaledCapsuleRadius', names)
            self.assertNotIn('K2_GetComponentRotation', names); self.assertNotIn('K2_GetComponentLocation', names)
            calls = [n['Parameters'][1]['Value'] for n in code if self.kind(n) == 'EX_LocalVirtualFunction']
            self.assertEqual([v[0]['Value'] for v in calls], [4, 6])  # look-at then actual focal mm
            self.assertEqual(calls[0][19]['Value'], -1)
            self.assertEqual(self.kind(calls[1][32]), 'EX_False')  # no cumulative relative zoom
            self.assertEqual(sum(map(self.vm_size, code)), fn['ScriptBytecodeSize'])
            for n in self.walk(code):
                if self.kind(n) == 'EX_LocalVariable':
                    self.assertEqual(n['Variable']['New']['ResolvedOwner'], int(identifier))
            self.assertTrue(any(p['Name'] == 'FFBE_Focus_Shot' for p in fn['LoadedProperties']))

    def test_real_canvas_regression_preserves_modest_default_relative_lens(self):
        # Actual rejected v5 run 20260913_190457_015 at source +.5s:
        # RF's 156-unit body was framed as a 4892-unit animation canvas.
        target = unit((-100, -525, 0), 492.17, 34, (230.702, 1071, 1045.865))
        caster = unit((-80.149, -243.465, 8.108), 155.95, 27.2, (532.292, 2503.2, 2445.957))
        caster['m_pSsPlayerComponent']['sockets']['NULL_Head'] = xyz((-30.757, -241.117, 164.059))
        target['m_pSsPlayerComponent']['sockets']['NULL_Head'] = xyz((27.969, -522.876, 492.17))
        for default in (25.5, 32.5, 40.):
            for index, factor in enumerate((1.25, 1.05)):
                first, _ = self.evaluate(index, caster, [target], camera(default))
                self.assertAlmostEqual(first[1][27], default*factor)
                changed = deepcopy(target); changed['m_pSsPlayerComponent']['extent'] = xyz((1e6, 1e6, 1e6))
                second, _ = self.evaluate(index, caster, [changed], camera(default))
                self.assertEqual(first, second)

    def test_repeated_refresh_never_feeds_back_current_pose_or_inflight_lens(self):
        caster, target, cam = unit((0, 180, 0)), unit((0, -550, 0), 710), camera()
        for index in (0, 1):
            first, _ = self.evaluate(index, caster, [target], cam)
            drifted = deepcopy(cam)
            drifted['location'] = xyz((-15000, -3000, 5000))
            drifted['Cine'].update(location=xyz((-15000, -3000, 5000)),
                rotation={'Pitch': -40, 'Yaw': 37, 'Roll': 0}, CurrentFocalLength=8.)
            for _ in range(12): self.assertEqual(self.evaluate(index, caster, [target], drifted)[0], first)

    def test_target_pan_projects_body_center_near_requested_circle(self):
        target, cam = unit((-81, -529, 0), 716, 150), camera()
        emitted, vm = self.evaluate(1, unit(), [target], cam)
        aim = vector(target['location']) + vector(emitted[0][14])
        origin = vector(cam['defaultTransform']['location']); forward = aim-origin; forward /= np.linalg.norm(forward)
        right = np.cross([0., 0., 1.], forward); right /= np.linalg.norm(right); up = np.cross(forward, right)
        center = vector(target['location']) + [0, 0, 358]; delta = center-origin; depth = delta@forward
        x = .5 + (delta@right)*emitted[1][27]/(23.76*depth)
        y = .5 - (delta@up)*emitted[1][27]*1280/(23.76*depth*720)
        self.assertAlmostEqual(x, .35, delta=.04); self.assertAlmostEqual(y, .56, delta=.04)

    def test_all_actual_targets_influence_fit_and_capsule_is_safe_fallback(self):
        caster = unit(); left = unit((0, -1700, 0), 700); right = unit((0, 1700, 0), 500)
        one, _ = self.evaluate(1, caster, [left]); both, vm = self.evaluate(1, caster, [left, right])
        self.assertEqual(vm.values['FFBE_Focus_Count'], 2)
        self.assertLess(both[1][27], one[1][27]); self.assertGreaterEqual(both[1][27], 8.)
        reverse, _ = self.evaluate(1, caster, [right, left])
        self.assertAlmostEqual(reverse[1][27], both[1][27])
        np.testing.assert_allclose(vector(left['location'])+vector(both[0][14]),
            vector(right['location'])+vector(reverse[0][14]))
        fallback = unit((0, -400, 0), 400, sockets=False)
        emitted, fallback_vm = self.evaluate(1, caster, [fallback])
        self.assertEqual(fallback_vm.values['FFBE_Focus_Height'], 400.)
        self.assertAlmostEqual(emitted[1][27], 32.5*1.05)

    def test_independent_look_at_projection_keeps_a_battle_target_union_visible(self):
        targets = [unit((0, -1100, 0), 700, 100), unit((120, 500, 0), 490, 80)]
        cam = camera(); emitted, _ = self.evaluate(1, unit(), targets, cam)
        origin = vector(cam['defaultTransform']['location'])
        aim = vector(targets[0]['location']) + vector(emitted[0][14])
        forward = aim-origin; forward /= np.linalg.norm(forward)
        right = np.cross([0., 0., 1.], forward); right /= np.linalg.norm(right); up = np.cross(forward, right)
        for target in targets:
            feet = vector(target['location']); head = vector(target['m_pSsPlayerComponent']['sockets']['NULL_Head'])
            radius = max(target['m_pRootCapsuleComponent']['radius'], np.linalg.norm(head-feet)*.25)
            for endpoint in (feet, head):
                for side in (-radius, radius):
                    point = endpoint + np.array([0, side, 0])-origin; depth = point@forward
                    x = .5 + (point@right)*emitted[1][27]/(23.76*depth)
                    y = .5 - (point@up)*emitted[1][27]*1280/(23.76*depth*720)
                    self.assertTrue(.02 < x < .98 and .02 < y < .98, (x, y))

    def test_invalid_zoom_factor_is_not_reinterpreted_as_focal_mm(self):
        before = self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()
        for value in (True, .99, 1.51, 32.5, float('nan')):
            op = deepcopy(self.ops[0]); op['set']['NativeParticipantCamera_ZoomFactor'] = value
            result = self.patch([op]); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()))

    def test_empty_targets_and_invalid_viewport_do_not_mutate_camera(self):
        for viewport in ((1280, 720), (0, 720), (1280, 0)):
            self.assertEqual(self.evaluate(1, unit(), [], viewport=viewport)[0], [])


if __name__ == '__main__': unittest.main()
