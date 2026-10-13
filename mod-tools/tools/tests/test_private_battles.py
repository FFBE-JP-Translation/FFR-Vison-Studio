"""Integration checks against the latest locally built NPC addon; no game writes."""
import json
from pathlib import Path
import subprocess
import struct
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT / "tools/private")]
from ffbe_effects.acb_cues import CueGraph, utf, commands
from ffbe_effects.acb_native import awb_files
from npc_assets import MAP, EVENT, streaming_levels, property_of, add_battle_streaming
from make_npc_battles import (RETURN, RETURN_SEQUENCE, ENEMIES, BATTLES, EVENT_TABLES, CHOICE,
                              STAGE_TABLE, BATTLE_STAGE, TRAINING_FORM, TRAINING_UNIT, TRAINING_HP_MAX, TRAINING_STAT_MAX)
from battle_music import DEFAULT_CUE_GAIN, NATIVE_BATTLE_CUE_GAIN, pcm
from battle_hca import adapt as adapt_music
from ffbe_effects.hca_host import key_from_config, encryption_table, crc


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


class PrivateBattleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        latest = ROOT / "build/npc-battles/latest.json"
        if not latest.exists():
            raise unittest.SkipTest("Build the private NPC addon first")
        cls.work = Path(read(latest)["work"])

    def rows(self, rel):
        return read(self.work / "verified" / (rel + ".json"))["rows"]

    def test_menu_and_every_battle_have_non_story_return_paths(self):
        events = self.rows(EVENT_TABLES[1])
        dialog = self.rows("UI/Common/Dialog/DT_DIalogChoice")["Private_Battles"]
        self.assertEqual(dialog["ChoiceTag"]["TagName"], CHOICE)
        self.assertEqual(len(dialog["ChoiceTextList"]), 6)
        self.assertEqual(dialog["CancelIndex"], 5)
        branches = events[EVENT]["ChoicesBranchEventList"]
        groups = self.rows("Encount/DT_BattleGroup")
        self.assertEqual([b["Index"] for b in branches], list(range(6)))
        for i, battle in enumerate(BATTLES):
            event = branches[i]["EventList"][0]["EventId"]
            group = groups[event]
            self.assertEqual(events[event]["encountGroupId"], group["ID"])
            self.assertEqual(group["UnitIdList"], battle[1])
            for field in ("battleFinishEventId", "battleFinishEscapeEventId", "battleFinishLoseEventId"):
                self.assertEqual(group[field], RETURN)
        self.assertEqual(branches[5]["EventList"][0]["EventId"], RETURN)
        for event in [EVENT, RETURN] + [f"Private_Battles_{i+1}" for i in range(5)]:
            for key in ("OnFlagList", "OffFlagList", "ProgressList", "ChangeUnitJoinStatusList", "ContinuousEventList"):
                self.assertEqual(events[event][key], [], (event, key))
            self.assertFalse(events[event]["IsGameOver"])
        self.assertEqual(events[RETURN]["encountGroupId"], -1)
        self.assertTrue(events[RETURN]["IsRecover"])

    def test_return_event_runs_native_fade_in_before_finishing(self):
        events = self.rows(EVENT_TABLES[1])
        self.assertEqual(events[RETURN]["EventSequence"], RETURN_SEQUENCE)
        self.assertEqual(events[RETURN]["RestoreBGMSettings"]["Type"], "MapBGM")
        native = read(self.work / "return-sequence-full.json")
        def walk(value):
            if isinstance(value, dict):
                yield value
                for child in value.values():
                    yield from walk(child)
            elif isinstance(value, list):
                for child in value:
                    yield from walk(child)
        times = {}
        for export in native["Exports"]:
            if not export["ObjectName"].startswith("MovieSceneEventTriggerSection"):
                continue
            channel = {p["Name"]: p["Value"] for p in property_of(export, "EventChannel")["Value"]}
            for time, event in zip(channel["KeyTimes"], channel["KeyValues"]):
                index = next(p["Value"] for p in walk(event) if p.get("Name") == "Function")
                function = native["Exports"][index - 1]
                for value in walk(function.get("ScriptBytecode", [])):
                    if value.get("$type", "").split(",")[0].endswith("EX_StructConst"):
                        # ETalkEventCmdType: FadeIn=12, FadeOut=13, FadeWait=14.
                        code = value["Value"][0].get("Value")
                        if code in (12, 14):
                            times[code] = time["Value"][0]["Value"]["Value"]
        self.assertEqual(set(times), {12, 14})
        self.assertLess(times[12], times[14])
        self.assertIn("ExecuteFooter", [i["ObjectName"] for i in native["Imports"]])

    def test_enemies_have_selected_sprites_and_test_stats(self):
        stats = self.rows("Unit/DT_UnitParameter")
        visuals = self.rows("Asset/Battle/Unit/DT_BtlUnitAsset")
        for i, (form, name) in enumerate(ENEMIES):
            row = "Private_Battles_" + form
            self.assertEqual(stats[row]["MaxHitPoint"], TRAINING_HP_MAX if form == TRAINING_FORM else read(self.work / "verification.json")["hp"])
            self.assertEqual(stats[row]["Experience"], 0)
            self.assertEqual(stats[row]["DropNormalItem"], -1)
            self.assertIn(f"monster{9461+i}", visuals[row]["animationAssetList"][0]["Ss6Project"])

    def test_training_dummy_cannot_attack_or_counter_and_allows_escape(self):
        row = 'Private_Battles_' + TRAINING_FORM
        stats = self.rows('Unit/DT_UnitParameter')[row]
        self.assertEqual([stats[k] for k in ('MaxHitPoint', 'Defence', 'Mind')], [TRAINING_HP_MAX, TRAINING_STAT_MAX, TRAINING_STAT_MAX])
        ai = self.rows('Unit/AI/DT_BtlUnitAIParameter')[row]
        self.assertEqual(ai['aiId'], 0)
        for key in ('fightSkillId', 'chaseSkillId', 'silenceFightId'):
            self.assertEqual(ai[key], -1)
        for key in ('skillRandData1', 'skillRandData2'):
            self.assertEqual(ai[key], [])
        for key in ('counterSkillIdList', 'highRiskSkillIdList'):
            self.assertTrue(all(s == -1 for s in ai[key]))
        group = self.rows('Encount/DT_BattleGroup')['Private_Battles_5']
        self.assertEqual(group['UnitIdList'], [TRAINING_UNIT])
        self.assertTrue(group['CanEscape'])
        self.assertEqual(group['probabilityOfSuccessfulEscape'], 100.0)

    def test_packed_map_includes_npc_event_name_in_serialized_prefix(self):
        # A legacy map can reparse successfully yet crash AsyncLoading2 if the
        # newly added event name is beyond NamesReferencedFromExportDataCount.
        packed = read(self.work / "map-cooked.json")
        self.assertLess(packed["NameMap"].index(EVENT), packed["NamesReferencedFromExportDataCount"])
        actor = next(x for x in packed["Exports"] if x["ObjectName"] == "BP_MapUnit_NPC_PrivateBattles")
        self.assertIn(EVENT, json.dumps(actor["Data"]))
        level = packed["Exports"][actor["OuterIndex"] - 1]
        self.assertIn(packed["Exports"].index(actor) + 1, level["Actors"])

    def test_appended_music_graph_points_to_verified_recordings(self):
        original = (self.work / "legacy/FFRS/Content/Sound/Cri/Bgm/BGM_PP/BGM_PP.uexp").read_bytes()
        start = original.index(b"@UTF")
        original = utf(original[start:start+8+int.from_bytes(original[start+4:start+8], "big")])[1][0]
        merged = utf((self.work / "music/BGM_PP.acb").read_bytes())[1][0]
        graph = CueGraph(merged)
        by_id = {r["CueId"]: r for r in utf(merged["CueTable"])[1]}
        waves = awb_files(merged["AwbFile"])
        for i in range(len(BATTLES)):
            indices = graph.alternatives(by_id[i+1])
            self.assertEqual(len(indices), 1)
            row = graph.row("WaveformTable", indices[0])
            self.assertEqual(row["EncodeType"], 2)
            self.assertEqual(row["Streaming"], 0)
            self.assertEqual(row["NumChannels"], 2)
            self.assertEqual(row["StreamAwbPortNo"], 65535)
            self.assertEqual(row["StreamAwbId"], 65535)
            self.assertEqual(waves[row["MemoryAwbId"]], (self.work / f"music/{i+1}.hca").read_bytes())
        self.assertEqual(original["AwbFile"][6], merged["AwbFile"][6])
        self.assertEqual(original["AwbFile"][12:16], merged["AwbFile"][12:16])
        for row in utf(original["CueTable"])[1]:
            self.assertEqual(by_id[row["CueId"]], row)
        for key, audio in awb_files(original["AwbFile"]).items():
            self.assertEqual(waves[key], audio)

    def test_music_keeps_exact_source_pcm_and_encrypted_spectral_frames(self):
        key = key_from_config(ROOT / "extracted/pak/FFRS/Config/DefaultEngine.ini")
        merged = utf((self.work / "music/BGM_PP.acb").read_bytes())[1][0]
        subkey = int.from_bytes(merged["AwbFile"][14:16], "little")
        encrypt = encryption_table(key, subkey)
        decrypt = bytes(encrypt.index(i) for i in range(256))
        for i, rec in enumerate(read(self.work / "music/verification.json")):
            self.assertTrue(rec["pcmExact"])
            self.assertTrue(rec["bankPcmExact"])
            source_pcm, source_rate = pcm(self.work / f"music/{i+1}.wav")
            for suffix in ("roundtrip.wav", "bank.wav"):
                result_pcm, result_rate = pcm(self.work / f"music/{i+1}.{suffix}")
                self.assertEqual(source_rate, result_rate)
                self.assertEqual(source_pcm.tobytes(), result_pcm.tobytes())
            raw = next(iter(awb_files(utf(Path(rec["source"]).read_bytes())[1][0]["AwbFile"]).values()))
            adapted = (self.work / f"music/{i+1}.hca").read_bytes()
            size = int.from_bytes(raw[6:8], "big")
            frame_size = int.from_bytes(raw[28:30], "big")
            self.assertEqual(adapted[4:6], b"\x03\0")
            self.assertEqual(adapted[60:62], b"\0\x38")
            self.assertEqual(crc(adapted[:size]), 0)
            self.assertEqual(adapted[44:56], raw[44:56])  # exact loop frames/delay
            self.assertEqual(len(adapted), len(raw))
            for pos in range(size, len(raw), frame_size):
                self.assertEqual(adapted[pos:pos+frame_size-2].translate(decrypt), raw[pos:pos+frame_size-2])
        # Reject v2 layouts whose spectral interpretation changes in v3.
        for offset in (30, 33, 35, 36, 37, 38, 39):
            invalid = bytearray(raw); invalid[offset] ^= 1
            with self.assertRaises(ValueError):
                adapt_music(bytes(invalid), key, subkey)
        invalid = bytearray(raw); invalid[-1] ^= 1
        with self.assertRaises(ValueError):
            adapt_music(bytes(invalid), key, subkey)

    def test_packed_music_contains_the_verified_native_bank(self):
        import ffrenv
        rel = "FFRS/Content/Sound/Cri/Bgm/BGM_PP/BGM_PP"
        with tempfile.TemporaryDirectory(prefix="ffr-battle-music-") as tmp:
            subprocess.run([str(ffrenv.RETOC), "to-legacy", "--no-shaders", "--filter", rel,
                            str(self.work / "inputs"), tmp], check=True, capture_output=True)
            payload = (Path(tmp) / (rel + ".uexp")).read_bytes()
            start = payload.index(b"@UTF")
            bank = payload[start:start+8+int.from_bytes(payload[start+4:start+8], "big")]
            self.assertEqual(bank, (self.work / "music/BGM_PP.acb").read_bytes())

    def test_appended_music_uses_native_playback_settings_at_bounded_volume(self):
        bank = utf((self.work / "music/BGM_PP.acb").read_bytes())[1][0]
        rows = {r["CueId"]: r for r in utf(bank["CueTable"])[1]}
        sequences = utf(bank["SequenceTable"])[1]
        volume_commands = utf(bank["SeqCommandTable"])[1]
        native = sequences[rows[10005]["ReferenceIndex"]]  # BGM_PP_BATTLE1
        reference = list(commands(volume_commands[native["CommandIndex"]]["Command"]))
        self.assertAlmostEqual(next(struct.unpack(">f", a)[0] for op, a in reference if op == 0x92), NATIVE_BATTLE_CUE_GAIN)
        for cue_id in range(1, len(BATTLES) + 1):
            seq = sequences[rows[cue_id]["ReferenceIndex"]]
            actual = list(commands(volume_commands[seq["CommandIndex"]]["Command"]))
            self.assertEqual([(op, a) for op, a in actual if op != 0x92], [(op, a) for op, a in reference if op != 0x92])
            values = [struct.unpack(">f", args)[0] for op, args in
                      actual if op == 0x92]
            self.assertEqual(len(values), 1)
            self.assertAlmostEqual(values[0], DEFAULT_CUE_GAIN, places=7)
            self.assertAlmostEqual(values[0], NATIVE_BATTLE_CUE_GAIN, places=7)
            # The native synthesis settings must resolve after the bank merge.
            synth = utf(bank["SynthTable"])[1][len(utf(bank["SynthTable"])[1]) - len(BATTLES) - 1 + cue_id]
            self.assertEqual(utf(bank["SynthCommandTable"])[1][synth["CommandIndex"]], utf(bank["SynthCommandTable"])[1][0])

    def test_arena_is_registered_in_mitras_actual_world(self):
        # A valid battleStage table row alone did not load either arena level.
        stage = next(v for v in read(self.work / "rows" / (STAGE_TABLE + ".json"))["rows"].values()
                     if v["ID"] == BATTLE_STAGE)
        original = read(self.work / "persistent-original.json")
        packed = read(self.work / "persistent-cooked.json")
        _, _, before = streaming_levels(original)
        _, _, after = streaming_levels(packed)
        def paths(data, indices):
            return [property_of(data["Exports"][i-1], "WorldAsset")["Value"]["AssetPath"]["PackageName"] for i in indices]
        self.assertEqual(paths(original, before), paths(packed, after)[:len(before)])
        for path in stage["battleLevelList"]:
            self.assertEqual(paths(packed, after).count(path), 1)
            self.assertLess(packed["NameMap"].index(path), packed["NamesReferencedFromExportDataCount"])
            ex = packed["Exports"][after[paths(packed, after).index(path)] - 1]
            self.assertEqual(packed["Imports"][-ex["ClassIndex"]-1]["ObjectName"], "LevelStreamingDynamic")
        # Rebuilding must not register a second copy of the same background.
        again, added = add_battle_streaming(packed, stage["battleLevelList"])
        self.assertEqual(added, [])
        self.assertEqual(len(again["Exports"]), len(packed["Exports"]))

    def test_empty_struct_arrays_and_empty_names_can_be_cleared(self):
        # Regression: MakeElement used to throw even when writing [] to [].
        rel = EVENT_TABLES[0]
        source = read(self.work / "rows" / (rel + ".json"))["rows"]
        donor = next(k for k, v in source.items() if not v["CustomChoiceDialogDataList"])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            patch = {"legacyRoot": str(self.work / "legacy"), "outRoot": str(root), "tables": [{
                "asset": "FFRS/Content/Datatable/" + rel,
                "add": [{"row": "Private_EmptyRegression", "cloneFrom": donor, "set": {
                    "CustomChoiceDialogDataList": [], "LoadingScreenSetting": ""}}]}]}
            path = root / "patch.json"; path.write_text(json.dumps(patch), encoding="utf-8")
            command = ["dotnet", str(ROOT / "src/ffr-dt/bin/Release/net8.0/ffr-dt.dll")]
            options = ["--usmap", str(ROOT / "extracted/Mappings.usmap")]
            subprocess.run(command + ["patch", str(path)] + options, check=True, capture_output=True)
            output = root / "rows.json"
            subprocess.run(command + ["rows", str(root / ("FFRS/Content/Datatable/" + rel + ".uasset")), str(output)] + options,
                           check=True, capture_output=True)
            row = read(output)["rows"]["Private_EmptyRegression"]
            self.assertEqual(row["CustomChoiceDialogDataList"], [])
            self.assertIn(row["LoadingScreenSetting"], ("", "None"))


if __name__ == "__main__":
    unittest.main()
