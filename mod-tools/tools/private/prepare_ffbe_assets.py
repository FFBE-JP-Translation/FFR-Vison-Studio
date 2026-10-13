"""Prepare a local, searchable FFBE music and enemy sprite review folder.

This is a developer utility. It does not change the game or the Studio catalog.
Requires Pillow, ffmpeg, vgmstream-cli, and (for --extract-monsters) DataExtractor.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "ffbe2ss6"))
from PIL import Image
from ffbe_frames import read_cgg, read_cgs, compose_frame

LIVE = Path("C:/Users/Raegen/AppData/Roaming/AndApp/GameData/5701868182306816/5574872228495360/public")
EXPORT = Path("S:/FFBE JP Data Export")
PATCH = Path("T:/ffbe_patch")
WINDOWS_ASSETS = Path("T:/Projects/ffbe/windows assets")
NAMES = PATCH / "english_patch/texts/0xkPiwVI.txt"
EXTRACTOR = Path("T:/Projects/FFBE Patch/cpk_2")
MUSIC_RE = re.compile(r"^(?:Ver\d+_)?(?:la\d|bgm_|M\d\d_)", re.I)
MONSTER_RE = re.compile(r"^monster_anime_(\d+)\.png$", re.I)
VERSION_RE = re.compile(r"^Ver\d+_", re.I)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def signature(paths):
    values = [(str(p.resolve()), p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def filename(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")[:150]


def relative(path, output):
    return path.relative_to(output).as_posix()


def extract_monsters(output):
    """Use a fresh job folder per archive; never remove an existing directory."""
    base = output / "_cache" / "monster-archives"
    base.mkdir(parents=True, exist_ok=True)
    failures = []
    archives = sorted(LIVE.glob("monster*.cpk"))
    archives += sorted((PATCH / "source/jp/on_demand_asset3").glob("monster*.cpk"))
    if not archives:
        return [{"kind": "archive", "reason": f"No monster archives found in {LIVE}"}]
    for number, archive in enumerate(archives, 1):
        marker_name = archive.stem
        if archive.parent != LIVE:
            marker_name += "-" + hashlib.sha256(str(archive).encode()).hexdigest()[:10]
        marker = base / (marker_name + ".json")
        stamp = signature([archive])
        if marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("signature") == stamp:
            continue
        job = Path(tempfile.mkdtemp(prefix=archive.stem + "-", dir=base))
        # DataExtractor only accepts an input inside a directory named cpk.
        cpk_dir = job / "cpk"
        cpk_dir.mkdir()
        try:
            for source in EXTRACTOR.iterdir():
                if source.suffix.lower() in (".exe", ".dll"):
                    shutil.copy2(source, job / source.name)
            copied = cpk_dir / archive.name
            shutil.copy2(archive, copied)
            result = subprocess.run([str(job / "DataExtractor.exe"), str(copied)], cwd=job,
                                    capture_output=True, timeout=1800)
            (job / "extract.log").write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"DataExtractor exit {result.returncode}; see {job / 'extract.log'}")
            sprites = list(cpk_dir.rglob("monster_anime_*.png"))
            if not sprites:
                raise RuntimeError("Archive produced no monster atlases")
            for sprite in sprites:
                with sprite.open("rb") as stream:
                    if stream.read(8) != b"\x89PNG\r\n\x1a\n":
                        raise RuntimeError(f"Undecoded PNG: {sprite.name}")
            # Remove only our exact copied input after extraction succeeds.
            copied.unlink()
            write_json(marker, {"signature": stamp, "folder": str(cpk_dir), "atlases": len(sprites)})
            print(f"Archive {number}/{len(archives)}: {archive.name}, {len(sprites)} atlases", flush=True)
        except Exception as error:
            failures.append({"kind": "archive", "source": str(archive), "reason": str(error)})
            print(f"Archive failed: {archive.name}: {error}", flush=True)
    return failures


def music_inventory():
    candidates = {}
    # Prefer the live Windows bank, then the older export. Other platform copies
    # provide fallbacks and cues no longer present in the live client.
    for directory in (LIVE, EXPORT / "public", WINDOWS_ASSETS, EXPORT, PATCH):
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.acb")):
            if not MUSIC_RE.match(path.name):
                continue
            key = VERSION_RE.sub("", path.stem).lower()
            sources = candidates.setdefault(key, [])
            if path not in sources:
                sources.append(path)
    return candidates


def run_music(key, sources, output, vgmstream, ffmpeg):
    cache = output / "_cache/music" / (key + ".json")
    stamp = signature(sources)
    if cache.exists():
        saved = json.loads(cache.read_text(encoding="utf-8"))
        if saved.get("signature") == stamp and all((output / r["file"]).exists() for r in saved["records"]):
            return saved["records"], []
    errors = []
    for source in sources:
        try:
            metadata = subprocess.run([str(vgmstream), "-I", str(source)], capture_output=True,
                                      text=True, encoding="utf-8", errors="replace", timeout=30, check=True)
            info = json.loads(metadata.stdout)
            count = max(1, info.get("streamInfo", {}).get("total", 1))
            records = []
            for stream in range(1, count + 1):
                if count > 1:
                    result = subprocess.run([str(vgmstream), "-I", "-s", str(stream), str(source)],
                                            capture_output=True, text=True, timeout=30, check=True)
                    info = json.loads(result.stdout)
                cue = info.get("streamInfo", {}).get("name") or VERSION_RE.sub("", source.stem)
                item_id = key + (f"__{stream:03d}" if count > 1 else "")
                destination = output / "Music" / (filename(item_id) + ".mp3")
                temporary = destination.with_suffix(".tmp.mp3")
                # Temporary PCM files keep errors isolated and avoid pipe deadlocks.
                with tempfile.TemporaryDirectory(prefix="music-", dir=output / "_cache") as scratch:
                    if not Path(scratch).resolve().is_relative_to((output / "_cache").resolve()):
                        raise ValueError("Temporary audio path escaped the output cache")
                    wav = Path(scratch) / "decoded.wav"
                    subprocess.run([str(vgmstream), "-i", "-s", str(stream), "-o", str(wav), str(source)],
                                   capture_output=True, timeout=180, check=True)
                    subprocess.run([str(ffmpeg), "-v", "error", "-y", "-i", str(wav), "-threads", "1",
                                    "-c:a", "libmp3lame", "-q:a", "3", "-metadata", f"title={cue}",
                                    str(temporary)], capture_output=True, timeout=180, check=True)
                temporary.replace(destination)
                records.append({"id": item_id, "name": cue, "file": relative(destination, output),
                                "seconds": round(info["numberOfSamples"] / info["sampleRate"], 2),
                                "channels": info["channels"], "sampleRate": info["sampleRate"],
                                "subsong": stream, "source": str(source),
                                "sources": [str(p) for p in sources], "loop": info.get("loopingInfo")})
            write_json(cache, {"signature": stamp, "records": records})
            return records, []
        except Exception as error:
            detail = getattr(error, "stderr", b"") or str(error)
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            errors.append(f"{source}: {detail[-1500:]}")
    return [], [{"kind": "music", "id": key, "reason": "No source decoded", "attempts": errors}]


def enemy_inventory(output):
    candidates = {}
    roots = []
    markers = (output / "_cache/monster-archives").glob("*.json")
    for marker in sorted(markers, key=lambda path: ("-" in path.stem, path.name)):
        roots.append(Path(json.loads(marker.read_text(encoding="utf-8"))["folder"]))
    roots += [EXPORT / "monsters", PATCH / "gl_extracted/common_lang/sd",
              PATCH / "jp_extracted/on_demand_asset3", EXPORT, PATCH, WINDOWS_ASSETS.parent]
    for directory in roots:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("monster_anime_*.png")):
            match = MONSTER_RE.fullmatch(path.name)
            if match:
                sources = candidates.setdefault(match[1], [])
                if path not in sources:
                    sources.append(path)
    return candidates


def enemy_names():
    english, japanese = {}, {}
    if NAMES.exists():
        for line in NAMES.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("^")
            if len(parts) > 1 and parts[0].startswith("MST_MONSTER_NAME_"):
                key = parts[0].removeprefix("MST_MONSTER_NAME_")[:-2]
                english.setdefault(key, parts[1])
    dictionary = ROOT / "build/devui/live_jp/F_MONSTER_DICTIONARY_MST.json"
    if dictionary.exists():
        table = json.loads(dictionary.read_text(encoding="utf-8"))
        for row in table.get("rows", []) if isinstance(table, dict) else table:
            japanese[str(row["monster_id"])] = row["name"]
    return english, japanese


def run_enemy(key, sources, output, names):
    english, japanese = names
    name = english.get(key) or japanese.get(key) or "Unnamed enemy"
    destination = output / "Enemies" / (filename(f"{key} - {name}") + ".png")
    raw = output / "Enemy Sources" / key
    errors = []
    for source in sources:
        cgg = source.with_name(f"monster_cgg_{key}.csv")
        cgs = source.with_name(f"monster_idle_cgs_{key}.csv")
        try:
            source_files = [source, cgg, cgs]
            stamp = signature(source_files)
            cache = output / "_cache/enemies" / (key + ".json")
            if cache.exists():
                saved = json.loads(cache.read_text(encoding="utf-8"))
                if saved.get("signature") == stamp and destination.exists() and (raw / source.name).exists():
                    return [saved["record"]], []
            frames, steps = read_cgg(cgg), read_cgs(cgs)
            atlas = Image.open(source).convert("RGBA")
            composed = None
            for step in steps:
                parts = frames[step["frame"]]
                if any(p["pageId"] != 0 for p in parts):
                    raise ValueError("Multiple texture pages require a dedicated renderer")
                # Rotation expands parts; allow the full diagonal to avoid clipping.
                extent = max((max(abs(p["xPos"]), abs(p["yPos"])) +
                              math.hypot(p["imgW"], p["imgH"]) for p in parts), default=1)
                canvas = max(128, 2 * math.ceil(extent + 8))
                if canvas > 8192:
                    raise ValueError(f"Unexpected frame extent: {canvas}")
                rendered = compose_frame(atlas, parts, canvas=canvas)
                bounds = rendered.getchannel("A").getbbox()
                if bounds:
                    composed = rendered.crop(bounds)
                    break
            if composed is None:
                raise ValueError("Idle animation contains no visible frame")
            composed.save(destination)
            raw.mkdir(parents=True, exist_ok=True)
            assets = []
            for path in sorted(source.parent.glob(f"monster_*_{key}.*")):
                if path.suffix.lower() in (".csv", ".png"):
                    shutil.copy2(path, raw / path.name)
                    assets.append(relative(raw / path.name, output))
            record = {"id": key, "name": name, "japanese": japanese.get(key, ""),
                      "file": relative(destination, output), "width": composed.width,
                      "height": composed.height, "frame": step["frame"], "source": str(source),
                      "sources": [str(p) for p in sources], "assets": assets,
                      "atlas": relative(raw / source.name, output)}
            write_json(cache, {"signature": stamp, "record": record})
            return [record], []
        except Exception as error:
            errors.append(f"{source}: {error}")
    # Preserve every available atlas even when no idle preview can be composed.
    raw.mkdir(parents=True, exist_ok=True)
    for source in sources:
        try:
            Image.open(source).verify()
            for path in sorted(source.parent.glob(f"monster_*_{key}.*")):
                if path.suffix.lower() in (".csv", ".png"):
                    shutil.copy2(path, raw / path.name)
            record = {"id": key, "name": name, "japanese": japanese.get(key, ""),
                      "file": relative(raw / source.name, output), "atlasOnly": True,
                      "source": str(source), "reason": "Idle preview unavailable; showing source atlas"}
            return [record], [{"kind": "enemy_preview", "id": key, "attempts": errors}]
        except Exception as error:
            errors.append(str(error))
    return [], [{"kind": "enemy", "id": key, "reason": "No source rendered", "attempts": errors}]


def process_batch(items, worker, workers, label):
    records, failures = [], []
    started = last_print = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {pool.submit(worker, key, paths): key for key, paths in items.items()}
        for done, future in enumerate(as_completed(pending), 1):
            try:
                result, errors = future.result()
                records.extend(result)
                failures.extend(errors)
            except Exception as error:
                failures.append({"kind": label.lower(), "id": pending[future], "reason": str(error)})
            now = time.monotonic()
            if done == len(items) or now - last_print > 10:
                print(f"{label}: {done}/{len(items)}, {len(failures)} issues, {now - started:.0f}s", flush=True)
                last_print = now
    return sorted(records, key=lambda row: row["id"]), failures


def build_index(output, manifest):
    template = Path(__file__).with_name("ffbe_asset_picker.html").read_text(encoding="utf-8")
    fields = {"id", "name", "file", "japanese", "atlas", "atlasOnly", "seconds", "sampleRate"}
    browser_data = {"folder": manifest["folder"], "issues": manifest["issues"]}
    for section in ("music", "enemies"):
        browser_data[section] = [{k: v for k, v in row.items() if k in fields} for row in manifest[section]]
    payload = json.dumps(browser_data, ensure_ascii=False).replace("<", "\\u003c")
    (output / "index.html").write_text(template.replace("__ASSET_DATA__", payload), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "build/ffbe-asset-picker")
    parser.add_argument("--extract-monsters", action="store_true")
    parser.add_argument("--only", choices=("all", "music", "enemies", "index"), default="all")
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    output = args.out.resolve()
    for directory in ("Music", "Enemies", "Enemy Sources", "_cache/music", "_cache/enemies"):
        (output / directory).mkdir(parents=True, exist_ok=True)
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    failures = json.loads((output / "failures.json").read_text(encoding="utf-8")) if (output / "failures.json").exists() else []
    if args.extract_monsters:
        failures = [r for r in failures if r["kind"] != "archive"] + extract_monsters(output)
    if args.only in ("all", "music"):
        ffmpeg = shutil.which("ffmpeg")
        vgmstream = ROOT / "tools/vgmstream/vgmstream-cli.exe"
        if not ffmpeg or not vgmstream.exists():
            parser.error("ffmpeg and tools/vgmstream/vgmstream-cli.exe are required")
        inventory = music_inventory()
        print(f"Found {len(inventory)} music banks (version/platform copies grouped by filename)", flush=True)
        manifest["music"], errors = process_batch(inventory,
            lambda key, paths: run_music(key, paths, output, vgmstream, ffmpeg), args.workers, "Music")
        manifest["musicBanks"] = len(inventory)
        failures = [r for r in failures if r["kind"] != "music"] + errors
        write_json(manifest_path, manifest)
        write_json(output / "failures.json", failures)
    if args.only in ("all", "enemies"):
        inventory, names = enemy_inventory(output), enemy_names()
        print(f"Found {len(inventory)} enemy IDs", flush=True)
        manifest["enemies"], errors = process_batch(inventory,
            lambda key, paths: run_enemy(key, paths, output, names), args.workers, "Enemies")
        manifest["enemyIds"] = len(inventory)
        failures = [r for r in failures if not r["kind"].startswith("enemy")] + errors
    manifest.update({"generated": datetime.now(timezone.utc).isoformat(), "folder": str(output),
                     "issues": len(failures), "music": manifest.get("music", []),
                     "enemies": manifest.get("enemies", [])})
    write_json(manifest_path, manifest)
    write_json(output / "failures.json", failures)
    build_index(output, manifest)
    (output / "README.txt").write_text(
        "FFBE asset picker\n\nOpen index.html in your browser. Search, play music, and browse enemies.\n"
        "Use Pick music / Pick enemy, then copy the selection text back into our conversation.\n"
        "You can also browse Music and Enemies directly in Windows Explorer.\n\n"
        f"Music: {len(manifest['music'])} decoded cues from {manifest.get('musicBanks', 0)} local banks.\n"
        f"Enemies: {len(manifest['enemies'])} previews / atlases from {manifest.get('enemyIds', 0)} IDs.\n"
        f"Issues: {len(failures)} (see failures.json for exact reasons).\n\n"
        "Music files are MP3 listening copies: one pass without repeated loops. Original ACB sources,\n"
        "subsong IDs and loop points are retained in manifest.json for the eventual game import.\n"
        "Version prefixes and platform duplicates are grouped by filename, preferring the live Windows\n"
        "copy. This includes crossover music and short jingles, not just the commercial FFBE OST.\n"
        "Enemy previews show a composed idle pose. Enemy Sources contains original sprite sheets and\n"
        "animation CSVs. Entries without a usable idle animation are explicitly labeled as atlases.\n"
        "This is the available local collection; it does not download missing assets or modify the game.\n",
        encoding="utf-8")
    print(f"Ready: {output / 'index.html'}", flush=True)


if __name__ == "__main__":
    main()
