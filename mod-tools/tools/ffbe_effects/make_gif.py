r"""make_gif.py - animated GIFs of an exported ability (see export_ability.py): one per effect file, plus one of the whole
skill with its layers composited on the game's timeline.

    python tools/ffbe_effects/make_gif.py abilities/firaga [--fps 30] [--width 420] [--frames 260] [--keep 0.9] [--particles 256]

Scale: render.py fits the canvas to the effect's full world extent, which a spark burst or a background plate blows up until
the rest is a dot. So each file is rendered twice: a cheap probe pass measures, for every frame, the centred box holding
`--keep` of that frame's light, and takes the median over the frames that draw anything; the real pass picks the
pixels-per-unit that makes that box fill the frame. Sparks that fly off screen and faint haze stop deciding the framing, the
same way they do not in the game. Each effect gets its own GIF at its own scale; the composite renders them again at the
finest scale of the skill, so relative sizes and the offsets from the effect-group table stay true.

Layers are combined with screen blending: glows add up in the dark parts without burning the picture to white.
"""
import json, os, shutil, subprocess, sys
import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
RENDER = os.path.join(ROOT, "tools", "ffbe_effects", "render.py")
EFFECTS_DEC = os.path.join(ROOT, "build", "ffbe_cpk", "effects_dec")
BG = (10, 10, 12)


def run_render(bmb, out, assets, size, ppu=None, step=1, max_frames=600, exclude=(), particles=256):
    cmd = [sys.executable, RENDER, bmb, out, "--size", str(size), "--step", str(step), "--max-frames", str(max_frames),
           "--particles", str(particles)]
    for a in assets: cmd += ["--assets", a]
    if ppu: cmd += ["--ppu", f"{ppu:.4f}"]
    if exclude: cmd += ["--exclude", ",".join(str(i) for i in exclude)]
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    if r.returncode != 0: raise RuntimeError(f"render failed for {bmb}:\n{r.stdout}\n{r.stderr}")
    return json.load(open(os.path.join(out, "_info.json"), encoding="utf-8"))


def frames_of(d):
    return sorted(f for f in os.listdir(d) if f.startswith("frame_") and f.endswith(".png"))


def light_stack(d, rgb=False):
    """Every frame's light as one array (frames, h, w)."""
    out = []
    for f in frames_of(d):
        a = np.asarray(Image.open(os.path.join(d, f)).convert("RGBA"), dtype=np.float32)
        out.append(a[:, :, :3].max(axis=2) if rgb else a[:, :, 3])
    return np.stack(out) if out else None


def _half_spans(stack, keep):
    """Per frame: half-width of the centred box holding `keep` of that frame's light (0 for an empty frame)."""
    n, h, w = stack.shape
    ys, xs = np.indices((h, w))
    r = np.maximum(np.abs(xs - w / 2), np.abs(ys - h / 2)).ravel()
    order = np.argsort(r); rs = r[order]
    spans = []
    for a in stack:
        c = np.cumsum(a.ravel()[order])
        spans.append(rs[min(np.searchsorted(c, keep * c[-1]), len(rs) - 1)] if c[-1] > 0 else 0.0)
    return np.array(spans, dtype=np.float32)


def content_box(stack, floor=0.02):
    """The box the effect's lasting light occupies: pixels whose summed brightness over the whole sequence clears `floor` of the
    brightest such pixel. A spark that crosses the canvas for three frames adds almost nothing to the sum and is left out."""
    if stack is None: return None
    acc = stack.sum(axis=0)
    if not acc.max(): return None
    ys, xs = np.nonzero(acc > floor * acc.max())
    if not len(xs): return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def core_half_span(stack, keep=0.9, pct=50):
    """The framing radius: the `pct`th percentile of the per-frame boxes, over the frames that draw something. The median frames
    the effect on what it draws for most of its life; a brief spark burst (whose particle speeds the simulation only guesses at)
    then flies off the edge instead of shrinking everything else to a dot."""
    if stack is None: return None
    spans = _half_spans(stack, keep)
    live = spans[spans > 0]
    return float(np.percentile(live, pct)) if len(live) else None


def fitted_ppu(bmb, assets, probe_dir, size=256, fill=0.86, max_frames=600, keep=0.9, particles=256):
    info = run_render(bmb, probe_dir, assets, size=size, step=4, max_frames=max_frames, particles=particles)
    half = core_half_span(light_stack(probe_dir), keep, pct=50)
    ppu = float(info["pixelsPerUnit"])
    return ppu if not half else ppu * (size / 2 * fill) / max(half, 1.0)


