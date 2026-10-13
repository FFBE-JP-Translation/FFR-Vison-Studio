"""Audit every catalog form/LB through the current automatic resonance importer.

python -B tools/audit_resonances.py
python -B tools/audit_resonances.py --unit Agnes --regions studio
python -B tools/audit_resonances.py --compare build/lb-audit/<previous>/results.jsonl

PASS means source, automatic mechanics, LB sprite references, sound scheduling
and in-memory sequence authoring passed. It does not mean a cooked package or
gameplay was tested. Warnings retain known omissions, including side effects.
Only the new report directory is written; no specs, game files or hosts change.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import csv
from functools import lru_cache
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import traceback
import unicodedata
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/devui"), str(ROOT / "tools/ffbe2ss6")]
from PIL import Image
import ffbe_audio
import ffbe_lb
import ffbe_resonance
import ffrenv
from ffbe_frames import read_cgg, read_cgs

SCHEMA = 1
DAMAGE_TYPES = {1, 15}  # The automatic importer currently implements these two.


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def digest(path):
    with Path(path).open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def normalized(value):
    return "".join(c for c in unicodedata.normalize("NFKD", str(value)) if not unicodedata.combining(c)).casefold()


def ids(value):
    return [str(v) for v in (value.split(",") if isinstance(value, str) else value or []) if str(v) not in ("", "0")]


class Sources:
    def __init__(self):
        self.master_units = {str(r["unit_evo_id"]): r for r in ffbe_lb.table("F_UNIT_MST")["rows"]}
        self.master_lbs = {str(r["lb_id"]): r for r in ffbe_lb.table("F_LIMITBURST_MST")["rows"]}
        self.regional = {r.upper(): ffbe_lb.datamine(r) for r in ("gl", "jp")}
        import ffbe_catalog
        self.catalog_archive = Path(ffbe_catalog.ZIP)
        membership = {}
        if self.catalog_archive.is_file():
            with zipfile.ZipFile(self.catalog_archive) as archive:
                for region, prefix in ffbe_catalog.SRC.items():
                    membership[region] = set(json.loads(archive.read(prefix + "units.json")))
        for region, (_, _, folder) in self.regional.items():
            membership[region + "W"] = set(read_json(Path(folder) / "units.json")) if folder else set()
        membership["LIVE"] = {str(r.get("unit_id")) for r in self.master_units.values()}
        self.unit_regions = {}
        for region in ffbe_catalog.REGION_ORDER:
            for uid in membership.get(region, []):
                self.unit_regions.setdefault(uid, "GL" if region.startswith("GL") else "JP")

    def primary_region(self, unit):
        # The display index merges regions. Follow unit_detail/region_of's
        # actual membership, including JP taking precedence over GLW.
        return self.unit_regions.get(str(unit["id"]), "GL" if str(unit.get("source", "JP")).startswith("GL") else "JP")

    def available(self, form, region):
        return form in self.regional[region][0] or region == "JP" and form in self.master_units

    def variants(self, form, region):
        # Follow resolve()'s precedence, while enumerating before parsing: one
        # malformed first variant must never hide its sibling variants.
        if region == "GL":
            found = ids(self.regional["GL"][0].get(form, {}).get("limitburst_id"))
            if found:
                return found
        found = ids(self.master_units.get(form, {}).get("lb_id"))
        if found:
            return found
        for r in (region, "JP" if region == "GL" else "GL"):
            found = ids(self.regional[r][0].get(form, {}).get("limitburst_id"))
            if found:
                return found
        return []

    def raw(self, case):
        form, region, lid = case["formId"], case["region"], case["lbId"]
        if region == "GL" and lid in self.regional["GL"][1]:
            return self.regional["GL"][1][lid]
        if lid in self.master_lbs and lid in ids(self.master_units.get(form, {}).get("lb_id")):
            return self.master_lbs[lid]
        for r in (region, "JP" if region == "GL" else "GL"):
            if lid in self.regional[r][1]:
                return self.regional[r][1][lid]
        return None


def cases(units, sources, regions="all", query=None):
    for unit in units:
        forms = sorted(set(map(str, unit.get("forms", []) + unit.get("spriteForms", [])))) or [str(unit["id"])]
        primary = sources.primary_region(unit)
        whole_match = query is None or normalized(query) in normalized(f"{unit['id']} {unit.get('name', '')}")
        for form in forms:
            if not whole_match and normalized(query) not in normalized(form):
                continue
            requested = [primary] if regions == "studio" else [regions] if regions in ("GL", "JP") else [primary, "JP" if primary == "GL" else "GL"]
            for region in requested:
                if region != primary and not sources.available(form, region):
                    continue
                for index, lid in enumerate(dict.fromkeys(sources.variants(form, region) or [None])):
                    yield {"caseId": f"{unit['id']}:{form}:{region}:{lid or 'none'}", "unitId": str(unit["id"]),
                           "name": unit.get("name", str(unit["id"])), "roles": unit.get("roles") or [],
                           "formId": form, "region": region, "lbId": lid, "defaultLb": index == 0,
                           "studioRegion": region == primary}


def issue(code, message):
    return {"code": code, "message": message}


@lru_cache(maxsize=1)
def native_effect_rows():
    return read_json(ROOT / "extracted/rows/Skill/DT_SkillEffectData.json")["rows"]


def check_support_effects(profile):
    import ffbe_lb_support
    tables = {}
    def tbl(rel): return tables.setdefault(rel, {"add": []})
    def row_by(rel, field, value):
        return next((k, v) for k, v in native_effect_rows().items() if v[field] == value)
    settings = ffbe_lb_support.materialize(profile, 444010, "AuditSupport", tbl, row_by)
    return {"effects": len(settings["effectBundleList"])}


def family(types):
    count = sum(kind in DAMAGE_TYPES for kind in types)
    return "single_damage" if count == 1 else "multiple_damage" if count else "support_or_other" if types else "unresolved"


def raw_types(raw):
    if not raw:
        return []
    if raw.get("effect_type"):
        return [int(v) for v in str(raw["effect_type"]).split("@") if v.isdigit()]
    levels = raw.get("levels") or {}
    if levels:
        return [c[2] for c in levels[min(levels, key=int)].get("effects_raw", []) if len(c) > 2]
    return []


def mechanics_reasons(source, profile):
    """Explain the production profile's broad rejection without changing it."""
    if profile.get("mode") == "support":
        return [issue("support.unsupported_component", " ".join(profile.get("issues", [])))]
    components = source.get("components", [])
    damage = [c for c in components if c["type"] in DAMAGE_TYPES]
    reasons = []
    if not damage:
        reasons.append(issue("mechanics.no_supported_damage", "No physical/magic damage component; support or other effect types need an adapter."))
    elif len(damage) > 1:
        reasons.append(issue("mechanics.multiple_damage", f"{len(damage)} damage components need a combined damage/timing adapter."))
    elif not source.get("hitFrames"):
        raw = (source.get("rawAttackFrames") or "").split("@")
        i = 0 if len(raw) == 1 else damage[0]["index"]
        count = len(raw[i].split("-")) if i < len(raw) and raw[i] else 0
        code = "mechanics.over_30_hits" if count > 30 else "mechanics.unresolved_timing"
        reasons.append(issue(code, f"Damage component has {count} raw hit entries; its timing is not supported by the importer."))
    elif damage[0]["target"] != 1 or damage[0]["range"] not in (1, 2):
        reasons.append(issue("mechanics.targeting", f"Damage target/range {damage[0]['target']}/{damage[0]['range']} needs an adapter."))
    if len(source.get("elements", [])) > 1:
        reasons.append(issue("mechanics.multiple_elements", "The source has multiple damage elements; FFR's current skill row accepts one."))
    if source.get("moveType") not in (0, 1, 4):
        reasons.append(issue("movement.unsupported_type", f"Movement type {source.get('moveType')} needs an adapter."))
    # Never turn an unknown/new production rejection into a false PASS.
    if not profile["supported"] and not reasons:
        reasons.append(issue("mechanics.unsupported", " ".join(profile.get("issues", []))))
    return reasons


