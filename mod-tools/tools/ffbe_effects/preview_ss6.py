r"""preview_ss6.py - draw what an effect ss6 spec (from to_ss6.py) will show: composites the parts' cells at given frames.

python tools/ffbe_effects/preview_ss6.py <spec dir> [--frames 0,30,60,...] [--canvas 512] [--zoom 1.5]
Writes <spec dir>/preview.png (contact sheet). Origin = canvas centre, +Y up, additive parts composited with screen-like add.
"""
import json, os, sys
from PIL import Image, ImageChops, ImageOps

def key_at(keys, t, default):
    v = default
    for kt, kv in keys:
        if kt <= t: v = kv
        else: break
    return v

def main():
    d = sys.argv[1]
    spec = json.load(open(os.path.join(d, "spec.json"), encoding="utf-8"))
    atlas = Image.open(os.path.join(d, "tex.png")).convert("RGBA")
    cells = {c["name"]: c for c in spec["cells"]}
    anim = next(a for a in spec["animations"] if not a.get("isSetup"))
    fc = anim["frameCount"]
    frames = [int(x) for x in sys.argv[sys.argv.index("--frames") + 1].split(",")] if "--frames" in sys.argv else [int(fc * i / 12) for i in range(12)]
    size = int(sys.argv[sys.argv.index("--canvas") + 1]) if "--canvas" in sys.argv else 512
    zoom = float(sys.argv[sys.argv.index("--zoom") + 1]) if "--zoom" in sys.argv else 1.0
    blends = {p["name"]: p.get("blend", "Mix") for p in spec.get("model", {}).get("parts", [])}
    tiles = []
    for t in frames:
        canvas = Image.new("RGBA", (size, size), (12, 12, 16, 255))
        for pn, attrs in anim["parts"].items():
            if pn == "root" or "Cell" not in attrs: continue
            if key_at(attrs.get("Hide", []), t, 0.0) >= 0.5: continue
            cell = cells.get(key_at(attrs["Cell"], t, None))
            if not cell: continue
            x, y, w, h = cell["pos"][0], cell["pos"][1], cell["size"][0], cell["size"][1]
            im = atlas.crop((int(x), int(y), int(x + w), int(y + h)))
            sx, sy = key_at(attrs.get("Sclx", []), t, 1.0), key_at(attrs.get("Scly", []), t, 1.0)
            tw, th = max(1, int(abs(sx) * w * zoom)), max(1, int(abs(sy) * h * zoom))
            im = im.resize((tw, th), Image.BILINEAR)
            if sx < 0: im = ImageOps.mirror(im)          # negative scale = mirrored sprite (SS6 flips the cell)
            if sy < 0: im = ImageOps.flip(im)
            rot = key_at(attrs.get("Rotz", []), t, 0.0)
            if rot: im = im.rotate(rot, expand=True, resample=Image.BILINEAR)
            alpha = key_at(attrs.get("Alpha", []), t, 1.0)
            if alpha < 1.0:
                a = im.getchannel("A").point(lambda v: int(v * alpha)); im.putalpha(a)
            px = size / 2 + key_at(attrs.get("Posx", []), t, 0.0) * zoom - im.size[0] / 2
            py = size / 2 - key_at(attrs.get("Posy", []), t, 0.0) * zoom - im.size[1] / 2
            layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0)); layer.paste(im, (int(px), int(py)), im)
            if blends.get(pn) == "Add":
                rgb = Image.new("RGBA", canvas.size, (0, 0, 0, 255)); rgb.paste(layer, (0, 0), layer)
                pre = Image.merge("RGBA", [ImageChops.multiply(ch, layer.getchannel("A")) for ch in rgb.split()[:3]] + [Image.new("L", canvas.size, 255)])
                canvas = ImageChops.add(canvas, pre)
            else:
                canvas.alpha_composite(layer)
        tiles.append(canvas)
    cols = 6; rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * size, rows * size), (0, 0, 0))
    for i, tl in enumerate(tiles): sheet.paste(tl.convert("RGB"), ((i % cols) * size, (i // cols) * size))
    sheet.thumbnail((1800, 1800)); sheet.save(os.path.join(d, "preview.png"))
    print("preview:", os.path.join(d, "preview.png"), "frames", frames)

if __name__ == "__main__":
    main()