def screen_onto(canvas, img, x, y):
    """Screen-blends `img` (RGBA) onto the 0..1 float canvas at top-left (x, y): 1-(1-a)(1-b), so glows pile up without burning out."""
    H, W = canvas.shape[:2]; h, w = img.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x0 >= x1 or y0 >= y1: return
    sub = img[y0 - y:y1 - y, x0 - x:x1 - x].astype(np.float32) / 255.0
    src = sub[:, :, :3] * sub[:, :, 3:4]
    dst = canvas[y0:y1, x0:x1]
    canvas[y0:y1, x0:x1] = 1.0 - (1.0 - dst) * (1.0 - src)


def build(folder, fps=30, width=420, max_frames=260, size=512, fill=0.86, keep=0.9, particles=256):
    folder = folder if os.path.isabs(folder) else os.path.join(ROOT, folder)
    man = json.load(open(os.path.join(folder, "manifest.json"), encoding="utf-8"))
    assets = [os.path.join(folder, "textures"), os.path.join(folder, "meshes"), EFFECTS_DEC]
    work = os.path.join(ROOT, "build", "effects", "gif_" + os.path.basename(folder))
    out_dir = os.path.join(folder, "gif"); os.makedirs(out_dir, exist_ok=True); os.makedirs(work, exist_ok=True)

    files = [f for f in man["effects"] if not man["effects"][f].get("missing")]
    ppus, plates = {}, {}
    for f in files:
        probe = os.path.join(work, "probe_" + f[:-4])
        ppus[f] = fitted_ppu(os.path.join(folder, "effects", f), assets, probe, fill=fill, keep=keep, particles=particles,
                             max_frames=min(max_frames, man["effects"][f]["durationFrames"]))
        # emitters that paint the whole canvas: one tints the screen behind the effect, but several spawns of one file stack
        # into a white wash, so the composite leaves them out
        plates[f] = json.load(open(os.path.join(probe, "_info.json"), encoding="utf-8")).get("backgroundPlateEmitters") or []
    # the shared scale frames the layers that play in front; a backdrop is meant to cover the screen, so letting it decide
    # would shrink the spell itself to a dot
    front = {sp["file"] for g in man["groups"] if (g.get("rawFlags") or ["1"])[0] != "2" for sp in g["spawns"]} & set(files)
    ppu = min((ppus[f] for f in front), default=min(ppus.values()))
    print("  pixels per unit:", {k[:-4]: round(v, 3) for k, v in ppus.items()},
          "-> shared", round(ppu, 3), "(framed on " + ", ".join(sorted(f[:-4] for f in front)) + ")" if front else "")

    renders = {}
    for f in files:
        dur = min(max_frames, man["effects"][f]["durationFrames"])
        own = os.path.join(work, f[:-4])
        run_render(os.path.join(folder, "effects", f), own, assets, size=size, ppu=ppus[f], max_frames=dur, particles=particles)
        write_gif(os.path.join(out_dir, f[:-4] + ".gif"), own, frames_of(own), fps=fps, width=width, keep=keep)
        if abs(ppus[f] - ppu) / ppu < 0.02 and not plates[f]:
            renders[f] = (own, frames_of(own)); continue
        d = os.path.join(work, f[:-4] + "_shared")     # the same effect at the skill's shared scale, without its plates
        run_render(os.path.join(folder, "effects", f), d, assets, size=size, ppu=ppu, max_frames=dur, exclude=plates[f], particles=particles)
        renders[f] = (d, frames_of(d))

    spawns = [(g["skillFrame"] + sp["frame"], sp["file"], sp["x"], sp["y"]) for g in man["groups"] for sp in g["spawns"] if sp["file"] in renders]
    if not spawns: return
    start = min(s[0] for s in spawns)
    total = min(max(s[0] - start + len(renders[s[1]][1]) for s in spawns), max_frames)
    pad_x = int(max(abs(s[2]) for s in spawns) * ppu) + 1
    pad_y = int(max(abs(s[3]) for s in spawns) * ppu) + 1
    W, H = size + 2 * pad_x, size + 2 * pad_y
    comp = os.path.join(work, "_composite"); shutil.rmtree(comp, ignore_errors=True); os.makedirs(comp)
    cache = {}
    for t in range(total):
        canvas = np.zeros((H, W, 3), np.float32)
        for at, f, ox, oy in spawns:
            i = t - (at - start)
            d, fl = renders[f]
            if 0 <= i < len(fl):
                key = (f, i)
                if key not in cache:
                    cache.clear()
                    cache[key] = np.asarray(Image.open(os.path.join(d, fl[i])).convert("RGBA"))
                screen_onto(canvas, cache[key], pad_x + int(ox * ppu), pad_y + int(oy * ppu))
        Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8)).save(os.path.join(comp, f"frame_{t:04d}.png"))
    write_gif(os.path.join(out_dir, f"{man['name'].lower()}.gif"), comp, frames_of(comp), fps=fps, width=width, keep=keep, opaque=True)
    note_in_readme(folder, man, fps)
    print("  ->", out_dir, "|", ", ".join(sorted(os.listdir(out_dir))))