class MotionFiles:
    def __init__(self, output, packs=None):
        self.output = Path(output).resolve()
        self.packs = Path(packs) if packs else None
        self.cache = {}

    def check(self, form):
        if form not in self.cache:
            try:
                self.cache[form] = self.inspect(form)
            except Exception as ex:
                self.cache[form] = ex
        value = self.cache[form]
        if isinstance(value, Exception):
            raise value
        return value

    def inspect(self, form):
        if self.packs:
            path = self.packs / f"{form}.zip"
            with zipfile.ZipFile(path) as archive:
                return self.read(form, archive.namelist(), archive.read, str(path), digest(path))
        import ffbe_catalog
        folder = ffbe_catalog.sprite_dir(form)
        if not folder:
            raise FileNotFoundError(f"No readable sprite source for form {form}")
        folder = Path(folder)
        return self.read(form, [p.name for p in folder.iterdir()], lambda name: (folder / name).read_bytes(), str(folder), None)

    def read(self, form, names, reader, path, sha):
        motion = next((name for name in (f"unit_limitatk_cgs_{form}.csv", f"unit_limit_atk_cgs_{form}.csv") if name in names), None)
        if motion is None:
            raise FileNotFoundError(f"Form {form} has no limitatk/limit_atk motion")
        with Image.open(io.BytesIO(reader(f"unit_anime_{form}.png"))) as atlas:
            atlas.load()
            size = atlas.size
        # Reuse the converter's CSV parsers on scratch files, without extracting
        # arbitrary archive paths. The cleanup target stays inside this report.
        with tempfile.TemporaryDirectory(prefix="motion-", dir=self.output) as directory:
            scratch = Path(directory).resolve()
            assert scratch.is_relative_to(self.output)
            cgg_path, cgs_path = scratch / "cgg.csv", scratch / "cgs.csv"
            cgg_path.write_bytes(reader(f"unit_cgg_{form}.csv"))
            cgs_path.write_bytes(reader(motion))
            frames, steps = read_cgg(cgg_path), read_cgs(cgs_path)
        if not steps:
            raise ValueError("The LB motion has no animation steps")
        used = {s["frame"] for s in steps}
        if any(i < 0 or i >= len(frames) for i in used):
            raise ValueError("The LB motion references a missing composition frame")
        parts = [p for i in used for p in frames[i]]
        if not parts:
            raise ValueError("All LB composition frames are empty")
        warnings = []
        if any(p["pageId"] != 0 for p in parts):
            warnings.append(issue("motion.extra_pages", "LB cells reference extra sprite pages; the current composer uses one atlas."))
        if any(p["imgX"] < 0 or p["imgY"] < 0 or p["imgX"] + p["imgW"] > size[0] or p["imgY"] + p["imgH"] > size[1] for p in parts):
            warnings.append(issue("motion.cell_outside_atlas", "Some LB cell rectangles extend outside the primary atlas."))
        return {"path": path, "sha256": sha, "file": motion, "seconds": sum(max(1, s["delay"]) for s in steps) / 60,
                "steps": len(steps), "compositionFrames": len(used), "atlasSize": list(size), "warnings": warnings}


