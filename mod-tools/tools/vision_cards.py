"""Vision-card catalog and source-art importer, shared by Studio and the game mod.

The first two source stat values are level-one and maximum-level stats. The
remaining values are growth modifiers, not additional equipment bonuses.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading

from PIL import Image, ImageChops, ImageStat

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools/devui'), str(ROOT / 'tools/ffbe2ss6')]
import ffrenv
from cpk import Cpk
from ffbe_frames import read_cgg, read_cgs, compose_frame

ROOT = Path(ffrenv.ROOT)
DATA = ROOT / 'data/vision_cards'
STAT_KEYS = ('hp', 'mp', 'atk', 'def', 'mag', 'spr')
PARAMETERS = dict(zip(STAT_KEYS, ('HitPoint', 'MagicPoint', 'PhysicalAttack',
                                'PhysicalDefense', 'MagicalAttack', 'MagicalDefense')))
AZURE = '401000401'
_import_lock = threading.Lock()
_render_lock = threading.Lock()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def normalize(card_id, row, region):
    card_id = str(card_id)
    if not re.fullmatch(r'\d{9}', card_id):
        raise ValueError(f'Invalid vision card ID: {card_id}')
    level = int(row['max_level'])
    if not 1 <= level <= 100:
        raise ValueError(f'{card_id}: invalid maximum level')
    stats = {}
    for key in STAT_KEYS:
        values = row['stats'][key]
        if not isinstance(values, list) or len(values) < 2:
            raise ValueError(f'{card_id}: missing maximum {key.upper()}')
        value = int(values[1])
        if value < 0 or value > 999999:
            raise ValueError(f'{card_id}: invalid {key.upper()}')
        stats[key] = value
    return {'id': card_id, 'name': row.get('name') or f'Vision Card {card_id}', 'description': row.get('description') or '',
            'region': region, 'maxLevel': level, 'stats': stats,
            'price': 1, 'abilities': [], 'imported': False, 'animated': False}


def sources():
    config = ffrenv.load_config().get('visionCards', {})
    datamine = Path(config.get('metadataRoot') or ROOT / 'data/ffbe')
    paths = [Path(p) for p in config.get('assetRoots', [])]
    if not paths:
        paths = [ROOT / 'data/vision_cards/source']
    return datamine, paths


def source_catalog(metadata=None):
    metadata = Path(metadata or sources()[0])
    cards = {}
    # Prefer GL's English names and GL stats for overlapping IDs; preserve JP-only cards.
    for region in ('jp', 'gl'):
        path = metadata / region / 'vision_cards.json'
        if path.is_file():
            for card_id, row in read_json(path).items():
                previous = cards.get(str(card_id))
                card = normalize(card_id, row, region.upper())
                if not row.get('name') and previous:
                    card['name'] = previous['name']
                card['sourceName'] = card['name']
                cards[str(card_id)] = card
    if not cards:
        raise FileNotFoundError('No vision_cards.json found. Choose the datamine data folder containing gl and jp.')
    # Local English translations for titles never localized in GL. Never replace
    # a genuine English source title if a later datamine supplies one.
    names = read_json(ROOT / 'tools/vision_card_names.json')
    for card_id, card in cards.items():
        if card_id in names and (card['name'].startswith('Vision Card ') or
                                re.search(r'[\u3040-\u30ff\u3400-\u9fff]', card['name'])):
            card['name'] = names[card_id]
            card['nameSource'] = 'local_translation'
    return cards


def catalog(data=DATA):
    path = Path(data) / 'catalog.json'
    if path.is_file():
        return read_json(path)
    return {'version': 1, 'cards': list(source_catalog().values()), 'shop': [], 'imported': 0}


def pick_shop(cards):
    ready = sorted((c for c in cards if c['imported']), key=lambda c: c['id'])
    if len(ready) < 10:
        raise ValueError('At least ten cards with artwork are needed for the Mitra shop.')
    # Reproducibly random assortment: rebuilding never unexpectedly changes the shop.
    selected = [c for c in ready if c['id'] == AZURE]
    level_one = [c for c in ready if c['maxLevel'] == 1 and c not in selected]
    if level_one:
        selected.append(level_one[0])
    pool = sorted((c for c in ready if c not in selected),
                  key=lambda c: hashlib.sha256(('Mitra Vision Cards:' + c['id']).encode()).digest())
    return [c['id'] for c in (selected + pool)[:10]]


def assign_native_ids(cards, data=DATA):
    """Keep FFBE IDs separate from the game's 10000–12999 equipment namespace.

    Persist allocations so future imports cannot remap inventory in old saves.
    """
    path = Path(data) / 'item_ids.json'
    ids = read_json(path) if path.exists() else {}
    used = set(ids.values())
    for card in sorted(cards, key=lambda c: c['id']):
        if card['id'] not in ids:
            available = next((i for i in range(12200, 13000) if i not in used), None)
            if available is None:
                raise ValueError('The reserved vision-card equipment ID range is full.')
            ids[card['id']] = available
            used.add(available)
        card['itemId'] = ids[card['id']]
    atomic_json(path, ids)


def import_all(metadata=None, asset_roots=None, data=DATA, progress=lambda **kw: None):
    """Copy all available source artwork, then publish one complete catalog atomically."""
    if not _import_lock.acquire(blocking=False):
        raise RuntimeError('A vision card import is already running.')
    try:
        data = Path(data)
        cards = source_catalog(metadata)
        roots = [Path(p) for p in (asset_roots or sources()[1])]
        raw = data / 'source'
        raw.mkdir(parents=True, exist_ok=True)
        valid = re.compile(r'vc_(?:(?:cgg|cgs|vignette_anime|vignette_icon_s|vignette_item_icon)_\d{9}\.(?:png|csv)|(?:bg|frame)_\d{2}_ll\.png)$')
        for source in roots:
            if not source.is_dir():
                continue
            progress(stage=f'Reading {source.name}')
            for path in source.glob('vc_*'):
                if path.is_file() and valid.fullmatch(path.name):
                    shutil.copy2(path, raw / path.name)
            for path in sorted(source.glob('*visioncard*.cpk')):
                archive = Cpk(str(path))
                with closing(archive.f):
                    for entry in archive.entries:
                        name = entry['name'] or ''
                        if valid.fullmatch(name):
                            payload = archive.read(entry)
                            target = raw / name
                            if not target.exists() or target.read_bytes() != payload:
                                target.write_bytes(payload)
        total = len(cards)
        for index, card in enumerate(cards.values()):
            cid = card['id']
            static = raw / f'vc_vignette_icon_s_{cid}.png'
            if not static.is_file():
                static = raw / f'vc_vignette_item_icon_{cid}.png'
            if static.is_file():
                with Image.open(static) as image:
                    image.verify()
                folder = data / cid
                folder.mkdir(exist_ok=True)
                shutil.copy2(static, folder / 'static.png')
                card['imported'] = True
                card['animated'] = all((raw / f'{prefix}_{cid}.{ext}').is_file()
                                       for prefix, ext in (('vc_cgg', 'csv'), ('vc_cgs', 'csv'), ('vc_vignette_anime', 'png')))
                if card['animated']:
                    steps = read_cgs(raw / f'vc_cgs_{cid}.csv')
                    card['animated'] = len({s['frame'] for s in steps}) > 1
            progress(stage=card['name'], completed=index + 1, total=total)
        result = {'version': 1, 'cards': sorted(cards.values(), key=lambda c: c['name'].casefold()),
                  'imported': sum(c['imported'] for c in cards.values()),
                  'missingArt': [c['id'] for c in cards.values() if not c['imported']],
                  'shop': pick_shop(cards.values())}
        assign_native_ids(result['cards'], data)
        atomic_json(data / 'catalog.json', result)
        if metadata is not None or asset_roots is not None:
            config = ffrenv.load_config()
            settings = config.setdefault('visionCards', {})
            if metadata is not None:
                settings['metadataRoot'] = str(Path(metadata).resolve())
            if asset_roots is not None:
                settings['assetRoots'] = [str(Path(p).resolve()) for p in asset_roots]
            ffrenv.save_config(config)
        return result
    finally:
        _import_lock.release()


def card_framing(preview, samples):
    """Recover the full-card camera from its supplied still, excluding the frame.

    FFBE's vignette coordinates describe a small stage. Card icons crop a 2x
    view of that stage, with a different camera offset for each illustration.
    Match distributed scene landmarks; never zoom around one moving character.
    """
    import cv2
    import numpy as np
    sift = cv2.SIFT_create()
    matcher = cv2.BFMatcher()
    mask = np.zeros((256, 192), np.uint8)
    mask[25:231, 20:172] = 255
    still = np.array(preview.convert('RGB'))
    target_points, target_desc = sift.detectAndCompute(cv2.cvtColor(still, cv2.COLOR_RGB2GRAY), mask)
    best = {'scale': 1, 'x': 0, 'y': 0, 'landmarks': 0}
    if target_desc is None:
        return best
    for sample in samples:
        scene = np.array(sample.convert('RGB').resize((384, 512), Image.Resampling.NEAREST))
        points, desc = sift.detectAndCompute(cv2.cvtColor(scene, cv2.COLOR_RGB2GRAY), None)
        if desc is None:
            continue
        matches = [a for a, b in matcher.knnMatch(desc, target_desc, k=2) if a.distance < .72 * b.distance]
        if len(matches) < 8:
            continue
        origin = np.float32([points[m.queryIdx].pt for m in matches])
        target = np.float32([target_points[m.trainIdx].pt for m in matches])
        # Art uses integer pixel scaling, never rotation. Voting on translation
        # rejects independently moving characters that can fool an affine fit.
        for scale in (1, 2, 3):
            offsets = origin * (scale / 2) - target
            for proposal in offsets:
                keep = np.max(np.abs(offsets - proposal), axis=1) < 2
                count = int(keep.sum())
                if (count < max(8, best['landmarks'] + 1) or count < len(matches) * .35 or
                        np.ptp(target[keep], axis=0).min() < 35):
                    continue
                offset = np.median(offsets[keep], axis=0)
                best = {'scale': scale, 'x': int(round(offset[0])), 'y': int(round(offset[1])), 'landmarks': count}
    if not best['landmarks']:
        # Strong animated glow can hide SIFT corners (e.g. The Book Burning).
        # Require several separate background patches to agree on one camera.
        for sample in samples[::max(1, len(samples) // 3)]:
            for scale in (2, 3):
                scene = np.array(sample.convert('RGB').resize((192 * scale, 256 * scale), Image.Resampling.NEAREST))
                votes, locations = [], []
                for y in range(28, 206, 28):
                    for x in range(22, 142, 24):
                        patch = still[y:y + 32, x:x + 32]
                        scores = cv2.matchTemplate(scene, patch, cv2.TM_CCOEFF_NORMED)
                        _, score, _, point = cv2.minMaxLoc(scores)
                        if score >= .7:
                            votes.append((point[0] - x, point[1] - y))
                            locations.append((x, y))
                if not votes:
                    continue
                offsets, positions = np.array(votes), np.array(locations)
                for proposal in offsets:
                    keep = np.max(np.abs(offsets - proposal), axis=1) <= 2
                    count = int(keep.sum())
                    span = np.ptp(positions[keep], axis=0)
                    if count < max(5, best['landmarks'] + 1) or span.min() < 24 or span.max() < 56:
                        continue
                    offset = np.median(offsets[keep], axis=0)
                    best = {'scale': scale, 'x': int(round(offset[0])), 'y': int(round(offset[1])),
                            'landmarks': count, 'method': 'background_patches'}
    return best


def card_art(card_id, animated=False, data=DATA):
    if not re.fullmatch(r'\d{9}', str(card_id)):
        raise ValueError('Invalid card ID')
    data = Path(data)
    card = next((c for c in catalog(data)['cards'] if c['id'] == card_id), None)
    if not card or not card['imported']:
        raise FileNotFoundError('Card artwork has not been imported.')
    static = data / card_id / 'static.png'
    if not animated or not card['animated']:
        return static
    with _render_lock:
        output = data / card_id / 'animated.webp'
        raw = data / 'source'
        inputs = [static, raw / f'vc_cgg_{card_id}.csv', raw / f'vc_cgs_{card_id}.csv',
                  raw / f'vc_vignette_anime_{card_id}.png', *raw.glob('vc_frame_*_ll.png'), *raw.glob('vc_bg_*_ll.png'), Path(__file__)]
        if output.is_file() and output.stat().st_mtime >= max(p.stat().st_mtime for p in inputs):
            return output
        frames = read_cgg(raw / f'vc_cgg_{card_id}.csv')
        steps = read_cgs(raw / f'vc_cgs_{card_id}.csv')
        with Image.open(raw / f'vc_vignette_anime_{card_id}.png') as source:
            atlas = source.convert('RGBA')
        # Assemble the complete timeline in stage coordinates before applying
        # the card's camera; keep the decorative frame outside that transform.
        with Image.open(static) as preview:
            preview = preview.convert('RGBA').resize((192, 256))
        borders = []
        for path in raw.glob('vc_frame_*_ll.png'):
            with Image.open(path) as source:
                border = source.convert('RGBA').resize((192, 256), Image.Resampling.LANCZOS)
            mask = border.getchannel('A').point(lambda a: 255 if a > 240 else 0)
            difference = ImageChops.difference(preview.convert('RGB'), border.convert('RGB'))
            score = sum(ImageStat.Stat(difference, mask=mask).mean)
            borders.append((score, border, path))
        chosen = min(borders, key=lambda b: b[0]) if borders else None
        border = chosen[1] if chosen else None
        background = Image.new('RGBA', (192, 256))
        if chosen:
            bg = raw / chosen[2].name.replace('vc_frame_', 'vc_bg_')
            if bg.exists():
                with Image.open(bg) as source:
                    background = source.convert('RGBA').resize((192, 256), Image.Resampling.LANCZOS)
        scenes = {}
        for step in steps:
            key = (step['frame'], step['x'], step['y'])
            if key not in scenes:
                full = compose_frame(atlas, frames[step['frame']])
                x, y = step['x'], step['y']
                scenes[key] = full.crop((512-x, 256-y, 704-x, 512-y))
        unique = list(scenes.values())
        samples = []
        for index in sorted({round(i * (len(unique) - 1) / 12) for i in range(13)}):
            sample = background.copy()
            sample.alpha_composite(unique[index])
            samples.append(sample)
        framing = card_framing(preview, samples)
        atomic_json(data / card_id / 'framing.json', framing)
        composed = {}
        for key, scene in scenes.items():
            scale, x, y = framing['scale'], framing['x'], framing['y']
            scene = scene.resize((192 * scale, 256 * scale), Image.Resampling.NEAREST)
            frame = background.copy()
            frame.alpha_composite(scene.crop((x, y, x + 192, y + 256)))
            if border:
                frame.alpha_composite(border)
            composed[key] = frame
        sequence, durations = [], []
        for step in steps:
            image = composed[(step['frame'], step['x'], step['y'])]
            sequence.append(image)
            durations.append(max(10, round(step['delay'] * 1000 / 60)))
        temporary = output.with_suffix('.tmp')
        sequence[0].save(temporary, format='WEBP', save_all=True, append_images=sequence[1:],
                         duration=durations, loop=0, lossless=True)
        temporary.replace(output)
        return output


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', type=Path)
    parser.add_argument('--assets', type=Path, action='append')
    args = parser.parse_args()
    result = import_all(args.metadata, args.assets, progress=lambda **kw: print(json.dumps(kw), flush=True))
    print(json.dumps({k: v for k, v in result.items() if k != 'cards'}, indent=2))
