"""Independent decode checks for the formerly omitted Sora reflection cue."""
from pathlib import Path
import hashlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ffbe_effects import acb_native, hca_host, hca_transcode
from ffbe_effects.acb_cues import cues, utf


class HcaTranscodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path("S:/FFBE JP Data Export/public/SE.acb")
        cls.decoder = ROOT / "tools/vgmstream/vgmstream-cli.exe"
        if not path.is_file() or not cls.decoder.is_file():
            raise unittest.SkipTest("Supply the local FFBE audio bank and vgmstream")
        try:
            hca_transcode.codec()
        except ValueError as ex:
            raise unittest.SkipTest(str(ex))
        data = path.read_bytes()
        selected, = acb_native.recordings(data, [175], {175: cues(path)[175]["name"]})
        cls.original = acb_native.awb_files(utf(data)[1][0]["AwbFile"])[selected["sourceWaveId"]]

    def test_reflection_conversion_preserves_samples_and_timing_in_independent_decoder(self):
        converted, record = hca_transcode.convert(self.original)
        self.assertEqual((record["sampleRate"], record["samples"], record["channels"]), (48000, 38438, 1))
        self.assertEqual(record["sourceSha256"], hashlib.sha256(self.original).hexdigest())
        self.assertGreaterEqual(record["snrDb"], 55)
        hca_host.validate_layout(converted)
        with tempfile.TemporaryDirectory() as temporary:
            decoded = []
            for name, raw in (("source", self.original), ("converted", converted)):
                path = Path(temporary) / (name + ".hca")
                output = path.with_suffix(".wav")
                path.write_bytes(raw)
                subprocess.run([str(self.decoder), "-o", str(output), str(path)],
                               check=True, capture_output=True)
                decoded.append(hca_transcode.pcm(output.read_bytes()))
            checks = hca_transcode.fidelity(*decoded)
            # Compares sample-for-sample at the original time, with no lag
            # search: encoder padding mistakes and drift must fail this check.
            self.assertGreater(checks["snrDb"], 60)
            self.assertLess(checks["maxPcmError"], 64)

    def test_verified_cache_reuses_conversion_without_optional_encoder(self):
        with tempfile.TemporaryDirectory() as temporary:
            output, record = hca_transcode.prepare(self.original, temporary)
            with patch.object(hca_transcode, "codec", side_effect=AssertionError("Encoder must not run")):
                cached, cached_record = hca_transcode.prepare(self.original, temporary)
            self.assertEqual(cached, output)
            self.assertEqual(cached_record, record)
            with patch.object(hca_transcode, "codec", side_effect=AssertionError("Encoder must not run")):
                compatible, no_conversion = hca_transcode.prepare(output, temporary)
            self.assertEqual(compatible, output)
            self.assertIsNone(no_conversion)

    def test_corrupt_source_is_rejected_before_optional_encoder(self):
        damaged = bytearray(self.original)
        damaged[100] ^= 1
        with patch.object(hca_transcode, "codec", side_effect=AssertionError("Encoder must not run")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                hca_transcode.convert(bytes(damaged))


if __name__ == "__main__":
    unittest.main()
