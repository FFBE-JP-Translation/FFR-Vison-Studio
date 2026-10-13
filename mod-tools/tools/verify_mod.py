"""Diff every DataTable in build/visions_mod/assets against extracted/rows: pre-existing rows must be unchanged
unless explicitly expected or matching the converter's append-only skill bindings.
Exit code 1 on unexpected changes.
usage: python tools/verify_mod.py"""
import glob, json, os, subprocess, sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools")); import ffrenv
import vision_icons
import skill_icons
BASE = os.path.join(ROOT, "build", "visions_mod", "assets", "FFRS", "Content", "Datatable")
TMP = os.path.join(ROOT, "build", "visions_mod", "verify")
def expected_rows():
    return {   # table -> rows the generator edits in place
        "Shop/DT_ShopList": {"ミトラ_道具　1章"},
    }


def equivalent(a, b):
    """UAssetAPI may serialize signed floating zero as a string or a number."""
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b))
    if type(a) is str and a in ("+0", "-0") and type(b) in (int, float):
        return b == 0
    if type(b) is str and b in ("+0", "-0") and type(a) in (int, float):
        return a == 0
    return a == b


def expected_general_change(rel, row, original, built, planned):
    """Accept only planned binding appends, preserving every native entry and field."""
    if rel != 'Skill/Other/DT_SkillGeneralData':
        return False
    edits = [edit for table in planned.get('tables', [])
             if table['asset'] == 'FFRS/Content/Datatable/' + rel
             for edit in table.get('set', []) if edit['row'] == row]
    if len(edits) != 1:
        return False
    settings = edits[0]['set']
    allowed = {'equipperActionVisionSkills', 'additionalCostData', 'costCheckData'}
    if not settings or not settings.keys() <= allowed:
        return False
    for field, values in settings.items():
        native = original.get(field)
        if not isinstance(native, list) or not isinstance(values, list):
            return False
        if not equivalent(values[:len(native)], native):
            return False
    return equivalent(built, {**original, **settings})


def main():
    expected = expected_rows()
    recipe = Path(BASE).parents[3] / 'patch.json'
    planned = json.loads(recipe.read_text(encoding='utf-8')) if recipe.is_file() else {}
    os.makedirs(TMP, exist_ok=True)
    env = dict(os.environ, MSYS_NO_PATHCONV="1")
    bad = 0
    for ua in sorted(glob.glob(os.path.join(BASE, "**", "*.uasset"), recursive=True)):
        rel = os.path.relpath(ua, BASE).replace("\\", "/")[:-7]
        orig_p = os.path.join(ROOT, "extracted", "rows", rel + ".json")
        if not os.path.exists(orig_p):
            print(f"[new package] {rel}"); continue
        orig = json.load(open(orig_p, encoding="utf-8"))
        if "rows" not in orig:
            print(f"[not a table] {rel}"); continue
        out = os.path.join(TMP, rel.replace("/", "_") + ".json")
        r = subprocess.run(ffrenv.FFRDT + ["rows", ua, out, "--usmap", os.path.join(ROOT, "extracted", "Mappings.usmap")],
                           capture_output=True, text=True, env=env)
        if r.returncode:
            print(f"ROWS FAILED {rel}: {r.stderr[-300:]}"); bad += 1; continue
        built = json.load(open(out, encoding="utf-8"))["rows"]; orig = orig["rows"]
        changed = [k for k in orig if k in built and not equivalent(built[k], orig[k])]
        missing = [k for k in orig if k not in built]
        added = [k for k in built if k not in orig]
        unexpected = [k for k in changed if k not in expected.get(rel, set())
                      and not expected_general_change(rel, k, orig[k], built[k], planned)] + missing
        flag = "  !! UNEXPECTED: " + ", ".join(unexpected) if unexpected else ""
        print(f"{rel}: {len(orig)}->{len(built)} rows, +{len(added)}, changed {len(changed)}{flag}")
        if unexpected: bad += 1
    try:
        verify_command_icons(Path(ROOT), Path(BASE).parents[2], Path(TMP))
    except (RuntimeError, ValueError, OSError, KeyError) as ex:
        print(f"COMMAND ICONS FAILED: {ex}"); bad += 1
    print("OK: no pre-existing row changed unexpectedly" if not bad else f"FAILED: {bad} table(s) with unexpected changes")
    sys.exit(1 if bad else 0)

