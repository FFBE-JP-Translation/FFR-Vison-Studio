"""Inventory effect mechanics for review; never converts units or writes game data.

python -B tools/audit_ability_effects.py --out docs/build16
Reads native FFR tables/enums, GL/JP datamines, older FFBE Equip sources,
cached JP client masters, and the datamine's effect definitions/formatters.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import html
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def plain(value):
    if isinstance(value, list):
        return '; '.join(plain(v) for v in value)
    text = re.sub(r'<br\s*/?>|<t>', ' / ', str(value or ''))
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]*>', '', text))).strip()


def cell(value):
    return plain(value).replace('|', '\\|').replace('\n', ' ')


def enums(path):
    text = path.read_text(encoding='utf-8')
    return {name: {n: int(v) for n, v in re.findall(r'^\s*(\w+)\s*=\s*(\d+),', body, re.M)
                   if not n.endswith('_MAX')}
            for name, body in re.findall(r'enum class (\w+)\s*\{(.*?)\};', text, re.S)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT/'build/build16/effect-audit')
    parser.add_argument('--datamine', type=Path, default=Path('T:/Projects/ffbe/ffbe-wiki-tools/datamine'))
    parser.add_argument('--archive', type=Path, default=Path('S:/ffbeEquip-master.zip'))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = {}

    def track(path):
        if str(path) not in inputs:
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            inputs[str(path)] = {'bytes': path.stat().st_size, 'sha256': digest}
        return path

    enum_path = track(ROOT/'extracted/CXXHeaderDump/mucha_enums.hpp')
    enum = enums(enum_path)
    native = {}
    for key, rel in [('skills','Skill/DT_SkillData.json'),('effects','Skill/DT_SkillEffectData.json'),
                     ('passives','Skill/DT_PassiveSkillData.json'),('statuses','Unit/DT_StatusConditionDetailData.json')]:
        native[key] = read(track(ROOT/'extracted/rows'/rel))['rows']
    catalog = read(track(ROOT/'build/devui/ffr_catalog.json'))
    uses = defaultdict(list)
    names = {kind: {v['id']:v for v in catalog[kind]} for kind in ('skills','passives')}
    for kind in ('skills','passives'):
        for row, v in native[kind].items():
            for effect in v.get('effectBundleList',[]):
                if effect.get('effectId',-1) >= 0:
                    uses[effect['effectId']].append({'kind':kind,'id':v['ID'],'row':row,
                        'name':names[kind].get(v['ID'],{}).get('name'),
                        'target':effect.get('TargetType'),'relation':effect.get('targetRelation'),
                        'activeTiming':effect.get('activeSkillAddTiming'),'passiveTiming':effect.get('passiveSkillAddTiming')})
    native_fx = []
    for name, code in enum['eSkillEffectType'].items():
        rows = [{'row':k,**v,'usedBy':uses[v['ID']]} for k,v in native['effects'].items() if v['EffectType']==name]
        direct = [{'row':k,'id':v['ID']} for k,v in native['skills'].items() if v['skillEffectType']==name]
        native_fx.append({'code':code,'type':name,'effectRows':rows,'directSkillRows':direct,
                          'evidence':'rows_present' if rows or direct else 'enum_only'})
    axes = {key:dict(Counter(str(v.get(key)) for v in native['skills'].values())) for key in
            ('DamageType','damageCalcType','parameterType','parameterVariationType','TargetType','defaultTargetRelation','targetRage','skillAttrType')}
    ffr = {'counts':{k:len(v) for k,v in native.items()}, 'effectTypes':native_fx,'skillAxes':axes,
           'statuses':[{'row':k,**v} for k,v in native['statuses'].items()],
           'enums':{k:enum[k] for k in ('eSkillEffectType','eSkillDamageType','eSkillDamageCalcType','eRace',
                'eUnitStatusCondition','eUnitParameterType','eSkillEffectActivationCondition','eActiveSkillEffectTiming','eSkillTiming')}}

    definitions = defaultdict(dict)
    for ns, stem, formatter in [('active','PROCESS_TYPE','ActiveSkillEffectFormatter'),
                                ('passive','PROCESS_PASSIVE_TYPE','PassiveSkillEffectFormatter'),
                                ('field','AREA_PROCESS_PASSIVE_TYPE','AreaEffectFormatter')]:
        path = args.datamine/'src/Solaris/Formatter'/(formatter+'.php')
        text = track(path).read_text(encoding='utf-8')
        for m in re.finditer(r'(?:protected|public|private)\s+function effect(\d+)\(',text):
            prior=text[:m.start()].rstrip(); start=prior.rfind('/**')
            comment=prior[start:] if prior.endswith('*/') else ''
            parts=[re.sub(r'^\s*\*\s?','',line).strip() for line in comment.splitlines()[1:-1]]
            title=next((line for line in parts if line and not line.startswith('@')),'')
            definitions[ns][int(m[1])]={'formatterLabel':title,'formatterFile':str(path),
                                      'formatterLine':text[:m.start()].count('\n')+1}
        for reg in ('gl','jp'):
            path=args.datamine/'dat_raw'/reg/('F_'+stem+'_MST.txt')
            if not path.exists(): continue
            for n,line in enumerate(track(path).read_text(encoding='utf-8-sig').splitlines(),1):
                if not line.strip(): continue
                row=json.loads(line)
                code=int(next(iter(row.values())))
                entry=definitions[ns].setdefault(code,{})
                entry.setdefault('definitionRows',[]).append({'source':str(path),'line':n})
        path=args.datamine/'dat_raw/gl'/('F_TEXT_'+stem+'_EXPLAIN_LONG.txt')
        if path.exists():
            for n,line in enumerate(track(path).read_text(encoding='utf-8-sig').splitlines(),1):
                parts=line.split('^'); match=re.search(r'_(\d+)$',parts[0])
                if not match or len(parts)<2: continue
                entry=definitions[ns].setdefault(int(match[1]),{})
                entry.update(englishTemplate=plain(parts[1]),templateFile=str(path),templateLine=n)

    # New JP BOOST mechanics are described in the cached client's own templates,
    # even where the older wiki formatter has no handler.
    translations={('active',22):'Physical damage with a race-specific damage bonus',
                  ('active',23):'Magic damage with a race-specific damage bonus',
                  ('passive',45):'Unit experience gained boost',
                  ('passive',109):'BOOST: fill LB gauge at turn start while active',
                  ('passive',110):'BOOST: fully restore MP at turn start while active',
                  ('passive',111):'BOOST: grant HP barrier when activated',
                  ('passive',112):'BOOST: max-HP pursuit damage at turn end (strongest once per turn)',
                  ('passive',113):'BOOST: reduce cooldown at turn start while active',
                  ('field',14):'Category-restricted damage boost (excludes damage to self)'}
    for ns,table in [('active','F_PROCESS_TYPE_MST'),('passive','F_PROCESS_PASSIVE_TYPE_MST'),('field','F_AREA_PROCESS_PASSIVE_TYPE_MST')]:
        path=ROOT/'build/devui/live_jp'/(table+'.json')
        if not path.exists():continue
        for row in read(track(path))['rows']:
            code=int(next(iter(row.values()))); entry=definitions[ns].setdefault(code,{})
            entry.update(jpClientTemplate=plain(row.get('explain_long')),jpClientTemplateSource=str(path))
            if (ns,code) in translations:entry['translatedLabel']=translations[ns,code]

    groups={}; source_counts={}; anomalies=[]; corrections=[]
    def register(ns, code, source, kind, sid, name, params, target, text, duration=None):
        key=f'{ns}:{code}'
        g=groups.setdefault(key,{'key':key,'namespace':ns,'code':code,'occurrences':0,
                                'sourceCounts':Counter(),'kinds':Counter(),'records':set(),'examples':[]})
        g['occurrences']+=1; g['sourceCounts'][source]+=1; g['kinds'][kind]+=1
        g['records'].add((source,kind,str(sid)))
        if len(g['examples'])<3 and not any(x['name']==name and x['text']==plain(text) for x in g['examples']):
            g['examples'].append({'source':source,'kind':kind,'id':str(sid),'name':name,'target':target,
                                  'params':params,'text':plain(text),
                                  **({'duration':duration} if ns=='field' else {})})

    def structured(source, kind, sid, row, ns=None):
        ns=ns or ('active' if row.get('active',True) else 'passive')
        effects=row.get('effects_raw') or []; descriptions=row.get('effects') or []
        for i, raw in enumerate(effects):
            if not isinstance(raw,list) or len(raw)<(3 if ns=='field' else 4):
                anomalies.append({'source':source,'kind':kind,'id':str(sid),'reason':'malformed effects_raw','raw':raw}); continue
            code=raw[1] if ns=='field' else raw[2]
            if not isinstance(code,int):
                anomalies.append({'source':source,'kind':kind,'id':str(sid),'reason':'non-integer opcode','raw':raw});continue
            text=descriptions[i] if len(descriptions)==len(effects) else ''
            register(ns,code,source,kind,sid,row.get('name') or row.get('desc_short'),raw[-1],
                     None if ns=='field' else raw[:2],text,raw[0] if ns=='field' else None)

    jp_skills={}
    for region in ('gl','jp'):
        for tab in ('skills','monster_skills','limitbursts','area_effects'):
            path=track(args.datamine/'data'/region/(tab+'.json')); data=read(path)
            source=region.upper()+'_2024'; source_counts[f'{source}/{tab}']=len(data)
            if region=='jp' and tab=='skills':jp_skills=data
            for sid,row in data.items():
                if tab=='limitbursts':
                    for lv,v in (row.get('levels') or {}).items():
                        structured(source,'LB level',f'{sid}/level/{lv}',{'name':row.get('name'),**v},'active')
                else:
                    kind='field' if tab=='area_effects' else 'enemy skill' if tab=='monster_skills' else 'passive' if not row.get('active',True) else 'magic' if row.get('type')=='MAGIC' else 'ability'
                    structured(source,kind,sid,row,'field' if tab=='area_effects' else None)
    if args.archive.exists():
        track(args.archive)
        with zipfile.ZipFile(args.archive) as archive:
            for region in ('GL','JP'):
                for tab,ns,kind in [('skills_ability','active','ability'),('skills_magic','active','magic'),('skills_passive','passive','passive')]:
                    data=json.loads(archive.read(f'ffbeEquip-master/tools/{region}/sources/{tab}.json'))
                    source=region+'_2022';source_counts[f'{source}/{tab}']=len(data)
                    for sid,row in data.items():structured(source,kind,sid,row,ns)
                data=json.loads(archive.read(f'ffbeEquip-master/tools/{region}/sources/limitbursts.json'))
                source_counts[f'{region}_2022/limitbursts']=len(data)
                for sid,row in data.items():
                    levels=row.get('levels') or []
                    for n,lv in enumerate(levels,1):
                        texts=row.get('min_level',[]) if n==1 else row.get('max_level',[]) if n==len(levels) else []
                        structured(region+'_2022','LB level',f'{sid}/level/{n}',
                                   {'name':row.get('name'),'effects_raw':lv[1],'effects':texts},'active')

    # Raw JP flags mark some callable subskills passive. Reuse the datamine's
    # reference-graph correction only when its opcode vector still matches.
    for tab,idkey,kind in [('F_ABILITY_MST','ability_id','ability'),('F_MAGIC_MST','magic_id','magic'),('F_LIMITBURST_MST','lb_id','LB')]:
        path=track(ROOT/'build/devui/live_jp'/(tab+'.json')); rows=read(path)['rows'];source='JP_CLIENT'
        source_counts[f'{source}/{tab}']=len(rows)
        for row in rows:
            ns='passive' if tab=='F_ABILITY_MST' and row.get('is_active')=='1' else 'active'
            sid=row[idkey];types=str(row.get('effect_type') or '').split('@');params=str(row.get('effect_param') or '').split('@')
            known=jp_skills.get(sid,{})
            if tab=='F_ABILITY_MST' and 'active' in known and known['active']!=(ns=='active'):
                if types==[str(e[2]) for e in known.get('effects_raw',[])]:
                    corrections.append(sid); ns='active' if known['active'] else 'passive'
            if len(types)!=len(params):anomalies.append({'source':source,'kind':kind,'id':sid,'reason':'effect/parameter group count differs','types':len(types),'params':len(params)})
            for i,code in enumerate(types):
                if not re.fullmatch(r'-?\d+',code):
                    anomalies.append({'source':source,'kind':kind,'id':sid,'reason':'empty or malformed live opcode','code':code});continue
                targets=[str(row.get(k,'')).split('@') for k in ('target_range','target')]
                register(ns,int(code),source,'passive' if ns=='passive' else kind,sid,row.get('name'),
                         params[i] if i<len(params) else None,[v[min(i,len(v)-1)] for v in targets],'')

    path=track(ROOT/'build/devui/live_jp/F_FIELD_EFFECT_MST.json')
    fields=read(path)['rows'];source_counts['JP_CLIENT/F_FIELD_EFFECT_MST']=len(fields)
    for row in fields:
        types=str(row.get('effect_type') or '').split('@');params=str(row.get('effect_param') or '').split('@')
        for i,code in enumerate(types):
            if not re.fullmatch(r'-?\d+',code):
                anomalies.append({'source':'JP_CLIENT','kind':'field','id':row['area_effect_id'],'reason':'malformed field opcode','code':code});continue
            register('field',int(code),'JP_CLIENT','field',row['area_effect_id'],row.get('explain_short'),
                     params[i] if i<len(params) else None,None,row.get('explain_long'),row.get('turns'))

    for ns, entries in definitions.items():
        for code in entries:
            groups.setdefault(f'{ns}:{code}',{'key':f'{ns}:{code}','namespace':ns,'code':code,'occurrences':0,
                              'sourceCounts':{},'kinds':{},'records':set(),'examples':[]})
    ffbe=[]
    for g in sorted(groups.values(),key=lambda g:(g['namespace'],g['code'])):
        g['recordCount']=len(g.pop('records'));g.update(definitions[g['namespace']].get(g['code'],{}))
        label=g.get('translatedLabel') or g.get('formatterLabel') or ''
        if not label:
            text=g.get('englishTemplate') or next((e['text'] for e in g['examples'] if e['text'] and not re.search(r'unknown|error:',e['text'],re.I)),'')
            label=text.split(' / ')[0][:130]
        g['label']=label or 'Unresolved opcode'
        g['evidence']='unresolved' if g['label']=='Unresolved opcode' or re.search(r'^unknown\b|error:',g['label'],re.I) else 'tentative' if '?' in g['label'] else 'source_description'
        g['observed']=g['occurrences']>0
        ffbe.append(g)
    tribes=track(args.datamine/'dat_raw/gl/F_TEXT_TRIBE.txt').read_text(encoding='utf-8-sig')
    races={int(m[1]):m[2] for m in re.finditer(r'^MST_TRIBE_NAME_(\d+)\^([^\^\r\n]+)',tribes,re.M)}
    summary={'ffr':ffr['counts'],'ffrEffectTypes':len(native_fx),'ffrTypesWithEffectRows':sum(bool(x['effectRows']) for x in native_fx),
             'ffrEnumOnlyTypes':sum(x['evidence']=='enum_only' for x in native_fx),'ffbeByNamespace':{},
             'ffbeSources':source_counts,'ffbeRaces':races,'liveFlagCorrections':len(corrections),'anomalies':len(anomalies)}
    for ns in ('active','passive','field'):
        group=[g for g in ffbe if g['namespace']==ns]
        summary['ffbeByNamespace'][ns]={'listed':len(group),'observed':sum(g['observed'] for g in group),
            'unresolvedObserved':sum(g['observed'] and g['evidence']=='unresolved' for g in group)}
    assert sum(len(v['effectRows']) for v in native_fx)==len(native['effects'])
    assert sum(len(v['directSkillRows']) for v in native_fx)==len(native['skills'])
    assert len({g['key'] for g in ffbe})==len(ffbe)
    track(Path(__file__))
    for name,data in [('ffr-effects.json',ffr),('ffbe-effects.json',ffbe),('summary.json',summary),
                      ('sources.json',inputs),('anomalies.json',{'records':anomalies,'correctedLiveFlags':corrections})]:
        (args.out/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

    lines=['# FFR effect inventory','', 'Generated from the extracted demo, including enemy/internal rows. A named enum is not proof of runtime support. See `ffr-effects.json` for every effect row, parameter and skill reference.','',
           '| Code | Effect type | Effect rows | Direct skill rows | Native usage examples |','|---|---|---:|---:|---|']
    for effect in native_fx:
        examples=[]
        for row in effect['effectRows']:
            for u in row['usedBy']:
                s=f'{u["name"] or u["row"]} ({u["id"]}; effect {row["ID"]})'
                if s not in examples:examples.append(s)
        fallback=('Effect rows present; no skill reference' if effect['effectRows'] else
                  'Direct skill field' if effect['directSkillRows'] else 'Enum only')
        lines.append(f'| {effect["code"]} | {effect["type"]} | {len(effect["effectRows"])} | {len(effect["directSkillRows"])} | {cell("; ".join(examples[:2]) or fallback)} |')
    for axis, values in axes.items():
        lines+=['',f'## {axis}','',', '.join(f'`{k}` ({n})' for k,n in values.items())]
    lines+=['','## Status definitions','','| Status | Debuff | Bad status | Removable by Esuna | Removable by Dispel |','|---|---|---|---|---|']
    for s in ffr['statuses']:lines.append(f'| {s["statusCondition"]} | {s["isDebuff"]} | {s["isBadStatus"]} | {s["isEsunaToOut"]} | {s["isDispelToOut"]} |')
    (args.out/'ffr-effects.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    lines=['# FFBE effect inventory','','Codes belong to separate active, passive and field namespaces. Active includes abilities, magic and LB components. Counts are source-record occurrences, including historical duplicates, enemies and all datamined LB levels; they are not unit counts. Definitions with zero occurrences are retained. Labels come from local formatter comments, client description templates or aligned effect text; question marks remain unresolved semantics. See `ffbe-effects.json` for parameters, examples and source references.']
    for ns in ('active','passive','field'):
        lines+=['',f'## {ns.title()} effects','','| Code | Meaning / source label | Occurrences | Record cases | Example |','|---|---|---:|---:|---|']
        for g in ffbe:
            if g['namespace']!=ns:continue
            ex=g['examples'][0] if g['examples'] else None
            lines.append(f'| {g["code"]} | {cell(g["label"])} | {g["occurrences"]} | {g["recordCount"]} | {cell((str(ex["name"])+" / "+ex["id"]+" / "+ex["source"]) if ex else "Definition only")} |')
    (args.out/'ffbe-effects.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
