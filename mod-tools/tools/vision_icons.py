"""Command-icon tags registered through FFR's existing gameplay-tag table."""
import json
from pathlib import Path
import subprocess

REGISTRY_ASSET = 'FFRS/Plugins/DebugMenuWidget/Content/Data/GameplayTag/DM_CDT_GamplayTag'
ICON_TABLES = ('UI/Skill/DT_CommandSkillIcon', 'UI/Skill/CDT_SkillIcon')


def command_tag(vision_id):
    return f'UI.Skill.Command.Icon.FFRStudio.{int(vision_id)}'


def registry_rows(legacy, cache, ffrdt, usmap, retoc, game):
    """Existing installations acquire this small native table on their next build."""
    asset = Path(legacy)/(REGISTRY_ASSET+'.uasset')
    if not asset.is_file():
        if not game:
            raise ValueError('Choose the game folder in Studio before building command icons.')
        result = subprocess.run([str(retoc), 'to-legacy', '--no-shaders', '--filter',
                                 'DebugMenuWidget/Content/Data/GameplayTag/DM_CDT_GamplayTag',
                                 str(Path(game)/'FFRS/Content/Paks'), str(legacy)],
                                capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode or not asset.is_file():
            raise RuntimeError('Could not extract the command-icon tag registry: '+(result.stderr or result.stdout)[-600:])
    target = Path(cache); target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([*ffrdt, 'rows', str(asset), str(target), '--usmap', str(usmap)],
                            capture_output=True, text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError('Could not read the command-icon tag registry: '+(result.stderr or result.stdout)[-600:])
    data = json.loads(target.read_text(encoding='utf-8'))
    if data.get('_rowStruct') != 'GameplayTagTableRow' or not data.get('rows'):
        raise ValueError('The game command-icon tag registry has an unexpected schema.')
    return data['rows']


def registry_patch(units, native):
    donor = next(iter(native)); occupied_rows = set(native)
    occupied_tags = {row['Tag'] for row in native.values()}; additions = []
    for unit in units:
        tag = command_tag(unit['id']); name = f"FFRStudio_Command_{int(unit['id'])}"
        if tag in occupied_tags or name in occupied_rows:
            raise ValueError(f'Duplicate command icon for vision {unit["id"]}. Prepare clean game tables and check for duplicate units.')
        occupied_tags.add(tag); occupied_rows.add(name)
        additions.append({'row':name, 'cloneFrom':donor, 'set':{'Tag':tag, 'DevComment':'FFR Vision Studio command icon'}})
    return {'asset':REGISTRY_ASSET, 'add':additions, 'set':[]}


def add_icon_rows(unit, tbl, row_by):
    vid = int(unit['id']); tag = command_tag(vid)
    package = f'/Game/UI/Textures/Icon/menu/ICON_Ability_summon{vid}'
    for rel in ICON_TABLES:
        donor, _ = row_by(rel, 'Tag', {'TagName':'UI.Skill.Command.Icon.13110'})
        tbl(rel)['add'].append({'row':f'FFRStudio_Command_{vid}', 'cloneFrom':donor, 'set':{
            'Tag.TagName':tag, 'Brush.ResourceObject':package,
            'Brush.ImageSize':{'X':64.0, 'Y':64.0}, 'Brush.bIsDynamicallyLoaded':True,
            'Brush.ResourceName':f'{package}.ICON_Ability_summon{vid}'}})
    return tag
