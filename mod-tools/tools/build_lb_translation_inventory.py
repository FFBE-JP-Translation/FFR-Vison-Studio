"""Build a deterministic review inventory for Japanese FFBE Limit Burst names.

This is an editorial-input generator: it intentionally does not update the
runtime glossary.  It joins all locally installed FFBE sources, prefers an
official English spelling for an identical LB ID, and writes only names with
no English value into three stable review batches.

Run with: PYTHONUTF8=1 python -B tools/build_lb_translation_inventory.py
Rebuild the packaged lookup after all three editorial maps are reviewed with:
PYTHONUTF8=1 python -B tools/build_lb_translation_inventory.py --merge-runtime
"""
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ZIP = Path(r"S:/ffbeEquip-master.zip")
DATAMINE = Path(r"T:/Projects/ffbe/ffbe-wiki-tools/datamine/data")
LIVE = ROOT / "build/devui/live_jp"
EN_CACHE = ROOT / "build/devui/ffbe_en.json"
GLOSSARY = ROOT / "tools/devui/jp_glossary.json"
OUT = ROOT / "build/lb-translations"
JP_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rows(data):
    """The live extractor writes {rows: [...]}; fixture tables may be lists."""
    if isinstance(data, dict):
        return data.get("rows") or list(data.values())
    return data or []


