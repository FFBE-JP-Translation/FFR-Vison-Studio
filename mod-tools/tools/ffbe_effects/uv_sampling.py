"""Source UV animation, sampled before mesh/quad vertex colour and atlas packing.

FFBE TransformSRT uses inverse texture-space controls. Animated pixels are
stored in bounded atlas pages because SpriteStudio UV wrapping acts on an
entire texture, not an individual packed cell.
"""
import math
import numpy as np


def coordinates(u, v, channel):
    """Native inverse SRT, evaluated on the texture plane at Z=0.5."""
    u, v = np.asarray(u, dtype=np.float32), np.asarray(v, dtype=np.float32)
    tx, ty = channel['translation'][:2]
    px, py = channel['pivot'][:2]
    sx, sy = channel['scaling'][:2]
    rx, ry, rz = channel['rotation']
    c, s = math.cos(math.radians(rz)), math.sin(math.radians(rz))
    x, y = u - tx - px, v - ty - py
    # Native TransformSRT masks the reciprocal to zero below float32 1e-6
    # (0x28bd068-0x28bd104; threshold literal at0x28bd278). A collapsed
    # texture axis samples its pivot; it is not an invalid source effect.
    epsilon = float(np.float32(1e-6))
    if abs(rx) > 1e-6 or abs(ry) > 1e-6:
        # TransformSRT at0x28bd030-0x28bd0fc constructs the first two rows
        # of Rz(-rz) * Rx(-rx) * Ry(-ry). The input texture plane is Z=.5:
        # 0x28bcd04/0x28bcd14 form .5 - translationZ - pivotZ.
        # Apply inverse Y, then X, then Z; scaling remains after rotation.
        z = .5 - channel['translation'][2] - channel['pivot'][2]
        cx, sin_x = math.cos(math.radians(rx)), math.sin(math.radians(rx))
        cy, sin_y = math.cos(math.radians(ry)), math.sin(math.radians(ry))
        x_y = cy*x - sin_y*z
        z_y = sin_y*x + cy*z
        y_x = cx*y + sin_x*z_y
        dx, dy = c*x_y + s*y_x, -s*x_y + c*y_x
    else:
        # Preserve the established Z-only calculation and its rounding.
        dx, dy = c*x + s*y, -s*x + c*y
    return (np.full_like(dx, px) if abs(sx) < epsilon else px + dx / sx,
            np.full_like(dy, py) if abs(sy) < epsilon else py + dy / sy)


def sample(texture, u, v, wrap=1, filtering=1):
    """Bilinear GPU-style texel-centre sampling; 0 clamp, 1 repeat, 2 mirror."""
    texture = np.asarray(texture, dtype=np.float32)
    h, w = texture.shape[:2]
    if not np.isfinite(u).all() or not np.isfinite(v).all():
        raise ValueError('Non-finite UV coordinates')
    def indices(values, count):
        if wrap == 0:
            values = np.clip(values, 0., 1.)
        elif wrap == 1:
            values = np.mod(values, 1.)
        elif wrap == 2:
            phase = np.mod(values, 2.)
            values = np.where(phase <= 1., phase, 2. - phase)
        else:
            raise ValueError(f'Unknown texture wrapping mode {wrap}')
        position = values * count - .5
        if filtering == 0:
            nearest = np.floor(position + .5).astype(np.int64)
            nearest = nearest % count if wrap == 1 else np.clip(nearest, 0, count-1)
            return nearest, nearest, np.zeros_like(values)[..., None]
        if filtering != 1:
            raise ValueError(f'Unknown texture filter {filtering}')
        floored = np.floor(position)
        first = floored.astype(np.int64)
        # Subtract while both arrays are float32. Subtracting int64 indices
        # promotes every sampled animated texture to double precision.
        fraction = (position-floored)[..., None]
        second = first + 1
        if wrap == 1:
            first, second = first % count, second % count
        else:
            first, second = np.clip(first, 0, count-1), np.clip(second, 0, count-1)
        return first, second, fraction
    x0, x1, fx = indices(np.asarray(u, dtype=np.float32), w)
    y0, y1, fy = indices(np.asarray(v, dtype=np.float32), h)
    top = texture[y0, x0] * (1-fx) + texture[y0, x1] * fx
    bottom = texture[y1, x0] * (1-fx) + texture[y1, x1] * fx
    return top * (1-fy) + bottom * fy


def channel_sample(texture, u, v, channel, wrap=1):
    return sample(texture, *coordinates(u, v, channel), wrap)


def shade(primary, secondary, u, v, channels, material, color=1.):
    """Selected original GLSL operations, not a second independent sprite."""
    mode = material['mode']
    wraps, filters = material['wrap'], material['filter']
    uv1 = coordinates(u, v, channels[0])
    sub = None
    if mode:
        if secondary is None:
            raise ValueError('Active secondary texture is missing')
        uv2 = coordinates(u, v, channels[1])
        sub = sample(secondary, *uv2, wraps[1], filters[1])
    if mode == 6:
        sub = sub.copy()
        sub[..., :3] -= np.asarray(material['distortionMid'], dtype=np.float32)[:3]
        sub *= np.asarray(material['colorScale2'], dtype=np.float32)
        sub[..., :3] *= sub[..., 3:4]
        uv1 = uv1[0] + sub[..., 0], uv1[1] + sub[..., 1]
    result = sample(primary, *uv1, wraps[0], filters[0]) * np.asarray(color, dtype=np.float32)
    result *= np.asarray(material['colorScale1'], dtype=np.float32)
    if mode in (1, 2):
        sub = sub * np.asarray(material['colorScale2'], dtype=np.float32)
        if mode == 1:
            result *= sub[..., 3:4]
        else:
            result[..., :3] += sub[..., :3] * sub[..., 3:4]
            result[..., :3] = np.clip(result[..., :3], 0., 1.)
    elif mode == 6:
        result[..., 3] *= sub[..., 3]
    elif mode != 0:
        raise ValueError(f'Unsupported secondary texture operation {mode}')
    return np.clip(result, 0., 1.)


def grid(width, height):
    return np.meshgrid((np.arange(width, dtype=np.float32)+.5)/width,
                       (np.arange(height, dtype=np.float32)+.5)/height)
