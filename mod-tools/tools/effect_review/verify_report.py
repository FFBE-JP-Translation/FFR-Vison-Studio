"""Read and check every saved conversion draft, not a sample."""
from collections import Counter
import json
import sqlite3
import zlib
from .conversion.run import current_folder
from .conversion.prepare import write


def effect_specs(value):
    if isinstance(value,dict):
        if isinstance(value.get('set'),dict) and 'EffectType' in value['set']:yield value
        # Only output graphs, never discarded candidates or source snapshots.
        for k,v in value.items():
            if k in ('effects','children','randomChoices','applications','reraise','automaticPassive','delayedAction','child','native'):
                yield from effect_specs(v)
    elif isinstance(value,list):
        for v in value:yield from effect_specs(v)


def main():
    folder=current_folder();db=sqlite3.connect((folder/'report.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    counts=Counter();examples={}
    def flag(kind,key):
        counts[kind]+=1
        if len(examples.setdefault(kind,[]))<12:examples[kind].append(key)
    for ordinal,(key,outcome,blob) in enumerate(db.execute('SELECT source_key,outcome,detail FROM records ORDER BY ordinal')):
        r=json.loads(zlib.decompress(blob));counts['checked']+=1
        if r['outcome']!=outcome:flag('inconsistent_outcome',key)
        if outcome=='good':
            counts['goodChecked']+=1
            if r['issues'] or not r['native'] or not r['validation']['tableCompatible']:flag('invalid_good_record',key)
            n=r['native']
            if not n['effects'] and not any(v['set'].get('magnification',0)>0 for v in [n,*n.get('applications',[])]):flag('empty_native_output',key)
            for spec in effect_specs(n):
                row=spec['set'];p=row['ParamList']
                if row['EffectType']=='ParameterVariation' and p[1] in (2,4):
                    if row['applyTiming']!='AddEffect' or row['proceedTiming']!='AddEffect' or row['effectEndActionNum']!=1:flag('repeating_mp_or_resonance',key)
                    if p[0]==0:flag('zero_resource_amount',key)
                    if spec.get('target',{}).get('relation')=='Enemies':flag('enemy_resonance_target' if p[1]==4 else 'enemy_mp_recovery_retains_source_scope',key)
                if row['EffectType']=='AutomaticSkill' and row['applyTiming']=='BeginTurn' and spec.get('automaticPassive'):
                    for nested in effect_specs(spec['automaticPassive']['child']['native']):
                        s=nested['set']
                        if s['EffectType']=='ParameterVariation' and s['ParamList'][1] in (2,4):flag('repeated_automatic_resource',key)
        if (ordinal+1)%100000==0:print(f'Verified {ordinal+1:,} stored drafts',flush=True)
    report={'counts':dict(counts),'examples':examples};write(folder/'exhaustive-verification.json',report)
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