class AudioFiles:
    def __init__(self, attack, system):
        self.attack = Path(attack) if attack else None
        self.system = Path(system) if system else None
        self.metadata = {}

    @lru_cache(maxsize=2)
    def bank(self, path):
        if path is None or not path.is_file():
            return {}, {}, {}, "Sound bank is not available locally"
        info = ffbe_audio.bank_info(str(path.resolve()), path.stat().st_mtime_ns)
        recordings, omitted = ffbe_audio.native_selection(str(path.resolve()), path.stat().st_mtime_ns,
                                                          tuple(sorted(info["cues"])), True)
        by_cue = defaultdict(list)
        for rec in recordings:
            by_cue[rec["sourceCueId"]].append(rec)
        self.metadata[str(path)] = {"sha256": info["sha256"], "cues": len(info["cues"]), "omittedCues": omitted}
        return info["cues"], by_cue, omitted, None

    def check(self, source):
        events, warnings = [], []
        counts = Counter()
        requested = list((source or {}).get("sounds", []))
        cues, recordings, omitted, error = self.bank(self.attack) if requested else ({}, {}, {}, None)
        if error:
            warnings.append(issue("audio.missing_bank", error))
        skipped = {}
        for sound in requested:
            cid = sound["cueId"]
            choices = recordings.get(cid, [])
            if not choices:
                skipped[str(cid)] = omitted.get(cid, error or "Cue not found")
                continue
            rec = choices[counts[cid] % len(choices)]; counts[cid] += 1
            events.append({"frame": sound["frame"], "cueName": rec["name"], "durationMs": rec["durationMs"], "bank": "AuditAttack"})
        if skipped:
            warnings.append(issue("audio.omitted_cues", json.dumps(skipped, ensure_ascii=False)))
        system, recs, _, system_error = self.bank(self.system)
        opening = next((cid for cid, cue in system.items() if cue["name"] == ffbe_audio.LB_OPENING_CUE), None)
        if opening is not None and recs.get(opening):
            rec = recs[opening][0]
            events.append({"frame": 0, "cueName": rec["name"], "durationMs": rec["durationMs"], "bank": "AuditOpening"})
        else:
            warnings.append(issue("audio.missing_opening", system_error or "The common opening cue is unavailable/unsupported"))
        return {"requestedAttackEvents": len(requested), "scheduledEvents": len(events), "omittedCues": skipped,
                "events": events, "warnings": warnings}


