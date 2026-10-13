"""Batch conversion, single-record inspection and native mechanics exports."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time
import tempfile

from .catalog import SourceCatalog
from .general import TABLE as GENERAL_TABLE
from .compiler import Converter, SCHEMA_VERSION, TableWriter
from .graph import SkillGraph
from .sources import ARTIFACTS, DEFAULT_DATAMINE, ROOT, iter_sources, read
from .runs import file_hashes, implementation_hashes, require_current_run, require_matching


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def line(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(",",":"))+"\n")


def source_options(args):
    return dict(datamine=args.datamine, client=args.client, archive=args.archive,
                sources=tuple(args.sources.split(",")), all_levels=not args.max_level)


def populate(catalog, args):
    for record in iter_sources(**source_options(args)):
        catalog.add(record)
        if catalog.count % 50000 == 0:
            print(f"Indexed {catalog.count:,} source records for reference resolution", file=sys.stderr, flush=True)
    catalog.finish()


def build(args):
    args.out.mkdir(parents=True, exist_ok=True)
    # Reject an old/incompatible ledger before clearing the source index or
    # changing the completion marker of the previous catalog.
    if (args.out/"ids.json").exists():
        TableWriter(Converter(args.artifacts).native, read(args.out/"ids.json"))
    dump(args.out/"run.json",{"status":"running","schemaVersion":SCHEMA_VERSION})
    with SourceCatalog(args.out/"source-index.sqlite") as catalog:
        populate(catalog, args)
        return build_catalog(args, catalog)


def build_catalog(args, catalog):
    converter = Converter(args.artifacts, resolver=catalog)
    ledger_path = args.out/"ids.json"
    writer = TableWriter(converter.native, read(ledger_path) if ledger_path.exists() else None)
    graph = SkillGraph()
    counts, components, reasons, by_source, by_kind = Counter(), Counter(), Counter(), defaultdict(Counter), defaultdict(Counter)
    codes = defaultdict(Counter)
    source_paths, source_hashes = catalog.paths, {}
    started = time.monotonic()
    implementation = implementation_hashes()
    dump(args.out/"run.json",{"status":"running","schemaVersion":SCHEMA_VERSION})
    options = source_options(args)
    total = 0
    with (args.out/"converted.jsonl").open("w",encoding="utf-8") as records, \
         (args.out/"native-rows.jsonl").open("w",encoding="utf-8") as native_rows, \
         (args.out/"bindings.jsonl").open("w",encoding="utf-8") as bindings, \
         (args.out/"strings.jsonl").open("w",encoding="utf-8") as strings, \
         (args.out/"review.jsonl").open("w",encoding="utf-8") as review:
        for record in catalog:
            if args.id and record.id != args.id and record.key != args.id:
                continue
            result = converter.convert(record)
            graph.add(result)
            counts[result["status"]] += 1
            by_source[record.source][result["status"]] += 1
            by_kind[record.kind][result["status"]] += 1
            source_paths.add(record.path.split("!",1)[0])
            for component in result["components"]:
                components[component["status"]] += 1
                codes[component.get("key","malformed")][component["status"]] += 1
            if result["validation"]["tableCompatible"]:
                result["destinationId"] = writer.add(result)
                for table, changes in writer.tables.items():
                    for row in changes["add"]:
                        line(native_rows, {"table":table, **row})
                for binding in writer.bindings:
                    line(bindings, binding)
                for table, entries in writer.strings.items():
                    for key, value in entries.items():
                        line(strings, {"table":table, "key":key, "value":value})
                writer.tables.clear(); writer.bindings.clear(); writer.strings.clear()
            else:
                line(review, {"source":result["source"],"name":result["name"],"status":result["status"],"issues":result["issues"]})
            for issue in result["issues"]:
                reason = issue.split(": ",1)[-1] if issue.startswith("Component ") else issue
                reasons[reason] += 1
            line(records, result)
            total += 1
            if total % 10000 == 0:
                print(f"Converted {total:,} records; {sum(v for k,v in counts.items() if k not in ('blocked','noop')):,} table-compatible", file=sys.stderr, flush=True)
            if args.limit and total >= args.limit:
                break
        if general := writer.general.patch():
            for change in general["set"]:
                line(native_rows, {"table":GENERAL_TABLE, "operation":"set", **change})
    resolved = graph.resolve(catalog)
    dump(args.out/"graph.json", resolved)
    for source_path in sorted(source_paths):
        path = Path(source_path)
        if path.is_file():
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            source_hashes[source_path] = {"bytes":path.stat().st_size,"sha256":digest}
    dump(ledger_path, writer.ledger)
    report = {"schemaVersion":SCHEMA_VERSION, "records":total, "indexedRecords":catalog.count,
              "statuses":dict(counts), "components":dict(components),
              "bySource":dict(by_source),"byKind":dict(by_kind),"opcodes":dict(sorted(codes.items())),
              "listedOpcodes":len(converter.registry), "encounteredOpcodes":len(set(codes)-{"malformed"}),
              "malformedComponents":sum(codes.get("malformed",{}).values()),
              "fullyEmittedOpcodes":[k for k,v in codes.items() if not v.get("blocked")],
              "blockedReasons":dict(reasons.most_common()),
              "graph":{"nodes":resolved["nodes"],"edges":len(resolved["edges"]),"missing":len(resolved["missing"]),
                       "ambiguous":len(resolved["ambiguous"]),"cycles":len(resolved["cycles"])},
              "validation":{"nativeRows":"validated during conversion", "runtime":"not_run", "cookedPackages":"not_generated"},
              "artifacts":converter.artifacts,"sources":source_hashes,"options":{k:str(v) for k,v in options.items()},
              "elapsedSeconds":round(time.monotonic()-started,2)}
    report["implementation"] = implementation
    dump(args.out/"report.json", report)
    dump(args.out/"registry.json",[{**rule,"outcomes":dict(codes.get(key,{}))}
                                  for key,rule in sorted(converter.registry.items())])
    compatible = sum(n for k,n in counts.items() if k not in ("blocked","noop"))
    lines = ["# FFBE → FFR ability conversion", "", f"Schema: `{SCHEMA_VERSION}`.", "",
             f"Processed **{total:,}** source records. **{compatible:,}** have native-compatible mechanics rows; **{counts['blocked']:,}** retain blocking issues.",
             "", "Table compatibility is not in-game verification. Sequencers, commands, resonance costs and equipping-actor ownership must be bound by the consumer before installation.",
             "", "| Status | Records |", "|---|---:|"]
    lines += [f"| {k} | {v:,} |" for k,v in counts.items()]
    lines += ["", "Every raw component and source identity is retained in `converted.jsonl`. `native-rows.jsonl` contains cloneFrom/set patches only for compatible entries. `bindings.jsonl` and `strings.jsonl` are required companion data. `review.jsonl` lists held entries, and `graph.json` resolves regional child references and detects cycles.",
              "", "## Most common held mechanics", ""]
    lines += [f"- {n:,}: {reason}" for reason,n in reasons.most_common(15)]
    (args.out/"README.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    require_matching(implementation, implementation_hashes(), "implementation")
    require_matching(converter.artifacts, file_hashes(converter.artifact_paths), "conversion inputs")
    dump(args.out/"run.json",{"status":"complete","schemaVersion":SCHEMA_VERSION,"records":total})
    print(json.dumps({k:report[k] for k in ("records","statuses","components","encounteredOpcodes","graph","elapsedSeconds")},indent=2))
    return 1 if not total or args.strict and counts["blocked"] else 0


def one(args):
    matches = 0
    with tempfile.TemporaryDirectory(prefix="ffbe-source-") as temporary, \
         SourceCatalog(Path(temporary)/"sources.sqlite") as catalog:
        populate(catalog, args)
        converter = Converter(args.artifacts, resolver=catalog)
        for record in catalog:
            if record.id == args.id or record.key == args.id:
                print(json.dumps(converter.convert(record),ensure_ascii=False,indent=2))
                matches += 1
                if args.limit and matches >= args.limit:
                    break
    if not matches:
        print(f"No source record matches {args.id}",file=sys.stderr)
    return 0 if matches else 1


def export(args):
    converter = Converter(args.artifacts)
    require_current_run(args.out, converter)
    ledger_path = args.out/"ids.json"
    writer = TableWriter(converter.native, read(ledger_path) if ledger_path.exists() else None)
    found = None
    with (args.out/"converted.jsonl").open(encoding="utf-8") as stream:
        for raw in stream:
            record = json.loads(raw)
            if record["source"]["key"] == args.id:
                found = record
                break
    if not found:
        raise ValueError("Export needs an exact source key from converted.jsonl")
    writer.add(found)
    target = args.output or args.out/"selected-ability.json"
    dump(target, {"schemaVersion":SCHEMA_VERSION, **writer.patch(args.out/"selected-assets"),
                  "strings":writer.strings,"source":found["source"]})
    print(target)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("convert","one","report","export","verify","availability","availability-probe"),nargs="?",default="convert")
    parser.add_argument("id",nargs="?")
    parser.add_argument("--datamine",type=Path,default=DEFAULT_DATAMINE)
    parser.add_argument("--client",type=Path,default=ROOT/"build/devui/live_jp")
    parser.add_argument("--archive",type=Path,default=Path("S:/ffbeEquip-master.zip") if Path("S:/ffbeEquip-master.zip").exists() else None)
    parser.add_argument("--no-archive",action="store_true",help="Exclude the older FFBE Equip snapshots")
    parser.add_argument("--sources",default="gl,jp,client")
    parser.add_argument("--artifacts",type=Path,default=ARTIFACTS)
    parser.add_argument("--out",type=Path,default=ROOT/"build/abilities/v1")
    parser.add_argument("--output",type=Path)
    parser.add_argument("--limit",type=int)
    parser.add_argument("--max-level",action="store_true",help="Only the highest LB level per source")
    parser.add_argument("--strict",action="store_true",help="Exit nonzero if any source record is held")
    args = parser.parse_args(argv)
    if args.no_archive:
        args.archive = None
    if args.command in ("one","export") and not args.id:
        parser.error("one/export requires an ID (export requires its full source key)")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    if any(v not in ("gl","jp","client") for v in args.sources.split(",")):
        parser.error("--sources accepts gl,jp,client")
    try:
        if args.command == "availability":
            from .availability import write_plans
            return write_plans(args)
        if args.command == "availability-probe":
            from .availability import write_probe
            return write_probe(args)
        if args.command == "report":
            print(json.dumps(read(args.out/"report.json"),ensure_ascii=False,indent=2))
            return 0
        if args.command == "verify":
            from .verify import verify
            report = verify(Converter(args.artifacts),args.out,args.limit or 256)
            print(json.dumps({k:v for k,v in report.items() if k not in ("selected","coveredOpcodes")},indent=2))
            return 0
        return {"convert":build,"one":one,"export":export}[args.command](args)
    except (ValueError, OSError) as ex:
        print(f"Conversion failed: {ex}",file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
