"""Build an offline enemy-AI study pack from local FFR and FFBE data.

Reads base-game packages only. Does not install, patch, or upload anything.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import queue
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
AI_PATH = Path('FFRS/Content/BP/Battle/AI')
AI_TABLE = Path('FFRS/Content/Datatable/Asset/Battle/AI')
FFBE_KEYS = {
    '8a6gAwN9': 'ai_id', 'w7VR6ypY': 'priority', 'WhQL5ev9': 'name',
    'B2FW5Qjq': 'conditions', 'ry3J4UNG': 'AI_COND_TARGET',
    '9Fe2mBtK': 'AI_COND1', '0wEykBj5': 'AI_PARAM1',
    'J38o4DRA': 'AI_COND2', '8vTj4XRb': 'AI_PARAM2',
    'piK07TV4': 'AI_ACT_TARGET', 'VuUTL8v6': 'AI_SEARCH_COND',
    'z5hB3P01': 'action', 'ixDq7yJ8': 'weight',
}


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def annotate(value, asset):
    """Retain bytecode fields; add names beside local package-index references."""
    if isinstance(value, list):
        return [annotate(v, asset) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, v in value.items():
        result[key] = annotate(v, asset)
        if key in ('StackNode', 'ResolvedOwner', 'SuperStruct') and isinstance(v, int) and v:
            entries = asset['Exports'] if v > 0 else asset['Imports']
            index = v-1 if v > 0 else -v-1
            if 0 <= index < len(entries):
                result[key+'Name'] = entries[index]['ObjectName']
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', type=Path, default=Path('T:/SteamLibrary/steamapps/common/FINAL FANTASY RESONANCE DEMO'))
    parser.add_argument('--datamine', type=Path, default=Path('T:/Projects/ffbe/ffbe-wiki-tools/datamine'))
    parser.add_argument('--out', type=Path, default=ROOT/'build/enemy-action-study')
    args = parser.parse_args()
    work = args.out.resolve(); work.mkdir(parents=True, exist_ok=True)
    pack = work/'FFR-Enemy-Action-Study'; pack.mkdir(exist_ok=True)
    included = set(); provenance = []

    def add(source, relative):
        dest = pack/relative; dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest); included.add(dest)
        provenance.append({'path': dest.relative_to(pack).as_posix(),
                           'source': str(source), 'sha256': digest(dest)})
        return dest

    def emit(relative, data):
        path = pack/relative; write(path, data); included.add(path); return path

    def run(command):
        result = subprocess.run([str(x) for x in command], capture_output=True,
                                text=True, encoding='utf-8', errors='replace', timeout=120)
        if result.returncode:
            raise RuntimeError('Command failed: '+str(command)+'\n'+result.stdout+result.stderr)
        return result.stdout+result.stderr

    inputs = work/'inputs'; inputs.mkdir(exist_ok=True)
    for name in ('global.utoc', 'global.ucas', 'FFRS-Windows.utoc', 'FFRS-Windows.ucas'):
        source = args.game/'FFRS/Content/Paks'/name
        if not source.is_file(): raise FileNotFoundError(source)
        link = inputs/name
        if link.exists():
            if link.resolve() != source.resolve(): raise ValueError('Input link points to a different game: '+str(link))
        else: link.symlink_to(source.resolve())
    # Ignore any stale/unexpected inputs; no installed mod containers are allowed.
    if {p.name for p in inputs.iterdir()} != {'global.utoc', 'global.ucas', 'FFRS-Windows.utoc', 'FFRS-Windows.ucas'}:
        raise ValueError('Study inputs must contain only the four base-game containers')
    legacy = work/'legacy'
    for filt in ('BP/Battle/AI', 'Datatable/Asset/Battle/AI'):
        print(run([ROOT/'tools/retoc/retoc.exe', 'to-legacy', '--no-shaders', '--filter', filt, inputs, legacy]).strip(), flush=True)
    packages = sorted((legacy/AI_PATH).rglob('*.uasset'))
    if not packages: raise ValueError('No AI Blueprints extracted')
    for path in sorted(legacy.rglob('*')):
        if path.is_file(): add(path, Path('FFR/legacy')/path.relative_to(legacy))
    add(ROOT/'extracted/Mappings.usmap', 'FFR/Mappings.usmap')
    for path in sorted((ROOT/'extracted/CXXHeaderDump').glob('BP_BtlUnitAI*.hpp')):
        add(path, Path('FFR/headers')/path.name)
    for name in ('mucha.hpp', 'mucha_enums.hpp'):
        add(ROOT/'extracted/CXXHeaderDump'/name, Path('FFR/headers')/name)
    rows = ['Unit/AI/DT_BtlUnitAIParameter', 'Unit/DT_UnitParameter',
            'Unit/DT_StatusConditionDetailData', 'Encount/DT_BattleGroup',
            'Skill/DT_SkillData', 'Skill/DT_SkillEffectData', 'Skill/DT_PassiveSkillData',
            'Skill/Other/DT_SkillTargetData', 'Skill/Other/DT_SkillGeneralData',
            'Skill/Other/DT_SkillDamageCalcData', 'Skill/Other/DT_SkillRecoveryCalcData',
            'Strings/ST_Unit/ST_UnitName', 'Strings/ST_Skill/ST_SkillName']
    for rel in rows:
        add(ROOT/'extracted/rows'/(rel+'.json'), Path('FFR/tables')/(rel+'.json'))
    dt = ['dotnet', ROOT/'src/ffr-dt/bin/Release/net8.0/ffr-dt.dll']
    for asset in sorted((legacy/AI_TABLE).glob('*.uasset')):
        out = pack/'FFR/tables/Asset/Battle/AI'/(asset.stem+'.json'); out.parent.mkdir(parents=True, exist_ok=True)
        run([*dt, 'rows', asset, out, '--usmap', ROOT/'extracted/Mappings.usmap']); included.add(out)

    # UAssetAPI opens mappings exclusively. Each concurrent reader gets its own copy.
    maps = queue.Queue()
    for n in range(4):
        path = work/f'worker-{n}.usmap'; shutil.copy2(ROOT/'extracted/Mappings.usmap', path); maps.put(path)

    def export(asset):
        mapping = maps.get()
        relative = asset.relative_to(legacy/AI_PATH).with_suffix('.json')
        out = pack/'FFR/blueprints'/relative; out.parent.mkdir(parents=True, exist_ok=True)
        try:
            log = run([*dt, 'tojson', asset, out, '--usmap', mapping])
            data = read(out)
            funcs = [{'name':e['ObjectName'], 'flags':e['FunctionFlags'],
                      'SuperStruct':e['SuperStruct'], 'ScriptBytecode':e.get('ScriptBytecode'),
                      'ScriptBytecodeSize':e.get('ScriptBytecodeSize'),
                      'ScriptBytecodeRaw':e.get('ScriptBytecodeRaw')}
                     for e in data['Exports'] if 'FunctionExport' in e.get('$type','')]
            annotated = pack/'FFR/functions'/relative
            write(annotated, {'source': (Path('FFR/blueprints')/relative).as_posix(),
                             'note':'Annotated structured bytecode, not reconstructed source. Numeric references and jump byte offsets are retained.',
                             'functions': annotate(funcs, data),
                             'classDefaults':[e for e in data['Exports'] if e.get('ObjectName','').startswith('Default__')]})
            return {'asset':asset.stem, 'blueprint':out.relative_to(pack).as_posix(),
                    'functions':annotated.relative_to(pack).as_posix(), 'exportCount':len(data['Exports']),
                    'functionCount':len(funcs), 'parsedFunctions':sum(f['ScriptBytecode'] is not None for f in funcs),
                    'opaqueFunctions':[f['name'] for f in funcs if f['ScriptBytecodeRaw']],
                    'binaryRoundtrip': 'roundtrip=True' in log}, (out, annotated)
        finally: maps.put(mapping)

    blueprints = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for n, (record, paths) in enumerate(pool.map(export, packages), 1):
            blueprints.append(record); included.update(paths)
            if n % 50 == 0 or n == len(packages): print(f'Exported {n}/{len(packages)} AI Blueprints', flush=True)
    emit('FFR/blueprint-index.json', blueprints)
    asset_rows = read(pack/'FFR/tables/Asset/Battle/AI/DT_CompositeBtlUnitAIAsset.json')['rows']
    classes = {v['ID']:v['UnitAIClass'] for v in asset_rows.values()}
    bp_index = {v['asset']+'_C':v for v in blueprints}
    skill_names = {v['id']:v.get('name') for v in read(ROOT/'build/devui/ffr_catalog.json')['skills']}
    ai_rows = read(pack/'FFR/tables/Unit/AI/DT_BtlUnitAIParameter.json')['rows']
    index = []
    for row, v in ai_rows.items():
        bp = bp_index.get(classes.get(v['aiId']))
        skill_ids = {v['fightSkillId'], v['chaseSkillId'], v['silenceFightId'],
                     *v['counterSkillIdList'], *v['highRiskSkillIdList'],
                     *(s['SkillId'] for s in v['skillRandData1']), *(s['SkillId'] for s in v['skillRandData2'])}
        index.append({'unitId':v['ID'], 'row':row, 'aiId':v['aiId'], 'aiClass':classes.get(v['aiId']),
                      'blueprint':bp['blueprint'] if bp else None,
                      'skills':[{'id':sid, 'englishName':skill_names.get(sid)} for sid in sorted(skill_ids) if sid >= 0]})
    emit('FFR/unit-ai-skill-index.json', index)

    ffbe_counts = {}
    for region in ('gl', 'jp'):
        source = args.datamine/'dat_raw'/region/'F_AI_MST.txt'
        add(source, f'FFBE/{region}/F_AI_MST.txt')
        normalized = pack/f'FFBE/{region}/ai-rules.jsonl'
        count = 0; ai_ids = set(); bahamut = []
        with normalized.open('w', encoding='utf-8', newline='\n') as output:
            for n, line in enumerate(source.read_text(encoding='utf-8-sig').splitlines(), 1):
                if not line.strip(): continue
                raw = json.loads(line)
                row = {FFBE_KEYS.get(k,k):v for k,v in raw.items()}
                if len(row) != len(raw): raise ValueError('FFBE key mapping collision')
                row['_sourceLine'] = n
                output.write(json.dumps(row, ensure_ascii=False)+'\n'); count += 1; ai_ids.add(row['ai_id'])
                if 'ダークバハムート' in row.get('name','') or 'dark bahamut' in row.get('name','').lower():
                    bahamut.append(row)
        included.add(normalized)
        emit(f'FFBE/{region}/dark-bahamut-rules.json', bahamut)
        ffbe_counts[region] = {'rules': count, 'aiIds':len(ai_ids)}
        for name in ('F_MONSTER_SKILL_SET_MST.txt', 'F_MONSTER_SKILL_MST.txt'):
            add(args.datamine/'dat_raw'/region/name, f'FFBE/{region}/{name}')
        add(args.datamine/'data'/region/'monster_skills.json', f'FFBE/{region}/monster-skills-readable.json')
    emit('FFBE/field-names.json', {'mapping':FFBE_KEYS,
         'source':str(args.datamine/'src/Sol/FFBE/GameFile.php'),
         'note':'Field names only, based on the local datamine reader; conditions/actions are deliberately not interpreted. WhQL5ev9 is called name by MissionResponseReader.readAi.'})

    summary = {'blueprints':len(blueprints), 'functions':sum(b['functionCount'] for b in blueprints),
               'roundtripVerified':sum(b['binaryRoundtrip'] for b in blueprints),
               'opaqueFunctions':sum(len(b['opaqueFunctions']) for b in blueprints),
               'unitAIRows':len(index), 'ffbe':ffbe_counts}
    emit('summary.json', summary)
    add(ROOT/'docs/25-enemy-action-study.md', 'README.md')
    add(Path(__file__), 'reproduce/dump_enemy_actions.py')
    emit('source-manifest.json', provenance)
    manifest = [{'path':p.relative_to(pack).as_posix(), 'bytes':p.stat().st_size, 'sha256':digest(p)} for p in sorted(included)]
    emit('manifest.json', manifest)
    archive = work/'FFR-Enemy-Action-Study.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(included): z.write(path, (Path(pack.name)/path.relative_to(pack)).as_posix())
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None: raise ValueError('ZIP integrity failed')
        for row in manifest:
            blob = z.read(pack.name+'/'+row['path'])
            if hashlib.sha256(blob).hexdigest() != row['sha256']: raise ValueError('ZIP checksum mismatch: '+row['path'])
    print(json.dumps({'folder':str(pack),'zip':str(archive),'zipBytes':archive.stat().st_size,**summary}, indent=2), flush=True)


if __name__ == '__main__': main()
