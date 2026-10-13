"""
render.py -- render an FFBE ".bmb" effect to a PNG frame sequence.

    python render.py <file.bmb> <out dir> [options]

Composes every frame from the effect's textures onto a transparent canvas with
a stable origin (the world->pixel mapping is computed once for the whole
animation, so frames can be flip-booked), and writes a contact sheet
`_contact.png` showing every Nth frame.

The container format is decoded with high confidence (see FORMAT.md); the
*particle simulation* is an approximation, so treat the output as
"what the effect is made of and roughly how it moves", not a pixel-accurate
reproduction of the game.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import hashlib
try:
    from .conversion_io import atomic_png
except ImportError:
    from conversion_io import atomic_png
import json
import math
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ibmb  # noqa: E402
import uv_sampling

DEFAULT_ASSET_DIR = r"S:/Projects/ffr/build/ffbe_cpk/effects_dec"
MESH_SPRITE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "build", "effects", "textures")


# ---------------------------------------------------------------------------
# texture loading
# ---------------------------------------------------------------------------
class TextureCache:
    def __init__(self, asset_dirs, *, virtual_cache_limit=32, virtual_cache_bytes=128 * 1024 * 1024):
        self.dirs = asset_dirs
        self.index = {}
        for d in asset_dirs:
            if not os.path.isdir(d):
                continue
            for fn in os.listdir(d):
                stem, ext = os.path.splitext(fn)
                if ext.lower() in (".png", ".tga", ".jpg"):
                    self.index.setdefault(stem.lower(), os.path.join(d, fn))
        self.cache = {}
        self.virtual_cache = OrderedDict()
        self.virtual_cache_limit = max(0, virtual_cache_limit)
        self.virtual_cache_bytes = max(0, virtual_cache_bytes)
        self.virtual_bytes = 0
        self.missing = set()

    def _store_virtual(self, name, arr):
        """Bound generated frame pixels while keeping source textures and paths."""
        key = name.lower()
        arr = np.asarray(arr, dtype=np.float32) if arr is not None else None
        self.virtual_bytes -= self.virtual_cache.pop(key, 0)
        self.cache[key] = arr
        size = arr.nbytes if arr is not None else 0
        self.virtual_cache[key] = size
        self.virtual_bytes += size
        while len(self.virtual_cache) > self.virtual_cache_limit or self.virtual_bytes > self.virtual_cache_bytes:
            oldest, size = self.virtual_cache.popitem(last=False)
            self.virtual_bytes -= size
            self.cache.pop(oldest, None)
        return arr

    def get(self, name):
        """Return an HxWx4 float32 array in 0..1 (straight alpha), or None."""
        key = name.lower()
        if key in self.cache:
            if key in self.virtual_cache:
                self.virtual_cache.move_to_end(key)
            return self.cache[key]
        if name == "solid:white":
            # Native untextured particles shade vertex RGBA directly. A white
            # cell is the neutral carrier for those independently baked
            # color/alpha channels in SpriteStudio; it is not replacement art.
            path = os.path.join(MESH_SPRITE_DIR, "native_solid_white.png")
            os.makedirs(MESH_SPRITE_DIR, exist_ok=True)
            valid = False
            try:
                with Image.open(path) as cell:
                    valid = cell.mode == 'RGBA' and cell.size == (2, 2) and bool(np.all(np.asarray(cell) == 255))
            except (OSError, ValueError):
                pass
            if not valid:
                atomic_png(Image.new("RGBA", (2, 2), (255, 255, 255, 255)), path)
            self.index[key] = path
            arr = np.ones((2, 2, 4), dtype=np.float32)
            self.cache[key] = arr
            return arr
        if name.startswith("mesh:"):
            return self._mesh_sprite(name)
        if name.startswith("quadcolor:"):
            return self._quad_color_sprite(name)
        if name.startswith("nativeuv:"):
            return self._native_uv_sprite(name)
        path = self.index.get(key)
        if path is None:
            self.missing.add(name)
            self.cache[key] = None
            return None
        im = Image.open(path)
        # palette PNGs (mode "P") carry their alpha in the palette
        im = im.convert("RGBA")
        arr = np.asarray(im).astype(np.float32) / 255.0
        self.cache[key] = arr
        return arr

    def _native_uv_sprite(self, name):
        """Sample authored UV controls before geometry/vertex colour shading."""
        data = json.loads(name[len('nativeuv:'):])
        material = data.get('material')
        # Model-only emitters have no primary texture. The historical resource
        # accessor falls back to the model name, which is not a missing PNG.
        # Use the same neutral texture as the existing vertex-coloured mesh
        # rasterizer; a genuinely named but missing texture still fails.
        untextured_model = bool(data.get('model') and material and material.get('primary') is None
                                and material.get('mode') == 0 and data['texture'] == data['model'])
        texture = self.get('solid:white' if untextured_model else data['texture'])
        if texture is None:
            return self._store_virtual(name, None)
        stamp = hashlib.sha256((str(ibmb.BAKE_VERSION) + name).encode())
        stamp.update(texture.tobytes())
        secondary = None
        if material and material['mode']:
            secondary = self.get(material['secondary'])
            if secondary is None:
                raise ValueError('Missing active secondary texture '+str(material['secondary']))
            stamp.update(secondary.tobytes())
        mesh_path = None
        if data.get('model'):
            mesh_path = next((os.path.join(d, data['model']+'.m3r') for d in self.dirs
                              if os.path.isfile(os.path.join(d, data['model']+'.m3r'))), None)
            if mesh_path:
                with open(mesh_path, 'rb') as stream: stamp.update(stream.read())
        path = os.path.join(MESH_SPRITE_DIR, 'nativeuv__'+stamp.hexdigest()[:24]+'.png')
        if os.path.isfile(path):
            arr = np.asarray(Image.open(path).convert('RGBA'), dtype=np.float32)/255.
        else:
            def sampler(u, v, color=1.):
                color = color * np.asarray([*data.get('color', [1., 1., 1.]), 1.], dtype=np.float32)
                if data.get('vertexColors'):
                    tl, bl, br, tr = np.asarray(data['vertexColors'], dtype=np.float32)
                    cu, cv = np.asarray(u)[...,None], np.asarray(v)[...,None]
                    rgb = np.where(cv >= cu, tl*(1-cv)+bl*(cv-cu)+br*cu,
                                   tl*(1-cu)+br*cv+tr*(cu-cv))
                    vertex = np.concatenate([rgb, np.ones_like(cu)], axis=-1)
                    color = color * vertex
                if material:
                    return uv_sampling.shade(texture, secondary, u, v, data['channels'], material, color)
                return uv_sampling.channel_sample(texture, u, v, data['channels'][0], data['wrap']) * color
            if mesh_path:
                arr = ibmb.rasterise_mesh(ibmb.parse_m3r(mesh_path), texture,
                                         *data['tilt'], texture_sampler=sampler)
            else:
                height, width = texture.shape[:2]
                factor = min(1., 512/max(width, height))
                width, height = max(1, round(width*factor)), max(1, round(height*factor))
                arr = sampler(*uv_sampling.grid(width, height))
            if arr is None:
                # A fully culled/degenerate projected mesh has no covered
                # pixels. Retain a transparent cell for its virtual texture;
                # exporting the literal nativeuv JSON as a filename is invalid.
                arr = np.zeros((1, 1, 4), dtype=np.float32)
            os.makedirs(MESH_SPRITE_DIR, exist_ok=True)
            atomic_png(Image.fromarray((np.clip(arr, 0, 1)*255).astype(np.uint8), 'RGBA'), path)
        self.index[name.lower()] = path
        return self._store_virtual(name, arr)

    def _quad_color_sprite(self, name):
        """Bake native four-corner RGB into a texture; alpha stays separate."""
        source, payload = name[len("quadcolor:"):].rsplit("|", 1)
        colors, region, flips = json.loads(payload)
        texture = self.get(source)
        if texture is None:
            return None
        stamp = hashlib.sha256(name.encode())
        stamp.update(str(ibmb.BAKE_VERSION).encode())
        stamp.update(texture.tobytes())
        path = os.path.join(MESH_SPRITE_DIR, "quadcolor__" + stamp.hexdigest()[:24] + ".png")
        if os.path.exists(path):
            arr = np.asarray(Image.open(path).convert("RGBA"), dtype=np.float32) / 255.
        else:
            # A white 2px source still needs enough texels for its authored
            # gradient; this changes sampling resolution, never world size.
            h, w = texture.shape[:2]
            h, w = max(64, h), max(64, w)
            raw = Image.fromarray((np.clip(texture, 0, 1) * 255).astype(np.uint8), "RGBA")
            arr = np.asarray(raw.resize((w, h), Image.Resampling.BILINEAR), dtype=np.float32) / 255.
            arr = arr.copy()
            u = (np.arange(w, dtype=np.float32) + .5) / w
            v = (np.arange(h, dtype=np.float32) + .5) / h
            if flips[0]: u = 1 - u
            if flips[1]: v = 1 - v
            u, v = np.meshgrid(region[0] + u * (region[2] - region[0]),
                               region[1] + v * (region[3] - region[1]))
            u, v = u[..., None], v[..., None]
            tl, bl, br, tr = np.asarray(colors, dtype=np.float32)
            tint = np.where(v >= u, tl * (1-v) + bl * (v-u) + br * u,
                            tl * (1-u) + br * v + tr * (u-v))
            arr[..., :3] *= tint
            os.makedirs(MESH_SPRITE_DIR, exist_ok=True)
            atomic_png(Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA"), path)
        self.index[name.lower()] = path
        return self._store_virtual(name, arr)


    def _mesh_sprite(self, name):
        """'mesh:<model>|<texture>|<rx>|<ry>' -> the mesh rasterised with its
        texture, saved once under build/effects/textures (where to_ss6.py also
        looks) and indexed like any other texture."""
        key = name.lower()
        model, tex_name, rx, ry = name[5:].split("|")
        mpath = next((os.path.join(d, model + ".m3r") for d in self.dirs if os.path.exists(os.path.join(d, model + ".m3r"))), None)
        texture_path = self.index.get(tex_name.lower())
        stamp = hashlib.sha256(str(ibmb.BAKE_VERSION).encode())
        for dependency in (mpath, texture_path):
            if dependency:
                with open(dependency, 'rb') as stream:
                    stamp.update(stream.read())
        fname = "mesh__%s__%s__x%s_y%s__%s.png" % (model, tex_name, rx, ry, stamp.hexdigest()[:12])
        fname = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in fname)
        path = os.path.join(MESH_SPRITE_DIR, fname)
        if os.path.exists(path):
            arr = np.asarray(Image.open(path).convert("RGBA")).astype(np.float32) / 255.0
        else:
            arr = None
            tex = self.get(tex_name)
            if mpath:
                try:
                    arr = ibmb.rasterise_mesh(ibmb.parse_m3r(mpath), tex, float(rx), float(ry))
                except Exception as ex:  # pragma: no cover - diagnostics only
                    print("mesh sprite failed for %s: %s" % (name, ex), file=sys.stderr)
            if arr is None:
                if tex is not None:
                    self.index[key] = self.index.get(tex_name.lower())
                return self._store_virtual(name, tex)  # no mesh: the plain textured quad as before
            os.makedirs(MESH_SPRITE_DIR, exist_ok=True)
            atomic_png(Image.fromarray((np.clip(arr, 0, 1) * 255).astype(np.uint8), "RGBA"), path)
        self.index[key] = path
        return self._store_virtual(name, arr)


# ---------------------------------------------------------------------------
# sprite compositing
# ---------------------------------------------------------------------------
def _prepare_sprite(tex, w, h, angle_deg, flip_x=False, flip_y=False):
    """Scale + flip + rotate a texture, returning a float32 HxWx4 RGBA patch."""
    w = max(1, min(int(round(w)), 4096))
    h = max(1, min(int(round(h)), 4096))
    img = Image.fromarray((np.clip(tex, 0, 1) * 255).astype(np.uint8), "RGBA")
    img = img.resize((w, h), Image.BILINEAR)
    if flip_x:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    if flip_y:
        img = img.transpose(Image.FLIP_TOP_BOTTOM)
    if abs(angle_deg) > 0.01:
        img = img.rotate(angle_deg, resample=Image.BILINEAR, expand=True)
    return np.asarray(img).astype(np.float32) / 255.0


def _blit(canvas, patch, cx, cy, color, alpha, mode):
    """Composite `patch` centred at (cx, cy) into the float RGBA `canvas`."""
    H, W = canvas.shape[:2]
    ph, pw = patch.shape[:2]
    x0 = int(round(cx - pw / 2.0))
    y0 = int(round(cy - ph / 2.0))
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww = min(pw - sx0, W - dx0)
    hh = min(ph - sy0, H - dy0)
    if ww <= 0 or hh <= 0:
        return
    src = patch[sy0:sy0 + hh, sx0:sx0 + ww]
    dst = canvas[dy0:dy0 + hh, dx0:dx0 + ww]
    a = src[..., 3:4] * alpha
    rgb = src[..., :3] * np.asarray(color, dtype=np.float32)
    if mode == "add":
        dst[..., :3] += rgb * a
        dst[..., 3:4] = np.clip(dst[..., 3:4] + a, 0, 1)
    else:  # normal, straight-alpha over
        dst[..., :3] = dst[..., :3] * (1.0 - a) + rgb * a
        dst[..., 3:4] = dst[..., 3:4] + a * (1.0 - dst[..., 3:4])


# ---------------------------------------------------------------------------
def compute_extent(baked, sprite_gain, skip=()):
    """World-space bounding box over the whole animation."""
    xs, ys = [], []
    for parts in baked["frames"]:
        for p in parts:
            if p["emitter"] in skip:
                continue
            sw = abs(p["scale"][0]) * sprite_gain
            sh = abs(p["scale"][1]) * sprite_gain
            r = 0.5 * math.hypot(sw, sh) + 1e-3
            xs += [p["pos"][0] - r, p["pos"][0] + r]
            ys += [p["pos"][1] - r, p["pos"][1] + r]
    if not xs:
        return (-100.0, -100.0, 100.0, 100.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _mapping(extent, size):
    x0, y0, x1, y1 = extent
    cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    span = max(x1 - x0, y1 - y0, 1e-3) * 1.06
    ppu = size / span
    return ppu, size / 2.0 - cx * ppu, size / 2.0 + cy * ppu, span


def _part_texture_name(name, part):
    if not part.get("vertexColors"):
        return name
    if name.startswith('nativeuv:'):
        data = json.loads(name[len('nativeuv:'):])
        data['vertexColors'] = part['vertexColors']
        return 'nativeuv:' + json.dumps(data, sort_keys=True, separators=(',', ':'))
    return "quadcolor:" + name + "|" + json.dumps(
        [part["vertexColors"], part.get("colorRegion", [0, 0, 1, 1]),
         part.get("colorTextureFlip", [False, False])], separators=(",", ":"))


def build_doc(baked, tc, ppu, sprite_gain, max_sprites=64, fps=60,
              origin_world=(0.0, 0.0)):
    """Turn the baked particle list into the `doc.json` that to_ss6.py eats.

    Schema (see tools/ffbe_effects/to_ss6.py):
      {"fps", "frameCount", "textures": ["name.png", ...],
       "frames": [[{"tex", "uv":[x,y,w,h] px, "pos":[x,y] px +Y up,
                    "scale":[sx,sy] multiplier on the uv rect,
                    "rot" deg, "alpha", "blend":"mix"|"add",
                    "flipX", "flipY"}, ...], ...]}

    `pos` is in the same pixels-per-unit as the PNG frames, measured from
    `origin_world` (default world 0,0 -- the effect origin / the unit's feet).
    The chosen scale is echoed back as "pixelsPerUnit" so a consumer can
    rescale.  With --ppu the same value can be forced across several layers of
    one effect so their doc coordinates are directly comparable.
    We have not decoded sub-rect UVs or flipbook stepping, so every sprite
    uses the whole texture and flipX/flipY are always false.
    """
    tex_files, tex_size = [], []
    for name in baked["textures"]:
        arr = tc.get(name)
        path = tc.index.get(name.lower())
        tex_files.append(os.path.basename(path) if path else name + ".png")
        tex_size.append((arr.shape[1], arr.shape[0]) if arr is not None else (64, 64))

    frames = []
    color_textures = {}
    for parts in baked["frames"]:
        out = []
        for i, p in enumerate(parts):
            texture_index = p["tex"]
            if p.get("vertexColors"):
                name = _part_texture_name(baked["textures"][texture_index], p)
                if name not in color_textures:
                    arr = tc.get(name)
                    if arr is not None:
                        color_textures[name] = len(tex_files)
                        tex_files.append(os.path.basename(tc.index[name.lower()]))
                        tex_size.append((arr.shape[1], arr.shape[0]))
                texture_index = color_textures.get(name, texture_index)
            tw, th = tex_size[texture_index]
            w = abs(p["scale"][0]) * sprite_gain * ppu
            h = abs(p["scale"][1]) * sprite_gain * ppu
            if w < 0.5 or h < 0.5 or p["alpha"] <= 0.004:
                continue
            out.append({
                "tex": texture_index,
                "uv": [0, 0, tw, th],
                "pos": [round((p["pos"][0] - origin_world[0]) * ppu, 3),
                        round((p["pos"][1] - origin_world[1]) * ppu, 3)],
                "scale": [round(w / tw, 5), round(h / th, 5)],
                "rot": p["rot"],
                "alpha": p["alpha"],
                "color": [round(float(c), 4) for c in (p.get("color") or [1, 1, 1])[:3]],   # rgb multiplier, baked into the atlas by to_ss6
                "blend": "add" if p["blend"] == "add" else "mix",
                "flipX": bool(p.get("flipX", False)) ^ (p["scale"][0] < 0),
                "flipY": bool(p.get("flipY", False)) ^ (p["scale"][1] < 0),
                "_order": i, "_area": w * h * p["alpha"],
            })
        if len(out) > max_sprites:
            # keep the visually heaviest; "faintest" first out
            out.sort(key=lambda s: -s["_area"])
            out = out[:max_sprites]
            out.sort(key=lambda s: s["_order"])
        for s in out:
            del s["_order"], s["_area"]
        frames.append(out)

    return {"fps": fps, "frameCount": len(frames), "bakeVersion": baked.get("bakeVersion"),
            "pixelsPerUnit": round(ppu, 6),
            "originWorld": [origin_world[0], origin_world[1]],
            "textures": tex_files, "frames": frames}


def render(bmb_path, out_dir, asset_dirs, size=512, step=1, max_frames=600,
           particles=64, sprite_gain=None, exclude=None, doc=False,
           max_sprites=64, ppu_fixed=None, origin_world=(0.0, 0.0),
           quiet=False, repeat=1, interval=0):
    eff = ibmb.parse(bmb_path)
    baked = ibmb.bake(eff, max_frames=max_frames, max_particles=particles,
                      repeat=repeat, interval=interval)
    if exclude:
        # --exclude leaves emitters out of everything (frames, extent, doc),
        # e.g. bm_2020_fire3 #27, a 440-unit light_burst1 star the game never
        # shows (see FORMAT.md 7)
        ex = set(exclude)
        baked["frames"] = [[p for p in parts if p["emitter"] not in ex]
                           for parts in baked["frames"]]
    tc = TextureCache(asset_dirs)

    # --- sprite gain -----------------------------------------------------
    # Sizes come straight out of the file (node scale x emitter base scale x
    # scale curve).  --sprite-gain is only an escape hatch for inspecting
    # effects whose sizing we got wrong.
    if sprite_gain is None:
        sprite_gain = 1.0

    x0, y0, x1, y1 = compute_extent(baked, sprite_gain)
    if ppu_fixed:
        # Fixed scale: skip the auto-fit entirely and centre the canvas on
        # `origin_world`.  Needed when several layers of one effect must share
        # a coordinate system, or when one runaway emitter would otherwise
        # squash the auto-fit to nothing.
        ppu = float(ppu_fixed)
        span = size / ppu
        ox = size / 2.0 - origin_world[0] * ppu
        oy = size / 2.0 + origin_world[1] * ppu
    else:
        ppu, ox, oy, span = _mapping((x0, y0, x1, y1), size)

    # Emitters whose sprite is (nearly) the whole scene are full-screen
    # plates / flashes; they swamp a contact sheet, so we also produce a
    # second sheet without them.
    plate = set()
    for parts in baked["frames"]:
        for p in parts:
            if max(abs(p["scale"][0]), abs(p["scale"][1])) * sprite_gain >= 0.60 * span:
                plate.add(p["emitter"])
    plate |= set(exclude or ())

    os.makedirs(out_dir, exist_ok=True)
    thumbs, thumbs_fg = [], []
    written = 0

    if ppu_fixed:
        fg_ppu, fg_ox, fg_oy = ppu, ox, oy
    else:
        fg_ppu, fg_ox, fg_oy, _ = _mapping(
            compute_extent(baked, sprite_gain, plate), size)

    def draw(parts, skip, m=None):
        _ppu, _ox, _oy = m or (ppu, ox, oy)
        canvas = np.zeros((size, size, 4), dtype=np.float32)
        for p in parts:
            if p["emitter"] in skip:
                continue
            tex = tc.get(_part_texture_name(baked["textures"][p["tex"]], p))
            if tex is None:
                continue
            w = abs(p["scale"][0]) * sprite_gain * _ppu
            h = abs(p["scale"][1]) * sprite_gain * _ppu
            if w < 0.6 or h < 0.6 or w > 6000 or h > 6000:
                continue
            patch = _prepare_sprite(tex, w, h, p["rot"],
                                    bool(p.get("flipX")) ^ (p["scale"][0] < 0),
                                    bool(p.get("flipY")) ^ (p["scale"][1] < 0))
            px = _ox + p["pos"][0] * _ppu
            py = _oy - p["pos"][1] * _ppu
            _blit(canvas, patch, px, py, p["color"], p["alpha"], p["blend"])
        np.divide(canvas[..., :3], canvas[..., 3:4], out=canvas[..., :3], where=canvas[..., 3:4] > 0)
        return Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGBA")

    for f, parts in enumerate(baked["frames"]):
        if f % step:
            continue
        img = draw(parts, set(exclude or ()))
        img.save(os.path.join(out_dir, "frame_%04d.png" % f))
        thumbs.append((f, img))
        if plate:
            thumbs_fg.append((f, draw(parts, plate, (fg_ppu, fg_ox, fg_oy))))
        written += 1

    # --- contact sheets --------------------------------------------------
    def sheet(entries, path):
        if not entries:
            return
        n = len(entries)
        keep = entries if n <= 36 else [entries[i] for i in
                                        sorted(set(round(i * (n - 1) / 35)
                                                   for i in range(36)))]
        cols = min(6, len(keep))
        rows = (len(keep) + cols - 1) // cols
        cell = 216
        sh = Image.new("RGBA", (cols * cell, rows * cell), (32, 32, 40, 255))
        for i, (fi, img) in enumerate(keep):
            t = img.resize((cell - 4, cell - 4), Image.LANCZOS)
            bg = Image.new("RGBA", t.size, (10, 10, 14, 255))
            bg.alpha_composite(t)
            sh.paste(bg, ((i % cols) * cell + 2, (i // cols) * cell + 2))
        sh.save(path)

    sheet(thumbs, os.path.join(out_dir, "_contact.png"))
    sheet(thumbs_fg, os.path.join(out_dir, "_contact_fg.png"))

    # --- doc.json export --------------------------------------------------
    doc_stats = None
    if doc:
        d = build_doc(baked, tc, ppu, sprite_gain, max_sprites=max_sprites,
                      origin_world=origin_world)
        with open(os.path.join(out_dir, "doc.json"), "w", encoding="utf-8") as fh:
            json.dump(d, fh, separators=(",", ":"))
        counts = [len(f) for f in d["frames"]]
        doc_stats = {"frameCount": d["frameCount"], "textures": d["textures"],
                     "sprites": sum(counts),
                     "spritesPerFrameMax": max(counts) if counts else 0,
                     "spritesPerFrameAvg": round(sum(counts) / max(1, len(counts)), 2),
                     "pixelsPerUnit": d["pixelsPerUnit"],
                     "originWorld": d["originWorld"],
                     "canvasOriginPx": [round(ox, 2), round(oy, 2)]}

    meta = {
        "file": os.path.basename(bmb_path),
        "durationFrames": eff.duration,
        "bakeVersion": baked.get("bakeVersion"),
        "repeat": baked.get("repeat", 1),
        "intervalFrames": baked.get("interval", 0),
        "excluded": sorted(set(exclude or ())),
        "renderedFrames": written,
        "doc": doc_stats,
        "textures": eff.textures,
        "models": eff.models,
        "emitters": [{"i": c.index, "type": ibmb.TYPE_NAME.get(c.type),
                      "texture": c.texture, "model": c.model,
                      "life": c.life,
                      "blend": ibmb.BLEND_NAMES.get(c.blend, "add"),
                      "curves": sorted(c.slot_name(i) for i in c.slots)}
                     for c in eff.emitters()],
        "worldExtent": [round(v, 3) for v in (x0, y0, x1, y1)],
        "pixelsPerUnit": round(ppu, 4),
        "spriteGain": round(sprite_gain, 4),
        "backgroundPlateEmitters": sorted(plate),
        "missingTextures": sorted(tc.missing),
    }
    with open(os.path.join(out_dir, "_info.json"), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)
    if not quiet:
        print("%s -> %s  (%d frames, %d emitters, ppu=%.3f, gain=%.2f)%s"
              % (os.path.basename(bmb_path), out_dir, written,
                 len(meta["emitters"]), ppu, sprite_gain,
                 "  MISSING:" + ",".join(sorted(tc.missing)) if tc.missing else ""))
        if doc_stats:
            print("   doc.json: %d frames, %d sprites (max %d/frame, avg %.1f), %d textures"
                  % (doc_stats["frameCount"], doc_stats["sprites"],
                     doc_stats["spritesPerFrameMax"],
                     doc_stats["spritesPerFrameAvg"], len(doc_stats["textures"])))
    return meta


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bmb")
    ap.add_argument("out_dir")
    ap.add_argument("--assets", action="append", default=[],
                    help="directory to search for textures (repeatable)")
    ap.add_argument("--size", type=int, default=512)
    ap.add_argument("--step", type=int, default=1, help="write every Nth frame")
    ap.add_argument("--max-frames", type=int, default=600)
    ap.add_argument("--particles", type=int, default=64,
                    help="safety cap on live particles per emitter; the actual "
                         "count comes from the file (usually 1)")
    ap.add_argument("--sprite-gain", type=float, default=None,
                    help="override the sprite-size heuristic (1.0 = raw file values)")
    ap.add_argument("--exclude", default="",
                    help="comma-separated emitter indices to leave out")
    ap.add_argument("--doc", action="store_true",
                    help="also write <out dir>/doc.json for to_ss6.py")
    ap.add_argument("--max-sprites", type=int, default=64,
                    help="cap on sprites per frame in doc.json (faintest dropped)")
    ap.add_argument("--ppu", type=float, default=None,
                    help="fix the world->pixel scale instead of auto-fitting; "
                         "use the same value across the layers of one effect")
    ap.add_argument("--origin-world", default="0,0",
                    help="world point that is the doc origin / canvas centre")
    ap.add_argument("--repeat", type=int, default=1,
                    help="play the file N times as one sequence (FFBE groups "
                         "spawn e.g. bm_2001_fire1 seven times)")
    ap.add_argument("--interval", type=int, default=0,
                    help="frames between the repeats")
    a = ap.parse_args()
    dirs = a.assets or [DEFAULT_ASSET_DIR]
    render(a.bmb, a.out_dir, dirs, size=a.size, step=a.step,
           max_frames=a.max_frames, particles=a.particles,
           sprite_gain=a.sprite_gain, doc=a.doc, max_sprites=a.max_sprites,
           ppu_fixed=a.ppu,
           origin_world=tuple(float(x) for x in a.origin_world.split(",")[:2]),
           exclude=[int(x) for x in a.exclude.split(",") if x.strip()],
           repeat=a.repeat, interval=a.interval)


if __name__ == "__main__":
    main()
