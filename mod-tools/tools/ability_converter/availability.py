"""Availability contracts and held payload plans, never unrestricted exports.

These contracts are executable by runtime/availability.lua. They deliberately
do not certify an FFR hook: an ordinary table export still rejects the source.
"""
from copy import deepcopy
from dataclasses import replace

GATE_CODES = (130, 157, 1014)
SCHEMA_VERSION = "ffbe-ffr-availability/1"
BINDING_HOLD = "Availability needs an authoritative FFR execution gate and battle/owner/turn lifecycle binding"


def decode(code, parameters, source_id):
    # Import here so the ordinary component adapter can share this decoder.
    from .adapters import integer
    p = parameters
    if not isinstance(p, list):
        raise ValueError("Availability parameters must be an array")
    def value(index, label, minimum=0, maximum=2147483647):
        return integer(p[index], label, minimum, maximum)
    if code == 130:
        if len(p) not in (3, 4) or not isinstance(p[2], list) or len(p[2]) != 2:
            raise ValueError("Unknown cooldown parameter layout")
        value(1, "cooldown mode", 0, 1)
        turns = integer(p[2][0], "cooldown", 0, 2147483646) + 1
        initial = turns - integer(p[2][1], "initial cooldown reduction", 0, turns - 1)
        no_dw = value(3, "dual-wield flag", 0, 1) if len(p) == 4 else 0
        return {"kind":"cooldown", "childId":str(value(0, "child ID", 1)),
                "cooldownTurns":turns, "availableOnTurn":initial,
                "singleCastWhenDualWielding":no_dw == 0}
    if code == 157:
        if len(p) != 9:
            raise ValueError("Unknown limited-use parameter layout")
        value(1, "limited-use mode", 0, 1)
        uses = value(2, "maximum uses", 1)
        # The formatter names these fields unknown. The observed ordinary
        # layout repeats the limit, then 1,1,flags,0. Preserve other layouts
        # as holds instead of silently ignoring a possible restriction.
        if p[3] != uses or p[4:6] != [1,1] or p[8] != 0:
            raise ValueError("Unresolved limited-use control parameters")
        return {"kind":"limited", "childId":str(value(0, "child ID", 1)),
                "maximumUses":uses,
                "singleCastWhenDualWielding":value(6, "dual-wield flag", 0, 1) == 0,
                "uniqueSelectionOnMulticast":value(7, "multicast flag", 0, 1) == 0}
    if code == 1014:
        if len(p) != 6 or p[1] != 2:
            raise ValueError("Unknown charge-limit parameter layout")
        maximum = value(3, "maximum charges", 1)
        starting = value(2, "starting charges", 0, maximum)
        cost = value(4, "charge cost", 1, maximum)
        reference = str(value(0, "charge reference ID", 1))
        return {"kind":"charges", "referenceId":reference,
                "appliesToSelf":reference == str(source_id),
                "startingCharges":starting, "maximumCharges":maximum, "chargeCost":cost,
                "rechargeable":value(5, "recharge flag", 0, 1) == 1}
    raise ValueError(f"No availability decoder for opcode {code}")


def has_gate(record):
    return record.namespace == "active" and any(
        isinstance(raw, list) and len(raw) == 4 and raw[2] in GATE_CODES
        for raw in record.data.get("effects_raw", []))


