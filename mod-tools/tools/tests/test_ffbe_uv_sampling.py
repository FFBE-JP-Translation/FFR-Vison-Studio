"""Pixel-space regressions for native texture motion, separate from geometry."""
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'ffbe_effects'))
import uv_sampling as uv


def state(translation=(0, 0, 0), rotation=(0, 0, 0), scale=(1, 1, 1)):
    return {'translation': translation, 'rotation': rotation,
            'scaling': scale, 'pivot': [.5, .5, .5]}


class NativeUvPixels(unittest.TestCase):
    def test_native_executed_srt_order(self):
        # GL9.1.0 ARM64 TransformSRT, executed native fixture offset+basis;
        # native FRECPE differs from exact reciprocal by approximately .2%.
        points = np.asarray([0., 1., 0.]), np.asarray([0., 0., 1.])
        u, v = uv.coordinates(*points, state((.1,.2,0),(0,0,45),(.5,2,1)))
        np.testing.assert_allclose(u, [-1.334887, .0765643, .0765648], atol=.004)
        np.testing.assert_allclose(v, [.4647138, .1118508, .8175766], atol=.001)

    def test_positive_rotation_moves_top_left_clockwise(self):
        u, v = uv.coordinates(np.array([1.]), np.array([0.]), state(rotation=(0,0,90)))
        np.testing.assert_allclose([u[0],v[0]], [0,0], atol=1e-6)

    def test_repeat_scroll_is_continuous_and_changes_pixels(self):
        texture = np.arange(4*4*4, dtype=np.float32).reshape(4,4,4)/63
        u,v = uv.grid(4,4)
        before = uv.channel_sample(texture,u,v,state())
        after = uv.channel_sample(texture,u,v,state((.25,0,0)))
        np.testing.assert_allclose(before,texture)
        np.testing.assert_allclose(after,np.roll(texture,1,axis=1))
        np.testing.assert_allclose(uv.channel_sample(texture,u,v,state((1,0,0))),before)

    def test_mirror_and_clamp_boundaries(self):
        texture = np.array([[[1,0,0,1],[0,1,0,1]]],dtype=np.float32)
        at = np.asarray([-.25,.25,.75,1.25])
        v = np.zeros_like(at)+.5
        mirrored = uv.sample(texture,at,v,2)
        np.testing.assert_allclose(mirrored,texture[0,[0,0,1,1]])
        np.testing.assert_allclose(uv.sample(texture,at,v,0),texture[0,[0,0,1,1]])

    def test_secondary_mask_multiplies_rgba_and_addition_preserves_alpha(self):
        primary = np.array([[[.2,.4,.6,.8]]])
        secondary = np.array([[[.6,.2,.4,.5]]])
        u,v=uv.grid(1,1)
        mat={'mode':1,'wrap':[1,1],'filter':[1,1],
             'colorScale1':[1,1,1,1],'colorScale2':[1,1,1,1]}
        masked=uv.shade(primary,secondary,u,v,[state(),state()],mat)
        np.testing.assert_allclose(masked,primary*.5)
        # Vertex RGB must affect the primary before secondary glow is added.
        mat['mode']=2
        added=uv.shade(primary,secondary,u,v,[state(),state()],mat,np.array([.5,.5,.5,1.]))
        np.testing.assert_allclose(added,[[[.4,.3,.5,.8]]])

    def test_distortion_offsets_primary_after_its_uv_transform(self):
        primary=np.array([[[1,0,0,1],[0,1,0,.5]]],dtype=np.float32)
        secondary=np.array([[[.75,.5,.5,1]]],dtype=np.float32)
        mat={'mode':6,'wrap':[1,1],'filter':[0,0],
             'colorScale1':[1,1,1,1],'colorScale2':[1,1,1,1],
             'distortionMid':[.5,.5,.5]}
        result=uv.shade(primary,secondary,np.array([[.25]]),np.array([[.5]]),[state(),state()],mat)
        np.testing.assert_allclose(result,[[[0,1,0,.5]]])


if __name__ == '__main__': unittest.main()
