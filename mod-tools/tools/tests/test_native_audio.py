"""Cue graph regressions and native ACB adaptation against local game banks."""
from pathlib import Path
import hashlib
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ffbe_audio
from ffbe_effects import acb_native as native
from ffbe_effects import hca_host
from ffbe_effects.acb_cues import CueGraph, commands, cues, utf


class GraphTests(unittest.TestCase):
    def test_hca_checksum_and_known_cipher_permutation(self):
        self.assertEqual(hca_host.crc(b"123456789"), 0xfee8)
        table = hca_host.encryption_table(12345678, 4321)
        # Independently checked against CriCodecs' type-56 encryption.
        self.assertEqual(hashlib.sha256(table).hexdigest(), "35460439ffa148bc9b815579799b3ac9e0df1660209d4538ee7fa93e79e2cbe9")
        self.assertEqual(sorted(table), list(range(256)))

    def graph(self):
        graph = CueGraph({})
        graph.tables = {
            "WaveformTable": [{}, {}],
            "SynthTable": [{"ReferenceItems": struct.pack(">HH", 1, i)} for i in (0, 1)],
            "TrackTable": [{"EventIndex": 0}, {"EventIndex": 1}],
            "TrackEventTable": [{"Command": struct.pack(">HBHH", 2000, 4, 2, i)} for i in (1, 0)],
            "SequenceTable": [{"Type": 3, "NumTracks": 2, "TrackIndex": b"\0\0\0\1", "TrackValues": b"\0\x64\0\x64"}],
        }
        return graph

    def test_sequence_reference_preserves_alternative_track_order(self):
        graph = self.graph()
        self.assertEqual(graph.waveforms(3, 0), [1, 0])
        self.assertEqual(graph.alternatives({"ReferenceType": 3, "ReferenceIndex": 0}), [1, 0])
        self.assertEqual(graph.waveforms(2, 0), [0])

    def test_layered_duplicate_waves_and_malformed_graphs_are_rejected(self):
        cue = {"ReferenceType": 3, "ReferenceIndex": 0}
        for change in ({"Type": 0}, {"TrackValues": b"\0\x64\0\x32"}, {"NumTracks": 3}):
            graph = self.graph(); graph.tables["SequenceTable"][0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError): graph.alternatives(cue)
        graph = self.graph()
        graph.tables["SynthTable"][1]["ReferenceItems"] *= 2
        with self.assertRaises(ValueError): graph.alternatives(cue)
        graph = self.graph()
        graph.tables["SynthTable"][1]["ReferenceItems"] = struct.pack(">HH", 2, 1)
        with self.assertRaises(ValueError): graph.alternatives(cue)
        graph = self.graph()
        graph.tables["TrackEventTable"][0]["Command"] += b"\0\1"
        with self.assertRaises(ValueError): graph.alternatives(cue)


class NativeBankTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.path = Path("S:/FFBE JP Data Export/public/SE.acb")
        host_path = ROOT / "extracted/legacy" / (ffbe_audio.SHELL + ".uexp")
        if not cls.path.is_file() or not host_path.is_file():
            raise unittest.SkipTest("Supply the local FFBE and FFR audio banks")
        cls.source = cls.path.read_bytes()
        host = host_path.read_bytes(); host = host[host.index(b"@UTF"):]
        cls.host = host[:int.from_bytes(host[4:8], "big") + 8]
        cls.cues = cues(cls.path)
        cls.selected = native.recordings(cls.source, [1, 4, 181, 647], {i: c["name"] for i, c in cls.cues.items()})
        cls.built = native.build(cls.source, cls.host, "TestLB", cls.selected)

    def test_correct_source_sequence_and_hca_mx_metadata(self):
        self.assertEqual(self.cues[647]["waveformIndices"], [633])
        self.assertEqual(self.cues[4]["waveformIndices"], [7, 6, 8])
        self.assertIsNone(self.cues[1]["waveformIndex"])
        self.assertEqual(next(r for r in self.selected if r["sourceCueId"] == 181)["sourceEncodeType"], 6)

    def test_host_profile_keeps_native_subkey_and_reversible_frames(self):
        config = ROOT / "extracted/pak/FFRS/Config/DefaultEngine.ini"
        if not config.is_file(): self.skipTest("Extract FFR's audio configuration")
        key = hca_host.key_from_config(config)
        bank = native.build(self.source, self.host, "HostLB", self.selected, waveform_profile={"key": key})
        awb = utf(bank)[1][0]["AwbFile"]
        host_awb = utf(self.host)[1][0]["AwbFile"]
        self.assertEqual(awb[12:16], host_awb[12:16])
        self.assertEqual(awb[6], host_awb[6])
        subkey = int.from_bytes(awb[14:16], "little")
        enc = hca_host.encryption_table(key, subkey)
        decrypt = bytes(enc.index(i) for i in range(256))
        src = native.awb_files(utf(self.source)[1][0]["AwbFile"])
        dst = native.awb_files(awb)
        for i, rec in enumerate(self.selected):
            original = src[rec["sourceWaveId"]]; changed = dst[i]
            self.assertEqual(changed[4:6], b"\x03\0")
            self.assertEqual(changed[44:46], b"\0\x38")
            self.assertEqual(hca_host.crc(changed[:96]), 0)
            size = int.from_bytes(original[28:30], "big")
            for start in range(96, len(changed), size):
                frame = changed[start:start+size]
                self.assertEqual(hca_host.crc(frame), 0)
                self.assertEqual(frame[:-2].translate(decrypt), original[start:start+size-2])
        for offset in (12, 36, 52, 100):
            malformed = bytearray(original); malformed[offset] ^= 1
            with self.assertRaises(ValueError): hca_host.adapt(bytes(malformed), key, subkey)

    def test_native_bank_preserves_recordings_and_routes_bounded_cues(self):
        h = utf(self.built)[1][0]; original = utf(self.source)[1][0]
        self.assertEqual(h["Version"], 0x1420100)
        self.assertEqual(h["NumCueLimitListWorks"], 0)
        self.assertEqual(h["NumCueLimitNodeWorks"], 0)
        src = native.awb_files(original["AwbFile"]); dst = native.awb_files(h["AwbFile"])
        graph = CueGraph(h); cue_rows = utf(h["CueTable"])[1]
        names = utf(h["CueNameTable"])[1]
        for i, rec in enumerate(self.selected):
            self.assertEqual(graph.alternatives(cue_rows[i]), [i])
            self.assertEqual(dst[i], src[rec["sourceWaveId"]])
            self.assertEqual(names[i]["CueName"], rec["name"])
            self.assertEqual(cue_rows[i]["Length"], rec["durationMs"])
            self.assertEqual(graph.row("WaveformTable", i)["EncodeType"], 2)
        cmd = dict(commands(utf(h["SeqCommandTable"])[1][0]["Command"]))
        self.assertEqual(struct.unpack(">I", cmd[0x41])[0], 3)
        self.assertAlmostEqual(struct.unpack(">f", cmd[0x92])[0], 0.15)
        self.assertEqual(struct.unpack(">HH", cmd[0x6f]), (0, 10000))
        self.assertEqual(utf(h["StringValueTable"])[1], [{"StringValue": "MasterOut"}])

    def test_scheduler_names_alternatives_and_registers_bank_once(self):
        tables = {}
        def tbl(rel): return tables.setdefault(rel, {"add": []})
        sounds = [{"cueId": 1, "frame": i * 10} for i in range(4)]
        skill = {"audio": "native", "audio_bank": str(self.path), "lb_charge": False}
        bank, events = ffbe_audio.prepare({"key": "test"}, skill, {"sounds": sounds}, tbl)
        self.assertEqual([e["cueName"] for e in events], ["se_attack_sword_slash_1__v" + str(i) for i in (1, 2, 3, 1)])
        self.assertEqual([e["frame"] for e in events], [0, 10, 20, 30])
        self.assertTrue(all(0 < e["durationMs"] < 60000 for e in events))
        ffbe_audio.prepare({"key": "test"}, skill, {"sounds": sounds}, tbl)
        self.assertEqual([len(t["add"]) for t in tables.values()], [1, 1])
        self.assertEqual(bank["gain"], 0.15)

    def test_unsupported_sound_keeps_supported_cues_and_common_charge(self):
        # Cue IDs referenced by Ultimate Power Rain include a stereo/HFR wave.
        import ffbe_lb
        source = ffbe_lb.resolve({"ffbe": {"id": "100045927", "source": "JP"}}, {})
        self.assertIsNotNone(source)
        skill = {"audio": "native", "audio_codec": "host", "audio_bank": str(self.path)}
        tables = {}
        bank, events = ffbe_audio.prepare({"key": "rain"}, skill, source,
                                          lambda r: tables.setdefault(r, {"add": []}))
        ids = tuple(sorted({s["cueId"] for s in source["sounds"]}))
        _, omitted = ffbe_audio.native_selection(str(self.path.resolve()), self.path.stat().st_mtime_ns, ids, True)
        self.assertTrue(omitted)
        self.assertTrue(any(e["sourceCueName"] == ffbe_audio.LB_OPENING_CUE for e in events))
        self.assertTrue(any(e.get("role") != "lb_opening" for e in events))
        self.assertFalse(any(e["cueId"] in omitted for e in events if e.get("role") != "lb_opening"))
        for prepared in ffbe_audio.banks(bank):
            built = native.build(Path(prepared["path"]).read_bytes(), self.host, prepared["name"],
                                 prepared["recordings"], waveform_profile=prepared["waveformProfile"])
            self.assertTrue(utf(built)[1][0]["AwbFile"])

    def test_common_lb_opening_uses_legacy_system_bank_and_shared_registration(self):
        system = self.path.with_name("System.acb")
        if not system.is_file(): self.skipTest("Supply FFBE System.acb")
        tables = {}
        def tbl(rel): return tables.setdefault(rel, {"add": []})
        skill = {"audio": "native", "audio_bank": str(self.path), "audio_system_bank": str(system)}
        source = {"sounds": [{"cueId": 647, "frame": 6}, {"cueId": 1, "frame": 50}]}
        bank, events = ffbe_audio.prepare({"key": "test"}, skill, source, tbl)
        opening = bank["additionalBanks"][0]
        self.assertEqual([e["sourceCueName"] for e in events],
                         ["se_battle_limitopen_1", "se_slb_charge", "se_attack_sword_slash_1"])
        self.assertEqual([e["frame"] for e in events], [0, 6, 50])
        self.assertEqual(source["sounds"], [{"cueId": 647, "frame": 6}, {"cueId": 1, "frame": 50}])
        rec, = opening["recordings"]
        self.assertEqual((rec["sourceCueId"], rec["sourceWaveIndex"], rec["sourceWaveId"]), (45, 41, 14))
        self.assertEqual((rec["samples"], rec["sampleRate"], rec["sourceEncodeType"]), (95488, 48000, 6))
        built = native.build(system.read_bytes(), self.host, opening["name"], opening["recordings"])
        header = utf(built)[1][0]
        original = native.awb_files(utf(system.read_bytes())[1][0]["AwbFile"])[14]
        self.assertEqual(native.awb_files(header["AwbFile"])[0], original)
        self.assertEqual(utf(header["WaveformTable"])[1][0]["EncodeType"], 2)
        silent_bank, only_opening = ffbe_audio.prepare({"key": "silent"}, skill, {"sounds": []}, tbl)
        self.assertEqual(silent_bank["name"], opening["name"])
        self.assertEqual(len(only_opening), 1)
        self.assertEqual([len(t["add"]) for t in tables.values()], [2, 2])
        # Deduplicate after expanding shared banks, including when a later LB
        # uses the same attack bank with the opening explicitly disabled.
        off_bank, _ = ffbe_audio.prepare({"key": "off"}, {**skill, "lb_charge": False}, source, tbl)
        unique = {b["name"]: b for prepared in (bank, off_bank) for b in ffbe_audio.banks(prepared)}
        self.assertEqual(set(unique), {bank["name"], opening["name"]})
        _, existing = ffbe_audio.prepare({"key": "existing"}, {**skill, "audio_bank": str(system)},
                                         {"sounds": [{"cueId": 45, "frame": 0}]}, tbl)
        self.assertEqual(len(existing), 1)

    def test_explicit_missing_system_bank_is_not_silently_ignored(self):
        with self.assertRaises(FileNotFoundError):
            ffbe_audio.prepare({"key": "test"}, {"audio": "native", "audio_system_bank": "missing-system-bank.acb"},
                               {"sounds": []}, lambda _: {"add": []})

    def test_ability_cast_precedes_move_cues_without_adding_lb_or_magic_sound(self):
        tables = {}
        source = {"sounds": [{"cueId": 647, "frame": 6}],
                  "cast": {"bank": "SE", "cueName": ffbe_audio.ABILITY_OPENING_CUE, "frame": -9}}
        bank, events = ffbe_audio.prepare_command(
            {"key": "sora"}, {"audio": "native", "audio_bank": str(self.path)}, source,
            lambda r: tables.setdefault(r, {"add": []}))
        self.assertEqual([(e["sourceCueName"], e["frame"]) for e in events],
                         [("se_special_flash_1", -9), ("se_slb_charge", 6)])
        self.assertEqual(events[0]["role"], "casting")
        self.assertEqual(len(ffbe_audio.banks(bank)), 1)
        self.assertEqual(source["sounds"], [{"cueId": 647, "frame": 6}])

    def test_magic_cast_has_independent_bank_and_silent_move_still_casts(self):
        system = self.path.with_name("System.acb")
        if not system.is_file(): self.skipTest("Supply FFBE System.acb")
        tables = {}
        skill = {"audio": "native", "audio_bank": str(self.path), "audio_system_bank": str(system)}
        cast = {"bank": "System", "cueName": ffbe_audio.MAGIC_OPENING_CUE, "frame": -9}
        bank, events = ffbe_audio.prepare_command({"key": "magic"}, skill,
            {"sounds": [{"cueId": 29, "frame": 20}], "cast": cast},
            lambda r: tables.setdefault(r, {"add": []}))
        self.assertEqual([(e["sourceCueName"], e["frame"]) for e in events],
                         [("se_system_magicopen_1", -9), ("se_magic_fire_1", 20)])
        self.assertEqual(len(ffbe_audio.banks(bank)), 2)
        silent, events = ffbe_audio.prepare_command({"key": "silent"}, skill,
            {"sounds": [], "cast": cast}, lambda r: tables.setdefault(r, {"add": []}))
        self.assertEqual(len(events), 1)
        self.assertEqual(silent["name"], bank["additionalBanks"][0]["name"])
        self.assertTrue(all(len(t["add"]) == 2 for t in tables.values()))

    def test_ordinary_commands_do_not_infer_a_cast_from_damage_type(self):
        _, events = ffbe_audio.prepare_command({"key": "plain"},
            {"audio": "native", "audio_bank": str(self.path), "DamageType": "Magic"},
            {"sounds": [{"cueId": 29, "frame": 20}]}, lambda _: {"add": []})
        self.assertEqual([e["sourceCueName"] for e in events], ["se_magic_fire_1"])


if __name__ == "__main__":
    unittest.main()