def audit_case(case, sources, motions, audio, shell, cloud):
    # Keep unforeseen diagnostic/data errors scoped to their case too. A bad
    # raw record must never prevent the remaining catalog from being scanned.
    try:
        return _audit_case(case, sources, motions, audio, shell, cloud)
    except Exception as ex:
        return {**case, "status": "FAIL", "family": "unresolved", "checks": {"audit": "FAIL"},
                "failures": [issue("audit.exception", f"{type(ex).__name__}: {ex}")], "warnings": [],
                "exceptions": {"audit": traceback.format_exc()}, "gameplay": "NOT_RUN", "cookedPackage": "NOT_RUN"}


def _audit_case(case, sources, motions, audio, shell, cloud):
    result = {**case, "status": "FAIL", "checks": {}, "failures": [], "warnings": [], "gameplay": "NOT_RUN", "cookedPackage": "NOT_RUN"}
    source, profile, motion, sound = None, None, None, None

    def check(stage, action):
        try:
            value = action()
            result["checks"][stage] = "PASS"
            return value
        except Exception as ex:
            result["checks"][stage] = "FAIL"
            result["failures"].append(issue(f"{stage}.exception", f"{type(ex).__name__}: {ex}"))
            result.setdefault("exceptions", {})[stage] = traceback.format_exc()
            return None

    if case["lbId"] is None:
        result["checks"]["source"] = "FAIL"
        result["failures"].append(issue("source.no_lb", "No LB variant found for this form in the available source data."))
    else:
        source = check("source", lambda: ffbe_lb.resolve({"ffbe": {"id": case["formId"], "source": case["region"]}}, {"ffbe_lb_id": case["lbId"]}))
        if source is None and result["checks"]["source"] == "PASS":
            result["checks"]["source"] = "FAIL"
            result["failures"].append(issue("source.missing_record", "The listed LB variant could not be resolved."))
    if source:
        result["lbName"] = source.get("name")
        result["source"] = {key: source.get(key) for key in ("source", "components", "elements", "hitFrames", "hitPercents", "supportFrames", "moveType", "movement", "rawAttackFrames")}
        result["effectTypes"] = [c["type"] for c in source.get("components", [])]
        result["family"] = family(result["effectTypes"])
        for warning in source.get("warnings", []):
            code = "conditional_groups" if "Conditional" in warning else "missing_presentation" if "No matching" in warning else "regional_metadata" if "matching JP" in warning else "missing_sound_cue" if "Missing sound cue ID" in warning else "incomplete_metadata"
            result["warnings"].append(issue(f"source.{code}", warning))
        profile = check("mechanics", lambda: ffbe_lb.profile(source, cloud))
        if profile:
            result["profileIssues"] = profile.get("issues", [])
            if not profile["supported"]:
                result["checks"]["mechanics"] = "FAIL"
                result["failures"].extend(mechanics_reasons(source, profile))
            elif profile.get("mode") == "support":
                result["warnings"].extend(issue("support.native_translation", w) for w in profile.get("warnings", []))
                check("effects", lambda: check_support_effects(profile))
            else:
                ignored = [c["type"] for c in source["components"] if c["index"] != source["damageComponent"]]
                if ignored:
                    result["warnings"].append(issue("mechanics.side_effects_not_imported", f"Source effect types {sorted(set(ignored))} are not translated by the damage-only automatic profile."))
    else:
        result["rawLb"] = sources.raw(case)
        result["effectTypes"] = raw_types(result["rawLb"])
        result["family"] = family(result["effectTypes"])
        result["checks"]["mechanics"] = "BLOCKED"
    # These independent checks still run when mechanics fail, exposing all the
    # useful defects in a support LB instead of stopping at the first rejection.
    motion = check("motion", lambda: motions.check(case["formId"]))
    if motion:
        result["motion"] = {k: v for k, v in motion.items() if k != "warnings"}
        result["warnings"].extend(motion["warnings"])
    if source:
        sound = check("audio", lambda: audio.check(source))
        if sound:
            result["audio"] = {k: v for k, v in sound.items() if k not in ("events", "warnings")}
            result["warnings"].extend(sound["warnings"])
            if sound["warnings"]:
                result["checks"]["audio"] = "PARTIAL"
    else:
        result["checks"]["audio"] = "BLOCKED"
    if profile and profile["supported"] and motion and sound:
        plan = check("schedule", lambda: ffbe_resonance.schedule(motion["seconds"], profile["hits"], 444010, source, sound["events"]))
        if plan:
            result["schedule"] = {"seconds": plan["duration"] / ffbe_resonance.TICKS, "events": len(plan["events"])}
            check("authoring", lambda: ffbe_resonance.author(deepcopy(shell), plan))
        else:
            result["checks"]["authoring"] = "BLOCKED"
    else:
        result["checks"].update(schedule="BLOCKED", authoring="BLOCKED")
    result["status"] = "FAIL" if result["failures"] else "PASS"
    return result


