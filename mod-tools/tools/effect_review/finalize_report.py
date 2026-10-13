"""Exhaustive output-policy pass, recompiling every affected record by semantics.

This is an incremental correction of an already exhaustive conversion. It
reads every stored draft, never filters by name/ID or selects a sample. The
initial pass and implementation manifest remain available for reproduction.
"""
from collections import Counter
import json
import sqlite3
import zlib
from tools.ability_converter.catalog import SourceCatalog
from .conversion.run import current_folder,dumps,implementation_files
from .conversion.prepare import write
from .conversion.engine import ReviewedConverter
from .verify_report import effect_specs


def needs_main_cast_binding(result):
    for spec in effect_specs(result.get('native')):
        row=spec['set']
        resource=row['EffectType']=='LimitBurstPointDistribute' or row['EffectType']=='ParameterVariation' and row['ParamList'][1]==4
        if resource and spec.get('target',{}).get('relation')=='Enemies':return True
    return False


def reasons(r):return set([*r['issues'],*[o['reason'] for o in r.get('omissions',[])]])


def main():
    folder=current_folder();summary=json.loads((folder/'summary.json').read_text())
    if (folder/'finalization.json').exists():raise ValueError('The finalization pass already completed.')
    compiled=json.loads((folder/'compiled-rules.json').read_text(encoding='utf-8'))
    db=sqlite3.connect(folder/'report.sqlite');updates=[];checked=0
    with SourceCatalog.open_existing(folder/'source-index.sqlite') as sources:
        engine=ReviewedConverter(compiled['rules'],resolver=sources)
        for ordinal,key,blob in db.execute('SELECT ordinal,source_key,detail FROM records ORDER BY ordinal'):
            checked+=1;old=json.loads(zlib.decompress(blob))
            if needs_main_cast_binding(old):
                new=engine.convert(sources.get(key))
                if needs_main_cast_binding(new):raise ValueError('Main-cast routing failed: '+key)
                # This correction only routes gauge recovery. Outcome and all
                # component accounting must remain stable; otherwise stop and
                # use a complete new run rather than quietly stale totals.
                for name in ('outcome','partial','componentAccounting'):
                    assert old[name]==new[name],(key,name)
                updates.append((ordinal,key,old,new))
            if checked%100000==0:print(f'Checked {checked:,} drafts for main-cast recovery routing',flush=True)
        assert checked==summary['counts']['records']==658544
        original_reasons=Counter(dict(summary['reasons']))
        with db:
            for ordinal,key,old,new in updates:
                original_reasons.subtract(reasons(old));original_reasons.update(reasons(new))
                db.execute('UPDATE records SET summary=?,reason=?,detail=? WHERE ordinal=?',
                    (new['summary'],' | '.join(sorted(reasons(new))),zlib.compress(dumps(new).encode('utf-8'),3),ordinal))
        write(folder/'finalization-changes.json',[{'key':key,'before':old,'after':new} for _,key,old,new in updates])
        write(folder/'final-implementation-manifest.json',implementation_files(engine))
        summary['reasons']=Counter({k:v for k,v in original_reasons.items() if v>0}).most_common()
        summary['validation']['mainCastRecoveryPass']={'recordsChecked':checked,'recordsCorrected':len(updates),'criterion':'Every native resonance refill/distribution targets main-cast recipients.'}
        write(folder/'summary.json',summary)
        write(folder/'finalization.json',{'recordsChecked':checked,'recordsCorrected':len(updates),'method':'Exhaustive semantic scan followed by recompile of every affected source record.',
            'sourceRule':'All LB refill restores main-cast resonance; enemy-side gauge refill routes to allies without changing source single/group scope.'})
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.close()
        print(json.dumps({'checked':checked,'corrected':len(updates)}),flush=True)


if __name__=='__main__':main()