def verify_command_icons(root, assets, temp):
    """Verify tag registration as well as both icon lookups and their textures."""
    recipe = assets.parent/'patch.json'
    if not recipe.is_file():
        raise ValueError('Missing build recipe for command-icon verification')
    planned = json.loads(recipe.read_text(encoding='utf-8'))
    reg = next((t for t in planned.get('tables', []) if t['asset'] == vision_icons.REGISTRY_ASSET), None)
    if reg is None:
        if not any(t.get('add') for t in planned.get('tables', []) if t['asset'].endswith('/DT_CommandSkillData')):
            return
        raise ValueError('This build predates the command-icon fix. Rebuild the mod before installing it.')
    def dump(asset, label):
        output = temp/(label+'.json'); output.parent.mkdir(parents=True, exist_ok=True)
        r = subprocess.run(ffrenv.FFRDT + ['rows', str(asset)+'.uasset', str(output), '--usmap', str(root/'extracted/Mappings.usmap')],
                           capture_output=True, text=True, encoding='utf-8', errors='replace')
        if r.returncode: raise RuntimeError((r.stderr or r.stdout)[-500:])
        return json.loads(output.read_text(encoding='utf-8'))['rows']
    original = dump(root/'extracted/legacy'/vision_icons.REGISTRY_ASSET, 'command-tags-native')
    registry = dump(assets/vision_icons.REGISTRY_ASSET, 'command-tags-built')
    if any(not equivalent(row, registry.get(name)) for name, row in original.items()):
        raise ValueError('The command-icon registry changed a native tag')
    tags = [r['Tag'] for r in registry.values()]
    icons = {rel:dump(assets/'FFRS/Content/Datatable'/rel, rel.rsplit('/', 1)[1]) for rel in vision_icons.ICON_TABLES}
    commands = [a for a in reg['add'] if a['set']['Tag'].startswith('UI.Skill.Command.Icon.FFRStudio.')]
    for addition in commands:
        tag = addition['set']['Tag']; vid = int(tag.rsplit('.', 1)[1])
        if tags.count(tag) != 1: raise ValueError(f'{tag}: missing or duplicate registered tag')
        if not (assets/f'FFRS/Content/UI/Textures/Icon/menu/ICON_Ability_summon{vid}.uasset').is_file():
            raise ValueError(f'{tag}: missing command icon texture')
        for rel, data in icons.items():
            matching = [r for r in data.values() if r.get('Tag', {}).get('TagName') == tag]
            if len(matching) != 1: raise ValueError(f'{rel}: missing or duplicate {tag}')
            if matching[0]['Brush']['ResourceObject'] != f'ICON_Ability_summon{vid}':
                raise ValueError(f'{rel}: wrong texture for {tag}')
    print(f"Command icons: {len(commands)} unique registered tags and textures verified")
    ffbe = [a for a in reg['add'] if a['set']['Tag'].startswith(skill_icons.PREFIX)]
    if ffbe:
        actions = {rel:dump(assets/'FFRS/Content/Datatable'/rel, 'ffbe-'+rel.rsplit('/', 1)[1]) for rel in skill_icons.TABLES}
        for addition in ffbe:
            tag = addition['set']['Tag']; name = tag[len(skill_icons.PREFIX):]
            if tags.count(tag) != 1: raise ValueError(f'{tag}: missing or duplicate FFBE registration')
            if not (assets/f'FFRS/Content/UI/Textures/Icon/FFBE/FFBE_{name}.uasset').is_file():
                raise ValueError(f'{tag}: missing FFBE icon texture')
            for rel, data in actions.items():
                matching = [r for r in data.values() if r.get('Tag', {}).get('TagName') == tag]
                if len(matching) != 1 or matching[0]['Brush']['ResourceObject'] != f'FFBE_{name}':
                    raise ValueError(f'{rel}: invalid FFBE icon lookup for {tag}')
        for rel in ('Skill/DT_SkillData', 'Skill/DT_PassiveSkillData'):
            source = assets/'FFRS/Content/Datatable'/rel
            # An active-only build does not need to replace the native passive
            # table. Inspect the table that the game will actually mount.
            if not source.with_suffix('.uasset').is_file():
                source = root/'extracted/legacy/FFRS/Content/Datatable'/rel
            rows = dump(source, 'ffbe-'+rel.rsplit('/', 1)[1])
            for row in rows.values():
                tag = row.get('SkillIcon', {}).get('TagName', '')
                if tag.startswith(skill_icons.PREFIX) and tags.count(tag) != 1:
                    raise ValueError(f'{rel}: unregistered FFBE icon {tag}')
        print(f'FFBE icons: {len(ffbe)} registered textures and ability/bonus references verified')


if __name__ == "__main__":
    main()
