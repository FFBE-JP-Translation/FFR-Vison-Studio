"""Import authored PNG/animation JSON into the existing FFBE-to-SpriteStudio path."""
import base64
import binascii
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS = ('None', 'Fire', 'Ice', 'Wind', 'Earth', 'Thunder', 'Water', 'Light', 'Dark')
STATS = {'MaxHitPoint': 800, 'MaxMagicPoint': 100, 'Attack': 25, 'Defence': 30, 'Intelligence': 10, 'Mind': 20, 'Agility': 15}
MOTIONS = {'idle': 'idle', 'ready': 'standby', 'move': 'move', 'attack': 'atk', 'cast': 'magic_standby',
           'magic': 'magicatk', 'limitBurst': 'limitatk', 'jump': 'jump', 'hurt': 'dying', 'down': 'dead',
           'victory': 'win', 'victoryStart': 'winbefore'}
UNIT_TEMPLATE = {
    'schema': 'ffr-custom-unit-1', 'name': 'My Vision', 'key': 'my_vision',
    'description': 'An original vision.', 'attackType': 'Physic', 'element': 'Light',
    'stats': STATS, 'price': 1, 'menuScale': 2.52, 'skills': [],
    'resonance': {'name': 'Radiant Strike', 'hitFrames': [12, 24], 'moveType': 1},
}
ANIMATION_TEMPLATE = {
    'schema': 'ffr-animations-1', 'fps': 60, 'frameSize': [64, 64], 'pivot': [32, 60],
    'animations': {
        'idle': [{'frame': 0, 'hold': 24}, {'frame': 1, 'hold': 24}],
        'attack': [{'frame': 2, 'hold': 12}, {'frame': 3, 'hold': 12}],
        'limitBurst': [{'frame': 0, 'hold': 12}, {'frame': 2, 'hold': 12}, {'frame': 3, 'hold': 24}],
        'move': [{'frame': 1, 'hold': 8}], 'down': [{'frame': 4, 'hold': 60}],
        'victory': [{'frame': 5, 'hold': 60}],
    },
}


def integer(value, label, lo, hi):
    if type(value) is not int or not lo <= value <= hi:
        raise ValueError(f'{label} must be a whole number from {lo} to {hi}.')
    return value


def number(value, label, lo, hi):
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise ValueError(f'{label} must be a number from {lo} to {hi}.')
    return value


def text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValueError(f'{label} must contain 1 to {limit} characters.')
    return value.strip()


def png(encoded, label):
    try:
        raw = base64.b64decode(encoded, validate=True)
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError(f'{label} must be smaller than 16 MiB.')
        image = Image.open(io.BytesIO(raw))
        if image.format != 'PNG' or image.width > 4096 or image.height > 4096:
            raise ValueError(f'{label} must be a PNG no larger than 4096 × 4096 pixels.')
        image.load()
        return image.convert('RGBA')
    except (binascii.Error, OSError, TypeError, Image.DecompressionBombError) as ex:
        raise ValueError(f'{label} is not a readable PNG.') from ex


