"""Build idle previews, .ffr unit archives, and shared LB recordings.

The .ffr format is ZIP, extracted under engine/data/ffbe. Individual HCA
recordings are addressed by SHA256 and retain the tested native audio adapter.
"""
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import re
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/devui")]
import ffbe_catalog as fc
import ffbe_categories
import ffbe_lb
from ffbe_effects import acb_native, hca_transcode
from ffbe_effects.acb_cues import cues, utf


def encoded(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_bytes() != data:
        from ffbe_effects.conversion_io import atomic_bytes
        atomic_bytes(path, data)
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def archive(path, files):
    """Stable content and timestamps, so unchanged bundles keep their hashes."""
    import io
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return write(path, stream.getvalue())


def route_bundles(forms, limit=70 * 1048576, host='https://units{n}.luminest.io/'):
    """Separate unit shards keep the older sprite sites intact for old apps."""
    groups = [[]]; sizes = [0]
    for form, info in sorted(forms.items()):
        size = info['size'] + info.get('idle', {}).get('size', 0)
        if size > limit:
            raise ValueError(f'Unit bundle {form} exceeds the shard size limit')
        if sizes[-1] + size > limit and groups[-1]:
            groups.append([]); sizes.append(0)
        groups[-1].append(form); sizes[-1] += size
        base = host.format(n=len(groups)).rstrip('/') + '/'
        info['url'] = base + form + '.ffr'
        if info.get('idle'):
            info['idle']['url'] = base + form + '.webp'
    return groups, sizes


def idle_pack(out, forms, host='https://idle.luminest.io/'):
    """One startup download, changed only when an idle is added or replaced.

    Kept on its own site: putting about 68 MiB of previews beside the catalog/app
    would exceed the static site's upload limit. File names retain /previews/
    on that host so the local Studio host can serve the same relative path.
    """
    out = Path(out)
    files = {}
    for form, info in sorted(forms.items()):
        if not info.get('idle'):
            continue
        raw = (out / 'ffbe/idle' / (form + '.webp')).read_bytes()
        if hashlib.sha256(raw).hexdigest() != info['idle']['sha256']:
            raise ValueError(f'Idle checksum mismatch for {form}')
        files[form + '.webp'] = raw
    if not files:
        raise ValueError('No idle previews available for the startup pack')
    current = out / 'previews/idles-current.zip'
    info = archive(current, files)
    name = 'idles-' + info['sha256'][:16] + '.zip'
    current.replace(current.with_name(name))
    return {**info, 'version': info['sha256'], 'count': len(files),
            'url': host.rstrip('/') + '/previews/' + name}


class AudioLibrary:
    def __init__(self, name, out):
        source = ROOT / "data/ffbe/audio" / (name + ".acb")
        if not source.is_file():
            source = Path("S:/FFBE JP Data Export/public") / (name + ".acb")
        self.data = source.read_bytes()
        self.cues = cues(str(source))
        header = utf(self.data)[1][0]
        rows = utf(header["CueTable"])[1]
        for cue in self.cues.values():
            cue["durationMs"] = rows[cue["cueIndex"]]["Length"]
        self.waves = acb_native.awb_files(header["AwbFile"])
        self.out = Path(out)
        self.cache = {}

    def selection(self, ids):
        doc = {"schema": "ffr-audio-1", "cues": {}, "recordings": [], "waves": {}, "omitted": {}}
        for cid in sorted(set(ids)):
            if cid not in self.cache:
                try:
                    cue = self.cues[cid]
                    if not 0 < cue["durationMs"] < 60000:
                        raise ValueError("Missing or unbounded sound cue")
                    records = acb_native.recordings(self.data, [cid], {cid: cue["name"]})
                    assets = {}
                    for rec in records:
                        wid = rec["sourceWaveId"]
                        raw, conversion = hca_transcode.prepare(self.waves[wid], self.out)
                        digest = hashlib.sha256(raw).hexdigest()
                        info = write(self.out / (digest + ".hca"), raw)
                        assets[str(wid)] = {**info, "url": f"ffbe/audio/{digest}.hca"}
                        if conversion:
                            assets[str(wid)]["conversion"] = conversion
                    self.cache[cid] = (records, assets, None)
                except (KeyError, ValueError) as ex:
                    self.cache[cid] = ([], {}, str(ex))
            records, assets, error = self.cache[cid]
            if error:
                doc["omitted"][str(cid)] = error
            if cid in self.cues:
                cue = self.cues[cid]
                doc["cues"][str(cid)] = {k: cue[k] for k in ("name", "cueIndex", "durationMs")}
            doc["recordings"].extend(records)
            doc["waves"].update(assets)
        return doc


def unit_record(unit):
    detail = fc.unit_detail(unit["id"])
    ids = [unit["id"], unit.get("pairOf"), *(unit.get("mergedIds") or [])]
    result = {"schema": 1, "detail": detail, "sources": {}}
    for region, tables in fc.sources().items():
        units = {uid: tables["units"][uid] for uid in ids if uid in tables["units"]}
        if not units:
            continue
        raw = {t: {} for t in fc.TABLES}
        raw["units"] = units
        for unit in units.values():
            for sk in unit.get("skills") or []:
                sid = str(sk["id"])
                for kind in ("skills_ability", "skills_magic", "skills_passive"):
                    if sid in tables[kind]:
                        raw[kind][sid] = tables[kind][sid]
            for form in unit.get("entries", {}).values():
                lids = form.get("limitburst_id") or []
                if not isinstance(lids, list):
                    lids = str(lids).split(",")
                for lid in lids:
                    if str(lid) in tables["limitbursts"]:
                        raw["limitbursts"][str(lid)] = tables["limitbursts"][str(lid)]
        include_ability_children(region, raw)
        result["sources"][region] = raw
    return result


def include_ability_children(region, raw):
    """Carry resolved command proxies so an isolated .ffr stays reproducible."""
    from ability_converter.commands import profile
    from ability_converter.sources import SourceRecord
    from ability_converter.studio import StudioResolver, TABLES
    resolver = StudioResolver(fc)
    roots = [(table, sid, row) for table in TABLES.values() for sid,row in raw[table].items()]
    for table, sid, row in roots:
        source = SourceRecord(**fc.skill_record(region, sid, table, row))
        snapshot = profile(source, resolver)["snapshot"]
        for record in snapshot["records"]:
            if record["source"] != source.source or record["kind"] not in TABLES:
                raise ValueError("Unit archive dependency escaped its source revision")
            raw[TABLES[record["kind"]]][record["id"]] = record["data"]


def profiles(form):
    from audit_resonances import Sources
    # Source construction loads shared dictionaries once in build().
    source = profiles.sources
    doc = {"schema": 1, "form": form, "regions": {}}
    for region in ("GL", "JP"):
        values = {}
        for lid in source.variants(form, region) or [None]:
            try:
                resolved = ffbe_lb.resolve({"ffbe": {"id": form, "source": region}}, {"ffbe_lb_id": lid} if lid else {})
                values[str(lid or "none")] = {"source": resolved}
            except (ValueError, KeyError, TypeError) as ex:
                values[str(lid or "none")] = {"error": str(ex)}
        doc["regions"][region] = values
    doc["regions"]["GLW"] = doc["regions"]["GL"]
    doc["regions"]["JPW"] = doc["regions"]["LIVE"] = doc["regions"]["JP"]
    return doc


def build(units, legacy_forms, out, version, sprite_root=None):
    from audit_resonances import Sources
    profiles.sources = Sources()
    out = Path(out)
    sprite_root = Path(sprite_root) if sprite_root else out / "ffbe/sprites"
    ffbe_categories.enrich(units, fc.sources(), ffbe_lb.table("F_UNIT_MST")["rows"])
    audio = AudioLibrary("SE", out / "ffbe/audio")
    system = AudioLibrary("System", out / "ffbe/audio")
    opening = system.selection([cid for cid, cue in system.cues.items() if cue["name"] == "se_battle_limitopen_1"])
    if not opening["recordings"]:
        raise ValueError("The common LB charging sound is missing")
    common = {"audio/System.json": encoded(opening)}
    for wave in opening["waves"].values():
        digest = wave["sha256"]
        common[f"audio/samples/{digest}.hca"] = (out / "ffbe/audio" / (digest + ".hca")).read_bytes()
    forms = {}
    counts = Counter()
    report = []
    # Rendering is independent per form. Prewarm the shared read-only indexes
    # before workers enter PIL; four workers keep catalog generation practical.
    fc.sprite_map(); fc.index_rows(); fc.rarities()
    original_anims = fc.sprite_anims
    animation_dirs = {}
    def snapshot_anims(form):
        directory = fc.sprite_dir(form)
        if not directory:
            return []
        if directory not in animation_dirs:
            found = {}
            for name in os.listdir(directory):
                match = re.fullmatch(r"unit_(\w+)_cgs_(\d+)\.csv", name)
                if match:
                    found.setdefault(match[2], set()).add(fc.norm_anim(match[1]))
            animation_dirs[directory] = found
        return sorted(animation_dirs[directory].get(str(form), []))
    fc.sprite_anims = snapshot_anims
    def render_idle(form):
        path = out / "ffbe/idle" / (form + ".webp")
        if not path.exists():
            write(path, fc.render_webp(form, "idle", scale=1))
        return path
    executor = ThreadPoolExecutor(max_workers=4)
    idle_jobs = {str(form): executor.submit(render_idle, str(form)) for unit in units
                 for form in unit.get("spriteForms", []) if str(form) in legacy_forms}
    for index, unit in enumerate(units):
        unit["packs"] = sorted(str(f) for f in unit.get("spriteForms", []) if str(f) in legacy_forms)
        unit["hasSprites"] = bool(unit["packs"])
        record = unit_record(unit)
        detail = record["detail"]
        if detail is None:
            raise ValueError(f"Unit {unit['id']} has no catalog detail")
        unit["previewDetail"] = {k: detail[k] for k in ("id", "name", "jpname", "region", "maxForm", "rarity")}
        unit["previewDetail"]["forms"] = {fid: {k: value.get(k) for k in ("rarity", "shift")} for fid, value in detail["forms"].items()}
        for form in unit.get("spriteForms") or []:
            form = str(form)
            if form not in legacy_forms:
                continue
            lb = profiles(form)
            cue_ids = set()
            for region in ("GL", "JP"):
                for lid, entry in lb["regions"][region].items():
                    src = entry.get("source") or {}
                    cue_ids.update(s["cueId"] for s in src.get("sounds", []))
                    row = {"unit": unit["id"], "name": unit["name"], "form": form, "region": region, "lb": lid,
                           "frames": src.get("hitFrames") or src.get("presentationHitFrames") or [],
                           "cues": len(src.get("sounds", [])), "error": entry.get("error"), "warnings": src.get("warnings", [])}
                    counts["cases"] += 1
                    counts["with_frames"] += bool(row["frames"])
                    counts["with_sound_cues"] += bool(row["cues"])
                    counts["missing_source"] += not bool(src)
                    report.append(row)
            sound_doc = audio.selection(cue_ids)
            with zipfile.ZipFile(sprite_root / (form + ".zip")) as z:
                files = {f"sprites/{form}/{name}": z.read(name) for name in z.namelist() if not name.endswith("/")}
            files[f"unit_records/{unit['id']}.json"] = encoded(record)
            files[f"lb_profiles/{form}.json"] = encoded(lb)
            files[f"audio/lb/{form}.json"] = encoded(sound_doc)
            import reviewed_kits
            with reviewed_kits.connect() as kit_db:
                native_kit = reviewed_kits.export_bundle(form, kit_db)
            files[f"native_kits/{form}.json"] = encoded(native_kit)
            # Ability icons are unit assets, copied with the kit rather than a
            # request for every row in the abilities picker.
            for sk in detail.get("skills", []) + native_kit['kit']['entries']:
                name = sk.get("icon")
                path = fc.ability_icon_path(name)
                if path:
                    files["ability_icons/" + Path(path).name] = Path(path).read_bytes()
            import skill_icons
            aliases = skill_icons.ICONS/'aliases.json'
            if aliases.is_file(): files['ability_icons/aliases.json'] = aliases.read_bytes()
            info = archive(out / "ffbe/units" / (form + ".ffr"), files)
            host = legacy_forms[form]["url"].rsplit("/", 1)[0]
            info.update(url=f"{host}{form}.ffr", format="ffr-unit-1", unitId=unit["id"],
                        nativeKit=native_kit['rulesSha256'],
                        sounds=list({v["sha256"]: v for v in sound_doc["waves"].values()}.values()))
            # Render only idle now; other previews are rendered locally after
            # the complete unit bundle has arrived.
            idle_path = out / "ffbe/idle" / (form + ".webp")
            try:
                idle_path = idle_jobs[form].result()
                info["idle"] = {**write(idle_path, idle_path.read_bytes()), "url": f"{host}{form}.webp"}
            except (ValueError, IndexError, FileNotFoundError) as ex:
                counts["missing_idle"] += 1
                report.append({"form": form, "idleError": str(ex)})
            forms[form] = info
        if (index + 1) % 10 == 0:
            print(f"  unit bundles: {index + 1}/{len(units)}, {len(forms)} forms", flush=True)
    executor.shutdown()
    fc.sprite_anims = original_anims
    common_info = archive(out / "ffbe" / f"common-{version}.zip", common)
    compact = {"catalog.json": encoded({"units": units, "categories": ffbe_categories.labels()}),
               "ffbe_en.json": encoded(fc.english())}
    table_info = archive(out / "ffbe" / f"catalog-{version}.zip", compact)
    write(out / "metadata-coverage.json", encoded({"counts": counts, "audioOmitted": {str(k): v[2] for k, v in audio.cache.items() if v[2]}, "results": report}))
    print("LB metadata coverage", dict(counts), flush=True)
    return forms, {"url": f"ffbe/common-{version}.zip", "version": common_info["sha256"], **common_info}, \
        {"url": f"ffbe/catalog-{version}.zip", "version": table_info["sha256"], **table_info}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", default=str(ROOT / "build/release/host/ffbe/index.json"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--version", default="1.0.0.13")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    previous = json.loads(Path(args.index).read_text(encoding="utf-8"))
    units = fc.load_index()[:args.limit]
    ffbe_categories.enrich(units, fc.sources(), ffbe_lb.table("F_UNIT_MST")["rows"])
    forms, common, tables = build(units, previous["forms"], args.out, args.version, Path(args.index).parent / "sprites")
    route_bundles(forms)
    write(Path(args.out) / "ffbe/index.json", encoded({"version": args.version, "units": units, "forms": previous["forms"], "unitBundles": forms,
                                                     "categories": ffbe_categories.labels()}))
    write(Path(args.out) / "asset-packs.json", encoded({"common": common, "tables": tables}))
