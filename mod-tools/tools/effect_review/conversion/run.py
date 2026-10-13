"""Apply frozen effect rules to every indexed source, producing review drafts."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import traceback
import zlib
from tools.ability_converter.catalog import SourceCatalog
from .prepare import ROOT, digest, write
from .rules import compile_rules
from .engine import ReviewedConverter, useful


def current_folder():
    return Path(json.loads((ROOT/'build/ability-review/current.json').read_text())['directory'])


def dumps(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))


def implementation_files(engine):
    paths=[*sorted((ROOT/'tools/ability_converter').glob('*.py')),*sorted((ROOT/'tools/effect_review/conversion').glob('*.py'))]
    paths.extend(engine.artifact_paths.values())
    return {str(p):digest(p) for p in paths}


def run(folder):
    state=json.loads((folder/'run.json').read_text())
    if (folder/'report.sqlite').exists():raise ValueError('A report already exists in this run. Preserve it; use a new prepared run for a changed ruleset.')
    compiled=compile_rules(folder);write(folder/'compiled-rules.json',compiled)
    start=time.monotonic()
    with SourceCatalog.open_existing(folder/'source-index.sqlite') as sources:
        engine=ReviewedConverter(compiled['rules'],resolver=sources)
        hashes=implementation_files(engine);write(folder/'implementation-manifest.json',hashes)
        for name,meta in json.loads((folder/'source-manifest.json').read_text()).items():
            if digest(name)!=meta['sha256']:raise ValueError(f'Source snapshot changed: {name}')
        db=sqlite3.connect(folder/'report.sqlite')
        db.executescript('''
            PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA cache_size=-32768;
            CREATE TABLE records(ordinal INTEGER PRIMARY KEY,source_key TEXT UNIQUE NOT NULL,source TEXT,kind TEXT,source_id TEXT,level INTEGER,
                name TEXT,outcome TEXT,partial INTEGER,retained INTEGER,omitted INTEGER,summary TEXT,reason TEXT,detail BLOB);
            CREATE TABLE record_effects(ordinal INTEGER,key TEXT,retained INTEGER,omitted INTEGER,PRIMARY KEY(ordinal,key));
            CREATE TABLE dependencies(ordinal INTEGER,component INTEGER,kind TEXT,relation TEXT,target TEXT,issue TEXT);
            CREATE TABLE decisions(source_key TEXT PRIMARY KEY,status TEXT NOT NULL,notes TEXT NOT NULL,revision INTEGER NOT NULL,updated_at TEXT NOT NULL);
        ''')
        totals=Counter();sources_count=defaultdict(Counter);kinds=defaultdict(Counter);effects=defaultdict(Counter);reasons=Counter();exceptions=[]
        state.update(status='converting',processed=0,startedAt=datetime.now(timezone.utc).isoformat())
        write(folder/'run.json',state)
        for ordinal,record in enumerate(sources):
            try:
                result=engine.convert(record)
            except Exception as ex:
                # Unexpected failures are bad rows, never omissions from the
                # exhaustive scan. The stack is kept for actionable debugging.
                message=f'{type(ex).__name__}: {ex}'
                exceptions.append({'source':record.key,'error':message,'trace':traceback.format_exc()})
                raws=record.data.get('effects_raw') or []
                result={'source':record.provenance(),'name':record.data.get('name'),'sourceRaw':raws,'sourceMetadata':record.data,
                    'outcome':'bad','partial':False,'status':'blocked','summary':'Converter error: '+message,'issues':['Converter error: '+message],
                    'changes':[],'omissions':[],'native':None,'validation':{'tableCompatible':False,'runtime':'not_run'},
                    'components':[{'index':i,'raw':raw,'key':f'{record.namespace}:{raw[-2]}' if isinstance(raw,list) and len(raw)==(3 if record.namespace=='field' else 4) and type(raw[-2]) is int else None,
                        'effects':[],'actions':[],'dependencies':[],'issues':[message],'omissions':[{'kind':'exception','reason':message}]} for i,raw in enumerate(raws)]}
            raw_count=len(record.data.get('effects_raw') or [])
            assert len(result['components'])==raw_count,record.key
            retained=sum(useful(c) for c in result['components']);omitted=raw_count-retained
            totals[result['outcome']]+=1;totals['partial']+=bool(result['partial']);totals['records']+=1
            totals['rawComponents']+=raw_count;totals['retainedComponents']+=retained;totals['omittedComponents']+=omitted
            sources_count[record.source][result['outcome']]+=1;kinds[record.kind][result['outcome']]+=1
            why=list(dict.fromkeys([*result['issues'],*[o['reason'] for o in result.get('omissions',[])]]))
            reasons.update(why)
            perkey=defaultdict(Counter)
            for c in result['components']:
                if not c.get('key'):
                    totals['malformedComponents']+=1;continue
                key=c['key'];effects[key]['occurrences']+=1;perkey[key]['retained' if useful(c) else 'omitted']+=1
                effects[key]['retained' if useful(c) else 'omitted']+=1
                effects[key]['partialComponents']+=bool(useful(c) and c.get('omissions'))
                for dep in c['dependencies']:
                    db.execute('INSERT INTO dependencies VALUES (?,?,?,?,?,?)',(ordinal,c['index'],dep['kind'],dep['relation'],dep.get('resolved'),dep.get('resolutionIssue')))
            for key,v in perkey.items():
                effects[key]['records']+=1;effects[key][result['outcome']]+=1
                db.execute('INSERT INTO record_effects VALUES (?,?,?,?)',(ordinal,key,v['retained'],v['omitted']))
            db.execute('INSERT INTO records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(ordinal,record.key,record.source,record.kind,record.id,
                int(record.level) if record.level is not None else None,str(result.get('name') or record.id),result['outcome'],int(result['partial']),retained,omitted,
                result['summary'],' | '.join(why),zlib.compress(dumps(result).encode('utf-8'),3)))
            if (ordinal+1)%5000==0:
                db.commit()
                state.update(processed=ordinal+1,counts=dict(totals),elapsedSeconds=round(time.monotonic()-start))
                write(folder/'run.json',state)
                print(f"{ordinal+1:,}/{sources.count:,} | good {totals['good']:,} | bad {totals['bad']:,} | partial {totals['partial']:,}",flush=True)
        db.commit()
        db.executescript('''
            CREATE INDEX records_outcome ON records(outcome,ordinal);
            CREATE INDEX records_source ON records(source,outcome,ordinal);
            CREATE INDEX records_kind ON records(kind,outcome,ordinal);
            CREATE INDEX records_partial ON records(partial,ordinal);
            CREATE INDEX effect_lookup ON record_effects(key,ordinal);
            CREATE INDEX dependency_target ON dependencies(target);
        ''')
        assert totals['records']==sources.count==state['expectedRecords']
        assert totals['good']+totals['bad']==totals['records']
        assert totals['retainedComponents']+totals['omittedComponents']==totals['rawComponents']
        for key,rule in compiled['rules'].items():
            assert effects[key]['occurrences']==rule['occurrences'],(key,effects[key]['occurrences'],rule['occurrences'])
            assert effects[key]['records']==rule['recordCount'],(key,effects[key]['records'],rule['recordCount'])
        assert sum(e['occurrences'] for e in effects.values())==1620635
        current_hashes=implementation_files(engine)
        changed=[name for name,hash in hashes.items() if current_hashes.get(name)!=hash]
        # UI/server code may be added while the immutable conversion runs.
        assert not changed,changed
        db.execute('PRAGMA wal_checkpoint(TRUNCATE)');db.close()
        report={'schemaVersion':1,'run':folder.name,'savedRevision':compiled['savedRevision'],'counts':dict(totals),
            'sources':dict(sources_count),'kinds':dict(kinds),'effects':dict(effects),'reasons':reasons.most_common(),
            'exceptions':len(exceptions),'validation':{'allRecordsAccounted':True,'allEffectsAccounted':True,'allRawComponentsAccounted':True,
                'inputHashesMatch':True,'implementationStable':True,'runtime':'not_run','finalUnitCatalog':'not_created'},
            'completedAt':datetime.now(timezone.utc).isoformat(),'elapsedSeconds':round(time.monotonic()-start)}
        write(folder/'summary.json',report);write(folder/'exceptions.json',exceptions)
        state.update(status='complete',processed=totals['records'],counts=dict(totals),elapsedSeconds=report['elapsedSeconds'])
        write(folder/'run.json',state)
        print(dumps(report['counts']),flush=True)
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run',type=Path)
    args=parser.parse_args();folder=args.run or current_folder()
    try:run(folder)
    except Exception:
        state=json.loads((folder/'run.json').read_text());state.update(status='failed',failure=traceback.format_exc());write(folder/'run.json',state)
        raise


if __name__=='__main__':main()
