"""Replay generated availability contracts in the canonical Lua 5.4 engine.

This validates the data/runtime interface; it never claims FFR battle coverage.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"build/tooling/ability-runtime-tests"))

REPLAY = r'''
function(module, command)
    local e = module.new({command})
    local key, first, can_spend = command.key, 1, true
    for _,g in ipairs(command.gates) do
        if g.kind == "cooldown" then first=math.max(first,g.availableOnTurn) end
        if g.kind == "charges" and g.startingCharges < g.chargeCost then can_spend=false end
    end
    assert(first <= 512, "fixture warm-up exceeds bounded replay clock")
    local initial = first == 1 and can_spend
    assert(e:begin_battle("battle-1"))
    assert(e:register_owner("battle-1","owner-A",{key}))
    assert(e:begin_turn("battle-1","owner-A",1))
    local allowed = e:query("battle-1","owner-A",key,true)
    assert(allowed == initial, "incorrect initial availability")
    assert(not e:query("battle-1","owner-A",key,false), "native lock lost")
    for turn=2,first do assert(e:begin_turn("battle-1","owner-A",turn)) end
    allowed = e:query("battle-1","owner-A",key,true)
    assert(allowed == can_spend, "incorrect first eligible turn")
    if allowed then
        assert(e:reserve("battle-1","owner-A",key,"cast-1","selection-1",true))
        assert(not e:authorize("battle-1","owner-A",key,"cast-1","wrong-selection",true), "selection identity lost")
        assert(e:authorize("battle-1","owner-A",key,"cast-1","selection-1",true))
        assert(not e:authorize("battle-1","owner-A",key,"cast-1","selection-1",true), "duplicate cast authorized")
        assert(not e:cancel("battle-1","owner-A","cast-1"), "committed cast refunded")
        assert(e:finish_group("battle-1","owner-A","selection-1"))
        local expected = true
        for _,g in ipairs(command.gates) do
            if g.kind == "cooldown" then expected=false end
            if g.kind == "limited" and g.maximumUses <= 1 then expected=false end
            if g.kind == "charges" and g.startingCharges-g.chargeCost < g.chargeCost then expected=false end
        end
        local after = e:query("battle-1","owner-A",key,true)
        assert(after == expected, "incorrect post-cast balance")
        assert(e:set_alive("battle-1","owner-A",false))
        assert(not e:query("battle-1","owner-A",key,true), "dead owner can act")
        assert(e:set_alive("battle-1","owner-A",true))
        after = e:query("battle-1","owner-A",key,true)
        assert(after == expected, "revival reset a spent gate")
    end
    assert(e:register_owner("battle-1","owner-B",{key}))
    assert(e:begin_turn("battle-1","owner-B",1))
    local other = e:query("battle-1","owner-B",key,true)
    assert(other == initial, "gate state leaked between equipping actors")
    for turn=2,first do assert(e:begin_turn("battle-1","owner-B",turn)) end
    local direct = e:authorize("battle-1","owner-B",key,"direct-cast","selection-2",true)
    assert(direct == can_spend, "incorrect execution without prior selection")
    assert(not e:authorize("battle-1","owner-B",key,"direct-cast","selection-2",true), "duplicate direct cast authorized")
    -- Every real candidate retains exact balances across removal/regrant.
    local balances={}
    for gate,data in pairs(e.owners['owner-A'].gates) do
        balances[gate]={used=data.used,held=data.held,charges=data.charges,readyTurn=data.readyTurn}
    end
    assert(e:sync_loadout('battle-1','owner-A',{}))
    assert(not e:query('battle-1','owner-A',key,true),'removed command remained available')
    assert(e:sync_loadout('battle-1','owner-A',{key}))
    for gate,data in pairs(balances) do
        for field,value in pairs(data) do assert(e.owners['owner-A'].gates[gate][field]==value,'regrant reset a gate') end
    end
    assert(e:register_owner('battle-1','late-owner',{}))
    for turn=1,first do assert(e:begin_turn('battle-1','late-owner',turn)) end
    assert(not e:query('battle-1','late-owner',key,true),'empty loadout authorized a command')
    assert(e:sync_loadout('battle-1','late-owner',{key}))
    assert(e:query('battle-1','late-owner',key,true)==can_spend,'late grant used the wrong initial clock or balance')
    assert(e:end_battle("battle-1"))
    assert(not e:query("battle-1","owner-A",key,true), "ended battle accepts actions")
    assert(e:begin_battle("battle-2"))
    assert(e:register_owner("battle-2","owner-A",{key}))
    assert(e:begin_turn("battle-2","owner-A",1))
    local reset = e:query("battle-2","owner-A",key,true)
    assert(reset == initial, "new battle retained old gate state")
    assert(not e:commit("battle-1","owner-A","cast-1",true), "stale callback affected a new battle")
    return can_spend
end
'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plans",type=Path,default=ROOT/"build/abilities/v1/availability-plans.jsonl")
    parser.add_argument("--output",type=Path)
    args=parser.parse_args(argv)
    from lupa.lua54 import LuaRuntime
    lua=LuaRuntime(unpack_returned_tuples=True)
    runtime=ROOT/"tools/ability_converter/runtime/availability.lua"
    module=lua.execute(runtime.read_text(encoding="utf-8"))
    replay=lua.eval(REPLAY)
    counts, gates, failures = Counter(), Counter(), []
    started=time.perf_counter()
    run_report=args.plans.with_name(args.plans.stem+".report.json")
    if json.loads(run_report.read_text(encoding="utf-8")).get("status") != "complete":
        raise ValueError("Availability planning has not completed")
    with args.plans.open(encoding="utf-8") as stream:
        for line in stream:
            result=json.loads(line)
            counts["sourceRecords"]+=1
            try:
                assert not result["playable"] and result["status"] == "blocked"
                assert not result.get("payload") or not result["payload"]["validation"]["tableCompatible"]
                if not result["validation"]["payloadReady"]:
                    continue
                command={"key":result["source"]["key"],"gates":result["gates"]}
                spent=replay(module,lua.table_from(command,recursive=True))
                counts["contractsReplayed"]+=1
                counts["loadoutRegrantsExercised"]+=1
                counts["lateGrantsExercised"]+=1
                counts["firstCastsExercised"]+=bool(spent)
                counts["reservedAuthorizationsExercised"]+=bool(spent)
                counts["directAuthorizationsExercised"]+=bool(spent)
                gates.update(g["kind"] for g in result["gates"])
            except Exception as ex:
                failures.append({"source":result["source"]["key"],"error":str(ex)})
                if len(failures) >= 20:
                    break
    if not counts["contractsReplayed"]:
        failures.append({"error":"No candidate contracts were replayed"})
    with args.plans.open("rb") as stream:
        plans_hash=hashlib.file_digest(stream,"sha256").hexdigest()
    report={"status":"failed" if failures else "passed", **dict(counts), "gates":dict(gates),
            "validation":{"isolatedLua":"passed" if not failures else "failed", "nativeBattle":"not_run",
                          "executionGate":"unbound", "dualWieldBinding":"unbound",
                          "logicalCastAuthorization":"passed" if not failures else "failed"},
            "lua":lua.lua_implementation, "failures":failures,
            "elapsedSeconds":round(time.perf_counter()-started,3),
            "plansSha256":plans_hash,"runtimeSha256":hashlib.sha256(runtime.read_bytes()).hexdigest()}
    output=args.output or args.plans.with_name("availability-runtime-verification.json")
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
