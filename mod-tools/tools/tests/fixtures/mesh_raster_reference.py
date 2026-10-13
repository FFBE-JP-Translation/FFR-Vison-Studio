"""Frozen pre-cache mesh rasterizer, captured 2026-09-13 for pixel identity tests."""
import math
from ibmb import project_mesh_vertices

def rasterise_mesh(mesh: dict, tex, rx: float = 0.0, ry: float = 0.0, size: int = 256,
                   texture_sampler=None):
    """Draw a .m3r mesh (parse_m3r dict) textured with `tex` (HxWx4 float32
    RGBA, straight alpha, or None for white) into a size x size float32 RGBA
    image, orthographically, using its XY bounds AFTER rotation. The output
    sprite uses the same projected bounds. Ground-plane discs have zero
    unrotated Y extent; that old box clipped their upright X90 projection.

    Vertex colours (the discs' rim fade, the ball's pole fade, the aura
    strips' black ends) multiply the texture, which is what turns a square
    cloud texture into a round fireball.  rx / ry are the ancestor nodes'
    static X / Y rotations in degrees: a ground disc tilted 25 degrees comes
    out as the ellipse the game shows.  Triangles are drawn back to front with
    straight-alpha "over"; a two-sided additive sphere loses a little of its
    back-face brightness that way, which is the cheapest safe approximation.
    """
    import numpy as np
    V = np.asarray(mesh["vertices"], dtype=np.float32)
    if not len(V) or not mesh.get("indices"):
        return None
    C = np.asarray(mesh.get("colors") or [(1, 1, 1, 1)] * len(V), dtype=np.float32)
    UV = np.asarray(mesh["uvs"], dtype=np.float32)
    I = np.asarray(mesh["indices"], dtype=np.int64)
    I = I[: len(I) - len(I) % 3].reshape(-1, 3)
    P = np.asarray(project_mesh_vertices(mesh, rx, ry), dtype=np.float32)
    bx0, by0 = P[:, :2].min(axis=0)
    bx1, by1 = P[:, :2].max(axis=0)
    cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    hw, hh = max(1e-6, (bx1 - bx0) / 2.0), max(1e-6, (by1 - by0) / 2.0)
    P = P - np.array([cx, cy, 0.0], dtype=np.float32)
    px = (P[:, 0] / hw + 1.0) * 0.5 * size
    py = (1.0 - P[:, 1] / hh) * 0.5 * size
    out = np.zeros((size, size, 4), dtype=np.float32)
    if tex is None:
        tex = np.ones((2, 2, 4), dtype=np.float32)
    th, tw = tex.shape[:2]
    order = np.argsort(P[I].mean(axis=1)[:, 2])          # far (small z) first
    for ti in order:
        i0, i1, i2 = I[ti]
        x0, y0, x1, y1, x2, y2 = px[i0], py[i0], px[i1], py[i1], px[i2], py[i2]
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-6:
            continue
        xa, xb = int(max(0, math.floor(min(x0, x1, x2)))), int(min(size - 1, math.ceil(max(x0, x1, x2))))
        ya, yb = int(max(0, math.floor(min(y0, y1, y2)))), int(min(size - 1, math.ceil(max(y0, y1, y2))))
        if xa > xb or ya > yb:
            continue
        gx, gy = np.meshgrid(np.arange(xa, xb + 1) + 0.5, np.arange(ya, yb + 1) + 0.5)
        w0 = ((x1 - gx) * (y2 - gy) - (x2 - gx) * (y1 - gy)) / area
        w1 = ((x2 - gx) * (y0 - gy) - (x0 - gx) * (y2 - gy)) / area
        w2 = 1.0 - w0 - w1
        m = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not m.any():
            continue
        u = w0 * UV[i0, 0] + w1 * UV[i1, 0] + w2 * UV[i2, 0]
        v = w0 * UV[i0, 1] + w1 * UV[i1, 1] + w2 * UV[i2, 1]
        tx = (np.floor(u * tw).astype(np.int64)) % tw
        ty = (np.floor(v * th).astype(np.int64)) % th
        vertex_color = w0[..., None] * C[i0] + w1[..., None] * C[i1] + w2[..., None] * C[i2]
        col = texture_sampler(u, v, vertex_color) if texture_sampler is not None else tex[ty, tx] * vertex_color
        a = np.clip(col[..., 3:4], 0, 1) * m[..., None]
        dst = out[ya:yb + 1, xa:xb + 1]
        dst[..., :3] = dst[..., :3] * (1.0 - a) + np.clip(col[..., :3], 0, 1) * a
        dst[..., 3:4] = dst[..., 3:4] + a * (1.0 - dst[..., 3:4])
    # The accumulation above is premultiplied. TextureCache and the atlas
    # exporter consume straight RGBA, so divide exactly once at this boundary.
    # Returning premultiplied RGB here multiplied every mesh's vertex/texture
    # alpha a second time at playback and made soft rings/glows too dark.
    np.divide(out[..., :3], out[..., 3:4], out=out[..., :3], where=out[..., 3:4] > 0)
    return out
