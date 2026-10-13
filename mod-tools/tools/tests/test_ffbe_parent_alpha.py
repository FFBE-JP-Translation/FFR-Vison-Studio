"""Native Null opacity and independently aged parent/child instances."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb


def curve(*points):
    return ibmb.Curve(1, 0, [(t, [value], [1]) for t, value in points])


def chunk(index=0, mode=0, base=1., **kwargs):
    return ibmb.Chunk(index, 0, 0, 704, quad_alpha_mode=mode,
                      quad_alpha_base=base, **kwargs)


class NativeParentAlpha(unittest.TestCase):
    def fixture(self, suffix):
        path = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec' / (
            'lb_100032707_FFBE_NV_rainking_and_3rdfina_' + suffix + '.bmb')
        if not path.exists():
            self.skipTest('local source fixture unavailable')
        return ibmb.parse(str(path))

    def test_zero_selector_is_not_the_absent_module(self):
        # Native MakeVertexModuleOf table 0x38F25B0: mode0=NULL;
        # mode1=alpha::make_vertex::Zero at 0x28B37DC (writes float0).
        c = chunk(mode=0, base=.8, alpha_curve=curve((0., .7), (1., .4)))
        self.assertEqual(1., ibmb._native_alpha(c, .5))
        c.quad_alpha_mode = 1
        self.assertEqual(0., ibmb._native_alpha(c, .5))
        c.quad_alpha_mode = 2
        self.assertEqual(.8, ibmb._native_alpha(c, .5))

    def test_constant_variance_is_per_instance_and_clamped(self):
        c = chunk(mode=2, base=.9, alpha_variance=.6)
        samples = ibmb._CanonicalVariation(12345, 'alpha-fixture')
        a, b = samples.instance((0,)), samples.instance((1,))
        first = ibmb._native_alpha(c, 0., a)
        self.assertEqual(first, ibmb._native_alpha(c, .95, a))
        self.assertNotEqual(first, ibmb._native_alpha(c, .5, b))
        self.assertGreaterEqual(first, .3)
        self.assertLessEqual(first, 1.)
        self.assertEqual(1., ibmb._native_alpha(chunk(mode=2, base=1.8), .5))
        self.assertEqual(0., ibmb._native_alpha(chunk(mode=2, base=-.2), .5))

    def test_curve_clamps_value_and_partial_domain(self):
        c = chunk(mode=3, alpha_curve=curve((.2, 1.4), (.8, -.1)))
        self.assertEqual(1., ibmb._native_alpha(c, 0.))
        self.assertEqual(0., ibmb._native_alpha(c, 2.))

    def test_random_and_offset_curve_fallback_is_reported(self):
        chunks = [chunk(i, mode=i, alpha_curve=curve((0., .2), (1., .8)))
                  for i in range(7)]
        audit = ibmb._alpha_fidelity(chunks + chunks)
        self.assertEqual([0, 1, 2, 3], audit['supportedLocalModes'])
        self.assertEqual([4, 5, 6], [entry['mode'] for entry in audit['fallbacks']])
        self.assertAlmostEqual(.5, ibmb._native_alpha(chunks[4], .5))
        unavailable = ibmb._alpha_fidelity([chunk(8, mode=3)])
        self.assertEqual('selected-alpha-curve-unavailable', unavailable['fallbacks'][0]['reason'])

    def test_native_streak_parent_curves_are_parsed_with_local_lifetimes(self):
        for suffix, parents in [('back_center', (6, 10)),
                                ('front_center', (3, 7))]:
            eff = self.fixture(suffix)
            for index in parents:
                c = eff.chunks[index]
                self.assertEqual(3, c.quad_alpha_mode)
                self.assertEqual(25, c.duration)
                self.assertEqual(1, c.alpha_curve.dim)
                self.assertEqual(0., c.alpha_variance)
                self.assertEqual(3, c.to_dict()['globalAlphaMode'])
                # Frame30 is localage15 for the vertical streak parents.
                # The authored plateau rules out inventing a midlife fade.
                self.assertEqual(1., ibmb._native_alpha(c, 15 / 25))
                self.assertAlmostEqual(.10480389, ibmb._native_alpha(c, 1 / 25), places=6)
                self.assertAlmostEqual(.11161156, ibmb._native_alpha(c, 24 / 25), places=6)

    def test_null_inheritance_interpolates_and_can_reset_ancestor_alpha(self):
        parent = chunk(0, mode=2, base=.2)
        child = chunk(1, mode=2, base=.8, parent_alpha_weight=1.)
        self.assertAlmostEqual(.2, ibmb._node_alpha([parent, child], 3, 10))
        child.parent_alpha_weight = 0.
        self.assertAlmostEqual(.8, ibmb._node_alpha([parent, child], 3, 10))
        child.parent_alpha_weight = .25
        self.assertAlmostEqual(.65, ibmb._node_alpha([parent, child], 3, 10))
        child.quad_alpha_mode = 0
        child.parent_alpha_weight = 0.
        self.assertEqual(1., ibmb._node_alpha([parent, child], 3, 10))

    def test_drawable_mod_and_lerp_and_native_zero_weight_bypass(self):
        combine = ibmb._combine_drawable_alpha
        self.assertAlmostEqual(.1, combine(.4, .25, 1., 1))
        self.assertAlmostEqual(.25, combine(.4, .25, 1., 0))
        self.assertAlmostEqual(.05, combine(.4, .25, .5, 1))
        self.assertAlmostEqual(.325, combine(.4, .25, .5, 0))
        # AssignModule skips the blend module entirely for abs(weight)<1e-6.
        self.assertEqual(.4, combine(.4, .25, 0., 1))
        self.assertEqual(.4, combine(.4, .25, .0000001, 1))

    def test_parent_clock_is_not_reset_by_child_birth_or_repetition(self):
        parent = chunk(0, mode=3, duration=20, alpha_curve=curve((0., 0.), (1., 1.)))
        child = chunk(1, mode=0, duration=10, parent_alpha_weight=1.)
        # Same child localage1, but distinct parent instances have ages11/6.
        self.assertAlmostEqual(.55, ibmb._node_alpha([parent, child], 16, 40, [5., 15.]))
        self.assertAlmostEqual(.3, ibmb._node_alpha([parent, child], 16, 40, [10., 15.]))

    def test_source_streak_fades_are_inherited_without_retiming_midpoint(self):
        eff = self.fixture('back_center')
        ids = (7, 8, 9, 11, 12, 13)
        for index in ids:
            em = eff.chunks[index]
            self.assertEqual((1., 1), (em.parent_alpha_weight, em.parent_alpha_operation))
        baked = ibmb.bake(eff, max_frames=41, max_particles=256, canonical_variation=True)
        def alpha(frame, index):
            return next((p['alpha'] for p in baked['frames'][frame] if p['emitter'] == index), 0.)
        for index in ids:
            self.assertEqual(0., alpha(15, index))
            self.assertAlmostEqual(.1048, alpha(16, index), places=4)
            self.assertEqual(1., alpha(30, index))
            self.assertAlmostEqual(.1116, alpha(39, index), places=4)
            self.assertEqual(0., alpha(40, index))
        self.assertEqual([], baked['alphaFidelity']['fallbacks'])
        # Changing a local selector to explicit Zero must affect the emitted
        # data; tests of the parser alone would miss the former bake bypass.
        eff.chunks[7].quad_alpha_mode = 1
        zero = ibmb.bake(eff, max_frames=31, max_particles=256)
        self.assertFalse(any(p['emitter'] == 7 for p in zero['frames'][30]))
        self.assertTrue(any(p['emitter'] == 8 for p in zero['frames'][30]))

    def test_source_null_can_ignore_its_local_curve(self):
        eff = self.fixture('front_center')
        ctx = next(c for c in ibmb._collect(eff) if c.emitter.index == 14)
        node = eff.chunks[13]
        self.assertEqual(1., node.parent_alpha_weight)
        spawn, starts, _ = ibmb._regular_instances(ctx.chain, 20)[0]
        # Null13's local curve ends at0, but its D4=1 selects parent alpha.
        self.assertEqual(0., ibmb._native_alpha(node, 1.))
        self.assertEqual(1., ibmb._node_alpha(ctx.chain, starts[-1] + node.duration,
                                           eff.duration, starts))


if __name__ == '__main__':
    unittest.main()
