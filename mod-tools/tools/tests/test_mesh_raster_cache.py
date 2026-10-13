"""Pixel identity against the frozen original, including real animated UVs."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools/ffbe_effects')]
import ibmb
import uv_sampling

spec = importlib.util.spec_from_file_location('mesh_raster_reference', Path(__file__).parent/'fixtures/mesh_raster_reference.py')
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)
SOURCE = ROOT/'build/ffbe_cpk/effects_dec'


def overlap_mesh():
    return {'vertices':[(-1.,-1.,0.),(1.,-1.,0.),(0.,1.,0.),
                        (-.8,-1.,1.),(1.,-.8,1.),(0.,1.,1.)],
            'uvs':[(0.,0.),(1.,0.),(.5,1.)]*2,
            'colors':[(1.,.2,.4,.3)]*3+[(.3,1.,.6,.6)]*3,
            'indices':[0,1,2,3,4,5]}


class MeshRasterCache(unittest.TestCase):
    def assert_pixels(self, mesh, texture, cache, *, rx=0., ry=0., sampler=None):
        old = reference.rasterise_mesh(mesh, texture, rx, ry, size=48, texture_sampler=sampler)
        new = ibmb.rasterise_mesh(mesh, texture, rx, ry, size=48,
                                  texture_sampler=sampler, geometry_cache=cache)
        np.testing.assert_array_equal(new, old)
        np.testing.assert_array_equal((np.clip(new,0,1)*255).astype(np.uint8),
                                      (np.clip(old,0,1)*255).astype(np.uint8))

    def test_ordered_transparent_overlaps_and_changed_texture_are_identical(self):
        mesh = overlap_mesh()
        cache = ibmb.MeshRasterPlanCache(max_bytes=2*1024*1024)
        rng = np.random.default_rng(12345)
        for _ in range(3):
            self.assert_pixels(mesh, rng.random((9,11,4),dtype=np.float32), cache)
        self.assertEqual(cache.hits,2)
        self.assertEqual(cache.misses,1)

    def test_actual_stone_circle_uv_variants_keep_every_float(self):
        path = SOURCE/'bm_2006_stone1.bmb'
        if not path.is_file(): self.skipTest('Local source Stone is unavailable')
        effect = ibmb.parse(str(path))
        baked = ibmb.bake(effect,max_frames=200,max_particles=4096,seed=12345,canonical_variation=True)
        states = [json.loads(s[9:]) for s in baked['textures'] if s.startswith('nativeuv:')]
        circle = [s for s in states if s.get('model') == 'model_circle002_48pl_out_alpha']
        self.assertGreater(len(circle),5)
        mesh = ibmb.parse_m3r(str(SOURCE/(circle[0]['model']+'.m3r')))
        texture = np.asarray(Image.open(SOURCE/(circle[0]['texture']+'.png')).convert('RGBA'),dtype=np.float32)/255.
        cache = ibmb.MeshRasterPlanCache(max_bytes=8*1024*1024)
        for state in [circle[0],circle[1],circle[len(circle)//2],circle[-1]]:
            def sampler(u,v,color,state=state):
                color = color*np.asarray([*state['color'],1.],dtype=np.float32)
                return uv_sampling.shade(texture,None,u,v,state['channels'],state['material'],color)
            self.assert_pixels(mesh,texture,cache,rx=state['tilt'][0],ry=state['tilt'][1],sampler=sampler)
        self.assertEqual(cache.misses,1)
        self.assertEqual(cache.hits,3)

    def test_geometry_content_and_tilt_changes_invalidate(self):
        mesh = overlap_mesh()
        tex = np.ones((2,2,4),dtype=np.float32)
        cache = ibmb.MeshRasterPlanCache()
        self.assert_pixels(mesh,tex,cache)
        for field, replacement in [('vertices',(0.,0.,3.)),('uvs',(.7,.2)),('colors',(.2,.3,.4,.5))]:
            changed = deepcopy(mesh)
            changed[field][0] = replacement
            self.assert_pixels(changed,tex,cache)
        changed = deepcopy(mesh)
        changed['indices'] = [3,4,5,0,1,2]
        self.assert_pixels(changed,tex,cache)
        self.assert_pixels(mesh,tex,cache,rx=.125,ry=.25)
        self.assertEqual(cache.misses,6)

    def test_lru_byte_limit_and_oversized_streaming(self):
        mesh = overlap_mesh()
        tex = np.ones((2,2,4),dtype=np.float32)
        cache = ibmb.MeshRasterPlanCache(max_bytes=160000,max_entries=2)
        for tilt in range(8):
            self.assert_pixels(mesh,tex,cache,rx=tilt*2.)
            self.assertLessEqual(cache.bytes,cache.max_bytes)
            self.assertLessEqual(len(cache.plans),2)
        tiny = ibmb.MeshRasterPlanCache(max_bytes=1)
        self.assert_pixels(mesh,tex,tiny)
        self.assertEqual(tiny.bytes,0)
        self.assertEqual(len(tiny.plans),0)


if __name__ == '__main__': unittest.main()
