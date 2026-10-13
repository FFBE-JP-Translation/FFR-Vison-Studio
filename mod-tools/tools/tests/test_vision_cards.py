import json
from pathlib import Path
import sys
import tempfile
import unittest
from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
import vision_cards as vc


class VisionCardTests(unittest.TestCase):
    def test_full_card_animation_matches_still_and_keeps_timeline(self):
        card_id = vc.AZURE
        path = vc.card_art(card_id, True)
        framing = vc.read_json(path.parent / 'framing.json')
        self.assertEqual((framing['scale'], framing['x'], framing['y']), (2, 96, 84))
        # The temple's left pillar is a stable landmark behind the moving hero.
        with Image.open(path) as animation, Image.open(path.parent / 'static.png') as still:
            duration = 0
            for frame in range(animation.n_frames):
                animation.seek(frame)
                animation.load()
                duration += animation.info['duration']
            self.assertAlmostEqual(duration, 24000, delta=150)
            animation.seek(95)
            region = (22, 56, 63, 120)
            difference = ImageChops.difference(animation.convert('RGB').crop(region), still.convert('RGB').crop(region))
            self.assertLess(sum(ImageStat.Stat(difference).mean) / 3, 30)

    def test_featureless_artwork_is_not_arbitrarily_cropped(self):
        image = Image.new('RGB', (192, 256), (20, 30, 40))
        self.assertEqual(vc.card_framing(image, [image]), {'scale': 1, 'x': 0, 'y': 0, 'landmarks': 0})

    def test_blank_gl_name_keeps_jp_title_then_translates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            row = {'name': 'BLOODY ESCAPE -地獄の逃走劇-', 'max_level': 1,
                   'stats': {key: [0, 60] for key in vc.STAT_KEYS}}
            vc.atomic_json(root / 'jp/vision_cards.json', {'354000101': row})
            vc.atomic_json(root / 'gl/vision_cards.json', {'354000101': {**row, 'name': None}})
            card = vc.source_catalog(root)['354000101']
            self.assertEqual(card['name'], 'BLOODY ESCAPE: Escape from Hell')
            self.assertEqual(card['sourceName'], row['name'])
            vc.atomic_json(root / 'gl/vision_cards.json', {'354000101': {**row, 'name': 'Official localized title'}})
            self.assertEqual(vc.source_catalog(root)['354000101']['name'], 'Official localized title')

    def test_native_item_ids_survive_later_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            original = [{'id': '400000001'}, {'id': '500000001'}]
            vc.assign_native_ids(original, folder)
            later = [{'id': '100000001'}, {'id': '500000001'}, {'id': '400000001'}]
            vc.assign_native_ids(later, folder)
            self.assertEqual(original[0]['itemId'], later[2]['itemId'])
            self.assertEqual(original[1]['itemId'], later[1]['itemId'])
            self.assertEqual(len({c['itemId'] for c in later}), 3)

    def test_max_stats_ignore_growth_modifiers_and_abilities(self):
        row = {'name': 'Example', 'max_level': 1,
               'stats': {k: [10, 120, 999, 999] for k in vc.STAT_KEYS},
               'skills': [{'level': 1, 'id': 123}]}
        card = vc.normalize('100000001', row, 'GL')
        self.assertEqual(card['stats'], dict.fromkeys(vc.STAT_KEYS, 120))
        self.assertEqual(card['maxLevel'], 1)
        self.assertEqual(card['abilities'], [])

    def test_shop_is_ten_unique_available_cards_and_contains_azure(self):
        cards = vc.catalog()['cards']
        shop = vc.pick_shop(cards)
        self.assertEqual(len(set(shop)), 10)
        self.assertIn(vc.AZURE, shop)
        self.assertEqual(shop, vc.pick_shop(reversed(cards)))
        self.assertTrue(all(next(c for c in cards if c['id'] == cid)['imported'] for cid in shop))

    def test_packaged_card_stats_prices_and_original_rows(self):
        latest = vc.read_json(ROOT / 'build/vision-cards/latest-package.json')
        work = Path(latest['work'])
        relative = 'Item/DT_EquipmentItemData.json'
        original = vc.read_json(work / 'rows' / relative)['rows']
        actual = vc.read_json(work / 'verified' / relative)['rows']
        for name, row in original.items():
            self.assertEqual(row, actual[name])
        for card in vc.catalog()['cards']:
            row = actual['VisionCard_' + card['id']]
            self.assertEqual(row['buyingPrice'], 1)
            self.assertEqual(row['EquipmentType'], 'None')
            self.assertFalse(row['isAvailableSale'])
            for stat, value in card['stats'].items():
                self.assertEqual(row['params']['eUnitParameterType::' + vc.PARAMETERS[stat]], value)
        shop = vc.read_json(work / 'verified/Shop/DT_ShopList.json')['rows']['Mitra_VisionCards']
        cards = {c['id']: c for c in vc.catalog()['cards']}
        self.assertEqual([v['ItemId'] for v in shop['ItemList']], [cards[cid]['itemId'] for cid in latest['shop']])


if __name__ == '__main__':
    unittest.main()
