"""Regressions exposed by the recorded Crimson Judgment limit burst."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ffbe_effects'))
import ibmb


class Projection(unittest.TestCase):
    def test_ground_quad_rotated_upright_occupies_full_texture(self):
        mesh = {'vertices':[(-1,0,-1),(-1,0,1),(1,0,1),(1,0,-1)],
                'uvs':[(0,0),(0,1),(1,1),(1,0)], 'indices':[0,1,2,0,2,3],
                'bounds':[-1,0,-1,1,0,1]}
        image = ibmb.rasterise_mesh(mesh, np.ones((4,4,4),dtype=np.float32), rx=90, size=64)
        self.assertEqual((64,64,4), image.shape)
        self.assertGreater(np.count_nonzero(image[:,:,3]>.99), 4000)
        points = ibmb.project_mesh_vertices(mesh,90,0)
        self.assertAlmostEqual(2, max(p[1] for p in points)-min(p[1] for p in points))

    def test_rain_fina_partial_scale_domains_are_preserved(self):
        path=Path(__file__).resolve().parents[2]/'build/ffbe_cpk/effects_dec/lb_100032707_FFBE_NV_rainking_and_3rdfina_front_unit.bmb'
        if not path.is_file(): self.skipTest('Local source fixture unavailable')
        effect=ibmb.parse(str(path))
        self.assertAlmostEqual(.81145513,effect.chunks[40].slots[4].keys[-1][0])
        self.assertAlmostEqual(206.007507,ibmb._native_scale(effect.chunks[40],1,200)[0],places=4)
        self.assertAlmostEqual(.733762,ibmb._native_scale(effect.chunks[54],0,0)[0],places=5)
        baked=ibmb.bake(effect,max_frames=131,max_particles=4096)
        disc=next(p for p in baked['frames'][130] if p['emitter']==55)
        self.assertGreater(abs(disc['scale'][0]),200)
        self.assertGreater(abs(disc['scale'][1]),200)


if __name__=='__main__': unittest.main()