def animation_data(doc, image):
    if not isinstance(doc, dict) or doc.get('schema') != 'ffr-animations-1' or doc.get('fps') != 60:
        raise ValueError('Animation JSON must use schema ffr-animations-1 and fps 60. Download the template.')
    frames = doc.get('frames')
    if frames is None:
        size = doc.get('frameSize')
        if not isinstance(size, list) or len(size) != 2:
            raise ValueError('Set frameSize to [width, height], or provide frames with rect and pivot.')
        w, h = [integer(v, 'Frame size', 1, 512) for v in size]
        if image.width % w or image.height % h:
            raise ValueError('The sheet dimensions must be multiples of frameSize.')
        if image.width // w * (image.height // h) > 256:
            raise ValueError('The grid has more than 256 frames. Increase frameSize or split the sheet.')
        frames = [{'rect': [x, y, w, h], 'pivot': doc.get('pivot', [w // 2, h])}
                  for y in range(0, image.height, h) for x in range(0, image.width, w)]
    if not isinstance(frames, list) or not 1 <= len(frames) <= 256:
        raise ValueError('Provide between 1 and 256 sprite frames.')
    rows = []
    for n, frame in enumerate(frames):
        rect = frame.get('rect') if isinstance(frame, dict) else None
        if not isinstance(rect, list) or len(rect) != 4:
            raise ValueError(f'Frame {n}: rect must be [x, y, width, height].')
        x, y = [integer(v, f'Frame {n} position', 0, 4096) for v in rect[:2]]
        w, h = [integer(v, f'Frame {n} size', 1, 512) for v in rect[2:]]
        if x + w > image.width or y + h > image.height:
            raise ValueError(f'Frame {n} extends beyond the sprite sheet.')
        pivot = frame.get('pivot', [w // 2, h])
        if not isinstance(pivot, list) or len(pivot) != 2:
            raise ValueError(f'Frame {n}: pivot must be [x, y], measured from its top-left corner.')
        px = integer(pivot[0], f'Frame {n} pivot X', 0, w)
        py = integer(pivot[1], f'Frame {n} pivot Y', 0, h)
        rows.append([0, 1, -px, -py, 0, 0, 100, 0, x, y, w, h, 0])
    animations = doc.get('animations')
    if not isinstance(animations, dict) or any(a not in animations for a in ('idle', 'attack', 'limitBurst')):
        raise ValueError('Animations must include idle, attack and limitBurst.')
    unknown = set(animations) - MOTIONS.keys()
    if unknown:
        raise ValueError('Unknown animation names: ' + ', '.join(sorted(unknown)))
    normalized = {}
    for name, steps in animations.items():
        if not isinstance(steps, list) or not 1 <= len(steps) <= 600:
            raise ValueError(f'{name} must contain 1 to 600 steps.')
        out = []
        for step in steps:
            if not isinstance(step, dict):
                raise ValueError(f'{name}: each step needs frame and hold.')
            idx = integer(step.get('frame'), f'{name} frame', 0, len(rows) - 1)
            hold = integer(step.get('hold'), f'{name} hold', 1, 3600)
            offset = step.get('offset', [0, 0])
            if not isinstance(offset, list) or len(offset) != 2:
                raise ValueError(f'{name}: offset must be [x, y].')
            dx, dy = [integer(v, f'{name} offset', -256, 256) for v in offset]
            row = rows[idx]
            if not (-512 <= row[2] + dx and row[2] + dx + row[10] <= 512 and
                    -512 <= row[3] + dy and row[3] + dy + row[11] <= 512):
                raise ValueError(f'{name}: frame plus offset exceeds the 1024-pixel animation canvas.')
            out.append([idx, dx, dy, hold])
        if sum(s[3] for s in out) > 3600:
            raise ValueError(f'{name} must be at most 60 seconds long.')
        normalized[MOTIONS[name]] = out
    if not any(image.crop((r[8], r[9], r[8] + r[10], r[9] + r[11])).getbbox() for r in (rows[s[0]] for s in normalized['idle'])):
        raise ValueError('The idle animation is fully transparent. Choose a visible frame.')
    warnings = [f'{name} was not supplied; the idle animation will be used.' for name in ('move', 'magic', 'down', 'victory') if name not in animations]
    return rows, normalized, warnings


def prepare(body, units, catalog, make_spec):
    doc = body.get('unit')
    if not isinstance(doc, dict) or doc.get('schema') != 'ffr-custom-unit-1':
        raise ValueError('Unit JSON must use schema ffr-custom-unit-1. Download the template.')
    name = text(doc.get('name'), 'Name', 80)
    key = text(doc.get('key'), 'Key', 48)
    if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
        raise ValueError('Key must start with a lowercase letter and use only a-z, 0-9 and underscores.')
    if any(u['key'] == key for u in units) or (ROOT / 'units/custom' / key).exists():
        raise ValueError('That key already exists. Choose a different key to keep the existing unit intact.')
    attack = doc.get('attackType', 'Physic')
    element = doc.get('element', 'None')
    if attack not in ('Physic', 'Magic') or element not in ELEMENTS:
        raise ValueError('Choose Physic or Magic and a supported element from the unit template.')
    stats = doc.get('stats', {})
    if not isinstance(stats, dict) or set(stats) - STATS.keys():
        raise ValueError('Use the stat names in the unit template.')
    stats = {k: integer(stats.get(k, v), k, 1, 99999 if k == 'MaxHitPoint' else 9999) for k, v in STATS.items()}
    price = integer(doc.get('price', 1), 'Shop price', 0, 9999999)
    menu_scale = number(doc.get('menuScale', 2.52), 'Menu scale', .1, 10)
    skills = doc.get('skills', [])
    if not isinstance(skills, list) or len(skills) > 32:
        raise ValueError('skills must contain up to 32 existing FFR skill IDs.')
    allowed = {s['id'] for s in catalog['skills'] if s.get('seq') and s.get('attr') in ('Ability', 'Magic', 'MagicSword') and s.get('hasUnit') == 'All'}
    if any(type(s) is not int or s not in allowed for s in skills):
        raise ValueError('One or more skills are unavailable. Use the FFR skill IDs shown in Advanced Studio, or leave skills empty and add them later.')
    image = png(body.get('sheet'), 'Sprite sheet')
    rows, animations, warnings = animation_data(body.get('animations'), image)
    resonance = doc.get('resonance', {})
    if not isinstance(resonance, dict):
        raise ValueError('resonance must be an object with name, hitFrames and moveType.')
    duration = sum(s[3] for s in animations['limitatk'])
    hits = resonance.get('hitFrames', [max(0, duration * 3 // 5)])
    if not isinstance(hits, list) or not 1 <= len(hits) <= 30:
        raise ValueError('Resonance hitFrames must contain 1 to 30 frame numbers.')
    for value in hits:
        integer(value, 'Resonance hit frame', 0, duration - 1)
    if hits != sorted(hits):
        raise ValueError('Resonance hitFrames must be in chronological order.')
    move = integer(resonance.get('moveType', 0), 'Resonance moveType', 0, 1)
    lb_name = text(resonance.get('name', name + "'s Resonance"), 'Resonance name', 100)
    # Deleted visions free game IDs, but their uploaded artwork remains. Use a
    # separate source ID so the next custom unit cannot pick up an old preview.
    form = '99' + str(uuid.uuid4().int % 10**12).zfill(12)
    while list((ROOT / 'units/custom').glob(f'*/sprites/{form}')):
        form = '99' + str(uuid.uuid4().int % 10**12).zfill(12)
    detail = {'id': form, 'name': name, 'region': 'CUSTOM', 'roles': ['Mage' if attack == 'Magic' else 'Attacker'],
              'description': text(doc.get('description', 'An original vision.'), 'Description', 2000),
              'forms': {form: {'rarity': 'NV', 'sprites': list(animations), 'limitburst': {'name': lb_name}}},
              'maxForm': form, 'rarity': ['NV', 'NV'], 'ffrStats': stats, 'abilities': [], 'passives': [], 'skills': []}
    spec = make_spec(detail, form, key, name, units)
    dest = ROOT / 'units/custom' / key
    spec['ffbe'].update(dir=f'units/custom/{key}/sprites/{form}', id=form, base=form, source='CUSTOM')
    spec.update(custom={'schema': 1, 'animations': list(animations), 'warnings': warnings}, price=price, menuScale=menu_scale)
    spec['awakening'] = [[['ActiveSkill', sid] for sid in skills[i:i+8]] for i in range(0, 32, 8)]
    # Keep the private test shortcut when the local launcher requests it.
    if os.environ.get('FFR_LOCAL_RESONANCE_TEST') == '1':
        for sid, skill in spec['skills'].items():
            if skill.get('studio') == 'raegen_blast':
                tier = next((tier for tier in spec['awakening'] if len(tier) < 8), None)
                if tier is not None: tier.append(['ActiveSkill', int(sid)])
    count = len(hits)
    source = {'schema': 2, 'fps': 60, 'unitId': form, 'lbId': form, 'availableLbIds': [form], 'name': lb_name,
              'elements': [] if element == 'None' else [element], 'moveType': move, 'movement': {'type': move},
              'damageComponent': 0, 'components': [{'index': 0, 'type': 15 if attack == 'Magic' else 1, 'target': 1, 'range': 2}],
              'hitFrames': hits, 'hitPercents': [100 // count + (i < 100 % count) for i in range(count)],
              'sounds': [], 'source': {'presentation': 'Authored custom unit animation'}}
    description = f"{count} hits of {element if element != 'None' else 'non-elemental'} {'physical' if attack == 'Physic' else 'magic'} damage to all enemies."
    detail['forms'][form]['limitburst'].update(effects=[description], element=source['elements'], attack_count=[count])
    spec['lb_custom'].update(ffbe_lb=f'units/custom/{key}/resonance.json', ffbe_lb_id=form, nameAuto=False,
                             en=lb_name, desc=description, descAuto=True, mechanics='ffbe', presentation='ffbe', audio='native',
                             set={'element': element, 'hitCount': count, 'DamageType': attack, 'damageCalcType': attack})
    icon = png(body['icon'], 'Portrait icon') if body.get('icon') else None
    if icon is None:
        first = rows[animations['idle'][0][0]]
        icon = image.crop((first[8], first[9], first[8] + first[10], first[9] + first[11]))
        bounds = icon.getbbox()
        if bounds: icon = icon.crop(bounds)
        icon.thumbnail((56, 56), Image.Resampling.NEAREST)
        canvas = Image.new('RGBA', (56, 56)); canvas.alpha_composite(icon, ((56-icon.width)//2, (56-icon.height)//2)); icon = canvas
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.import-', dir=dest.parent))
    try:
        sprite = staging / 'sprites' / form; sprite.mkdir(parents=True)
        image.save(sprite / f'unit_anime_{form}.png')
        icon.save(sprite / f'unit_icon_{form}.png')
        with (sprite / f'unit_cgg_{form}.csv').open('w', newline='') as f:
            csv.writer(f).writerows(rows)
        for motion, steps in animations.items():
            with (sprite / f'unit_{motion}_cgs_{form}.csv').open('w', newline='') as f:
                csv.writer(f).writerows(steps)
        for filename, data in [('unit.json', doc), ('animations.json', body['animations']), ('detail.json', detail), ('resonance.json', source)]:
            (staging / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding='utf-8')
        staging.rename(dest)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return spec, warnings, dest
