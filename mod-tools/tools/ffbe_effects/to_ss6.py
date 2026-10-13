r"""to_ss6.py - FFBE battle effect (parsed frames) -> SpriteStudio 6 project spec + atlas for FF Resonance.

Input: an "effect document" (JSON) as produced by tools/ffbe_effects/ibmb.py:
  {"fps": 30, "frameCount": N, "textures": ["10Ariana_heart.png", ...],
   "frames": [[{"tex": 0, "uv": [x, y, w, h], "pos": [x, y], "scale": [sx, sy], "rot": deg, "alpha": 0..1, "blend": "mix"|"add",
                "flipX": false, "flipY": false}, ...], ...]}          (pos: pixels, +Y up, origin = the unit's feet / spawn point)
Output (in <out dir>): spec.json (for `ffr-dt make-ss6`, model + animation "effect"), tex.bgra + tex.png (atlas), preview.png.

python tools/ffbe_effects/to_ss6.py <effect.json> <out dir> [--name NAME] [--scale 1.0] [--scale-mult 1.6] [--add-gain 1.0] [--max-units 900] [--min-frames 270]
python tools/ffbe_effects/to_ss6.py --test-heart <out dir>      synthetic pulsing-hearts effect from 10Ariana_heart.png (pipeline test)

SS6 conventions (matching tools/ffbe2ss6/build_sprites.py): 60 fps animations, cell pivot = origin offset from the cell centre in
-0.5..0.5 with +Y up, part positions in pixels with +Y up, Sclx/Scly floats, Rotz degrees, Alpha 0..1, Hide 1 = hidden.
Parts: "root" (Null) then one Normal part per simultaneous sprite slot and blend mode ("mix_0", "add_0", ...); every sprite of a
frame is assigned to a free slot of its blend mode, so slots are reused across frames.
"""
import json, math, os, sys
from functools import lru_cache
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ffbe2ss6"))
from PIL import Image, ImageChops
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EFFECTS = os.path.join(ROOT, "build", "ffbe_cpk", "effects_dec")

def load_texture(name):
    for d in (EFFECTS, os.path.join(ROOT, "build", "effects", "textures")):
        p = os.path.join(d, name)
        if os.path.exists(p): return Image.open(p).convert("RGBA")
    raise FileNotFoundError(name)

def pack(images, max_w=2048):
    """shelf packer -> (W, H) power of two, {key: (x, y)}"""
    items = sorted(images.items(), key=lambda kv: -kv[1].size[1])
    W = 64
    while W < max((im.width for im in images.values()), default=1): W *= 2
    while True:
        x = y = shelf = 0; pos = {}
        for k, im in items:
            w, h = im.size
            if x + w + 1 > W: x = 0; y += shelf + 1; shelf = 0
            pos[k] = (x, y); x += w + 1; shelf = max(shelf, h)
        H = y + shelf + 1; p = 64
        while p < H: p *= 2
        if p <= W or W >= max_w: return (W, p), pos
        W *= 2

def pack_pages(images, max_w=2048, max_h=4096):
    """Keep small legacy atlases; bound animated texture pages for the GPU."""
    for im in images.values():
        if im.width > max_w or im.height > max_h:
            raise ValueError(f'Effect cell {im.width}x{im.height} exceeds atlas page {max_w}x{max_h}')
    dimensions, positions = pack(images, max_w)
    if dimensions[1] <= max_h:
        return [(dimensions, positions)]
    pages = []
    x = y = shelf = 0
    positions = {}
    for key, im in sorted(images.items(), key=lambda kv: -kv[1].height):
        w, h = im.size
        if w > max_w or h > max_h:
            raise ValueError(f'Effect cell {w}x{h} exceeds atlas page {max_w}x{max_h}')
        if x + w > max_w:
            x = 0; y += shelf + 1; shelf = 0
        if y + h > max_h:
            height = 64
            while height < y: height *= 2
            pages.append(((max_w, min(max_h, height)), positions))
            x = y = shelf = 0; positions = {}
        positions[key] = (x, y)
        x += w + 1; shelf = max(shelf, h)
    height = 64
    while height < y + shelf: height *= 2
    if positions: pages.append(((max_w, height), positions))
    return pages

