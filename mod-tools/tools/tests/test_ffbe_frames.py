"""CGG transform regression tests, independent of the rendered frame previews."""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ffbe2ss6"))
from ffbe_frames import compose_frame, read_cgg
from build_sprites import Sheets, build


class FrameTransformsTests(unittest.TestCase):
    def setUp(self):
        # Six asymmetric pixels make wrong signs, flip order and placement
        # distinguishable. CGG image coordinates are a crop within an atlas.
        self.colors = [(v, 0, 0, 255) for v in range(1, 7)]
        self.atlas = Image.new("RGBA", (5, 5))
        tile = Image.new("RGBA", (3, 2))
        tile.putdata(self.colors)
        self.atlas.paste(tile, (1, 2))

    def part(self, rotation=0, flip=0):
        # Exercise the public CSV parser rather than manufacturing its output.
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "unit_cgg_test.csv"
            source.write_text(f"0,1,-4,-5,{flip},0,100,{rotation},1,2,3,2,0\n")
            return read_cgg(source)[0]

    def rendered_values(self, rotation, expected_size, flip=0):
        image = compose_frame(self.atlas, self.part(rotation, flip), canvas=32)
        x, y = 16 - 4, 16 - 5
        w, h = expected_size
        # Rotation expands at the CGG part's top-left, preserving its placement.
        self.assertEqual((x, y, x + w, y + h), image.getbbox())
        return list(image.crop((x, y, x + w, y + h)).tobytes()[0::4])

    def test_cgg_positive_quarter_turn_is_counterclockwise(self):
        # Source rows [1,2,3]/[4,5,6] become [3,6]/[2,5]/[1,4].
        # This also matches the legacy assembler's clockwise Jimp.rotate(-90).
        self.assertEqual([3, 6, 2, 5, 1, 4], self.rendered_values(90, (2, 3)))

    def test_negative_quarter_turn_is_clockwise(self):
        self.assertEqual([4, 1, 5, 2, 6, 3], self.rendered_values(-90, (2, 3)))

    def test_unrotated_and_half_turn_parts_keep_their_orientation(self):
        self.assertEqual([1, 2, 3, 4, 5, 6], self.rendered_values(0, (3, 2)))
        self.assertEqual([6, 5, 4, 3, 2, 1], self.rendered_values(180, (3, 2)))

    def test_flips_happen_before_rotation(self):
        self.assertEqual([1, 4, 2, 5, 3, 6], self.rendered_values(90, (2, 3), flip=1))
        self.assertEqual([6, 3, 5, 2, 4, 1], self.rendered_values(90, (2, 3), flip=2))
        self.assertEqual([4, 1, 5, 2, 6, 3], self.rendered_values(90, (2, 3), flip=3))

    def test_exported_sprite_atlas_uses_corrected_compositor(self):
        cgg = [self.part(90)]
        steps = [{"frame": 0, "x": 7, "y": -8, "delay": 6}]
        sheets = Sheets((self.atlas, cgg, {"idle": steps, "magicatk": steps}))
        atlas, spec = build(sheets, [("magic_attack", "magicatk")], "test", 64)
        cell = spec["cells"][0]
        x, y = map(int, cell["pos"])
        w, h = map(int, cell["size"])
        values = list(atlas.crop((x, y, x + w, y + h)).tobytes()[0::4])
        self.assertEqual([3, 6, 2, 5, 1, 4], values)
        part = spec["animations"][0]["parts"]["part_0"]
        self.assertEqual([[0, 7.0]], part["Posx"])
        self.assertEqual([[0, 8.0]], part["Posy"])


if __name__ == "__main__":
    unittest.main()
