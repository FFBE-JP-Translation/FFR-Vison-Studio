"""Prepare a local Lua catalog and PNG animation frames for the card mod."""
import argparse
import json
from pathlib import Path
import shutil
from PIL import Image
import vision_cards as vc


def lua(value):
    if value is None: return 'nil'
    if isinstance(value, bool): return 'true' if value else 'false'
    if isinstance(value, (int, float)): return str(value)
    if isinstance(value, str): return json.dumps(value, ensure_ascii=False).replace('\\/', '/')
    if isinstance(value, list): return '{' + ','.join(lua(v) for v in value) + '}'
    return '{' + ','.join('['+lua(k)+']='+lua(v) for k,v in value.items()) + '}'


def export(destination, only_shop=False, reuse_art=False):
    destination = Path(destination)
    scripts = destination / 'Scripts'
    scripts.mkdir(parents=True, exist_ok=True)
    catalog = vc.catalog()
    for index, source in enumerate(catalog['cards']):
        card = dict(source)
        cid = card['id']
        card['id'] = int(cid)
        card['static'] = (vc.DATA / cid / 'static.png').as_posix()
        if card['animated'] and (not only_shop or cid in catalog['shop']):
            path = vc.DATA / cid / 'animated.webp'
            if not reuse_art or not path.exists():
                path = vc.card_art(cid, True)
            folder = vc.DATA / cid / 'frames'
            folder.mkdir(exist_ok=True)
            with Image.open(path) as image:
                card['frames'] = []
                for i in range(image.n_frames):
                    image.seek(i)
                    frame = folder / f'{i:04}.png'
                    if not frame.exists() or frame.stat().st_mtime < path.stat().st_mtime:
                        image.convert('RGBA').save(frame)
                    card['frames'].append({'path': frame.as_posix(), 'duration': image.info.get('duration', 100)})
        catalog['cards'][index] = card
        print(f"{index+1}/{len(catalog['cards'])} {card['name']}", flush=True)
    catalog['shop'] = [int(v) for v in catalog['shop']]
    catalog['icon'] = (vc.ROOT / 'src/ffr-vision-cards/assets/card-back-reference.png').as_posix()
    catalog['removeIcon'] = (vc.ROOT / 'download.png').as_posix()
    (scripts / 'catalog.lua').write_text('return '+lua(catalog)+'\n', encoding='utf-8')
    for source in (vc.ROOT / 'src/ffr-vision-cards').glob('*.lua'):
        shutil.copy2(source, scripts / source.name)
    (destination / 'dlls').mkdir(exist_ok=True)
    shutil.copy2(vc.ROOT / 'build/vision-cards/native/Release/main.dll', destination / 'dlls/main.dll')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--shop-only', action='store_true')
    parser.add_argument('--reuse-art', action='store_true', help='Reuse rendered artwork for metadata-only updates')
    args = parser.parse_args()
    export(args.destination, args.shop_only, args.reuse_art)
