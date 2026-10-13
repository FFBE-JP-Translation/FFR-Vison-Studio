r"""catalog.py - ability effect files and sound cues from matching regional masters.

Omitting source retains the historical live-JP reader. Explicit source never
falls back across regions. GL_2024 and JP_2024 read their raw datamine tables;
JP_CLIENT reads the cached live-client tables used by the source importer.

F_ABILITY_MST / F_MAGIC_MST / F_LIMITBURST_MST . effect_frames = "frame:groupId:a:b:c&..."        (a/b/c: layer / kind flags)
F_EFFECT_GROUP_MST . effect_frames        = "frame:effectId:reverseEffectId:reserved:xMode:yMode:x:y[:reverseX:reverseY],..."
                                         (one spawn per comma-separated item; source field x right / y down)
F_EFFECT_GROUP_MST . 1fVZ3rKd             = "frame:seId:?,..."                    (sound cue ids)
skill-level flags a:b:c  a = draw layer (1 front of the unit sprites, 2 behind); b = anchor: 1 each target unit, 2 the target
group's field rectangle (one instance, AoE), 3 the caster, 4 the screen (plates / strobes). Anchors 5/6/8/9 are projectiles;
their third flag is travel duration in source frames. See source_placement.py for the recovered native rectangle contract.
The historical effect key "loop" is retained for prepared-file compatibility; it contains the reverse-side effect ID, not a loop count.
F_EFFECT_MST                              = effectId -> label, file (.bmb), scale %

python tools/ffbe_effects/catalog.py lb 401000106          python tools/ffbe_effects/catalog.py ability 1502040
"""
import hashlib, json, os, re, sys
from pathlib import Path
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "tools", "devui"))
import ffbe_live
EFFECTS_DIR = os.path.join(ROOT, "build", "ffbe_cpk", "effects_dec")
RAW_ROOT = Path('T:/Projects/ffbe/ffbe-wiki-tools/datamine/dat_raw')
RAW_SOURCES = {'GL_2024': RAW_ROOT/'gl', 'JP_2024': RAW_ROOT/'jp'}

_cache = {}
_indexes = {}
_table_identities = {}


def normalize_source(source=None, region=None):
    aliases = {'GL': 'GL_2024', 'GLW': 'GL_2024', 'JP': 'JP_2024',
               'JPW': 'JP_2024', 'LIVE': 'JP_CLIENT'}
    def canonical(value):
        value = aliases.get(value, value)
        if value not in ('GL_2024', 'JP_2024', 'JP_CLIENT'):
            raise ValueError(f'Unsupported presentation source {value!r}; no regional fallback selected')
        return value
    if source is not None and region is not None and canonical(source) != canonical(region):
        raise ValueError('Conflicting presentation source and region')
    return canonical(source if source is not None else region) if source is not None or region is not None else 'JP_CLIENT'


def clear_cache():
    _cache.clear()
    _indexes.clear()
    _table_identities.clear()


def table(name, source=None):
    selected = normalize_source(source)
    key = name if selected == 'JP_CLIENT' else (selected, name)
    if key not in _cache:
        if selected == 'JP_CLIENT':
            doc = ffbe_live.load_table(name)
            rows = doc['rows']
            path = Path(ffbe_live.OUT)/(name+'.json')
            metadata = {'source': selected, 'table': name, 'clientFile': doc.get('file')}
        else:
            path = Path(RAW_SOURCES[selected])/(name+'.txt')
            names = json.loads(Path(ffbe_live.FIELDS).read_bytes())
            with path.open(encoding='utf-8') as handle:
                rows = [{names.get(k, k): v for k, v in json.loads(line).items()}
                        for line in handle if line.strip()]
            metadata = {'source': selected, 'table': name}
        if path.is_file():
            with path.open('rb') as handle:
                metadata.update(path=str(path.resolve()), sha256=hashlib.file_digest(handle, 'sha256').hexdigest())
        _cache[key] = rows
        _table_identities[selected, name] = metadata
    return _cache[key]


def _row_index(name, field, source=None):
    # Retain the one-argument table() call for existing consumers/test fixtures.
    rows = table(name) if source is None else table(name, source)
    key = normalize_source(source), name, field
    cached = _indexes.get(key)
    if cached is None or cached[0] is not rows:
        values = {}
        for row in rows:
            ident = str(row.get(field, ''))
            if ident in values:
                raise ValueError(f'{key[0]}/{name}: duplicate {field} {ident}')
            values[ident] = row
        cached = _indexes[key] = (rows, values)
    return cached[1]

def effect_rows(source=None):
    return _row_index('F_EFFECT_MST', 'h5t4yBm2', source)
def group_rows(source=None):
    return _row_index('F_EFFECT_GROUP_MST', 'qIy86WvJ', source)

