r"""build_icons.py - FFBE unit_icon -> Resonance vision icon textures (face 128x128, timeline 128x128, ability 64x64).

usage: python tools/ffbe2ss6/build_icons.py <sprite dir> <ffbe unit id> <out dir> [--style gem|border] [--rarity 5|6|7|NV|NV+] [--layout layout.json]

gem (v6):    Cloud's icons (build/icons/donors/{face,timeline,ability}_13110.png) provide the frame; the interior is cleared,
             the FFBE unit_icon_<id>.png (56x38) is placed in the upper part at 2x and a small gem fills the lower point.
border (v15): the user's frames from assets/ ("border 1" for the menu diamond = face + ability icons, "border 2" for the
             battle circle = timeline icon) with the unit_icon inside (clipped to the frame) and the FFBE rarity chip
             (assets/Rarity-N.webp, NV.webp, NV-plus.webp) = "legacy FFBE unit" marker. The layout (icon scale / offset,
             chip scale / offset per icon kind) comes from the dev UI's icon editor (mods/<mod>/icon_layout.json).
Writes face.bgra, timeline.bgra, ability.bgra (+ png previews).
"""
import json, os, sys
from PIL import Image, ImageDraw, ImageFilter
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DONORS = os.path.join(ROOT, "build", "icons", "donors")
ASSETS = os.path.join(ROOT, "assets")
GEM = ((70, 200, 255, 255), (20, 110, 190, 255), (235, 250, 255, 255))   # light, dark, highlight
# layout values are fractions of the icon size: iconScale multiplies the auto-fit width (0.86 of the frame), offsets move the
# centre; chipScale multiplies the chip's native size scaled to the frame, chip offsets move it from the lower-right corner
DEFAULT_LAYOUT = {
    "face": {"iconScale": 1.0, "iconX": 0.0, "iconY": 0.0, "chipScale": 1.0, "chipX": 0.0, "chipY": 0.0},
    "timeline": {"iconScale": 1.0, "iconX": 0.0, "iconY": 0.0, "chipScale": 1.0, "chipX": 0.0, "chipY": 0.0},
    "ability": {"iconScale": 1.0, "iconX": 0.0, "iconY": 0.0, "chipScale": 1.0, "chipX": 0.0, "chipY": 0.0},
    # per-rarity multiplier on top of the frame's chipScale: the NV / NV+ art is much wider than the star chips
    "chips": {"2": 1.0, "3": 1.0, "4": 1.0, "5": 1.0, "6": 1.0, "7": 1.0, "NV": 0.7, "NV+": 0.55},
}
CHIP_KEYS = ["2", "3", "4", "5", "6", "7", "NV", "NV+"]

def chip_key(rarity):
    """'nv plus' / 'NV-plus' / 'NV+' -> 'NV+', 'NV' -> 'NV', numbers -> the digit"""
    r = str(rarity or "7").strip().upper().replace(" ", "").replace("_", "-")
    if r in ("NV+", "NV-PLUS", "NVPLUS"): return "NV+"
    if r == "NV": return "NV"
    return r.lstrip("R")

def to_bgra(img):
    px = np.array(img.convert("RGBA")); return px[..., [2, 1, 0, 3]].tobytes()

