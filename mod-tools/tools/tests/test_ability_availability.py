"""Availability decoding, non-exportable plans and the real Lua state engine."""
from copy import deepcopy
import importlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
sys.path.insert(0, str(ROOT/"build/tooling/ability-runtime-tests"))
from ability_converter import Converter, SourceRecord
from ability_converter.availability import decode, plan, write_plans, write_probe
from ability_converter.catalog import SourceCatalog
from ability_converter.commands import SnapshotResolver, from_snapshot
from ability_converter.compiler import SCHEMA_VERSION, TableWriter
from ability_converter.graph import SkillGraph
from ability_converter.runs import implementation_hashes


def source(sid, effects, **extra):
    return SourceRecord("TEST", "ability", str(sid), {
        "name":"Availability fixture", "effects_raw":effects,
        "attack_frames":[[12,24]], "attack_damage":[[40,60]], "mp_cost":20, **extra})


class AvailabilityPlans(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = Converter()

    def test_cooldown_initial_turn_and_missing_dual_wield_flag(self):
        rule = decode(130, [2,1,[4,4]], "1")
        self.assertEqual((rule["cooldownTurns"],rule["availableOnTurn"]), (5,1))
        self.assertTrue(rule["singleCastWhenDualWielding"])
        self.assertEqual(decode(130,[2,1,[4,0],1],"1")["availableOnTurn"],5)
        for parameters in ([2,1,[4,5],0], [2,1,[4,-1],0], [2,1,[4,4],2], [2,1,[4,4],0,1]):
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                decode(130, parameters, "1")

    def test_limited_flags_are_boolean_with_correct_polarity(self):
        rule = decode(157, [2,1,3,3,1,1,0,0,0], "1")
        self.assertEqual(rule["maximumUses"],3)
        self.assertTrue(rule["singleCastWhenDualWielding"])
        self.assertTrue(rule["uniqueSelectionOnMulticast"])
        rule = decode(157,[2,1,3,3,1,1,1,1,0],"1")
        self.assertFalse(rule["singleCastWhenDualWielding"])
        self.assertFalse(rule["uniqueSelectionOnMulticast"])
        with self.assertRaisesRegex(ValueError,"control parameters"):
            decode(157,[2,1,3,3,1,0,1,1,0],"1")

    def test_charge_self_reference_is_not_an_execution_cycle(self):
        record = source(1, [[0,3,1014,[1,2,3,5,2,1]], [2,1,1,[0,0,0,0,0,0,500,0]]])
        result = self.compiler.convert(record)
        self.assertEqual(result["status"],"blocked")
        self.assertEqual(result["dependencies"][0]["relation"],"charge_pool")
        graph = SkillGraph(); graph.add(result)
        self.assertEqual(graph.resolve()["cycles"],[])
        self.assertEqual(graph.resolve()["missing"],[])
        contract = plan(record, compiler=self.compiler)
        self.assertTrue(contract["validation"]["payloadReady"], contract["issues"])
        self.assertEqual(contract["timeline"]["hitFrames"],[12,24])
        self.assertTrue(contract["gates"][0]["rechargeable"])
        with self.assertRaises(ValueError):
            TableWriter(self.compiler.native).add(contract["payload"])
        self.assertFalse(from_snapshot(contract["snapshot"])["supported"])

    def test_external_charge_reference_stays_a_non_executing_hold(self):
        record = source(1, [[0,3,1014,[2,2,1,1,1,0]]])
        converted = self.compiler.convert(record)
        graph = SkillGraph(); graph.add(converted)
        self.assertEqual(len(graph.resolve()["missing"]),1)
        self.assertEqual(converted["dependencies"][0]["relation"],"charge_pool")
        result = plan(record, compiler=self.compiler)
        self.assertFalse(result["validation"]["payloadReady"])
        self.assertIn("shared-pool",result["issues"][0])

    def test_wrapper_payload_keeps_child_hits_parent_cost_and_original_snapshot(self):
        root = source(1, [[0,3,130,[2,1,[4,4],0]]], mp_cost=50, attack_frames=[[0]])
        child = source(2, [[2,1,1,[0,0,0,0,0,0,500,0]]], mp_cost=80)
        with SourceCatalog() as catalog:
            catalog.add(root); catalog.add(child); catalog.finish()
            result = plan(root,catalog,self.compiler)
        self.assertTrue(result["validation"]["payloadReady"],result["issues"])
        self.assertEqual(result["payload"]["native"]["set"]["Cost"],75)
        self.assertEqual(result["timeline"]["hitFrames"],[12,24])
        self.assertFalse(result["playable"])
        self.assertEqual(SnapshotResolver(result["snapshot"]).root.data,root.data)
        self.assertFalse(from_snapshot(result["snapshot"])["supported"])
        self.assertEqual(len(result["snapshot"]["records"]),2)

    def test_missing_wrong_revision_and_restricted_children_cannot_become_payloads(self):
        root = source(1,[[0,3,130,[2,1,[4,4],0]]])
        child = source(2,[[0,3,157,[3,1,1,1,1,1,0,0,0]]])
        with SourceCatalog() as catalog:
            catalog.add(root); catalog.add(child); catalog.finish()
            result = plan(root,catalog,self.compiler)
        self.assertFalse(result["validation"]["payloadReady"])
        self.assertIn("blocking issues", " ".join(result["issues"]))
        self.assertFalse(plan(root,compiler=self.compiler)["validation"]["payloadReady"])

    def test_read_only_catalog_never_rebuilds_existing_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"catalog.sqlite"
            root = source(1,[[0,3,0,[]]])
            with SourceCatalog(path) as catalog:
                catalog.add(root); catalog.finish()
            original = path.read_bytes()
            with SourceCatalog.open_existing(path) as catalog:
                self.assertEqual(catalog.count,1)
                self.assertEqual(catalog.get(root.key).data,root.data)
                with self.assertRaises(sqlite3.OperationalError): catalog.add(source(2,[[0,3,0,[]]]))
            self.assertEqual(path.read_bytes(),original)

    def test_cli_plans_and_probe_preserve_conversion_artifacts_and_stay_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path/"run.json").write_text(json.dumps({"status":"complete","schemaVersion":SCHEMA_VERSION,"records":1}))
            original_report = json.dumps({"schemaVersion":SCHEMA_VERSION,"records":1,
                "implementation":implementation_hashes(),"artifacts":self.compiler.artifacts})
            (path/"report.json").write_text(original_report)
            root = source(1, [[0,3,1014,[1,2,1,1,1,0]], [2,1,1,[0,0,0,0,0,0,500,0]]])
            with SourceCatalog(path/"source-index.sqlite") as catalog:
                catalog.add(root); catalog.finish()
            original = (path/"source-index.sqlite").read_bytes()
            from ability_converter.sources import ARTIFACTS
            args = SimpleNamespace(out=path, output=None, id=None, limit=None, artifacts=ARTIFACTS)
            from contextlib import redirect_stdout
            import io
            with redirect_stdout(io.StringIO()):
                write_plans(args); write_plans(args); write_probe(args)
            report = json.loads((path/"availability-plans.report.json").read_text())
            self.assertEqual((report["records"],report["payloadReady"],report["playable"]),(1,1,0))
            self.assertEqual(report["status"],"complete")
            self.assertEqual((path/"source-index.sqlite").read_bytes(),original)
            self.assertEqual((path/"report.json").read_text(),original_report)
            self.assertTrue((path/"runtime-probe/FFRAvailabilityProbe/Scripts/main.lua").is_file())
            self.assertFalse(list((path/"runtime-probe").rglob("enabled.txt")))
            args.output=path/"report.json"
            with self.assertRaisesRegex(ValueError,"cannot overwrite"): write_plans(args)