SKIP_TEXTURES = ("distortion",)   # distortion / refraction passes have no sprite equivalent
MAX_SPRITE_UNITS = 900            # anything wider AND taller than this (world units) is a screen-fill plate, not part of the unit's
                                  # effect. Sizes are half-extents doubled (ibmb.SIZE_IS_HALF_EXTENT); Firaga's ring reaches 460 units,
                                  # x1.6 for the AoE layer, so the old 260 cap would have clipped the effect the recording shows.
                                  # Per layer: "max_units" on the ffbe_effects entry / --max-units.

def complete_export(folder):
    """A spec written by an interrupted old exporter is not a complete cache."""
    from pathlib import Path
    folder = Path(folder)
    try:
        spec = json.loads((folder/'spec.json').read_text(encoding='utf-8'))
        pages = spec.get('cellmaps', [spec])
        if not pages: return False
        for page in pages:
            width,height = page['pixelSize']
            if width <= 0 or height <= 0 or int(width) != width or int(height) != height:
                return False
            if (folder/page.get('textureFile','tex.bgra')).stat().st_size != int(width*height*4):
                return False
        return True
    except (OSError,ValueError,KeyError,TypeError,OverflowError):
        return False


def convert(doc, out, name, scale=None, fps_out=60, max_units=MAX_SPRITE_UNITS, add_gain=1.0, scale_mult=1.0, min_frames=0, max_cell_size=0):
    if scale is None: scale = 1.0 / float(doc.get("pixelsPerUnit") or 1.0)     # 1 FFBE world unit = 1 sprite pixel
    scale *= scale_mult; max_units = max_units * scale_mult
    def is_add(sp): return str(sp.get("blend", "mix")).lower() in ("add", "additive", "screen")
    # additive gain ("glow"): <= 1 dims the alpha; > 1 brightens the cell's colour and texture alpha (FFBE draws its low-alpha
    # flame textures far hotter than colour x texture alpha gives). Composed docs (layer_spec.compose_docs) carry a per-sprite
    # "gain"; plain docs use the layer's add_gain.
    def gain_of(sp): return float(sp.get("gain", add_gain))
    doc = dict(doc, frames=[[dict(sp, alpha=float(sp.get("alpha", 1.0)) * (min(1.0, gain_of(sp)) if is_add(sp) else 1.0)) for sp in fr] for fr in doc["frames"]])
    skip = {i for i, t in enumerate(doc["textures"]) if any(k in t.lower() for k in SKIP_TEXTURES)}
    plate_tex = {i for i, t in enumerate(doc["textures"]) if any(k in t.lower() for k in ("white", "tex_beta", "bg_", "black", "plate"))}
    shrunk = 0
    def keep(sp):
        if sp["tex"] in skip: return False
        w = abs(sp.get("scale", [1, 1])[0]) * sp["uv"][2] * scale; h = abs(sp.get("scale", [1, 1])[1]) * sp["uv"][3] * scale
        if w > max_units and h > max_units:
            if sp["tex"] in plate_tex: return False          # uniform screen-filling quads: FFR's tint / domain stands in
            nonlocal shrunk; shrunk += 1
            f = max_units / max(w, h); sp["scale"] = [sp["scale"][0] * f, sp["scale"][1] * f]   # textured flashes: shrink to fit
        return True
    before = sum(len(f) for f in doc["frames"])
    doc = dict(doc, frames=[[sp for sp in (dict(x) for x in fr) if keep(sp)] for fr in doc["frames"]])
    after = sum(len(f) for f in doc["frames"])
    if not after:
        raise ValueError('Effect has no drawable sprite frames after export filtering')
    if before != after or shrunk: print(f"{name}: dropped {before - after} sprites (distortion / plates), shrank {shrunk} oversized sprites to {max_units} units")
    @lru_cache(maxsize=32)
    def texture(index):
        return load_texture(doc['textures'][index]) if index not in skip else Image.new('RGBA', (1, 1))
    # cells: every distinct (tex, uv, tint) used; a sprite's colour multiplier is baked into its cell (SS6 colour keys are not
    # simple float keys, so tinting happens in the atlas; colours are quantised to 16 levels to keep the atlas small)
    def tint_key(sp):
        c = sp.get("color")
        if not c: return None
        q = tuple(min(15, max(0, int(round(float(v) * 15)))) for v in c[:3])
        return None if q == (15, 15, 15) else q
    def cell_key(sp):
        boost = max(1.0, gain_of(sp))
        return (sp["tex"], tuple(int(round(v)) for v in sp["uv"]), tint_key(sp), round(boost, 2) if (boost > 1.0 and is_add(sp)) else None)
    rects = {}
    for fr in doc["frames"]:
        for sp in fr:
            key = cell_key(sp)
            if key not in rects:
                x, y, w, h = key[1]; im = texture(sp["tex"]).crop((x, y, x + max(1, w), y + max(1, h)))
                if key[2]:
                    r, g, b = (int(v * 255 / 15) for v in key[2])
                    rgb = Image.merge("RGB", [ImageChops.multiply(ch, Image.new("L", im.size, val)) for ch, val in zip(im.split()[:3], (r, g, b))])
                    im = Image.merge("RGBA", list(rgb.split()) + [im.getchannel("A")])
                if key[3]:
                    # additive boost: FFBE's flames read as colour x vertex alpha with the texture's own (low) alpha barely
                    # attenuating, so lift both the colour and the cell alpha (clipped) -- see to_ss6 "glow" in the studio
                    k = key[3]; rgb = Image.merge("RGB", [ch.point(lambda v, k=k: min(255, int(v * k))) for ch in im.split()[:3]])
                    im = Image.merge("RGBA", list(rgb.split()) + [im.getchannel("A").point(lambda v, k=k: min(255, int(v * k)))])
                if max_cell_size and max(im.size) > max_cell_size:
                    factor = max_cell_size / max(im.size)
                    im = im.resize((max(1, round(im.width*factor)), max(1, round(im.height*factor))), Image.Resampling.LANCZOS)
                rects[key] = im
    texture.cache_clear()
    pages = pack_pages(rects)
    (W, H), _ = pages[0]
    cell_names = {key: f"{name}_c{i}" for i, key in enumerate(rects)}
    cellmaps = []
    for page, ((pw, ph), pos) in enumerate(pages):
        suffix = f'_{page}' if page else ''
        cells = [{"name": cell_names[key], "pos": list(pos[key]), "size": list(rects[key].size),
                  "pivot": [0.0, 0.0]} for key in pos]
        cellmaps.append({'cellmapName': name + suffix, 'pixelSize': [pw, ph], 'cells': cells,
                         'imagePath': f'{name}_tex{suffix}.png', 'textureFile': f'tex{suffix}.bgra'})
    cells = cellmaps[0]['cells']
    # Keep source draw order. Grouping all Mix parts before all Add parts
    # forces every glow over opaque foreground particles. Allocate by source
    # ordinal and blend; at most one part at each ordinal is visible per frame.
    max_slots = {"mix": 0, "add": 0}
    slots = set()
    per_frame = []
    for fr in doc["frames"]:
        counts = {"mix": 0, "add": 0}; assigned = []
        for ordinal, sp in enumerate(fr):
            b = "add" if str(sp.get("blend", "mix")).lower() in ("add", "additive", "screen") else "mix"
            assigned.append((b, ordinal, sp)); counts[b] += 1
            slots.add((b, ordinal))
        for b in counts: max_slots[b] = max(max_slots[b], counts[b])
        per_frame.append(assigned)
    model = [{"name": "root", "parent": -1, "type": "Null", "blend": "Mix", "inherit": "Self"}]
    slot_names = {}
    for b, i in sorted(slots, key=lambda pair: (pair[1], pair[0])):
        slot_names[(b, i)] = f"{b}_{i}"
        model.append({"name": f"{b}_{i}", "parent": 0, "type": "Normal",
                      "blend": "Add" if b == "add" else "Mix", "inherit": "Parent"})
    # keys per part: one key per source frame (converted to 60 fps ticks)
    src_fps = float(doc.get("fps") or 30); step = fps_out / src_fps
    parts = {"root": {"Hide": [[0, 0.0]]}}
    for (b, i), pn in slot_names.items():
        parts[pn] = {"Cell": [], "Posx": [], "Posy": [], "Sclx": [], "Scly": [], "Rotz": [], "Alpha": [], "Hide": [], "Fliph": [], "Flipv": [], "Posz": [[0, 1.0]]}
    ext = 32
    for fi, assigned in enumerate(per_frame):
        t = int(round(fi * step))
        used = set()
        for b, i, sp in assigned:
            pn = slot_names[(b, i)]; used.add(pn)
            key = cell_key(sp); pa = parts[pn]
            sx, sy = (sp.get("scale") or [1, 1]); px, py = (sp.get("pos") or [0, 0])
            # A smaller atlas cell must preserve the particle's world size.
            sx *= key[1][2] / rects[key].width
            sy *= key[1][3] / rects[key].height
            pa["Cell"].append([t, cell_names[key]]); pa["Posx"].append([t, float(px) * scale]); pa["Posy"].append([t, float(py) * scale])
            pa["Sclx"].append([t, float(sx) * scale * (-1 if sp.get("flipX") else 1)]); pa["Scly"].append([t, float(sy) * scale * (-1 if sp.get("flipY") else 1)])
            pa["Rotz"].append([t, float(sp.get("rot") or 0.0)]); pa["Alpha"].append([t, float(sp.get("alpha", 1.0))]); pa["Hide"].append([t, 0.0])
            w, h = rects[key].size
            ext = max(ext, abs(px * scale) + max(w, h) * max(abs(sx), abs(sy)) * scale, abs(py * scale) + max(w, h) * max(abs(sx), abs(sy)) * scale)
        for pn in slot_names.values():
            if pn not in used: parts[pn]["Hide"].append([t, 1.0])
    def dedupe(keys):
        out = []
        for k in keys:
            if out and out[-1][1] == k[1]: continue
            out.append(k)
        return out
    for pn, pa in parts.items():
        for attr in list(pa):
            if attr != "Cell": pa[attr] = dedupe(pa[attr])
            if not pa[attr]: del pa[attr]
    frame_count = max(1, int(round(len(per_frame) * step)))
    if min_frames and frame_count < int(min_frames):
        # the game's SpriteStudio actor loops its clip and outlives the battle sequence (Firaga's fireball restarted 2.67 s after
        # it started), so pad with hidden frames until past any skill's length
        for pn in slot_names.values(): parts[pn].setdefault("Hide", []).append([frame_count, 1.0])
        frame_count = int(min_frames)
    canvas = float(2 * int(ext) + 16)
    first_cell = next(iter(cell_names.values()))
    setup_parts = {"root": {"Hide": [[0, 0.0]]}}
    for pn in slot_names.values(): setup_parts[pn] = {"Cell": [[0, first_cell]], "Posz": [[0, 1.0]], "Sclx": [[0, 1.0]], "Scly": [[0, 1.0]], "Hide": [[0, 1.0]]}
    # FFR overrides only the no-parts-color additive material with an emissive
    # boost. An identity Mul color chooses stock SS6 AddMul without changing
    # texture RGB or the animated Alpha. Setup initializes every playback frame.
    for (blend, _), pn in slot_names.items():
        if blend == "add":
            setup_parts[pn]["PartsColor"] = [[0, {"target": "Whole", "blendType": "Mul",
                                                "rgba": [255, 255, 255, 255], "rate": 1.0}]]
    spec = {"pixelSize": [float(W), float(H)], "cells": cells,
            "model": {"parts": model},
            # The source ordinal is encoded by model part index. The donor's
            # Z sort reverses equal-Z parts in SS6; Priority preserves order.
            "animations": [{"name": "effect", "sortMode": "Priority", "fps": fps_out, "frameCount": frame_count, "canvas": [canvas, canvas], "pivot": [0.0, 0.0], "isSetup": False, "parts": parts},
                           {"name": "Setup", "sortMode": "Priority", "fps": fps_out, "frameCount": 1, "canvas": [0.0, 0.0], "pivot": [0.0, 0.0], "isSetup": True, "parts": setup_parts}],
            "cellmapName": name, "animePackName": name, "imagePath": f"{name}_tex.png"}
    spec['conversionAudit'] = {'droppedSpriteFrames': before-after, 'shrunkSpriteFrames': shrunk,
                              'maxCellSize': max_cell_size, 'sourceSpriteFrames': before,
                              'atlasPages': len(pages), 'atlasBytes': sum(w*h*4 for (w,h),_ in pages)}
    if len(cellmaps) > 1:
        spec['cellmaps'] = cellmaps
    os.makedirs(out, exist_ok=True)
    for page, ((pw, ph), pos) in enumerate(pages):
        atlas = Image.new('RGBA', (pw, ph))
        for key, xy in pos.items(): atlas.paste(rects[key], xy)
        suffix = f'_{page}' if page else ''
        atlas.save(os.path.join(out, f'tex{suffix}.png'))
        px = atlas.tobytes(); bgra = bytearray(px)
        bgra[0::4], bgra[2::4] = px[2::4], px[0::4]
        with open(os.path.join(out, f'tex{suffix}.bgra'), 'wb') as stream: stream.write(bgra)
    # Publish the completion marker only after every atlas page is finished.
    try:
        from .atomic_files import write_json
    except ImportError:
        from atomic_files import write_json
    write_json(os.path.join(out, 'spec.json'), spec, indent=1)
    print(f"{name}: {len(pages)} atlas page(s), {len(rects)} cells, {len(model) - 1} sprite slots ({max_slots}), {frame_count} frames @ {fps_out} fps -> {out}")
    return spec