def parse_frames(text):
    """"frame:...&frame:..." (skill rows) or "frame:...,frame:..." (group rows: Firaga's Lvup_Figa_B spawns bm_2001_fire1 seven
    times, 20 frames apart, comma-separated) -> [[field, ...], ...]"""
    out = []
    for item in re.split(r"[&,]", text or ""):
        if not item: continue
        parts = item.split(":")
        out.append(parts)
    return out

def group_detail(gid, source=None, *, region=None):
    explicit = source is not None or region is not None
    selected = normalize_source(source, region) if explicit else None
    g = group_rows(selected).get(str(gid))
    if not g: return None
    eff = effect_rows(selected); items = []
    for parts in parse_frames(g.get("effect_frames")):
        eid = parts[1] if len(parts) > 1 else None; e = eff.get(eid) or {}
        file_parts = (e.get("2HjxCGo6") or "").split(':')
        fname = file_parts[0]
        rotation = [float(v) for v in file_parts[1:4]] if len(file_parts) == 4 else [0., 0., 0.]
        item = {"frame": int(parts[0]) if parts[0].lstrip("-").isdigit() else 0, "effectId": eid, "label": e.get("o2ye8th6"), "file": fname,
                      "exists": bool(fname) and os.path.exists(os.path.join(EFFECTS_DIR, fname)), "scale": int(e.get("avX1k34K") or 100) / 100.0,
                      "rotation": rotation, "loop": parts[2] if len(parts) > 2 else None, "flags": parts[3:6] if len(parts) > 5 else parts[3:],
                      "x": int(parts[6]) if len(parts) > 6 and parts[6].lstrip("-").isdigit() else 0, "y": int(parts[7]) if len(parts) > 7 and parts[7].lstrip("-").isdigit() else 0}
        if explicit:
            typ = str(e.get('I1B7wNWc', 'unknown'))
            item.update(effectType=typ, sourceEffectPayload=e.get('2HjxCGo6'), source=selected)
            reason = None
            if not e:
                reason = f'{selected}: missing effect definition {eid}'
            elif typ == '1':
                reason = f'{selected} effect {eid}: source CGG/CGS effect requires its animation adapter'
                item['sourceDependencies'] = file_parts
            elif typ != '5':
                reason = f'{selected} effect {eid}: native effect type {typ} is outside the BMB visual adapter'
            elif not fname.lower().endswith('.bmb'):
                reason = f'{selected} effect {eid}: particle payload is not a BMB file'
            if reason:
                item['exists'] = False
                item['sourceIssue'] = reason
        items.append(item)
    sounds = [{"frame": int(p[0]) if p and p[0].lstrip("-").isdigit() else 0, "seId": p[1] if len(p) > 1 else None, "extra": p[2:]} for p in parse_frames(g.get("1fVZ3rKd"))]
    return {"groupId": str(gid), "name": g.get("h9UFW3qt"), "effects": items, "sounds": sounds,
            "sourceEffectFrames": g.get("effect_frames") or "", **({'source': selected} if explicit else {})}

def skill_effects(kind, sid, source=None, *, region=None):
    """kind: lb | ability | magic -> [{frame, group}] with the group's effects + sounds, plus attack_frames / motion info"""
    tbl, key = {"lb": ("F_LIMITBURST_MST", "lb_id"), "ability": ("F_ABILITY_MST", "ability_id"), "magic": ("F_MAGIC_MST", "magic_id")}[kind]
    explicit = source is not None or region is not None
    selected = normalize_source(source, region) if explicit else None
    row = _row_index(tbl, key, selected).get(str(sid))
    if not row: return None
    groups = []
    # @ separates mechanical components; it is not part of a layer flag.
    # Keep that identity so presentation can omit a removed component.
    for component, frames in enumerate((row.get("effect_frames") or "").split("@")):
        for parts in parse_frames(frames):
            gid = parts[1] if len(parts) > 1 else None
            gd = group_detail(gid, selected) if gid else None
            groups.append({"frame": int(parts[0]), "flags": parts[2:],
                           "component": component, "groupId": gid, "group": gd})
    return {"kind": kind, "id": str(sid), "name": row.get("name"), "motion": row.get("MotioinType"), "move_type": row.get("move_type"), "wait": row.get("wait"),
            "attack_frames": row.get("attack_frames"), "effect_type": row.get("effect_type"), "target": row.get("target"), "target_range": row.get("target_range"),
            "file_info": row.get("file_info"), "groups": groups,
            **({'source': selected, 'sourceTables': {
                name: _table_identities.get((selected, name), {'source': selected, 'table': name})
                for name in (tbl, 'F_EFFECT_GROUP_MST', 'F_EFFECT_MST')}} if explicit else {})}

if __name__ == "__main__":
    kind, sid = sys.argv[1], sys.argv[2]
    print(json.dumps(skill_effects(kind, sid), ensure_ascii=False, indent=1))
