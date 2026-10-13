"""Build/install an additive manual-test pack using existing converter bindings.

Run with prepare, build, verify, install or remove. No game launch or native hook.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/devui')]
import ffrenv
import make_vision_mod as generator
import autoport
from verify_mod import equivalent, verify_command_icons

WORK=ROOT/'build/ability-test-visions'
NAME='AbilityCategories_4'
STEM='zzz_'+NAME+'_P'
LEGACY=WORK/'extracted/legacy'
ASSETS=WORK/'build/assets'
SUFFIXES=('.pak','.utoc','.ucas')

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args,**kwargs):
    result=subprocess.run([str(a) for a in args],capture_output=True,text=True,encoding='utf8',errors='replace',**kwargs)
    if result.returncode:raise RuntimeError(f'{args[0]} failed: '+(result.stdout+result.stderr)[-4000:])
    return result
def dt_rows(asset,out):
    out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    run([*ffrenv.FFRDT,'rows',asset,out,'--usmap',ROOT/'extracted/Mappings.usmap'])
    return read(out)['rows']
def mods_dir():return Path(ffrenv.game_paks())/'~mods'
def check_inputs():
    entries=read(WORK/'inputs.json')['installedMods']
    actual={str(p) for p in mods_dir().iterdir() if p.is_file() and p.suffix in SUFFIXES and p.stem!=STEM}
    if actual!={v['path'] for v in entries}:raise ValueError('Installed mod inventory changed; prepare a fresh input snapshot.')
    for entry in entries:
        if sha(entry['path'])!=entry['sha256']:raise ValueError('Installed mod changed since preparation: '+entry['path'])

def prepare():
    if (WORK/'inputs.json').exists():
        check_inputs();print('Existing input snapshot matches installed mods.');return
    if LEGACY.exists():raise ValueError('Partial preparation exists; inspect it before retrying.')
    WORK.mkdir(parents=True,exist_ok=True)
    container=WORK/'inputs';container.mkdir(exist_ok=True)
    paks=Path(ffrenv.game_paks());installed=[]
    for p in paks.iterdir():
        if p.is_file() and p.suffix in SUFFIXES:
            (container/p.name).symlink_to(p.resolve())
    for p in sorted(mods_dir().iterdir()):
        if p.is_file() and p.suffix in SUFFIXES and p.stem!=STEM:
            shutil.copy2(p,container/p.name)
            installed.append({'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size})
    print('Copying extracted donor assets into the private build workspace.',flush=True)
    shutil.copytree(ROOT/'extracted/legacy',LEGACY)
    for pattern in ('Datatable','DebugMenuWidget/Content/Data/GameplayTag/DM_CDT_GamplayTag','DA_UIUnitSsLayout'):
        print('Reading installed overlay: '+pattern,flush=True)
        run([ffrenv.RETOC,'to-legacy','--no-shaders','--filter',pattern,container,LEGACY])
    (WORK/'extracted').mkdir(exist_ok=True)
    shutil.copy2(ROOT/'extracted/Mappings.usmap',WORK/'extracted/Mappings.usmap')
    write(WORK/'inputs.json',{'gameRoot':ffrenv.game_root(),'installedMods':installed,
        'preparedUtc':datetime.now(timezone.utc).isoformat(),'nativeHooks':False})
    print('Installed tables and original mod hashes preserved.',flush=True)

def configure():
    generator.LEGACY=str(LEGACY)
    generator.ROWS=str(WORK/'extracted/rows')
    generator.BUILD=str(WORK/'build')
    generator.OUT=str(ASSETS)
    generator.LEVEL_ID_BASE=91000
    ffrenv.MOD_NAME=NAME
    assert ASSETS.resolve().is_relative_to(WORK.resolve())

def build():
    check_inputs();configure()
    profiles=read(WORK/'selected-profiles.json')
    active=[p for p in profiles if p['conversion']['source']['kind']!='passive']
    passive=[p for p in profiles if p['conversion']['source']['kind']=='passive']
    berserk=[p for p in passive if 'berserk' in p['testFamilies']]
    passive=[p for p in passive if p not in berserk]
    represented=set()
    for p in profiles:
        remaining=set(p['testFamilies'])-represented
        p['testPrimaryFamily']=sorted(remaining or p['testFamilies'])[0]
        represented.update(p['testFamilies'])
    units=[];checklist=[]
    occupied_skills={r['ID'] for r in generator.rows('Skill/DT_SkillData').values()}
    occupied_passives={r['ID'] for r in generator.rows('Skill/DT_PassiveSkillData').values()}
    occupied_units={r['ID'] for r in generator.rows('Unit/DT_UnitParameter').values()}
    occupied_commands={r['ID'] for r in generator.rows('Skill/DT_CommandSkillData').values()}
    occupied_levels={r['ID'] for r in generator.rows('Unit/LevelParameter/DT_UnitLevelParameterList').values()}
    while any(generator.LEVEL_ID_BASE+i in occupied_levels for i in range(10)):
        generator.LEVEL_ID_BASE+=10
    # Nine converted commands plus the requested local Raegen Blast shortcut.
    regular_count=max(1,(len(active)+8)//9,(len(passive)+15)//16)
    count=regular_count+bool(berserk)
    templates={u['key']:u for u in generator.UNITS}
    roster=['esther','tsukiko','sylvie','orlandeau','katy','ariana','elena','sora']
    if count>len(roster):raise ValueError('Category set exceeds this bounded test roster.')
    vid=13800
    for i in range(count):
        while vid in occupied_units or any(autoport.unique_skill_base(vid)+j in occupied_skills for j in range(100)) or any(autoport.vision_passive_base(vid)+j in occupied_passives for j in range(100)):
            vid+=1
        if vid>=13999:raise ValueError('No free vision ID bank remains.')
        cmd=900+i
        while cmd in occupied_commands:cmd+=10
        occupied_commands.add(cmd)
        template=templates[roster[i]]
        u=deepcopy(template)
        u.update(key=f'categorytest{i+1}',jp=f'AbilityTest_{vid}',en=f'Test {i+1}: {template["en"]}',
            id=vid,sort=vid,price=1,desc='Manual converter category tests. D=direct, A=adapted, R=replacement. See the test checklist.',
            command={'id':cmd,'en':f'Test {i+1} Abilities','desc':'Converted mechanic samples; classification is shown in each name.'},
            master={'id':vid*100,'en':f'Test {i+1} Mastery','desc':'Native donor mastery; not a converter sample.'},
            skills={},convertedPassives={},awakening=[[],[],[],[]],synchro=[[] for _ in range(10)],ffbeMap={'skills':{},'passives':{}})
        for key in ('lb_custom','conversionReview'):u.pop(key,None)
        # Preserve each donor's stock resonance for this ordinary-command pack.
        active_chunk=active[i*9:(i+1)*9]
        passive_chunk=passive[i::regular_count] if i<regular_count else berserk
        if i==regular_count:
            u['en']='Test 6: Berserk Only'
            u['desc']='Isolated auto-berserk sample. Equip only when testing forced attacks; it can prevent manual commands.'
        for p in active_chunk+passive_chunk:
            r=p['conversion'];is_passive=r['source']['kind']=='passive'
            label={'direct':'D','adaptation':'A','replacement':'R'}[p['testClassification']]
            title=f'[{label}] '+p['testPrimaryFamily'].replace('_',' ').title()
            ab={'id':int(r['source']['id']),'kind':r['source']['kind'].upper(),'name':title,'level':1}
            held=autoport.import_entry(u,ab,r['source']['source'],resolved=p)
            if held:raise ValueError(f'Cannot place {r["source"]["key"]}: {held["issues"]}')
            target=u['convertedPassives'] if is_passive else u['skills']
            sid=next(int(k) for k,v in target.items() if v['conversionSource']['root']==r['source']['key'])
            # The full structured source remains embedded; only presentation is labeled.
            target[str(sid)]['descAuto']=False
            target[str(sid)]['desc']=f'{p["testClassification"].upper()}: '+p['description']
            checklist.append({'vision':u['en'],'visionId':vid,'name':title,'nativeId':sid,
                'source':r['source']['key'],'sourceName':r['name'],'kind':r['source']['kind'],'classification':p['testClassification'],
                'families':p['testFamilies'],'convertedDescription':p['description'],
                'changes':p['warnings'],'targets':[c.get('target') for c in r['components']],
                'status':'awaiting manual test'})
        blast=autoport.unique_skill_base(vid)+90
        u['skills'][str(blast)]={'from':445020,'jp':f'AbilityTest_{vid}_Blast','en':'Raegen Blast [test helper]',
            'desc':'Test shortcut: staggers enemies. This is not a converted FFBE sample.',
            'set':{'magnification':0,'breakDamageValue':9999,'accuracy':500,'Cost':0,
                'belongCommandList':[cmd],'commandIdBelongDebuggingAllSkills':[cmd,-1],
                'effectBundleList[0].effectId':-1,'effectBundleList[1].effectId':-1,'totalDamageDisplayRule':'Hidden'}}
        if autoport.add_grant(u,0,['ActiveSkill',blast]) is None:raise ValueError('No room for the test shortcut.')
        # Stage all grants across the native four awakening tiers. The local
        # save injection unlocks all four tiers for these test IDs only.
        grants=[g for tier in u['awakening'] for g in tier]
        if len(grants)>32:raise ValueError('Vision grant capacity exceeded.')
        u['awakening']=[grants[j:j+8] for j in range(0,32,8)]
        u['testAllGrants']=grants
        units.append(u);vid+=1
    write(WORK/'units.json',units);write(WORK/'checklist.json',checklist)
    for u in units:u['skills']={int(k):v for k,v in u['skills'].items()}
    generator.UNITS=units
    # Build only. Installation is a separate, hash-checked operation below.
    sys.argv=[sys.argv[0],'--no-install']
    generator.main()
    print(f'Built {len(units)} visions and {len(checklist)} converted samples.',flush=True)

def normalized(value):
    if isinstance(value,dict):return {normalized(k):normalized(v) for k,v in value.items()}
    if isinstance(value,list):return [normalized(v) for v in value]
    if isinstance(value,str) and '::' in value:return value.rsplit('::',1)[1]
    return value

def field_value(row,path):
    for key,index in re.findall(r'([^\.\[\]]+)(?:\[(\d+)\])?',path):
        row=row[key]
        if index:row=row[int(index)]
    return row

def authored_matches(expected,value):
    from ability_converter.verify import close
    expected=normalized(expected);value=normalized(value)
    # ffr-dt merges named map/struct fields into the cloned native template.
    if isinstance(expected,dict) and isinstance(value,dict):
        return all(k in value and authored_matches(v,value[k]) for k,v in expected.items())
    return close(expected,value)

def verify():
    from ability_converter.verify import close
    from make_party_mod import export_json
    check_inputs();configure()
    recipe=read(WORK/'build/patch.json');reports={};tables={}
    for table in recipe['tables']:
        asset=table['asset'];label=asset.replace('/','_')
        print('Checking '+asset,flush=True)
        original=dt_rows(LEGACY/(asset+'.uasset'),WORK/'verify'/('original_'+label+'.json'))
        actual=dt_rows(ASSETS/(asset+'.uasset'),WORK/'verify'/(label+'.json'))
        tables[asset]=actual
        modified={r['row']:r['set'] for r in table.get('set',[])}
        for name,old in original.items():
            if name not in actual:raise ValueError(f'Existing row lost: {asset}/{name}')
            excluded={re.split(r'[.\[]',k)[0] for k in modified.get(name,{})}
            if not equivalent({k:v for k,v in old.items() if k not in excluded},
                              {k:v for k,v in actual[name].items() if k not in excluded}):
                raise ValueError(f'Existing row changed: {asset}/{name}')
        for change in table.get('add',[])+table.get('set',[]):
            observed=actual[change['row']]
            for field,expected in change['set'].items():
                value=field_value(observed,field)
                leaf=field.rsplit('.',1)[-1]
                if isinstance(expected,dict) and isinstance(value,dict) and set(value)=={leaf} and leaf not in expected:
                    value=value[leaf]
                if isinstance(value,dict) and 'text' in value and isinstance(expected,str):value=value['text']
                if isinstance(expected,str) and expected.startswith('/Game/') and value==expected.rsplit('/',1)[-1]:continue
                if not authored_matches(expected,value):
                    raise ValueError(f'Authored field differs: {asset}/{change["row"]}/{field}: {expected!r} != {value!r}')
        if asset.endswith('/DT_SkillGeneralData'):
            for name,settings in modified.items():
                for field,values in settings.items():
                    old=original[name][field]
                    if isinstance(old,list) and not equivalent(values[:len(old)],old):
                        raise ValueError('An existing general-list entry was replaced')
        reports[asset]={'originalRows':len(original),'addedRows':len(actual)-len(original),
            'existingRowsPreserved':True,'authoredFieldsChecked':True}
    verify_command_icons(WORK,ASSETS,WORK/'verify/icons')
    dt='FFRS/Content/Datatable/'
    for rel in ('Skill/DT_SkillData','Skill/DT_PassiveSkillData','Skill/DT_SkillEffectData',
                'Skill/DT_CommandSkillData','Skill/DT_MasterSkillData','Unit/DT_UnitParameter','Item/Vision/DT_VisionItemData'):
        data=tables.get(dt+rel,{})
        ids=[row['ID'] for row in data.values()]
        if len(ids)!=len(set(ids)):raise ValueError('Duplicate IDs in '+rel)
    units=read(WORK/'units.json');checklist=read(WORK/'checklist.json')
    skills={r['ID']:r for r in tables[dt+'Skill/DT_SkillData'].values()}
    passives={r['ID']:r for r in tables[dt+'Skill/DT_PassiveSkillData'].values()}
    for u in units:
        for kind,sid,*_ in u['testAllGrants']:
            if sid not in (skills if kind=='ActiveSkill' else passives):raise ValueError('Missing granted skill '+str(sid))
        for sid in map(int,u['skills']):
            if u['command']['id'] not in skills[sid]['belongCommandList']:raise ValueError('Command membership missing')
            candidates={skills[sid]['playSequencerId'],sid,sid+1,sid+2}
            for rel in ('Asset/Skill/DT_SkillAsset','Asset/Skill/CDT_SkillAsset_Demo'):
                if not any(r['ID'] in candidates and r['LevelSequence'] for r in tables[dt+rel].values()):
                    raise ValueError('Skill has no sequence: '+str(sid))
    package=WORK/'package';package.mkdir(exist_ok=True)
    for suffix in SUFFIXES:
        source=ROOT/'build/out'/(STEM+suffix)
        shutil.copy2(source,package/source.name)
        shutil.copy2(source,WORK/'inputs'/source.name)
    # Reuse the existing cooked export tool against base + all installed mods +
    # this new overlay, proving package priority and native hard references.
    cooked={}
    for key,rel in (('visions','Item/Vision/DT_VisionItemData'),('units','Unit/DT_UnitParameter'),
                    ('skills','Skill/DT_SkillData'),('levels','Unit/LevelParameter/DT_UnitLevelParameterList')):
        cooked[key]=export_json(WORK/'inputs','/Game/Datatable/'+rel,WORK/'verify'/('cooked-'+key+'.json'))['Rows']
    for u in units:
        if not any(r['ID']==u['id'] for r in cooked['visions'].values()):raise ValueError('Cooked vision missing')
        for sid in map(int,u['skills']):
            if not any(r['ID']==sid for r in cooked['skills'].values()):raise ValueError('Cooked command missing')
    before_levels=export_json(ffrenv.game_paks(),'/Game/Datatable/Unit/LevelParameter/DT_UnitLevelParameterList',
        WORK/'verify/installed-levels-before.json')['Rows']
    missing_before={k for k,r in before_levels.items() if not r.get('DataTable')}
    missing_after={k for k,r in cooked['levels'].items() if not r.get('DataTable')}
    if missing_after!=missing_before:raise ValueError('The test overlay introduced an unresolved growth reference')
    if any(not cooked['levels'][f'ビジョン_{u["jp"]}'].get('DataTable') for u in units):
        raise ValueError('A new vision growth reference is unresolved')
    for name in ('Raegen','Helena'):
        if not any(r['Name'].get('CultureInvariantString')==name for r in cooked['units'].values()):
            raise ValueError('Existing private party member lost: '+name)
    result={'status':'passed','visions':len(units),'convertedSamples':len(checklist),
        'classifications':dict(Counter(r['classification'] for r in checklist)),
        'families':len({f for r in checklist for f in r['families']}),'tables':reports,
        'cookedOverlayPriority':'passed','privatePartyPreserved':True,'newVisionGrowthReferencesResolved':True,
        'preexistingUnresolvedGrowthEntries':sorted(missing_before),
        'gameplay':'pending manual user test','nativeHooksAdded':False,
        'package':{p.name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p in package.iterdir()}}
    write(WORK/'verification.json',result)
    stage_save(units)
    documentation()
    print('Verified tables, cooked package priority, grants, icons and staged save.',flush=True)

def save_key():
    path=ROOT/'extracted/pak/FFRS/Config/DefaultSaveGameUtility.ini'
    return re.search(r'^SaveDataEncryptionKey=(.+)$',path.read_text(),re.M).group(1).strip().encode()

def vision_rows(save):
    from ffr_party_save import Reader,properties
    prop=save.props['visionList']
    if prop.type[0]!='ArrayProperty' or prop.type[1][0][0]!='StructProperty':raise ValueError('Unexpected vision save property')
    reader=Reader(prop.data);count=reader.int();rows=[properties(reader) for _ in range(count)]
    if reader.pos!=len(prop.data):raise ValueError('Unexpected vision save tail')
    return rows

def stage_save(units):
    from ffr_party_save import Save,encode_properties,i32
    candidates=list((Path(os.environ['LOCALAPPDATA'])/'FFRS_DEMO/Steam').glob('*/GameSaveData*.sav'))
    if not candidates:raise ValueError('No progress save found for the test-vision injection')
    path=max(candidates,key=lambda p:p.stat().st_mtime)
    raw=path.read_bytes();save=Save(raw,save_key());original=deepcopy(save)
    rows=vision_rows(save);old_count=len(rows);ids={v['ID'].integer() for v in rows}
    if not rows:raise ValueError('No native saved vision structure to clone')
    for u in units:
        if u['id'] in ids:raise ValueError('Test vision already exists in the selected save')
        row=deepcopy(rows[0]);row['ID'].set_integer(u['id']);row['awakeningPoint'].set_integer(3)
        rows.append(row)
    save.props['visionList'].data=i32(len(rows))+b''.join(encode_properties(row) for row in rows)
    output=save.encode();check=Save(output,save_key());checked=vision_rows(check)
    for key,prop in original.props.items():
        if key!='visionList' and prop.encode()!=check.props[key].encode():raise ValueError('Unrelated save property changed')
    if any(encode_properties(a)!=encode_properties(b) for a,b in zip(vision_rows(original),checked[:old_count])):
        raise ValueError('Existing saved vision changed')
    if [(r['ID'].integer(),r['awakeningPoint'].integer()) for r in checked[old_count:]]!=[(u['id'],3) for u in units]:
        raise ValueError('Test vision save values failed round-trip')
    staged=WORK/'saves/staged'/path.name;staged.parent.mkdir(parents=True,exist_ok=True);staged.write_bytes(output)
    write(WORK/'save-plan.json',{'path':str(path),'staged':str(staged),'originalSha256':hashlib.sha256(raw).hexdigest(),
        'stagedSha256':sha(staged),'addedVisionIds':[u['id'] for u in units],'awakeningPoint':3,
        'unrelatedSaveDataUnchanged':True,'existingVisionsUnchanged':True,'gameplay':'pending manual test'})

def documentation():
    selection=read(WORK/'selection.json');items=read(WORK/'checklist.json');units=read(WORK/'units.json');save=read(WORK/'save-plan.json')
    lines=['# Converter ability tests','',
        'Six private test visions contain 62 converted samples spanning 61 mechanic families. These are representative samples, not every opcode, target combination or ability. Gameplay results are awaiting your tests.',
        '',f'Load `{Path(save["path"]).name}` (the most recently modified progress save). The six Test visions are added with awakening point 3, unlocking the four authored tiers. Existing party equipment is unchanged. Equip one Test vision at a time. They are also listed at the Mitra item shop for 1 gil.',
        '', 'D = direct adapter; A = adapted to FFR scales/structures; R = replacement mechanic. In particular, a replacement for multicast, jumps or cooldown support does not implement the original FFBE system. Read the stated behavior below.',
        '', 'Each vision has Raegen Blast as a local test helper. It is not a converter sample. Resonances and masteries remain native donors and are not counted as new converted tests. Test 6 isolates auto-berserk because it can force attacks and prevent manual commands.',
        '', 'For each check, note the target, resource cost, visible effect, duration and removal. Use comparable targets for damage tests; allow turns to pass for timed effects; use damaged/KO allies for recovery/revival. Passives apply to the equipping actor. Record observations before marking a check passed.',
        '']
    for u in units:
        lines += [f'## {u["en"]} — vision {u["id"]}','']
        for item in [v for v in items if v['visionId']==u['id']]:
            lines += [f'- [ ] **{item["name"]}** ({item["kind"]}, ID {item["nativeId"]}) — '+', '.join(item['families'])+'.',
                f'  Source: `{item["source"]}` — {item["sourceName"]}.',f'  Expected converted behavior: {item["convertedDescription"]}']
            if item['changes']:lines.append('  Disclosed changes: '+' '.join(item['changes']))
        lines.append('')
    lines += ['## Categories not exposed as playable tests','',
        'The existing command/passive binding could not produce a representative for the following families. No native hooks or additional engine research were added to release them. Some have table-only or LB candidates; this pack does not pretend those are ordinary playable commands.','']
    for family,held in selection['excludedFamilies'].items():
        reasons=list(held['candidateFailures']) or list(held['catalogBlockers']) or [held['reason']]
        lines.append(f'- **{family}**: '+reasons[0])
    lines += ['', '## Install and rollback','',
        'The new three-file overlay preserves the existing Studio, private party and battle packages. Installation backs up the selected save before adding only these new vision records.',
        '', '```powershell',f'python -X utf8 -B "{Path(__file__).resolve()}" install','```','',
        'Close the game before rollback. This command removes this overlay and restores the pre-test save; it deliberately discards progress made in that save since installation:',
        '', '```powershell',f'python -X utf8 -B "{Path(__file__).resolve()}" remove --restore-save','```','',
        'Without `--restore-save`, removal refuses if the save has changed. Backups and exact hashes are recorded in `installation.json`. The converter delivery and frozen native research are separate and unchanged.']
    if missing:=read(WORK/'verification.json').get('preexistingUnresolvedGrowthEntries'):
        lines += ['', '## Existing installation finding','',
            'The installed mods already contain seven unresolved growth-table references for older test visions. Readback before and after this overlay shows the same entries: '+', '.join(missing)+'. All six new test-vision growth references resolve. This pack preserves the existing entries and does not repair those older mods.']
    (WORK/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf8')

def install():
    if ffrenv.game_running():raise ValueError('Close FFR before installing the prepared test pack.')
    check_inputs();verification=read(WORK/'verification.json');save=read(WORK/'save-plan.json')
    if verification['status']!='passed':raise ValueError('The test pack did not pass verification')
    if (WORK/'installation.json').exists():raise ValueError('This test pack has an installation record; remove it before reinstalling.')
    if sha(save['path'])!=save['originalSha256']:raise ValueError('Save changed since staging; restage the save before installation.')
    if sha(save['staged'])!=save['stagedSha256']:raise ValueError('Staged save changed')
    backup=WORK/'backup'/datetime.now().strftime('%Y%m%d_%H%M%S');backup.mkdir(parents=True)
    saved=backup/Path(save['path']).name;shutil.copy2(save['path'],saved)
    placed=[]
    for name,entry in verification['package'].items():
        source=WORK/'package'/name
        if sha(source)!=entry['sha256']:raise ValueError('Package changed after verification')
        target=mods_dir()/name
        if target.exists():raise ValueError('Refusing to overwrite an existing category-test package: '+str(target))
    try:
        for name,entry in verification['package'].items():
            target=mods_dir()/name;shutil.copy2(WORK/'package'/name,target);placed.append(target)
            if sha(target)!=entry['sha256']:raise ValueError('Installed package hash mismatch')
        shutil.copy2(save['staged'],save['path'])
        if sha(save['path'])!=save['stagedSha256']:raise ValueError('Installed save hash mismatch')
        check_inputs()
    except BaseException:
        shutil.copy2(saved,save['path'])
        for path in placed:
            if path.parent.resolve()!=mods_dir().resolve():raise ValueError('Unexpected rollback path')
            path.unlink()
        raise
    write(WORK/'installation.json',{'status':'installed','installedUtc':datetime.now(timezone.utc).isoformat(),
        'package':{str(mods_dir()/name):entry for name,entry in verification['package'].items()},
        'save':save,'saveBackup':str(saved),'saveBackupSha256':sha(saved),'oldModsUnchanged':True,
        'gameLaunched':False,'nativeHooksAdded':False})
    print('Installed six test visions. Load '+Path(save['path']).name+'.',flush=True)

def remove():
    if ffrenv.game_running():raise ValueError('Close FFR before removing the test pack.')
    state=read(WORK/'installation.json');save=state['save']
    if state['status']!='installed':raise ValueError('The test pack is not marked installed')
    if sha(save['path'])!=save['stagedSha256'] and '--restore-save' not in sys.argv:
        raise ValueError('The save has changed. Use --restore-save only to deliberately restore the pre-test save.')
    if sha(state['saveBackup'])!=state['saveBackupSha256']:raise ValueError('Save backup changed')
    for name,entry in state['package'].items():
        path=Path(name)
        if path.parent.resolve()!=mods_dir().resolve() or path.stem!=STEM or sha(path)!=entry['sha256']:
            raise ValueError('Installed test package changed; inspect before removing')
    if '--restore-save' in sys.argv:
        shutil.copy2(save['path'],WORK/'backup'/('before-rollback-'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sav'))
    shutil.copy2(state['saveBackup'],save['path'])
    for name in state['package']:Path(name).unlink()
    state.update(status='removed',removedUtc=datetime.now(timezone.utc).isoformat());write(WORK/'installation.json',state)
    print('Removed the category overlay and restored the pre-test save.')

def main():
    action=sys.argv[1] if len(sys.argv)>1 else ''
    if action=='prepare':prepare()
    elif action=='build':build()
    elif action=='verify':verify()
    elif action=='install':install()
    elif action=='remove':remove()
    else:raise SystemExit('Use prepare, build, verify, install or remove.')

if __name__=='__main__':main()