def test_heart_doc():
    """three hearts rising and fading around the singer, 2 s, additive"""
    frames = []
    for f in range(60):
        t = f / 60.0; sprites = []
        for k in range(3):
            phase = (t * 1.5 + k / 3.0) % 1.0
            sprites.append({"tex": 0, "uv": [0, 0, 128, 128], "pos": [(-50 + 50 * k) + 20 * math.sin(phase * 6.28), 60 + 120 * phase],
                            "scale": [0.6 + 0.4 * (1 - phase)] * 2, "rot": 15 * math.sin(phase * 3.14), "alpha": max(0.0, 1.0 - phase), "blend": "add"})
        frames.append(sprites)
    return {"fps": 30, "frameCount": 60, "textures": ["10Ariana_heart.png"], "frames": frames}

def main():
    if "--test-heart" in sys.argv:
        out = sys.argv[sys.argv.index("--test-heart") + 1]
        convert(test_heart_doc(), out, os.path.basename(out.rstrip("/\\")) if os.path.basename(out.rstrip("/\\")) != "ss6" else os.path.basename(os.path.dirname(out.rstrip("/\\"))))
        return
    doc = json.load(open(sys.argv[1], encoding="utf-8")); out = sys.argv[2]
    name = sys.argv[sys.argv.index("--name") + 1] if "--name" in sys.argv else os.path.splitext(os.path.basename(sys.argv[1]))[0]
    scale = float(sys.argv[sys.argv.index("--scale") + 1]) if "--scale" in sys.argv else None
    add_gain = float(sys.argv[sys.argv.index("--add-gain") + 1]) if "--add-gain" in sys.argv else 1.0
    scale_mult = float(sys.argv[sys.argv.index("--scale-mult") + 1]) if "--scale-mult" in sys.argv else 1.0
    max_units = float(sys.argv[sys.argv.index("--max-units") + 1]) if "--max-units" in sys.argv else MAX_SPRITE_UNITS
    min_frames = int(sys.argv[sys.argv.index("--min-frames") + 1]) if "--min-frames" in sys.argv else 0
    convert(doc, out, name, scale, add_gain=add_gain, scale_mult=scale_mult, max_units=max_units, min_frames=min_frames)

if __name__ == "__main__":
    main()