class AvailabilityRuntime(unittest.TestCase):
    """The same Lua module is executed in Lua 5.4, with no Python mirror."""
    @classmethod
    def setUpClass(cls):
        try:
            cls.lupa = importlib.import_module("lupa.lua54")
        except ImportError as ex:
            raise RuntimeError("Install tools/tests/requirements-ability-runtime.txt; runtime tests require Lupa") from ex

    def setUp(self):
        self.lua = self.lupa.LuaRuntime(unpack_returned_tuples=True)
        self.module = self.lua.execute((ROOT/"tools/ability_converter/runtime/availability.lua").read_text())

    def engine(self, rules):
        commands = []
        for key,code,p in rules:
            rule = decode(code,p,"1")
            rule.update(key=key+"/gate", owner="equipping_actor")
            commands.append({"key":key,"gates":[rule]})
        engine = self.module.new(self.lua.table_from(commands, recursive=True))
        self.call(engine,"begin_battle","battle-1")
        self.call(engine,"register_owner","battle-1","owner-A",self.lua.table_from([r[0] for r in rules]))
        self.call(engine,"begin_turn","battle-1","owner-A",1)
        return engine

    def call(self, engine, method, *args):
        return engine[method](engine,*args)

    def cast(self,engine,command,token,group=None,owner="owner-A"):
        reserved = self.call(engine,"reserve","battle-1",owner,command,token,group or token,True)
        self.assertTrue(reserved[0],reserved)
        committed = self.call(engine,"commit","battle-1",owner,token,True)
        self.assertTrue(committed[0],committed)

    def query(self,engine,command,owner="owner-A",native=True,group=None):
        return self.call(engine,"query","battle-1",owner,command,native,group)

    def test_cooldown_boundary_duplicate_turn_and_other_owner_independence(self):
        e=self.engine([("cool",130,[2,1,[4,4],0])])
        self.cast(e,"cool","cast-1")
        self.assertEqual(self.query(e,"cool"),(False,"cooldown"))
        self.assertEqual(self.call(e,"begin_turn","battle-1","owner-A",1),(False,"duplicate_turn"))
        for turn in range(2,6):
            self.assertTrue(self.call(e,"begin_turn","battle-1","owner-A",turn)[0])
            self.assertFalse(self.query(e,"cool")[0])
        self.call(e,"register_owner","battle-1","owner-B",self.lua.table_from(["cool"]))
        self.call(e,"begin_turn","battle-1","owner-B",1)
        self.assertTrue(self.query(e,"cool",owner="owner-B")[0])
        self.call(e,"begin_turn","battle-1","owner-A",6)
        self.assertTrue(self.query(e,"cool")[0])

    def test_native_lock_cannot_be_overridden_or_spend_a_use(self):
        e=self.engine([("limited",157,[2,1,1,1,1,1,0,0,0])])
        self.assertEqual(self.query(e,"limited",native=False),(False,"native_unavailable"))
        self.assertTrue(self.call(e,"reserve","battle-1","owner-A","limited","a","g",True)[0])
        self.assertEqual(self.call(e,"commit","battle-1","owner-A","a",False),(False,"native_unavailable"))
        self.cast(e,"limited","b")
        self.assertFalse(self.query(e,"limited")[0])

    def test_execution_authorization_with_and_without_prior_selection(self):
        for selected in (False, True):
            with self.subTest(selected=selected):
                e=self.engine([("limited",157,[2,1,2,2,1,1,1,1,0])])
                if selected:
                    self.assertTrue(self.call(e,"reserve","battle-1","owner-A","limited","cast-1","group",True)[0])
                self.assertEqual(self.call(e,"authorize","battle-1","owner-A","limited","cast-1","group",True),(True,"committed"))
                self.assertFalse(self.call(e,"authorize","battle-1","owner-A","limited","cast-1","group",True)[0])
                self.assertTrue(self.query(e,"limited")[0])
                self.assertTrue(self.call(e,"authorize","battle-1","owner-A","limited","cast-2","group",True)[0])
                self.assertEqual(self.query(e,"limited"),(False,"uses_exhausted"))

    def test_execution_native_rejection_releases_selection_without_spending(self):
        for selected in (False, True):
            with self.subTest(selected=selected):
                e=self.engine([("limited",157,[2,1,1,1,1,1,0,0,0])])
                if selected:
                    self.assertTrue(self.call(e,"reserve","battle-1","owner-A","limited","cast-1","group",True)[0])
                self.assertEqual(self.call(e,"authorize","battle-1","owner-A","limited","cast-1","group",False),(False,"native_unavailable"))
                self.assertTrue(self.query(e,"limited")[0])
                self.assertTrue(self.call(e,"begin_turn","battle-1","owner-A",2)[0])
                self.assertFalse(self.call(e,"authorize","battle-1","owner-A","limited","cast-1","group",True)[0])
                self.assertTrue(self.call(e,"authorize","battle-1","owner-A","limited","cast-2","group-2",True)[0])

    def test_execution_mismatched_command_group_and_refill_cannot_steal_reservation(self):
        e=self.engine([("A",157,[2,1,1,1,1,1,0,0,0]),("B",1014,[1,2,2,2,1,1])])
        self.assertTrue(self.call(e,"reserve","battle-1","owner-A","A","cast-1","group",True)[0])
        for command,group in (("B","group"),("A","other"),("unknown","group")):
            self.assertEqual(self.call(e,"authorize","battle-1","owner-A",command,"cast-1",group,True),(False,"action_identity_mismatch"))
        self.assertTrue(self.call(e,"authorize","battle-1","owner-A","A","cast-1","group",True)[0])
        self.assertTrue(self.call(e,"refill","battle-1","owner-A","B/gate",1,"refill")[0])
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","B","refill","group",True),(False,"action_identity_mismatch"))
        self.assertTrue(self.call(e,"authorize","battle-1","owner-A","B","cast-2","group",True)[0])

    def test_execution_denial_tokens_are_bounded_and_cannot_revive_after_cooldown(self):
        e=self.engine([("cool",130,[2,1,[1,0],0])])
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","cool","early","group",True),(False,"cooldown"))
        self.assertTrue(self.call(e,"begin_turn","battle-1","owner-A",2)[0])
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","cool","early","group",True),(False,"not_reserved"))
        self.assertTrue(self.call(e,"authorize","battle-1","owner-A","cool","later","group-2",True)[0])
        e=self.engine([("A",157,[2,1,1,1,1,1,0,0,0])])
        for index in range(8193):
            self.assertFalse(self.call(e,"authorize","battle-1","owner-A","A",str(index),"group",False)[0])
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","A","over-capacity","group",True),(False,"event_capacity"))
        self.assertEqual(e["owners"]["owner-A"]["events"],8192)
        self.assertEqual(e["owners"]["owner-A"]["gates"]["A/gate"]["used"],0)

    def test_execution_unbound_dead_departed_and_stale_owners_do_not_authorize(self):
        e=self.engine([("A",157,[2,1,1,1,1,1,0,0,0])])
        self.assertEqual(self.call(e,"authorize","battle-1","vision","A","cast","group",True),(False,"unbound_owner"))
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","unknown","cast","group",True),(False,"unbound_command"))
        self.call(e,"set_alive","battle-1","owner-A",False)
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","A","cast","group",True),(False,"owner_dead"))
        self.call(e,"set_alive","battle-1","owner-A",True)
        self.assertFalse(self.call(e,"authorize","battle-1","owner-A","A","cast","group",True)[0])
        self.assertTrue(self.call(e,"authorize","battle-1","owner-A","A","revived-cast","group",True)[0])
        self.call(e,"depart","battle-1","owner-A")
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","A","cast-2","group",True),(False,"owner_departed"))
        self.call(e,"end_battle","battle-1")
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","A","cast-3","group",True),(False,"stale_battle"))

    def test_cancel_releases_reservation_duplicate_hits_never_recommit(self):
        e=self.engine([("limited",157,[2,1,1,1,1,1,0,0,0])])
        self.call(e,"reserve","battle-1","owner-A","limited","a","g",True)
        self.assertFalse(self.query(e,"limited")[0])
        self.call(e,"cancel","battle-1","owner-A","a")
        self.cast(e,"limited","b")
        for _ in range(20):
            self.assertEqual(self.call(e,"commit","battle-1","owner-A","b",True),(False,"not_reserved"))
        self.assertFalse(self.call(e,"cancel","battle-1","owner-A","b")[0])
        self.assertFalse(self.query(e,"limited")[0])

    def test_unique_multicast_selection_and_closed_group(self):
        e=self.engine([("limited",157,[2,1,3,3,1,1,0,0,0])])
        self.call(e,"reserve","battle-1","owner-A","limited","a","multicast",True)
        self.assertEqual(self.query(e,"limited",group="multicast"),(False,"unique_selection"))
        self.call(e,"commit","battle-1","owner-A","a",True)
        self.assertEqual(self.query(e,"limited",group="multicast"),(False,"unique_selection"))
        self.call(e,"finish_group","battle-1","owner-A","multicast")
        self.assertEqual(self.query(e,"limited",group="multicast"),(False,"group_closed"))
        self.cast(e,"limited","b","next")

    def test_charges_spend_cost_not_one_and_only_explicit_refills(self):
        e=self.engine([("charge",1014,[1,2,3,5,2,1]),("fixed",1014,[1,2,1,1,1,0])])
        self.cast(e,"charge","a")
        self.assertEqual(self.query(e,"charge"),(False,"charges_exhausted"))
        self.assertTrue(self.call(e,"refill","battle-1","owner-A","charge/gate",999,"refill")[0])
        self.assertFalse(self.call(e,"refill","battle-1","owner-A","charge/gate",999,"refill")[0])
        self.cast(e,"charge","b"); self.cast(e,"charge","c")
        self.assertFalse(self.query(e,"charge")[0])
        self.cast(e,"fixed","d")
        self.assertEqual(self.call(e,"refill","battle-1","owner-A","fixed/gate",1,"bad"),(False,"not_rechargeable"))

    def test_revive_escape_and_new_battle_have_distinct_reset_rules(self):
        e=self.engine([("limited",157,[2,1,2,2,1,1,0,1,0])])
        self.cast(e,"limited","a")
        self.call(e,"reserve","battle-1","owner-A","limited","pending","g",True)
        self.call(e,"set_alive","battle-1","owner-A",False)
        self.assertEqual(self.query(e,"limited"),(False,"owner_dead"))
        self.call(e,"set_alive","battle-1","owner-A",True)
        self.cast(e,"limited","b")
        self.assertFalse(self.query(e,"limited")[0])
        self.call(e,"depart","battle-1","owner-A")
        self.assertEqual(self.query(e,"limited"),(False,"owner_departed"))
        self.call(e,"end_battle","battle-1")
        self.assertEqual(self.query(e,"limited"),(False,"stale_battle"))
        self.assertFalse(self.call(e,"begin_battle","battle-1")[0])
        self.call(e,"begin_battle","battle-2")
        self.call(e,"register_owner","battle-2","owner-A",self.lua.table_from(["limited"]))
        self.call(e,"begin_turn","battle-2","owner-A",1)
        self.assertTrue(self.call(e,"query","battle-2","owner-A","limited",True,None)[0])
        self.assertFalse(self.call(e,"commit","battle-1","owner-A","a",True)[0])

    def test_initial_cooldown_no_turn_skipping_or_pending_transition(self):
        e=self.engine([("cool",130,[2,1,[2,0],0])])
        self.assertFalse(self.query(e,"cool")[0])
        self.assertEqual(self.call(e,"begin_turn","battle-1","owner-A",3),(False,"turn_out_of_order"))
        self.call(e,"begin_turn","battle-1","owner-A",2)
        self.call(e,"begin_turn","battle-1","owner-A",3)
        self.call(e,"reserve","battle-1","owner-A","cool","a","g",True)
        self.assertEqual(self.call(e,"begin_turn","battle-1","owner-A",4),(False,"pending_action"))
        self.call(e,"cancel","battle-1","owner-A","a")
        self.assertTrue(self.query(e,"cool")[0])

    def test_unbound_vision_actor_and_ungranted_command_are_denied(self):
        e=self.engine([("cool",130,[2,1,[4,4],0])])
        self.assertEqual(self.query(e,"cool",owner="temporary-vision"),(False,"unbound_owner"))
        self.assertEqual(self.query(e,"not-in-loadout"),(False,"unbound_command"))

    def test_late_grant_uses_observed_owner_clock_and_empty_loadout(self):
        e=self.engine([("cool",130,[2,1,[2,0],0])])
        self.assertEqual(self.call(e,"register_owner","battle-1","late",self.lua.table()),(True,"registered"))
        for turn in (1,2):self.assertTrue(self.call(e,"begin_turn","battle-1","late",turn)[0])
        self.assertEqual(self.query(e,"cool",owner="late"),(False,"unbound_command"))
        self.assertTrue(self.call(e,"sync_loadout","battle-1","late",self.lua.table_from(["cool"]))[0])
        self.assertEqual(self.query(e,"cool",owner="late"),(False,"cooldown"))
        self.call(e,"begin_turn","battle-1","late",3)
        self.cast(e,"cool","late-cast",owner="late")
        self.call(e,"sync_loadout","battle-1","late",self.lua.table())
        self.call(e,"sync_loadout","battle-1","late",self.lua.table_from(["cool"]))
        self.assertEqual(self.query(e,"cool",owner="late"),(False,"cooldown"))
        for turn in (4,5):self.call(e,"begin_turn","battle-1","late",turn)
        self.assertFalse(self.query(e,"cool",owner="late")[0])
        self.call(e,"begin_turn","battle-1","late",6)
        self.assertTrue(self.query(e,"cool",owner="late")[0])
        self.assertEqual(e.owners["owner-A"].turn,1)

    def test_remove_regrant_preserves_balances_and_cancelled_action_identity(self):
        e=self.engine([("limited",157,[2,1,1,1,1,1,0,1,0]),("charge",1014,[1,2,3,5,2,1])])
        self.cast(e,"limited","spent")
        self.cast(e,"charge","charged")
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table())
        self.assertEqual(self.query(e,"limited"),(False,"unbound_command"))
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["limited","charge"]))
        self.assertEqual(self.query(e,"limited"),(False,"uses_exhausted"))
        self.assertEqual(self.query(e,"charge"),(False,"charges_exhausted"))
        self.call(e,"refill","battle-1","owner-A","charge/gate",1,"refill")
        self.assertTrue(self.call(e,"reserve","battle-1","owner-A","charge","pending","group",True)[0])
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["limited"]))
        self.assertEqual(e.owners["owner-A"].gates["charge/gate"].held,0)
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["limited","charge"]))
        self.assertEqual(self.call(e,"authorize","battle-1","owner-A","charge","pending","group",True),(False,"not_reserved"))
        self.assertTrue(self.query(e,"charge")[0])
        self.cast(e,"charge","new-cast")

    def test_late_alias_preserves_shared_gate_and_only_removed_reservations_cancel(self):
        gate=decode(157,[2,1,3,3,1,1,0,1,0],"1");gate.update(key="shared",owner="equipping_actor")
        commands=[{"key":k,"gates":[dict(gate)]} for k in ("first","second")]
        e=self.module.new(self.lua.table_from(commands,recursive=True))
        self.call(e,"begin_battle","battle-1")
        self.call(e,"register_owner","battle-1","owner-A",self.lua.table_from(["first"]))
        self.call(e,"begin_turn","battle-1","owner-A",1)
        self.cast(e,"first","spent")
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["first","second"]))
        self.assertEqual(e.owners["owner-A"].gates.shared.used,1)
        self.call(e,"reserve","battle-1","owner-A","first","removed","g1",True)
        self.call(e,"reserve","battle-1","owner-A","second","kept","g2",True)
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["second"]))
        self.assertEqual(e.owners["owner-A"].gates.shared.held,1)
        self.assertEqual(self.call(e,"commit","battle-1","owner-A","removed",True),(False,"not_reserved"))
        self.assertTrue(self.call(e,"commit","battle-1","owner-A","kept",True)[0])
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["first","second"]))
        self.cast(e,"first","last")
        self.assertEqual(self.query(e,"second"),(False,"uses_exhausted"))

    def test_loadout_validation_is_atomic_and_stale_departed_owners_cannot_update(self):
        e=self.engine([("limited",157,[2,1,1,1,1,1,0,1,0])])
        self.call(e,"reserve","battle-1","owner-A","limited","pending","g",True)
        for bad in (["unknown"],["limited","limited"],{1:"limited",3:"unknown"},{"named":"limited"}):
            with self.subTest(bad=bad),self.assertRaises(self.lupa.LuaError):
                self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(bad))
            self.assertTrue(e.owners["owner-A"].commands.limited)
            self.assertEqual(e.owners["owner-A"].gates["limited/gate"].held,1)
        self.assertTrue(self.call(e,"commit","battle-1","owner-A","pending",True)[0])
        self.call(e,"set_alive","battle-1","owner-A",False)
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table())
        self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table_from(["limited"]))
        self.call(e,"set_alive","battle-1","owner-A",True)
        self.assertEqual(self.query(e,"limited"),(False,"uses_exhausted"))
        self.assertEqual(self.call(e,"sync_loadout","old-battle","owner-A",self.lua.table()),(False,"stale_battle"))
        self.call(e,"depart","battle-1","owner-A")
        self.assertEqual(self.call(e,"sync_loadout","battle-1","owner-A",self.lua.table()),(False,"owner_departed"))

    def test_multiple_gates_commit_atomically_and_aliases_share_one_gate(self):
        cooldown=decode(130,[2,1,[1,1],0],"1")
        limit=decode(157,[2,1,1,1,1,1,0,0,0],"1")
        cooldown.update(key="shared-cooldown",owner="equipping_actor")
        limit.update(key="one-use",owner="equipping_actor")
        # JSON plans contain separate objects. Lupa 2.6's recursive converter
        # can turn repeated Python object identities into empty Lua tables.
        commands=[{"key":"both","gates":[cooldown,limit]}, {"key":"alias","gates":[dict(cooldown)]}]
        e=self.module.new(self.lua.table_from(commands,recursive=True))
        self.call(e,"begin_battle","battle-1")
        self.call(e,"register_owner","battle-1","owner-A",self.lua.table_from(["both","alias"]))
        self.call(e,"begin_turn","battle-1","owner-A",1)
        self.cast(e,"both","a")
        self.assertFalse(self.query(e,"alias")[0])
        self.call(e,"begin_turn","battle-1","owner-A",2)
        self.call(e,"begin_turn","battle-1","owner-A",3)
        self.assertEqual(self.query(e,"both"),(False,"uses_exhausted"))
        self.assertFalse(self.call(e,"reserve","battle-1","owner-A","both","b","g",True)[0])
        self.assertTrue(self.query(e,"alias")[0])
        self.cast(e,"alias","c")

    def test_many_pending_uses_cannot_overspend_and_event_storage_is_bounded(self):
        e=self.engine([("limited",157,[2,1,3,3,1,1,1,1,0])])
        for token in ("a","b","c"):
            self.assertTrue(self.call(e,"reserve","battle-1","owner-A","limited",token,"group",True)[0])
        self.assertFalse(self.call(e,"reserve","battle-1","owner-A","limited","d","group",True)[0])
        for token in ("c","a","b"):
            self.assertTrue(self.call(e,"commit","battle-1","owner-A",token,True)[0])
        self.assertEqual(self.query(e,"limited"),(False,"uses_exhausted"))
        e=self.engine([("charge",1014,[1,2,1,1,1,1])])
        run=self.lua.eval('''function(e)
            for i=1,8191 do assert(e:refill("battle-1","owner-A","charge/gate",1,"r"..i)) end
            assert(e:reserve("battle-1","owner-A","charge","last","last",true))
            assert(e:commit("battle-1","owner-A","last",true))
            return e:refill("battle-1","owner-A","charge/gate",1,"overflow")
        end''')
        self.assertEqual(run(e),(False,"event_capacity"))

    def test_native_startup_schedules_observation_on_game_thread_without_enforcement(self):
        self.lua.execute(r'''
            records={}; attach_calls=0
            package.preload['availability_probe']=function()
                return {json=function(record) records[#records+1]=record; return 'record' end}
            end
            package.preload['availability_probe_main']=function() reflected_probe_loaded=true end
            print=function() end
            ExecuteInGameThread=function(callback) scheduled=callback end
            FFRAvailabilityNativeAttach=function(enforce,ids)
                attach_calls=attach_calls+1
                assert(enforce==false and ids=='', 'unexpected enforcement at startup')
                return true,'attached'
            end
        ''')
        self.lua.execute((ROOT/"tools/ability_converter/runtime/native_main.lua").read_text())
        self.assertTrue(self.lua.globals().reflected_probe_loaded)
        self.assertEqual(self.lua.globals().attach_calls,0)
        self.assertIsNotNone(self.lua.globals().scheduled)
        self.lua.globals().scheduled()
        self.assertEqual(self.lua.globals().attach_calls,1)
        callback=self.lua.globals().FFRAvailabilityOnNativeGuard
        self.assertTrue(callback(100,200,300,880001,5,1,2,True))
        self.assertFalse(callback(100,200,300,880001,5,1,2,False))
        self.assertEqual(self.lua.globals().records[2]["actor"],200)
        self.assertEqual(self.lua.globals().records[3]["nativeAllowed"],False)

    def test_probe_reads_native_params_without_overrides_and_reports_failures(self):
        probe=self.lua.execute((ROOT/"tools/ability_converter/runtime/probe.lua").read_text())
        host=self.lua.execute('''
            callbacks={}; observed={}; removed=0
            function remote(v) return {get=function() return v end, set=function() error("mutation") end} end
            return {
              register=function(path,cb) callbacks[path]=cb; return 1,2 end,
              unregister=function() removed=removed+1 end,
              emit=function(event) observed[#observed+1]=event end
            }
        ''')
        installed=probe.install(host)
        callback=self.lua.globals().callbacks["/Script/mucha.CPP_BFL_Battle:IsEnableCommand"]
        remote=self.lua.globals().remote
        self.assertIsNone(callback(remote(None),remote(4),remote(445001)))
        observations=self.lua.globals().observed
        last=observations[len(observations)]
        self.assertEqual((last["event"],last["uniqueId"],last["skillId"]),("query_enable",4,445001))
        bad=self.lua.globals().callbacks["/Script/mucha.CPP_UI_BattleSubsystem:HandleBeginTurn"]
        for _ in range(6): self.assertIsNone(bad(remote(None),remote(None)))
        failed=[v for v in observations.values() if v["event"]=="read_failed"]
        self.assertEqual(len(failed),3)
        count=len(observations)
        installed.stop()
        self.assertGreater(self.lua.globals().removed,0)
        self.assertIsNone(callback(remote(None),remote(4),remote(445001)))
        self.assertEqual(len(observations),count)

    def test_probe_json_and_native_empty_target_arrays(self):
        probe=self.lua.execute((ROOT/"tools/ability_converter/runtime/probe.lua").read_text())
        text='日本語 "quoted" \\ path\n\x00'
        self.assertEqual(json.loads(probe.json(self.lua.table_from({"text":text,"number":3}))),{"text":text,"number":3})
        host=self.lua.execute('''
            callbacks={}; observed={}
            return {register=function(path,cb) callbacks[path]=cb; return 1,2 end,
                    emit=function(event) observed[#observed+1]=event end}
        ''')
        probe.install(host)
        payload=self.lua.execute('''
            local array={GetArrayNum=function() return 0 end, ForEach=function() end}
            local object={SkillId=1,actionUnitUniqueId=2,isVisibleCounter=false,isVisibleSkillName=true,
                          targetUnitUniqueIdList=array, IsValid=function() return true end,
                          GetFullName=function() return "SkillBegin Fixture" end}
            return {get=function() return object end}
        ''')
        cb=self.lua.globals().callbacks["/Script/mucha.CPP_VM_BtlMsg:HandleBeginSkill"]
        self.assertIsNone(cb(None,payload))
        observations=self.lua.globals().observed
        entry=json.loads(probe.json(observations[len(observations)]))
        self.assertEqual(entry["targets"],[])
        self.assertEqual(entry["event"],"skill_begin_message")


if __name__ == "__main__":
    unittest.main()