def aggregate(results):
    groups = defaultdict(list)
    for result in results:
        groups[result["unitId"]].append(result)
    units = []
    for uid, rows in groups.items():
        passed = sum(r["status"] == "PASS" for r in rows)
        reasons = sorted({i["code"] for r in rows for i in r["failures"]})
        units.append({"unitId": uid, "name": rows[0]["name"], "status": "PASS" if passed == len(rows) else "FAIL" if not passed else "MIXED",
                      "passedCases": passed, "failedCases": len(rows) - passed, "reasons": reasons})
    return sorted(units, key=lambda u: normalized(u["name"]))


def compare(results, previous):
    old = {r["caseId"]: r for r in previous}
    new = {r["caseId"]: r for r in results}
    return {"fixed": sorted(k for k in old.keys() & new.keys() if old[k]["status"] == "FAIL" and new[k]["status"] == "PASS"),
            "regressed": sorted(k for k in old.keys() & new.keys() if old[k]["status"] == "PASS" and new[k]["status"] == "FAIL"),
            "newCases": sorted(new.keys() - old.keys()), "notRetested": sorted(old.keys() - new.keys())}


def write_reports(output, results, metadata, previous=None):
    output = Path(output)
    units = aggregate(results)
    counts = Counter(r["status"] for r in results)
    failures = Counter(i["code"] for r in results for i in r["failures"])
    warnings = Counter(i["code"] for r in results for i in r["warnings"])
    families = {}
    for family in sorted({r["family"] for r in results}):
        rows = [r for r in results if r["family"] == family]
        families[family] = dict(Counter(r["status"] for r in rows))
    summary = {**metadata, "complete": True, "counts": dict(counts), "units": dict(Counter(u["status"] for u in units)),
               "studioRegionCounts": dict(Counter(r["status"] for r in results if r["studioRegion"])),
               "passWithWarnings": sum(r["status"] == "PASS" and bool(r["warnings"]) for r in results),
               "failureReasons": dict(failures.most_common()), "warningReasons": dict(warnings.most_common()), "families": families}
    if previous is not None:
        summary["comparison"] = compare(results, previous)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    fields = ["status", "name", "unitId", "formId", "region", "lbId", "lbName", "family", "studioRegion", "failures", "warnings"]
    for filename, rows in (("results.csv", results), ("failures.csv", [r for r in results if r["status"] == "FAIL"]), ("units.csv", units)):
        with (output / filename).open("w", encoding="utf-8-sig", newline="") as file:
            columns = fields if filename != "units.csv" else list(units[0]) if units else ["unitId", "name", "status"]
            writer = csv.DictWriter(file, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                clean = {k: " | ".join(f"{v['code']}: {v['message']}" for v in row[k]) if k in ("failures", "warnings") else row.get(k, "") for k in columns}
                for key, value in clean.items():
                    if isinstance(value, list): value = " | ".join(map(str, value))
                    # A unit name or exception can be external data; keep CSV
                    # spreadsheet readers from interpreting it as a formula.
                    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")): value = "'" + value
                    clean[key] = value
                writer.writerow(clean)
    def cell(value): return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# Resonance audit", "", f"{len(units):,} units; {len(results):,} form/region/LB cases.", "",
             f"**PASS: {counts['PASS']:,} · FAIL: {counts['FAIL']:,}.** {summary['passWithWarnings']:,} passing cases have warnings.", "",
             "PASS covers source parsing, current automatic mechanics, LB sprite references, sound scheduling and in-memory sequence authoring.",
             "Cooked package serialization, full FFBE effect parity, attack particles and gameplay are not verified by this audit.",
             "A MIXED unit has passing and failing forms/variants/regions. GL/JP source fallback is reported, not hidden.",
             "The support_or_other family includes support and damage types the importer does not recognize; it is not a unit-role label.", "",
             "## Failures by cause", "", "A case can have more than one failure reason.", "", "| Reason | Cases |", "|---|---:|"]
    lines += [f"| {cell(code)} | {count:,} |" for code, count in failures.most_common()]
    lines += ["", "## Mechanics families", "", "| Family | PASS | FAIL |", "|---|---:|---:|"]
    lines += [f"| {family} | {values.get('PASS', 0):,} | {values.get('FAIL', 0):,} |" for family, values in families.items()]
    lines += ["", "## Units needing attention", "", "All cases and their exact reasons are in `failures.csv`; full diagnostic records are in `results.jsonl`.", "",
              "| Unit | ID | Status | Passing cases | Failing cases | Reasons |", "|---|---|---|---:|---:|---|"]
    lines += [f"| {cell(u['name'])} | {u['unitId']} | {u['status']} | {u['passedCases']} | {u['failedCases']} | {cell(', '.join(u['reasons']))} |" for u in units if u["failedCases"]]
    if "comparison" in summary:
        lines += ["", "## Compared with previous run", ""] + [f"- {key}: {len(value):,}" for key, value in summary["comparison"].items()]
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def first_file(*paths):
    return next((Path(p) for p in paths if p and Path(p).is_file()), None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--index", type=Path, default=ROOT / "build/devui/ffbe_index.json")
    parser.add_argument("--out", type=Path, default=ROOT / "build/lb-audit" / datetime.now().strftime("%Y%m%d-%H%M%S"))
    parser.add_argument("--regions", choices=("all", "studio", "GL", "JP"), default="all")
    parser.add_argument("--unit", help="Name, catalog ID or form ID (accent-insensitive)")
    parser.add_argument("--sprite-packs", type=Path, help="Existing per-form sprite zip cache; missing zips fail instead of downloading")
    parser.add_argument("--audio-bank", type=Path)
    parser.add_argument("--system-bank", type=Path)
    parser.add_argument("--compare", type=Path, help="Previous results.jsonl for fixed/regressed case IDs")
    parser.add_argument("--fail-on-error", action="store_true", help="Exit 1 if any case fails (default: exit 0 when the scan completes)")
    args = parser.parse_args(argv)
    if args.out.exists():
        parser.error("Output directory already exists; choose a new directory to preserve the earlier report")
    index = read_json(args.index)
    units = index["units"] if isinstance(index, dict) else index
    sources = Sources()
    wanted = list(cases(units, sources, args.regions, args.unit))
    if not wanted:
        parser.error("No matching catalog units/forms")
    cloud = ffbe_lb.cloud_reference()
    legacy = ROOT / "extracted/legacy" / (ffbe_resonance.SHELL + ".uasset")
    if not legacy.is_file():
        parser.error("The fresh event shell is missing; extract Sequencer/Battle/Skill/440110/440111 first")
    packs = args.sprite_packs
    if packs is None:
        candidate = ROOT / "build/release/host/ffbe/sprites"
        packs = candidate if candidate.is_dir() else None
    attack = args.audio_bank or first_file(ROOT / "data/ffbe/audio/SE.acb", "S:/FFBE JP Data Export/public/SE.acb")
    system = args.system_bank or first_file(attack.with_name("System.acb") if attack else None, ROOT / "data/ffbe/audio/System.acb", "S:/FFBE JP Data Export/public/System.acb")
    previous = [json.loads(line) for line in args.compare.read_text(encoding="utf-8").splitlines() if line] if args.compare else None
    args.out.mkdir(parents=True)
    start = time.monotonic()
    metadata = {"schema": SCHEMA, "started": datetime.now(timezone.utc).isoformat(), "regions": args.regions,
                "query": args.unit, "expectedCases": len(wanted), "index": str(args.index), "indexSha256": digest(args.index),
                "spritePacks": str(packs) if packs else None,
                "sourceFiles": {}, "toolHashes": {name: digest(ROOT / "tools" / name) for name in
                    ("audit_resonances.py", "ffbe_lb.py", "ffbe_lb_support.py", "ffbe_audio.py", "ffbe_resonance.py", "ffbe2ss6/ffbe_frames.py")}}
    for name in ("F_UNIT_MST", "F_LIMITBURST_MST", "F_EFFECT_GROUP_MST"):
        path = first_file(ROOT / "data/ffbe/master" / f"{name}.json", ROOT / "build/devui/live_jp" / f"{name}.json")
        metadata["sourceFiles"][name] = {"path": str(path), "sha256": digest(path)} if path else None
    for region, (_, _, folder) in sources.regional.items():
        for name in ("units", "limitbursts"):
            path = Path(folder) / f"{name}.json" if folder else None
            metadata["sourceFiles"][f"{region}/{name}"] = {"path": str(path), "sha256": digest(path)} if path else None
    for name, path in (("catalogArchive", sources.catalog_archive), ("eventShell", legacy),
                       ("eventShellData", legacy.with_suffix(".uexp")), ("usmap", Path(ffrenv.USMAP)),
                       ("nativeEffects", ROOT / "extracted/rows/Skill/DT_SkillEffectData.json")):
        metadata["sourceFiles"][name] = {"path": str(path), "sha256": digest(path)} if path.is_file() else None
    (args.out / "run.json").write_text(json.dumps({**metadata, "complete": False}, indent=2), encoding="utf-8")
    dumped = args.out / "event-shell.json"
    subprocess.run([*ffrenv.FFRDT, "tojson", str(legacy), str(dumped), "--usmap", ffrenv.USMAP], check=True, capture_output=True)
    shell = read_json(dumped)
    motions, audio = MotionFiles(args.out, packs), AudioFiles(attack, system)
    results = []
    print(f"Auditing {len(wanted):,} cases; report: {args.out}", flush=True)
    with (args.out / "results.jsonl").open("w", encoding="utf-8") as log:
        for i, case in enumerate(wanted, 1):
            result = audit_case(case, sources, motions, audio, shell, cloud)
            results.append(result)
            log.write(json.dumps(result, ensure_ascii=False) + "\n"); log.flush()
            if i % 100 == 0 or i == len(wanted):
                counts = Counter(r["status"] for r in results)
                print(f"  {i:,}/{len(wanted):,}: PASS {counts['PASS']:,}; FAIL {counts['FAIL']:,}; {time.monotonic()-start:.0f}s", flush=True)
    metadata.update(seconds=round(time.monotonic() - start, 2), audioBanks=audio.metadata)
    summary = write_reports(args.out, results, metadata, previous)
    (args.out / "run.json").write_text(json.dumps({**metadata, "complete": True}, indent=2), encoding="utf-8")
    print(json.dumps({"counts": summary["counts"], "units": summary["units"], "report": str(args.out / "summary.md")}), flush=True)
    return 1 if args.fail_on_error and summary["counts"].get("FAIL") else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as ex:
        print(f"Audit could not complete: {type(ex).__name__}: {ex}", file=sys.stderr)
        sys.exit(2)
