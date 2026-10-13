"""A real looping BMB cannot schedule UINT_MAX frames during catalog conversion."""
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from ffbe_effects import prepare_vision as prepare


class UnboundedSourceLifetime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.name='area_effect_fieldchange_front.bmb'
        cls.source=prepare.SOURCES/cls.name
        if not cls.source.is_file():
            raise unittest.SkipTest('Local decoded FFBE field-effect BMB required')
        cls.effect=prepare.ibmb.parse(str(cls.source))
        if cls.effect.duration != 0xffffffff:
            raise AssertionError('The real source fixture no longer contains its UINT_MAX lifetime')

    def test_real_looping_effect_requires_owning_action_window_before_any_bake(self):
        with patch.object(prepare.ibmb,'bake',side_effect=AssertionError('Unbounded bake must not start')):
            with self.assertRaisesRegex(ValueError,'unbounded source lifetime requires a finite'):
                prepare.bake_source(self.name,SimpleNamespace(missing=set()))

    def test_finite_window_bounds_real_primary_and_reference_simulation(self):
        # Exercise the real source parser and both real simulations. Pixel
        # rendering is irrelevant to lifetime safety and is intentionally tiny.
        real_bake=prepare.ibmb.bake
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(prepare,'CACHE',Path(directory)), \
             patch.object(prepare.ibmb,'bake',wraps=real_bake) as bake, \
             patch.object(prepare.render,'build_doc',return_value={
                 'fps':60,'frameCount':3,'pixelsPerUnit':2.4,'textures':[],
                 'frames':[[],[],[]]}):
            _,audit=prepare.bake_source(self.name,SimpleNamespace(missing=set()),
                max_frames=3,particle_budget=2,canonical_variation=True)
            self.assertEqual(2,bake.call_count)
            self.assertEqual([3,3],[call.kwargs['max_frames'] for call in bake.call_args_list])
            self.assertEqual([2,8],[call.kwargs['max_particles'] for call in bake.call_args_list])
            self.assertEqual(0xffffffff,audit['declaredFrames'])
            self.assertEqual(3,audit['maxFrames'])
            self.assertEqual(3,audit['actionLifetimeFrames'])

    def test_invalid_explicit_windows_never_reach_simulator(self):
        with patch.object(prepare.ibmb,'bake',side_effect=AssertionError('Invalid bake must not start')):
            for value in (0,-1,True,3.5):
                with self.subTest(value=value),self.assertRaisesRegex(ValueError,'positive integer'):
                    prepare.bake_source(self.name,SimpleNamespace(missing=set()),max_frames=value)


if __name__=='__main__':unittest.main()