def plan(record, resolver=None, compiler=None):
    """Separate a command's gates from a candidate payload without releasing it.

    Cooldown/limited-use components call children; a self charge component is
    a constraint on the current body. Other charge references remain held
    until shared-pool ownership is established. Nested restricted children
    remain held by the normal compiler, including through immediate proxies.
    """
    from .commands import RecordingResolver, SNAPSHOT_VERSION, application_frames, damage_phase_bindings
    from .compiler import Converter, TableWriter
    from dataclasses import asdict
    captured = RecordingResolver(record, resolver)
    result = {"schemaVersion":SCHEMA_VERSION, "source":record.provenance(), "name":record.data.get("name"),
              "status":"blocked", "playable":False, "bindingHold":BINDING_HOLD,
              "turnClock":"equipping_actor_turn", "turnAdaptation":"FFBE turn counts use the equipping actor's FFR turn opportunities; native turn events still need validation.",
              "validation":{"rulesDecoded":False, "payloadReady":False, "runtime":"not_run"},
              "gates":[], "issues":[], "payload":None}
    data = deepcopy(record.data)
    try:
        if not has_gate(record) or record.kind not in ("ability", "magic"):
            raise ValueError("Availability plans require a player ability with a supported availability component")
        for index, raw in enumerate(record.data["effects_raw"]):
            if not isinstance(raw, list) or len(raw) != 4 or raw[2] not in GATE_CODES:
                continue
            gate = decode(raw[2], raw[3], record.id)
            gate.update(key=f"{record.key}/component/{index}", component=index,
                        sourceOpcode=raw[2], raw=deepcopy(raw), owner="equipping_actor")
            result["gates"].append(gate)
            if gate["kind"] == "charges":
                if gate["appliesToSelf"]:
                    data["effects_raw"][index] = [0,3,0,[]]
            else:
                data["effects_raw"][index] = [0,3,71,[int(gate["childId"]),1]]
        result["validation"]["rulesDecoded"] = True
        if any(g["kind"] == "charges" and not g["appliesToSelf"] for g in result["gates"]):
            raise ValueError("External charge reference needs verified shared-pool ownership; it is not a child action")
        from copy import copy
        engine = copy(compiler) if compiler is not None else Converter()
        engine.resolver = captured
        body = engine.convert(replace(record, data=data))
        result["issues"].extend(body["issues"])
        if body["validation"]["tableCompatible"]:
            frames = application_frames(body)
            if not frames or any(type(f) is not int or f < 0 for f in frames):
                raise ValueError("Availability payload needs verified application frames")
            move = data.get("move_type", 0)
            if move not in (None, 0, 1, 4):
                raise ValueError(f"Movement type {move} needs a command movement adapter")
            phases = damage_phase_bindings(body)
            result["timeline"] = {"hitFrames":frames, "moveType":move or 0, "effectPhases":phases}
            result["description"] = TableWriter.description(body)
            result["validation"]["payloadReady"] = True
        # Even the nested candidate rejects TableWriter.add. The original
        # snapshot is the only rebuild input, not the gate-stripped body.
        body["validation"]["tableCompatible"] = False
        body["validation"]["availabilityBindingRequired"] = True
        body["status"] = "blocked"
        body["issues"].append(BINDING_HOLD)
        result["payload"] = body
        result["costPolicy"] = "The root command pays its native MP/LB costs once; immediate child MP is not charged again. Other child resource restrictions stay held."
    except (ValueError, TypeError, KeyError, IndexError) as ex:
        result["issues"].append(str(ex))
    result["snapshot"] = {"schemaVersion":SNAPSHOT_VERSION, "root":record.key,
                          "records":[asdict(r) for r in captured.records.values()]}
    return result


def write_plans(args):
    """Inspect an existing source index read-only; emit no native table rows."""
    from collections import Counter
    import json
    from .catalog import SourceCatalog
    from .compiler import Converter
    from .runs import file_hashes, implementation_hashes, require_current_run, require_matching
    compiler = Converter(args.artifacts)
    require_current_run(args.out, compiler)
    implementation = implementation_hashes(runtime=True)
    output = args.output or args.out/"availability-plans.jsonl"
    report_path = output.with_name(output.stem+".report.json")
    protected = {args.out/name for name in ("run.json", "source-index.sqlite", "converted.jsonl", "native-rows.jsonl",
        "bindings.jsonl", "strings.jsonl", "review.jsonl", "graph.json", "ids.json", "report.json", "registry.json",
        "verification.json", "README.md")}
    if any(p.resolve() in {p.resolve() for p in protected} for p in (output,report_path)):
        raise ValueError("Availability output cannot overwrite an existing conversion artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps({"schemaVersion":SCHEMA_VERSION,"status":"running"})+"\n",encoding="utf-8")
    counts, reasons, kinds = Counter(), Counter(), Counter()
    with SourceCatalog.open_existing(args.out/"source-index.sqlite") as catalog, output.open("w", encoding="utf-8") as stream:
        records = [catalog.get(args.id)] if args.id else catalog
        for record in records:
            if not has_gate(record):
                continue
            result = plan(record, catalog, compiler)
            stream.write(json.dumps(result, ensure_ascii=False, separators=(",",":"))+"\n")
            counts["records"] += 1
            counts["rulesDecoded"] += result["validation"]["rulesDecoded"]
            counts["payloadReady"] += result["validation"]["payloadReady"]
            for gate in result["gates"]:
                kinds[gate["kind"]] += 1
            reasons.update(result["issues"])
            if args.limit and counts["records"] >= args.limit:
                break
    if not counts["records"]:
        raise ValueError("No availability-gated source records matched")
    require_matching(implementation, implementation_hashes(runtime=True), "implementation")
    require_matching(compiler.artifacts, file_hashes(compiler.artifact_paths), "conversion inputs")
    report = {"schemaVersion":SCHEMA_VERSION, "status":"complete", **dict(counts), "gates":dict(kinds),
              "playable":0, "runtime":"not_run", "bindingHold":BINDING_HOLD,
              "issues":dict(reasons.most_common()), "output":str(output),
              "artifacts":compiler.artifacts, "implementation":implementation}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in ("implementation","issues")}, ensure_ascii=False, indent=2))
    return 0


def write_probe(args):
    """Stage the optional read-only observer; do not install or enable it."""
    import shutil
    from pathlib import Path
    directory = args.output or args.out/"runtime-probe/FFRAvailabilityProbe"
    scripts = directory/"Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    runtime = Path(__file__).parent/"runtime"
    shutil.copyfile(runtime/"probe.lua",scripts/"availability_probe.lua")
    shutil.copyfile(runtime/"probe_main.lua",scripts/"main.lua")
    shutil.copyfile(runtime/"README.md",directory/"README.md")
    print(f"Staged optional observation mod at {directory}; not installed or enabled")
    return 0