def note_in_readme(folder, man, fps):
    """Puts the previews at the top of the folder's README (replacing an earlier block), so the GIFs are what you see first."""
    path = os.path.join(folder, "README.md")
    if not os.path.exists(path): return
    text = open(path, encoding="utf-8").read()
    mark = "## Previews"
    body = [mark, "",
            f"Rendered from the files in this folder ({fps} fps; the particle simulation is an approximation, see",
            "`tools/ffbe_effects/FORMAT.md`). The first is the whole skill, its layers on the game's timeline.", "",
            f"![{man['name']}](gif/{man['name'].lower()}.gif)", ""]
    for f in man["effects"]:
        g = f"gif/{f[:-4]}.gif"
        if os.path.exists(os.path.join(folder, g)): body += [f"`{f}`", "", f"![{f[:-4]}]({g})", ""]
    block = chr(10).join(body)
    if mark in text:
        head, rest = text.split(mark, 1)
        tail = rest.split("## ", 1)
        text = head + block + ("## " + tail[1] if len(tail) > 1 else "")
    else:
        i = text.index("## Timing") if "## Timing" in text else len(text)
        text = text[:i] + block + text[i:]
    open(path, "w", encoding="utf-8").write(text)


def trim(files, stack, floor=0.005, pad=2):
    """Drops the frames at either end that draw (next to) nothing, so the loop starts on the first light and ends on the last."""
    if stack is None or not len(stack): return files
    light = stack.reshape(len(stack), -1).sum(axis=1)
    if not light.max(): return files
    live = np.nonzero(light > floor * light.max())[0]
    if not len(live): return files
    a, b = max(0, int(live[0]) - pad), min(len(files), int(live[-1]) + 1 + pad)
    return files[a:b]


def write_gif(path, d, files, fps=30, width=420, src_fps=60.0, keep=0.9, opaque=False):
    """Frame PNGs -> a GIF at `fps`, cropped to the part that carries the light, scaled to `width`, on a near-black ground."""
    step = max(1, int(round(src_fps / fps)))
    picked = files[::step]
    if not picked: return
    stack = light_stack(d, rgb=opaque)
    box = content_box(stack)
    if box is None: return
    picked = trim(picked, stack[::step])
    im0 = Image.open(os.path.join(d, picked[0]))
    m = 8
    box = (max(0, box[0] - m), max(0, box[1] - m), min(im0.width, box[2] + m), min(im0.height, box[3] + m))
    out = []
    for f in picked:
        c = Image.open(os.path.join(d, f)).crop(box).convert("RGBA")
        bg = Image.new("RGB", c.size, BG)
        if opaque: bg.paste(c.convert("RGB"), (0, 0))
        else: bg.paste(c, (0, 0), c)
        if bg.width > width: bg = bg.resize((width, max(1, round(bg.height * width / bg.width))), Image.LANCZOS)
        out.append(bg)
    # one palette for the whole animation, taken from a strip of frames across it: per-frame palettes drift as the effect
    # changes colour, and the drift shows up as flat washes of the wrong colour when the GIF is played back
    sample = out[:: max(1, len(out) // 16)][:16]
    strip = Image.new("RGB", (sample[0].width * len(sample), sample[0].height))
    for i, im in enumerate(sample): strip.paste(im, (i * im.width, 0))
    pal = strip.quantize(colors=255, method=Image.Quantize.MEDIANCUT)
    out = [im.quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG) for im in out]
    # disposal 1 (leave the frame in place): Pillow stores only the rectangle that changed, so a frame that erases to the
    # background colour first would show that colour everywhere the change does not cover
    out[0].save(path, save_all=True, append_images=out[1:], duration=round(1000 / fps), loop=0, optimize=True, disposal=1)


if __name__ == "__main__":
    argv = sys.argv[1:]
    def opt(n, d, cast=int): return cast(argv[argv.index(n) + 1]) if n in argv else d
    folders = [x for i, x in enumerate(argv) if not x.startswith("--") and not (i and argv[i - 1].startswith("--"))]
    for folder in folders:
        print(os.path.basename(folder))
        build(folder, fps=opt("--fps", 30), width=opt("--width", 420), max_frames=opt("--frames", 260),
              fill=opt("--fill", 0.86, float), keep=opt("--keep", 0.9, float), particles=opt("--particles", 256))