def lb_ids(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    return [v for v in re.split(r"[,\s]+", str(value)) if v]


def add_source(records, official, contexts, *, source, lbs, forms):
    """Record LB names and their form/unit contexts from one regional source."""
    for lid, lb in lbs.items():
        name = (lb.get("name") or "").strip()
        if not name:
            continue
        lid = str(lid)
        records[lid].add(name)
        if not JP_RE.search(name):
            official[lid].add(name)
    for form in forms:
        form_id = str(form.get("form_id") or form.get("unit_evo_id") or form.get("id") or "")
        unit_id = str(form.get("unit_id") or form.get("id") or form_id)
        unit_name = (form.get("unit_name") or form.get("name") or "").strip()
        ids = lb_ids(form.get("limitburst_id") if "limitburst_id" in form else form.get("lb_id"))
        for lid in ids:
            contexts[lid].append({"source": source, "unitId": unit_id, "unitName": unit_name, "formId": form_id})


def equip_sources(records, official, contexts):
    if not ZIP.exists():
        return
    prefixes = {"GL": "ffbeEquip-master/tools/GL/sources/", "JP": "ffbeEquip-master/tools/JP/sources/"}
    with zipfile.ZipFile(ZIP) as archive:
        for region, prefix in prefixes.items():
            units = json.loads(archive.read(prefix + "units.json"))
            lbs = json.loads(archive.read(prefix + "limitbursts.json"))
            forms = []
            for uid, unit in units.items():
                for fid, entry in (unit.get("entries") or {}).items():
                    forms.append({"unit_id": uid, "unit_name": unit.get("name"), "form_id": fid,
                                  "limitburst_id": entry.get("limitburst_id")})
            add_source(records, official, contexts, source=region, lbs=lbs, forms=forms)


def wiki_sources(records, official, contexts):
    for region, folder in (("GLW", DATAMINE / "gl"), ("JPW", DATAMINE / "jp")):
        if not folder.exists():
            continue
        units = load_json(folder / "units.json")
        lbs = load_json(folder / "limitbursts.json")
        forms = []
        for uid, unit in units.items():
            for fid, entry in (unit.get("entries") or {}).items():
                forms.append({"unit_id": uid, "unit_name": unit.get("name"), "form_id": fid,
                              "limitburst_id": entry.get("limitburst_id")})
        add_source(records, official, contexts, source=region, lbs=lbs, forms=forms)


def live_source(records, official, contexts):
    lb_file, unit_file = LIVE / "F_LIMITBURST_MST.json", LIVE / "F_UNIT_MST.json"
    if not lb_file.exists() or not unit_file.exists():
        return
    lbs = {str(row.get("lb_id")): row for row in rows(load_json(lb_file)) if row.get("lb_id") is not None}
    forms = []
    for row in rows(load_json(unit_file)):
        forms.append({"unit_id": row.get("unit_id"), "unit_name": row.get("name"), "form_id": row.get("unit_evo_id"),
                      "lb_id": row.get("lb_id")})
    add_source(records, official, contexts, source="LIVE", lbs=lbs, forms=forms)


def source_records():
    records, official, contexts = defaultdict(set), defaultdict(set), defaultdict(list)
    equip_sources(records, official, contexts)
    wiki_sources(records, official, contexts)
    live_source(records, official, contexts)
    return records, official, contexts


def english_sources():
    en = load_json(EN_CACHE).get("lb", {}) if EN_CACHE.exists() else {}
    gloss = load_json(GLOSSARY).get("lb", {}) if GLOSSARY.exists() else {}
    return en, gloss


def sort_id(value):
    return (int(value) if value.isdigit() else 10**30, value)


def write_runtime(records, official, en, gloss):
    """Assemble the tracked runtime helper data from source and reviewed maps.

    IDs retain their own exact Japanese names.  Name-only fallback is emitted
    only where every ID agrees, preventing unrelated/shared names from
    inheriting a title that belongs to another LB.
    """
    manual = {}
    for path in sorted((ROOT / "docs/translations").glob("lb_names_batch*.json")):
        manual.update({k: v for k, v in load_json(path).items() if not k.startswith("_")})
    by_id, candidate_by_name, unresolved, conflict_ids = defaultdict(dict), defaultdict(set), [], {}
    for lid in sorted(records, key=sort_id):
        patch_english = en.get(lid)
        if patch_english and JP_RE.search(patch_english):
            patch_english = None
        official_values = official[lid]
        if len(official_values) > 1:
            conflict_ids[lid] = sorted(official_values)
        for jp in sorted(name for name in records[lid] if JP_RE.search(name)):
            english = manual.get(jp) or patch_english or (next(iter(official_values)) if len(official_values) == 1 else None) or gloss.get(jp)
            if not english or JP_RE.search(english):
                unresolved.append((lid, jp))
                continue
            by_id[lid][jp] = english
            candidate_by_name[jp].add(english)
    if unresolved:
        raise RuntimeError(f"Cannot merge runtime lookup; untranslated ID/name pairs: {unresolved[:20]!r}")
    by_name, name_conflicts = {}, {}
    for jp, values in sorted(candidate_by_name.items()):
        if jp in manual:
            by_name[jp] = manual[jp]
        elif len(values) == 1:
            by_name[jp] = next(iter(values))
        else:
            name_conflicts[jp] = sorted(values)
    payload = {
        "schema": 1,
        "_note": "Generated by tools/build_lb_translation_inventory.py --merge-runtime from local FFBE sources and reviewed editorial batch maps.",
        "sourceCounts": {"lbIds": len(by_id), "idNamePairs": sum(len(names) for names in by_id.values()),
                         "uniqueJapaneseNames": len(candidate_by_name), "nameFallbacks": len(by_name),
                         "conflictedNameFallbacksOmitted": len(name_conflicts),
                         "conflictedOfficialIdsOmittedUnlessEditorial": len(conflict_ids)},
        "byId": {lid: by_id[lid] for lid in sorted(by_id, key=sort_id)},
        "byName": by_name,
        "conflicts": {"names": name_conflicts, "officialIds": conflict_ids},
    }
    (ROOT / "tools/devui/lb_names.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload["sourceCounts"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--merge-runtime", action="store_true", help="also rebuild tools/devui/lb_names.json from the three reviewed batch maps")
    args = parser.parse_args(argv)
    records, official, contexts = source_records()
    en, gloss = english_sources()

    resolved, unresolved = [], []
    for lid in sorted(records, key=sort_id):
        for name in sorted(records[lid]):
            if not JP_RE.search(name):
                continue
            patch_english = en.get(lid)
            if patch_english and JP_RE.search(patch_english):
                patch_english = None
            english = patch_english or next(iter(sorted(official[lid])), None) or gloss.get(name)
            item = {"jp": name, "lbIds": [lid], "contexts": sorted(contexts[lid], key=lambda c: (c["source"], c["unitId"], c["formId"])),
                    "english": english, "provenance": "english_patch" if patch_english else "official_gl" if official[lid] else "glossary" if gloss.get(name) else None}
            (resolved if english else unresolved).append(item)

    # Collapse equivalent JP names across IDs, retaining every id and form.
    by_name = {}
    for item in unresolved:
        target = by_name.setdefault(item["jp"], {"jp": item["jp"], "lbIds": [], "contexts": []})
        target["lbIds"].extend(item["lbIds"])
        target["contexts"].extend(item["contexts"])
    inventory = []
    for name in sorted(by_name):
        item = by_name[name]
        item["lbIds"] = sorted(set(item["lbIds"]), key=sort_id)
        item["contexts"] = sorted({(c["source"], c["unitId"], c["unitName"], c["formId"]) for c in item["contexts"]})
        item["contexts"] = [{"source": s, "unitId": u, "unitName": n, "formId": f} for s, u, n, f in item["contexts"]]
        inventory.append(item)

    OUT.mkdir(parents=True, exist_ok=True)
    summary = {"schema": 1, "sources": ["ffbeEquip GL/JP", "wiki datamine GLW/JPW", "live JP F_LIMITBURST_MST"],
               "officiallyResolvedOccurrences": len(resolved), "unresolvedUniqueJapaneseNames": len(inventory),
               "partition": "sorted by exact JP Unicode name; contiguous thirds"}
    (OUT / "inventory.json").write_text(json.dumps({**summary, "unresolved": inventory}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for i in range(3):
        start, end = len(inventory) * i // 3, len(inventory) * (i + 1) // 3
        payload = {**summary, "batch": i + 1, "start": start, "end": end, "entries": inventory[start:end]}
        (OUT / f"batch{i + 1}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {**summary, "batchCounts": [len(inventory) * (i + 1) // 3 - len(inventory) * i // 3 for i in range(3)]}
    if args.merge_runtime:
        result["runtime"] = write_runtime(records, official, en, gloss)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
