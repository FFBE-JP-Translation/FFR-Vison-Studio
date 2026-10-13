"""Cook the two-shot camera and independently inspect native bounds/lens code."""
from copy import deepcopy
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import unittest
import itertools
import math
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).resolve().parent)]
from tools.tests import test_ffbe_native_aura as aura
from tools.tests import test_ffbe_native_actor_root as actor_root
from tools.tests import test_ffbe_native_stage_camera as stage
import ffbe_resonance as resonance
import make_vision_mod as generator
from tools.tests.fixtures.participant_camera_vm import CameraVM, vector


class NativeParticipantFraming(unittest.TestCase):
    command = classmethod(aura.NativeAuraCooked.command.__func__)
    dump = classmethod(aura.NativeAuraCooked.dump.__func__)
    patch = classmethod(aura.NativeAuraCooked.patch.__func__)
    kind = staticmethod(aura.NativeAuraCooked.kind)
    walk = staticmethod(stage.NativeStageCameraCooked.walk)
    vm_size = classmethod(actor_root.NativeActorRoot.vm_size.__func__)

    @classmethod
    def setUpClass(cls):
        source = Path(generator.LEGACY)/(resonance.SHELL+'.uasset')
        if not source.is_file(): raise unittest.SkipTest('Native battle shell unavailable')
        cls.temp = tempfile.TemporaryDirectory(prefix='native-participant-framing-', dir=ROOT/'build')
        cls.addClassCleanup(cls.temp.cleanup); cls.work = Path(cls.temp.name); cls.asset = cls.work/'shell.uasset'
        cls.usmap = cls.work/'Mappings.usmap'; shutil.copy2(generator.USMAP, cls.usmap)
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if source.with_suffix(suffix).exists(): shutil.copy2(source.with_suffix(suffix), cls.asset.with_suffix(suffix))
        cls.identifiers = [key.split(':')[0] for key, value in cls.dump('seqdump').items()
                           if isinstance(value, dict) and value.get('$struct') == 'BTL_SEQUENCE_PARAMETER'][:2]
        cls.events = []
        for shot, xy, height, lens in [('caster', (.55, .52), .52, 52.), ('targets', (.35, .56), .32, 32.5)]:
            cls.events.append({'EventType': 'NativeParticipantCamera', 'NativeParticipantCamera_UnitId': 7777,
                'NativeParticipantCamera_Frame': 12, 'NativeParticipantCamera_Shot': shot,
                'NativeParticipantCamera_CenterX': xy[0], 'NativeParticipantCamera_CenterY': xy[1],
                'NativeParticipantCamera_HeightFraction': height, 'NativeParticipantCamera_MaxFocalLength': lens})
        cls.ops = [{'asset': 'shell', 'export': identifier, 'set': event} for identifier, event in zip(cls.identifiers, cls.events)]
        result = cls.patch(cls.ops)
        if result.returncode: raise AssertionError(result.stdout + result.stderr)

    def test_native_caster_and_all_selected_targets_round_trip(self):
        decoded = self.dump('seqdump'); document = self.dump('tojson')
        for identifier, event in zip(self.identifiers, self.events):
            self.assertEqual(next(v for k, v in decoded.items() if k.startswith(identifier+':')), event)
            fn = document['Exports'][int(identifier)-1]; code = fn['ScriptBytecode']
            imports = document['Imports']; named = lambda node: imports[-node['StackNode']-1]['ObjectName']
            calls = [node for node in self.walk(code) if 'StackNode' in node]
            names = [named(node) for node in calls]
            self.assertEqual(names.count('GetComponentBounds'), 1)
            self.assertNotIn('GetAllActorsOfClass', names)
            self.assertEqual('GetBattleUnitByUnitIdWithVision' in names, event['NativeParticipantCamera_Shot'] == 'caster')
            self.assertEqual(names.count('GetViewportSize'), 1)
            self.assertIn('GetForwardVector', names); self.assertIn('GetRightVector', names); self.assertIn('GetUpVector', names)
            self.assertNotIn('K2_SetActorLocation', names)
            native_events = [node for node in code if self.kind(node) == 'EX_LocalVirtualFunction']
            self.assertEqual(len(native_events), 2)
            pan, zoom = [node['Parameters'][1]['Value'] for node in native_events]
            self.assertEqual(pan[0]['Value'], 3)  # CameraSetViewLocation, absolute actor coordinates.
            self.assertEqual(zoom[0]['Value'], 6)  # CameraSetZoomInOut, native lens interpolation.
            self.assertEqual(self.kind(pan[13]), 'EX_False')  # RelativeLocation disabled.
            self.assertEqual(pan[9]['Value'], 12)
            self.assertEqual(self.kind(zoom[32]), 'EX_False')  # RelativeValue disabled.
            self.assertEqual(named(zoom[27]), 'Conv_DoubleToFloat')
            self.assertEqual(sum(map(self.vm_size, code)), fn['ScriptBytecodeSize'])
            offsets = set(); position = 0
            for node in code:
                offsets.add(position); position += self.vm_size(node)
            for node in self.walk(code):
                if self.kind(node) in ('EX_JumpIfNot', 'EX_Jump'): self.assertIn(node['CodeOffset'], offsets)
                if self.kind(node) == 'EX_Context_FailSilent': self.assertEqual(node['Offset'], self.vm_size(node['ContextExpression']))
                if self.kind(node) == 'EX_LocalVariable':
                    self.assertEqual(node['Variable']['New']['ResolvedOwner'], int(identifier))
            if event['NativeParticipantCamera_Shot'] == 'targets':
                selected = [node for node in self.walk(code) if self.kind(node) == 'EX_ArrayGetByRef']
                self.assertTrue(selected)
                self.assertTrue(all(node['ArrayIndex']['Variable']['New']['Path'] == ['FFBE_Framing_Index'] for node in selected))
                self.assertTrue(all(node['ArrayVariable']['ContextExpression']['Variable']['New']['Path'] == ['m_TargetUnitList'] for node in selected))

    def test_invalid_inputs_fail_without_changing_package(self):
        before = self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()
        for key, value in [('UnitId', True), ('Shot', 'all_enemies'), ('Frame', 0), ('Frame', 121),
                           ('CenterX', 0), ('CenterY', float('nan')), ('HeightFraction', True),
                           ('MaxFocalLength', 81), ('CenterY', .15)]:
            op = deepcopy(self.ops[0]); op['set']['NativeParticipantCamera_' + key] = value
            with self.subTest(key=key, value=value):
                result = self.patch([op]); self.assertNotEqual(result.returncode, 0)
        self.assertEqual(before, (self.asset.read_bytes(), self.asset.with_suffix('.uexp').read_bytes()))

    def test_changed_native_projection_formula_is_rejected(self):
        asset = self.work/'bad-projection.uasset'
        for suffix in ('.uasset', '.uexp', '.ubulk'):
            if self.asset.with_suffix(suffix).exists(): shutil.copy2(self.asset.with_suffix(suffix), asset.with_suffix(suffix))
        payload = asset.with_suffix('.uexp'); raw = payload.read_bytes()
        marker = b'\x37' + struct.pack('<d', 100.)
        self.assertEqual(raw.count(marker), 2)
        payload.write_bytes(raw.replace(marker, b'\x37' + struct.pack('<d', 101.), 1))
        result = self.command('seqdump', asset, self.work/'bad-projection.json')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Malformed NativeParticipantCamera', result.stdout + result.stderr)

    def test_actual_cooked_math_frames_caster_and_every_target_corner(self):
        document = self.dump('tojson')
        def xyz(value): return dict(zip(('X', 'Y', 'Z'), value))
        def actor(center, extent): return {'m_pSsPlayerComponent': {'origin': xyz(center), 'extent': xyz(extent)}}
        caster = actor((0, 100, 250), (20, 100, 220))
        for yaw, viewport, targets in [(0, (1280, 720), [actor((0, -300, 300), (35, 170, 280))]),
            (27, (2560, 1080), [actor((100, -850, 300), (70, 180, 280)), actor((-120, 650, 500), (100, 300, 470))]),
            (-12, (720, 1280), [actor((0, -3500, 2600), (120, 1000, 2500)), actor((200, 3000, 700), (70, 180, 650))])]:
            pitch = -8.; p, y = math.radians(pitch), math.radians(yaw)
            forward = np.array([math.cos(p)*math.cos(y), math.cos(p)*math.sin(y), math.sin(p)])
            right = np.array([-math.sin(y), math.cos(y), 0.]); up = np.cross(forward, right)
            origin = -2500 * forward
            cine = {'location': xyz(origin), 'rotation': {'Pitch': pitch, 'Yaw': yaw, 'Roll': 0},
                    'Filmback': {'SensorWidth': 23.76}, 'LensSettings': {'MinFocalLength': 4., 'MaxFocalLength': 200.}}
            camera = {'Cine': cine, 'location': xyz(origin + np.array([3., 2., 1.]))}
            for i, selected in enumerate(([caster], targets)):
                fn = document['Exports'][int(self.identifiers[i])-1]
                vm = CameraVM(document, fn, self.vm_size, caster, targets, camera, viewport)
                emitted = vm.run(); self.assertEqual(len(emitted), 2)
                # Native actor-position compensation must preserve the component pose.
                camera_point = vector(emitted[0][8]) - np.array([3., 2., 1.])
                focal = emitted[1][27]
                self.assertGreaterEqual(focal, 8.); self.assertLessEqual(focal, (52., 32.5)[i])
                projected = []
                for item in selected:
                    sprite = item['m_pSsPlayerComponent']
                    for sign in itertools.product((-1, 1), repeat=3):
                        point = vector(sprite['origin']) + vector(sprite['extent']) * sign - camera_point
                        depth = point @ forward; self.assertGreater(depth, 0)
                        x = .5 + (point @ right) * focal / (23.76 * depth)
                        sy = .5 - (point @ up) * focal * viewport[0] / (23.76 * depth * viewport[1])
                        projected.append((x, sy))
                self.assertTrue(all(.015 < x < .985 and .015 < sy < .985 for x, sy in projected), projected)
                center = np.array([vm.values['FFBE_Framing_MinR'] + vm.values['FFBE_Framing_MaxR'],
                                   vm.values['FFBE_Framing_MinU'] + vm.values['FFBE_Framing_MaxU'],
                                   vm.values['FFBE_Framing_MinF'] + vm.values['FFBE_Framing_MaxF']]) * .5
                world_center = center[0]*right + center[1]*up + center[2]*forward - camera_point
                expected = ((.55, .52), (.35, .56))[i]
                self.assertAlmostEqual(.5 + (world_center @ right) * focal / (23.76 * (world_center @ forward)), expected[0])
                self.assertAlmostEqual(.5 - (world_center @ up) * focal * viewport[0] / (23.76 * (world_center @ forward) * viewport[1]), expected[1])

    def test_no_targets_or_invalid_viewport_emit_no_camera_mutation(self):
        document = self.dump('tojson'); fn = document['Exports'][int(self.identifiers[1])-1]
        cine = {'location': {'X': -2500, 'Y': 0, 'Z': 0}, 'rotation': {'Pitch': 0, 'Yaw': 0, 'Roll': 0},
                'Filmback': {'SensorWidth': 23.76}, 'LensSettings': {'MinFocalLength': 4., 'MaxFocalLength': 200.}}
        camera = {'Cine': cine, 'location': cine['location']}
        for viewport in ((1280, 720), (0, 720), (1280, 0)):
            self.assertEqual(CameraVM(document, fn, self.vm_size, None, [], camera, viewport).run(), [])


if __name__ == '__main__': unittest.main()
