r"""flipbook.py - rendered effect frames (PNG sequence from render.py) -> effect document for to_ss6.py, one sprite per frame.

python tools/ffbe_effects/flipbook.py <frames dir> <out dir> [--fps 30] [--src-fps 60] [--max-atlas 2048] [--origin cx,cy]
  frames dir : frame_NNNN.png files (transparent canvas, stable origin) + _info.json from render.py
  out dir    : doc.json + textures/frame_*.png (cropped to content); feed doc.json to to_ss6.py

Frames are cropped to their content box, identical crops are shared, empty frames become hidden slots, and everything is
down-scaled by powers of two until the crops fit the atlas budget. The origin (the effect's world origin = the unit's feet
unless --origin is given) is the canvas centre, as render.py draws it.
"""
import glob, json, os, sys
from PIL import Image

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    src, out = args[0], args[1]
    fps = float(sys.argv[sys.argv.index("--fps") + 1]) if "--fps" in sys.argv else 30.0
    src_fps = float(sys.argv[sys.argv.index("--src-fps") + 1]) if "--src-fps" in sys.argv else 60.0
    budget = int(sys.argv[sys.argv.index("--max-atlas") + 1]) if "--max-atlas" in sys.argv else 2048
    files = sorted(glob.glob(os.path.join(src, "frame_*.png")))
    if not files: sys.exit("no frames")
    info = json.load(open(os.path.join(src, "_info.json"), encoding="utf-8")) if os.path.exists(os.path.join(src, "_info.json")) else {}
    # frame index in the source sequence -> time; render.py may have skipped frames (renderedFrames < durationFrames)
    total = int(info.get("durationFrames") or len(files)); rendered = len(files)
    src_step = total / rendered if rendered else 1.0            # source frames per rendered frame
    keep_every = max(1, int(round(src_fps / fps / src_step)))  # rendered frames per output frame
    picked = files[::keep_every]
    W, H = Image.open(files[0]).size
    if "--origin" in sys.argv:
        cx, cy = (float(v) for v in sys.argv[sys.argv.index("--origin") + 1].split(","))
    else:
        cx, cy = W / 2.0, H / 2.0
    crops = []   # (key, image, bbox)
    cache = {}
    for f in picked:
        im = Image.open(f).convert("RGBA"); bb = im.getchannel("A").getbbox()
        if not bb: crops.append(None); continue
        c = im.crop(bb); key = (c.size, c.tobytes()[:4096], bb)
        crops.append((key, c, bb))
    scale = 1.0
    while True:
        area = sum((c[1].size[0] * scale + 1) * (c[1].size[1] * scale + 1) for c in crops if c)
        if area <= budget * budget * 0.85 or scale <= 0.125: break
        scale /= 2
    os.makedirs(os.path.join(out, "textures"), exist_ok=True)
    textures = []; tex_index = {}; frames = []
    for i, c in enumerate(crops):
        if not c: frames.append([]); continue
        key, img, bb = c
        if key not in tex_index:
            if scale != 1.0: img = img.resize((max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale))), Image.LANCZOS)
            name = f"frame_{len(textures):04d}.png"; img.save(os.path.join(out, "textures", name))
            tex_index[key] = len(textures); textures.append(name)
        ti = tex_index[key]; tw, th = Image.open(os.path.join(out, "textures", textures[ti])).size
        # sprite centre relative to the origin, +Y up, in output pixels
        px = ((bb[0] + bb[2]) / 2.0 - cx) * scale; py = (cy - (bb[1] + bb[3]) / 2.0) * scale
        frames.append([{"tex": ti, "uv": [0, 0, tw, th], "pos": [px, py], "scale": [1.0, 1.0], "rot": 0.0, "alpha": 1.0, "blend": "mix"}])
    doc = {"fps": fps, "frameCount": len(frames), "textures": textures, "frames": frames,
           "source": os.path.basename(src.rstrip("/\\")), "downscale": scale, "srcFrameStep": src_step * keep_every}
    json.dump(doc, open(os.path.join(out, "doc.json"), "w", encoding="utf-8"))
    print(f"{doc['source']}: {len(frames)} frames @ {fps:g} fps, {len(textures)} unique crops, downscale x{scale:g}, canvas {W}x{H} -> {out}")

if __name__ == "__main__":
    main()
