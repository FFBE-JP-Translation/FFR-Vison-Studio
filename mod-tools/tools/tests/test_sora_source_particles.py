"""Real source regression for the opaque orbs caused by collapsed star instances."""
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/ffbe_effects'))
import ibmb


class SoraSourceParticles(unittest.TestCase):
    def test_star_and_glow_pairs_scatter_without_changing_source_blending(self):
        source=ROOT/'build/ffbe_cpk/effects_dec/KH_star_hit_eff_KingdomChain.bmb'
        if not source.is_file():
            self.skipTest('local FFBE source fixture unavailable')
        effect=ibmb.parse(str(source))
        emitters={emitter.index:emitter for emitter in effect.emitters()}
        # These source emitters intentionally use normal alpha compositing.
        # Turning them additive would hide the overlap without repairing it.
        self.assertEqual(emitters[21].blend,1)
        self.assertEqual(emitters[23].blend,1)
        baked=ibmb.bake(effect,max_frames=12,canonical_variation=True)
        pairs={emitter:[part for part in baked['frames'][10] if part['emitter']==emitter]
               for emitter in (21,23)}
        positions={emitter:{tuple(part['pos']) for part in parts}
                   for emitter,parts in pairs.items()}
        self.assertEqual(len(pairs[21]),12)
        self.assertEqual(len(pairs[23]),12)
        self.assertEqual(len(positions[21]),12)
        self.assertEqual(positions[21],positions[23])
        self.assertTrue(all(part['blend']=='normal' for parts in pairs.values() for part in parts))


if __name__=='__main__':
    unittest.main()
