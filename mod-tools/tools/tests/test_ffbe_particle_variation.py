"""Native-range fixed variation must preserve a particle branch's identity."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ffbe_effects'))
import ibmb


def node(index, **settings):
    return ibmb.Chunk(index, 0, ibmb.T_NODE, 704, **settings)


def sprite(index, **settings):
    return ibmb.Chunk(index, 0, ibmb.T_EMIT_B, 1840, res1='fixture.png', life=10,
                      scale_mode=2, base_scale=[1., 1., 1.], **settings)


def effect(root, duration=20):
    return ibmb.Effect('fixture.bmb', (1, 1, 3, 1), duration, 1., [], [], [],
                       [root], [root], 0, {})


class CanonicalTransformVariation(unittest.TestCase):
    def test_scalar_alpha_variation_preserves_its_dimension_and_range(self):
        owner = ibmb._CanonicalVariation(12345, 'fixture.bmb')
        samples = [owner.instance((i,)).sample('texture1_alpha', [.5], [.25]) for i in range(100)]
        self.assertTrue(all(len(row) == 1 and .25 <= row[0] < .75 for row in samples))
        self.assertEqual(samples[0], owner.instance((0,)).sample('texture1_alpha', [.5], [.25]))

    def test_native_ranges_use_full_spread_and_are_stable(self):
        owner = ibmb._CanonicalVariation(12345, 'fixture.bmb')
        values = [owner.instance((i,)).sample('rotation_base', [0.] * 3, [10.] * 3)
                  for i in range(100)]
        self.assertTrue(all(-10. <= value < 10. for row in values for value in row))
        self.assertLess(min(value for row in values for value in row), -5.)
        self.assertGreater(max(value for row in values for value in row), 5.)
        same = ibmb._CanonicalVariation(12345, 'another/directory/fixture.bmb')
        self.assertEqual(values[0], same.instance((0,)).sample('rotation_base', [0.] * 3, [10.] * 3))
        other = ibmb._CanonicalVariation(12346, 'fixture.bmb')
        self.assertNotEqual(values[0], other.instance((0,)).sample('rotation_base', [0.] * 3, [10.] * 3))

    def test_branch_children_share_parent_but_parent_siblings_differ(self):
        parent, child_a, child_b = node(10), node(20), node(30)
        owner = ibmb._CanonicalVariation(12345, 'fixture.bmb')
        sample = lambda chain, keys, index, copy=0: ibmb._node_variation(owner, chain, keys, index, copy)
        a = sample([parent, child_a], [0, 0], 0)
        b = sample([parent, child_b], [0, 7], 0)
        self.assertIs(a, b)
        self.assertIsNot(a, sample([parent, child_a], [1, 0], 0))
        self.assertIsNot(a, sample([parent, child_a], [0, 0], 0, 1))
        self.assertIsNot(sample([parent, child_a], [0, 0], 1),
                         sample([parent, child_a], [0, 1], 1))
        self.assertIsNone(ibmb._node_variation(owner, [parent], None, 0, 0))

    def test_constant_velocity_acceleration_keep_birth_samples(self):
        chunk = node(0, translation_mode=4, translation_base=[10.] * 3,
                     translation_variance=[3.] * 3, translation_velocity=[-2.] * 3,
                     translation_velocity_variance=[.5] * 3,
                     translation_acceleration=[.25] * 3,
                     translation_acceleration_variance=[.1] * 3)
        sample = ibmb._CanonicalVariation(12345, 'fixture.bmb').instance((0,))
        at0 = ibmb._native_translation(chunk, 0., 0., variation=sample)
        at1 = ibmb._native_translation(chunk, .1, 1., variation=sample)
        at2 = ibmb._native_translation(chunk, .2, 2., variation=sample)
        for axis in range(3):
            acceleration = at2[axis] - 2 * at1[axis] + at0[axis]
            velocity = at1[axis] - at0[axis] - acceleration * .5
            self.assertTrue(7. <= at0[axis] < 13.)
            self.assertTrue(-2.5 <= velocity < -1.5)
            self.assertTrue(.15 <= acceleration < .35)
        self.assertEqual(at1, ibmb._native_translation(chunk, .1, 1., variation=sample))

    def test_uniform_scale_uses_only_x_and_clamps_only_base(self):
        chunk = node(0, scale_mode=18, node_scale=[-3., 999., 999.],
                     scale_variance=[.1, 888., 888.], scale_velocity=[2., -999., -999.],
                     scale_velocity_variance=[.1, 888., 888.],
                     scale_acceleration=[-.25, 999., 999.],
                     scale_acceleration_variance=[.1, 888., 888.])
        sample = ibmb._CanonicalVariation(12345, 'fixture.bmb').instance((0,))
        self.assertEqual([0.] * 3, ibmb._native_scale(chunk, 0., 0., sample))
        at1 = ibmb._native_scale(chunk, .1, 1., sample)
        at2 = ibmb._native_scale(chunk, .2, 2., sample)
        self.assertEqual(at1, [at1[0]] * 3)
        self.assertEqual(at2, [at2[0]] * 3)
        self.assertLess(at2[0] - 2 * at1[0], 0.)

    def test_active_curves_do_not_consume_dormant_variance(self):
        curve = ibmb.Curve(3, 0, [(0., [1., 2., 3.], [1, 1, 1])])
        chunk = node(0, translation_mode=5, rotation_mode=4, scale_mode=5,
                     translation_variance=[100.] * 3, rotation_variance=[100.] * 3,
                     scale_variance=[100.] * 3,
                     slots={ibmb.SLOT_TRANSLATE: curve, ibmb.SLOT_ROTATE: curve, ibmb.SLOT_SCALE: curve})
        sample = ibmb._CanonicalVariation(12345, 'fixture.bmb').instance((0,))
        self.assertEqual([1., 2., 3.], ibmb._native_translation(chunk, .5, 5., variation=sample))
        self.assertEqual([1., 2., 3.], ibmb._native_rotation(chunk, .5, 5., sample))
        self.assertEqual([1., 2., 3.], ibmb._native_scale(chunk, .5, 5., sample))
        self.assertEqual({}, sample.cache)
        chunk.rotation_mode = 5
        self.assertIsNone(ibmb._native_rotation(chunk, .5, 5., sample))

    def test_bake_is_opt_in_reproducible_and_copies_differ(self):
        root = node(0, emit_count=2, rotation_mode=1, rotation_base=[0.] * 3,
                    rotation_variance=[0., 0., 90.], children=[sprite(1)])
        source = effect(root)
        legacy = ibmb.bake(source)
        self.assertEqual(legacy, ibmb.bake(source, canonical_variation=False))
        self.assertEqual(1, len({part['rot'] for part in legacy['frames'][0]}))
        varied = ibmb.bake(source, canonical_variation=True, repeat=2)
        self.assertEqual(varied, ibmb.bake(source, canonical_variation=True, repeat=2))
        self.assertEqual(4, len({part['rot'] for part in varied['frames'][0]}))
        self.assertEqual(varied['frames'][0], varied['frames'][9])

    def test_unsupported_generation_is_reported_without_false_identity(self):
        source = effect(node(0, emit_mode=1, children=[sprite(1)]))
        result = ibmb.bake(source, canonical_variation=True)
        self.assertEqual([1], result['canonicalVariation']['unsupportedLineageEmitters'])

    def test_emitter_delay_preserves_parent_clock_and_particle_lifetime(self):
        root = node(0, delay=2, translation_mode=3, translation_base=[0.] * 3,
                    translation_velocity=[1., 0., 0.], children=[sprite(1, emitter_delay=5)])
        result = ibmb.bake(effect(root), canonical_variation=True)
        self.assertTrue(all(not frame for frame in result['frames'][:7]))
        self.assertEqual([5., 0., 0.], result['frames'][7][0]['pos'])
        self.assertTrue(result['frames'][16])
        self.assertFalse(result['frames'][17])

    def test_integer_delay_uses_half_open_native_range(self):
        owner = ibmb._CanonicalVariation(12345, 'fixture.bmb')
        delays = [owner.instance((i,)).delay(10, 3) for i in range(100)]
        self.assertEqual(set(range(7, 13)), set(delays))
        self.assertTrue(all(isinstance(value, int) for value in delays))
        self.assertEqual(0, owner.instance(('negative',)).delay(-10, 1))


class RainFinaSourceVariation(unittest.TestCase):
    def test_radial_fans_retain_all_fourteen_distinct_instances(self):
        source = Path(__file__).resolve().parents[2] / 'build/ffbe_cpk/effects_dec/lb_100032707_FFBE_NV_rainking_and_3rdfina_front_unit.bmb'
        if not source.is_file():
            self.skipTest('Private source export is not available')
        parsed = ibmb.parse(str(source))
        varied = ibmb.bake(parsed, max_frames=286, max_particles=4096, canonical_variation=True)
        means = ibmb.bake(parsed, max_frames=151, max_particles=4096)
        self.assertEqual([], varied['canonicalVariation']['unsupportedLineageEmitters'])
        for emitter in (85, 90):
            for frame in (150, 225, 285):
                parts = [p for p in varied['frames'][frame] if p['emitter'] == emitter]
                self.assertEqual(14, len(parts))
                self.assertEqual(14, len({(tuple(p['pos']), p['rot']) for p in parts}))
                self.assertGreater(len({p['rot'] for p in parts}), 1)
            self.assertEqual(1, len({(tuple(p['pos']), p['rot']) for p in means['frames'][150]
                                     if p['emitter'] == emitter}))
        # White flash: parent84 + delay188 =272; gold:84+200=284.
        # Both alpha curves start at zero, so first visible samples are+1.
        for emitter, delay, birth in ((80, 188, 272), (42, 200, 284)):
            flash = next(c for c in parsed.chunks if c.index == emitter)
            self.assertEqual(delay, flash.emitter_delay)
            self.assertEqual([0.], flash.alpha_curve.sample(0.))
            self.assertFalse(any(p['emitter'] == emitter for p in varied['frames'][birth]))
            self.assertTrue(any(p['emitter'] == emitter for p in varied['frames'][birth + 1]))


if __name__ == '__main__':
    unittest.main()
