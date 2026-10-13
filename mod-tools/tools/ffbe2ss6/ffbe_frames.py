"""ffbe_frames.py - FFBE cgg/cgs sprite data -> composed RGBA frames (port of FFBE-sprite-sheet-assembler / puggsoy FFBETool).

cgg line : anchor, partCount, then per part: xPos, yPos, nextType, blendMode, opacity, rotate, imgX, imgY, imgW, imgH, pageId
cgs line : frameIndex, xOffset, yOffset, holdFrames
Parts are drawn last-to-first; frame origin = (0,0); +y down (screen space).
"""
import os, csv
from PIL import Image, ImageChops

RENDER_VERSION = 2  # Correct CGG/Pillow rotation handedness; invalidate old previews.

def read_cgg(path):
    frames = []
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    for line in lines:
        p = [x for x in line.strip().split(",") if x != ""]
        if len(p) < 2: frames.append([]); continue
        anchor, count = int(p[0]), int(p[1]); rest = p[2:]
        n = len(rest) // count if count else 0
        parts = []
        for i in range(count):
            f = rest[i*n:(i+1)*n]
            xPos, yPos, nextType, blendMode, opacity, rotate, imgX, imgY, imgW, imgH = [int(v) for v in f[:10]]
            pageId = int(f[10]) if len(f) > 10 else 0
            parts.append(dict(anchor=anchor, xPos=xPos, yPos=yPos, nextType=nextType, blendMode=blendMode, opacity=opacity, rotate=rotate,
                              imgX=imgX, imgY=imgY, imgW=imgW, imgH=imgH, pageId=pageId,
                              flipX=nextType in (1, 3), flipY=nextType in (2, 3)))
        frames.append(list(reversed(parts)))   # draw order: last part first
    return frames

def read_cgs(path):
    steps = []
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()
    for line in lines:
        p = [x for x in line.strip().split(",") if x != ""]
        if len(p) < 4: continue
        steps.append(dict(frame=int(p[0]), x=int(p[1]), y=int(p[2]), delay=int(p[3])))
    return steps

def _blend(img):
    """blendMode 1: premultiply rgb by alpha, alpha = mean(rgb) (additive-ish glow)"""
    px = img.load(); w, h = img.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a:
                af = a / 255.0
                px[x, y] = (int(r*af+0.5), int(g*af+0.5), int(b*af+0.5), int((r+g+b)/3+0.5))
    return img

def compose_frame(atlas, parts, canvas=1024):
    """returns (RGBA image of size canvas x canvas, origin at canvas/2) or None"""
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0)); c = canvas // 2
    for p in parts:
        crop = atlas.crop((p["imgX"], p["imgY"], p["imgX"]+p["imgW"], p["imgY"]+p["imgH"]))
        if p["blendMode"] == 1: crop = _blend(crop)
        if p["flipX"]: crop = crop.transpose(Image.FLIP_LEFT_RIGHT)
        if p["flipY"]: crop = crop.transpose(Image.FLIP_TOP_BOTTOM)
        # CGG angles are counterclockwise. The original JS assembler passes
        # -rotate to its legacy Jimp (clockwise-positive); Pillow is already
        # counterclockwise-positive. Copying the Jimp sign reverses every
        # rotated part, putting a 90-degree weapon 180 degrees out of place.
        if p["rotate"]: crop = crop.rotate(p["rotate"], expand=True, resample=Image.NEAREST)
        if p["opacity"] < 100:
            a = crop.getchannel("A").point(lambda v: int(v * p["opacity"] / 100)); crop.putalpha(a)
        img.alpha_composite(crop, (c + p["xPos"], c + p["yPos"]))
    return img

def trim(img):
    """-> (cropped image, (left, top)) relative to the canvas; None if empty"""
    bbox = img.getchannel("A").getbbox()
    if not bbox: return None, None
    return img.crop(bbox), (bbox[0], bbox[1])

ANIMS = ["idle", "standby", "move", "atk", "magic_standby", "magicatk", "limitatk", "super_limitatk_before", "jump", "dying", "dead", "win", "winbefore", "brave_shift", "atk1"]
ALIASES = {"magicatk": "magic_atk", "limitatk": "limit_atk", "super_limitatk_before": "super_limit_atk_before", "winbefore": "win_before"}   # newer archives spell them with an underscore

def load_unit(sprite_dir, unit_id):
    atlas = Image.open(os.path.join(sprite_dir, f"unit_anime_{unit_id}.png")).convert("RGBA")
    cgg = read_cgg(os.path.join(sprite_dir, f"unit_cgg_{unit_id}.csv"))
    anims = {}
    for a in ANIMS:
        for name in (a, ALIASES.get(a)):          # the JP live client writes limit_atk / magic_atk / win_before
            p = name and os.path.join(sprite_dir, f"unit_{name}_cgs_{unit_id}.csv")
            if p and os.path.exists(p): anims[a] = read_cgs(p); break
    return atlas, cgg, anims

if __name__ == "__main__":
    import sys
    d, uid = sys.argv[1], sys.argv[2]
    atlas, cgg, anims = load_unit(d, uid)
    print("atlas", atlas.size, "frames", len(cgg), "anims", {k: len(v) for k, v in anims.items()})
    out = sys.argv[3] if len(sys.argv) > 3 else None
    for a, steps in anims.items():
        for i, s in enumerate(steps[:1]):
            img = compose_frame(atlas, cgg[s["frame"]]); cr, tl = trim(img)
            if cr is None: print(a, "empty"); continue
            c = img.size[0]//2
            print(f"{a:<14} frame {s['frame']:>3} off=({s['x']},{s['y']}) hold={s['delay']}  bbox size={cr.size} left/top rel origin=({tl[0]-c},{tl[1]-c}) bottom rel origin={tl[1]-c+cr.size[1]}")
            if out: os.makedirs(out, exist_ok=True); cr.save(os.path.join(out, f"{uid}_{a}_{i}.png"))
