"""Expand reviewed-in-progress family proposals into a per-opcode review map.
This is a report generator. Nothing imports this policy into Studio.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=ROOT/'docs/build16')
    args=parser.parse_args(); folder=args.directory
    def read(name):return json.loads((folder/name).read_text(encoding='utf-8'))
    ffr=read('ffr-effects.json'); ffbe=read('ffbe-effects.json'); policies=read('proposed-policies.json')
    targets={t['type']:t for t in ffr['effectTypes']}
    assignments={}
    for rule in policies['families']:
        assert all(t in targets for t in rule['ffr']),rule['id']
        for ns,codes in rule['codes'].items():
            for code in codes:
                key=f'{ns}:{code}'
                if key in assignments:raise ValueError('Duplicate proposed policy: '+key)
                assignments[key]=rule
    rows=[]
    for effect in ffbe:
        rule=assignments.get(effect['key'])
        if effect['evidence']=='unresolved' and effect['observed']:
            rule=None
        strategy=rule['strategy'] if rule else 'REVIEW' if effect['observed'] else 'DEFINITION_ONLY'
        sources=[]
        if rule:
            for t in rule['ffr']:
                data=targets[t]
                examples=[]
                for r in data['effectRows']:
                    if r['usedBy']:
                        examples.append({'effectId':r['ID'],'row':r['row'],'nativeSkill':r['usedBy'][0]})
                    if len(examples)==2:break
                sources.append({'type':t,'effectRows':len(data['effectRows']),'directSkillRows':len(data['directSkillRows']),
                                'evidence':data['evidence'],'examples':examples})
        rows.append({'key':effect['key'],'label':effect['label'],'observed':effect['observed'],
                     'sourceEvidence':effect['evidence'],'recordCases':effect['recordCount'],
                     'family':rule['id'] if rule else None,'strategy':strategy,
                     'proposal':rule['proposal'] if rule else 'Decode the raw effect and its context before choosing a substitute.' if effect['observed'] else 'Retain in the registry; no observed source case in this scan.',
                     'nativeCandidates':sources,'approval':'pending','runtimeValidation':'not_run'})
    summary={'status':'proposal_only','totalOpcodes':len(rows),'observedOpcodes':sum(r['observed'] for r in rows),
             'observedStrategies':dict(Counter(r['strategy'] for r in rows if r['observed'])),
             'review':[r['key'] for r in rows if r['observed'] and r['strategy']=='REVIEW']}
    (folder/'proposed-map.json').write_text(json.dumps({'summary':summary,'effects':rows},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# Proposed FFBE → FFR effect map','','Proposal only. All entries await user review and runtime validation. `NATIVE_CANDIDATE` identifies an existing mechanism, not exact numerical parity. `ADAPT` needs parameter/target/timing work. `REPLACE` deliberately changes a mechanic. Unknown and lifecycle effects remain `REVIEW`. No unit has been converted by this report.','',
           '| FFBE code | Source meaning | Proposed route | FFR candidates | Replacement / implementation intent |','|---|---|---|---|---|']
    def c(v):return str(v).replace('|','\\|').replace('\n',' ')
    for row in rows:
        if not row['observed']:continue
        lines.append(f'| {row["key"]} | {c(row["label"])} | {row["strategy"]} | {", ".join(x["type"] for x in row["nativeCandidates"])} | {c(row["proposal"])} |')
    (folder/'proposed-map.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