def draw_gem(draw, cx, cy, r):
    top, bot, left, right = (cx, cy - r), (cx, cy + r), (cx - r, cy), (cx + r, cy)
    draw.polygon([top, right, bot, left], fill=GEM[1])
    draw.polygon([top, right, (cx, cy)], fill=GEM[0]); draw.polygon([top, (cx, cy), left], fill=GEM[0])
    draw.polygon([(cx - r // 2, cy - r // 2), (cx, cy - r + 1), (cx + r // 4, cy - r // 2)], fill=GEM[2])
    draw.line([top, right, bot, left, top], fill=(255, 255, 255, 255), width=1)

def make_gem(kind, icon, size):
    base = Image.open(os.path.join(DONORS, f"{kind}_13110.png")).convert("RGBA")
    mask = np.array(Image.open(os.path.join(DONORS, f"{kind}_mask.png")).convert("L")) > 0
    ys, xs = np.where(mask); x0, y0, x1, y1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    bw, bh = x1 - x0, y1 - y0
    arr = np.array(base); arr[mask] = 0
    out = Image.fromarray(arr)
    src = icon.convert("RGBA")
    if size == 128:
        src = src.resize((src.size[0] * 2, src.size[1] * 2), Image.NEAREST)
        ox, oy = x0 + (bw - src.size[0]) // 2, y0 + 4
        gem_c, gem_r = (size // 2, oy + src.size[1] + 14), 11
    else:
        tw = bw - 2; th = int(src.size[1] * tw / src.size[0])
        src = src.resize((tw, th), Image.BILINEAR)
        ox, oy = x0 + (bw - tw) // 2, y0 + 1
        gem_c, gem_r = (size // 2, oy + th + 7), 6
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0)); layer.paste(src, (ox, oy))
    d = ImageDraw.Draw(layer); draw_gem(d, gem_c[0], gem_c[1], gem_r)
    la = np.array(layer); la[~mask, 3] = 0
    out.alpha_composite(Image.fromarray(la))
    return out

def rarity_chip(rarity):
    """assets/Rarity-N | NV | NV-plus (.png preferred over .webp); "NV+" / "nv plus" / "NV-plus" all mean the NV+ chip"""
    r = chip_key(rarity)
    name = "NV" if r == "NV" else "NV-plus" if r == "NV+" else f"Rarity-{r}"
    for ext in (".png", ".webp"):
        p = os.path.join(ASSETS, name + ext)
        if os.path.exists(p): return Image.open(p).convert("RGBA")
    print(f"  ! no rarity chip for '{rarity}' (looked for {name}.png/.webp) - using the 7-star chip")
    return Image.open(os.path.join(ASSETS, "Rarity-7.webp")).convert("RGBA")

def make_border(kind, icon, size, rarity, layout=None):
    """border 1 (menu diamond) for face + ability, border 2 (battle circle) for the timeline; unit_icon inside (clipped to the
    frame's opaque area), rarity chip lower-right; layout = per-kind dict, see DEFAULT_LAYOUT"""
    lay = dict(DEFAULT_LAYOUT[kind]); lay.update((layout or {}).get(kind) or {})
    frame = Image.open(os.path.join(ASSETS, "border 1.png" if kind != "timeline" else "border 2.png")).convert("RGBA")
    k = size / frame.size[0]
    out = frame.resize((size, size), Image.LANCZOS)
    # clip mask: the frame's opaque pixels, shrunk a little so the unit art never overlaps the rim
    alpha = out.getchannel("A").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MinFilter(5))
    src = icon.convert("RGBA")
    f = size * 0.86 / src.size[0] * float(lay["iconScale"])
    tw, th = max(1, int(round(src.size[0] * f))), max(1, int(round(src.size[1] * f)))
    src = src.resize((tw, th), Image.NEAREST if abs(f - round(f)) < 0.05 and f >= 1 else Image.BILINEAR)
    cx, cy = size / 2 + float(lay["iconX"]) * size, size / 2 + float(lay["iconY"]) * size
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0)); layer.alpha_composite(src, (int(round(cx - tw / 2)), int(round(cy - th / 2))))
    la = np.array(layer); la[..., 3] = np.minimum(la[..., 3], np.array(alpha))
    out.alpha_composite(Image.fromarray(la))
    chip = rarity_chip(rarity)
    chips = dict(DEFAULT_LAYOUT["chips"]); chips.update((layout or {}).get("chips") or {})
    cs = k * float(lay["chipScale"]) * float(chips.get(chip_key(rarity), 1.0))
    cw, ch = max(6, int(round(chip.size[0] * cs))), max(6, int(round(chip.size[1] * cs)))
    chip = chip.resize((cw, ch), Image.LANCZOS)
    px = size - cw - int(size * 0.04) + int(float(lay["chipX"]) * size); py = size - ch - int(size * 0.04) + int(float(lay["chipY"]) * size)
    out.alpha_composite(chip, (px, py))
    return out

def render(kind, icon, size, style="border", rarity="7", layout=None):
    return make_border(kind, icon, size, rarity, layout) if style == "border" else make_gem(kind, icon, size)

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = {sys.argv[i][2:]: sys.argv[i + 1] for i in range(len(sys.argv) - 1) if sys.argv[i].startswith("--")}
    for v in opts.values():
        if v in args: args.remove(v)
    sdir, uid, out = args[0], args[1], args[2]; os.makedirs(out, exist_ok=True)
    style = opts.get("style", "gem"); rarity = opts.get("rarity", "7")
    layout = json.load(open(opts["layout"], encoding="utf-8")) if opts.get("layout") and os.path.exists(opts["layout"]) else None
    icon = Image.open(os.path.join(sdir, f"unit_icon_{uid}.png"))
    for kind, size in (("face", 128), ("timeline", 128), ("ability", 64)):
        img = render(kind, icon, size, style, rarity, layout)
        img.save(os.path.join(out, f"{kind}.png")); open(os.path.join(out, f"{kind}.bgra"), "wb").write(to_bgra(img))
        print(kind, img.size, style)

if __name__ == "__main__":
    main()
