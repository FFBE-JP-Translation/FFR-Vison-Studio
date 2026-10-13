"""Portable FFBE skill icons, shared by Studio previews and cooked game tables."""
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / 'data/ffbe/ability_icons'
PREFIX = 'UI.Skill.Action.Icon.FFBE.'
TABLES = ('UI/Skill/DT_ActionSkillIcon', 'UI/Skill/CDT_SkillIcon')


def filename(value):
    if not value: return None
    name = str(value)
    if name.isdecimal():
        aliases = ICONS / 'aliases.json'
        mapping = json.loads(aliases.read_text(encoding='utf-8')) if aliases.is_file() else {}
        name = mapping.get(name, '')
    return name if re.fullmatch(r'[A-Za-z0-9_]+\.png', name) else None


def path(value):
    name = filename(value)
    target = ICONS / name if name else None
    return target if target and target.is_file() else None


def tag(value):
    name = filename(value)
    return PREFIX + Path(name).stem if name else None


def catalog():
    return [{'tag': tag(p.name), 'row': 'FFBE · ' + p.stem.replace('_', ' '),
             'texture': 'FFBE_' + p.stem, 'png': 'ffbe_' + p.name, 'ffbeIcon': p.name}
            for p in sorted(ICONS.glob('*.png')) if filename(p.name)]


def recipe_tag(recipe, edits=None):
    """The source image is the default; explicit editor choices take priority."""
    settings = recipe.get('set', {})
    choice = (edits or {}).get('icon', recipe.get('iconChoice'))
    if choice: return choice
    source = recipe.get('ffbe', {}).get('icon')
    if source:
        source_path = path(source)
        if source_path: return tag(source_path.name)
        # No silent substitute for a missing source asset in a finished build.
        raise ValueError(f'Missing FFBE skill icon {source}. Add its icon asset before building.')
    return settings.get('SkillIcon.TagName')


def prepare(units, tbl, row_by, registry):
    """Bind every selected source/override icon, deduplicating across the roster."""
    used = set()
    for unit in units:
        recipes = [*unit.get('skills', {}).values(), *unit.get('convertedPassives', {}).values()]
        if unit.get('lb_custom'): recipes.append(unit['lb_custom'])
        for recipe in recipes:
            source = recipe.get('ffbe', {}).get('source')
            icon = recipe_tag(recipe, unit.get('nativeEdits', {}).get(source))
            if icon:
                recipe.setdefault('set', {})['SkillIcon.TagName'] = icon
                if icon.startswith(PREFIX): used.add(icon[len(PREFIX):] + '.png')
    donor = registry['add'][0]['cloneFrom'] if registry['add'] else None
    for name in sorted(used):
        if not path(name): raise ValueError(f'Missing selected FFBE icon {name}')
        icon = tag(name); stem = Path(name).stem
        package = f'/Game/UI/Textures/Icon/FFBE/FFBE_{stem}'
        registry['add'].append({'row': 'FFRStudio_Icon_' + stem, 'cloneFrom': donor,
                               'set': {'Tag': icon, 'DevComment': 'FFBE skill icon'}})
        for rel in TABLES:
            original, _ = row_by(rel, 'Tag', {'TagName': 'UI.Skill.Action.Icon.Fire'})
            tbl(rel)['add'].append({'row': 'FFRStudio_Icon_' + stem, 'cloneFrom': original,
                'set': {'Tag.TagName': icon, 'Brush.ResourceObject': package,
                        'Brush.ImageSize': {'X': 64.0, 'Y': 64.0}, 'Brush.bIsDynamicallyLoaded': True,
                        'Brush.ResourceName': package + '.FFBE_' + stem}})
    return sorted(used)


def build(names, legacy, output, work, ffrdt, usmap, run):
    from PIL import Image, ImageOps
    donor = Path(legacy) / 'FFRS/Content/UI/Textures/Icon/menu/ICON_Ability_summon13110.uasset'
    original = '/Game/UI/Textures/Icon/menu/ICON_Ability_summon13110'
    scratch = Path(work) / 'skill-icons'; scratch.mkdir(parents=True, exist_ok=True)
    for name in names:
        stem = Path(name).stem
        with Image.open(path(name)) as source:
            icon = ImageOps.contain(source.convert('RGBA'), (64, 64), Image.Resampling.LANCZOS)
            canvas = Image.new('RGBA', (64, 64))
            canvas.paste(icon, ((64-icon.width)//2, (64-icon.height)//2))
        payload = scratch / (stem + '.bgra'); payload.write_bytes(canvas.tobytes('raw', 'BGRA'))
        package = f'/Game/UI/Textures/Icon/FFBE/FFBE_{stem}'
        target = Path(output) / ('FFRS/Content/UI/Textures/Icon/FFBE/FFBE_' + stem + '.uasset')
        target.parent.mkdir(parents=True, exist_ok=True)
        run([*ffrdt, 'make-texture', str(donor), str(payload), '64', '64', str(target),
             original, package, f'ICON_Ability_summon13110=FFBE_{stem}', '--usmap', usmap])
