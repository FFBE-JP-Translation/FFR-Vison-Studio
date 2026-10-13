"""Package completed catalog output; no game, native hooks, or new mechanics."""
import argparse
from collections import Counter, defaultdict
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
import zipfile

from ability_converter import Converter
from ability_converter.compiler import TableWriter
from ability_converter.runs import require_current_run, require_matching
from ability_converter.sources import ARTIFACTS, ROOT, read

LABELS={'converted':'direct','adapted':'adaptation','replaced':'replacement','blocked':'unsupported','noop':'no_op'}
TABLES={'Skill/DT_SkillData','Skill/DT_PassiveSkillData','Skill/DT_SkillEffectData','Skill/Other/DT_SkillGeneralData'}

def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf8')

def line(stream,value):
    stream.write(json.dumps(value,ensure_ascii=False,separators=(',',':'))+'\n')

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def audit_records(catalog,out):
    counts=Counter();by_source=defaultdict(Counter);by_kind=defaultdict(Counter);reasons=Counter()
    roots=defaultdict(set);examples={};seen=set();total=0
    with ExitStack() as stack:
        supported=stack.enter_context((out/'supported.jsonl').open('w',encoding='utf8'))
        unsupported=stack.enter_context((out/'unsupported.jsonl').open('w',encoding='utf8'))
        noops=stack.enter_context((out/'noops.jsonl').open('w',encoding='utf8'))
        source=stack.enter_context((catalog/'converted.jsonl').open(encoding='utf8'))
        for number,raw in enumerate(source,1):
            record=json.loads(raw);status=record['status'];label=LABELS[status]
            key=record['source']['key']
            if key in seen:raise ValueError(f'Duplicate source record: {key}')
            seen.add(key);counts[label]+=1;total+=1
            by_source[record['source']['source']][label]+=1;by_kind[record['source']['kind']][label]+=1
            base={'source':record['source'],'name':record['name'],'classification':label,
                  'originalStatus':status,'conversionRecordLine':number,'gameplayCompatibility':'not_verified'}
            if label in ('direct','adaptation','replacement'):
                if not record['validation']['tableCompatible'] or record['issues'] or not record.get('destinationId'):
                    raise ValueError(f'Inconsistent supported record: {key}')
                table=record['native']['table'];identifier=record['destinationId']
                if identifier in roots[table]:raise ValueError(f'Duplicate root ID: {table}/{identifier}')
                roots[table].add(identifier)
                line(supported,{**base,'tableCompatible':True,'destinationTable':table,'destinationId':identifier,
                    'changes':record['changes'],'integrationStatus':'binding_recipes_required'})
            elif label=='unsupported':
                if record['validation']['tableCompatible'] or not record['issues']:
                    raise ValueError(f'Unsupported record has no explicit reason: {key}')
                unique_reasons=list(dict.fromkeys(record['issues']))
                line(unsupported,{**base,'tableCompatible':False,'reasons':unique_reasons})
                normalized={issue.split(': ',1)[-1] if issue.startswith('Component ') else issue for issue in unique_reasons}
                reasons.update(normalized)
            else:
                if record['validation']['tableCompatible']:raise ValueError(f'No-op unexpectedly exported: {key}')
                line(noops,{**base,'tableCompatible':False,
                    'reasons':record['issues'] or ['All source components decode as explicit no-ops; no FFR ability row is emitted.']})
            if label not in examples:examples[label]=record
            if key=='GL_2024/ability/150300':examples['limited-use-hold']=record
            if key=='JP_2024/magic/20010':examples['fire']=record
            if number%100000==0:print(f'Audited {number:,} output records',flush=True)
    return {'records':total,'classifications':dict(counts),'bySource':dict(by_source),'byKind':dict(by_kind),
            'unsupportedReasons':dict(reasons.most_common()),'reasonCountsOverlap':True},roots,examples

def make_patch(catalog,out,roots):
    ffr=out/'ffr';ffr.mkdir(exist_ok=True)
    counts=defaultdict(Counter);native_ids=defaultdict(set)
    # Spool individual tables so the complete FFR patch never needs to fit in
    # memory. These files are created under this delivery and removed there.
    with tempfile.TemporaryDirectory(prefix='.patch-',dir=out) as temporary:
        temporary=Path(temporary).resolve()
        assert temporary.is_relative_to(out.resolve())
        paths={}
        with ExitStack() as stack:
            streams={}
            source=stack.enter_context((catalog/'native-rows.jsonl').open(encoding='utf8'))
            for raw in source:
                row=json.loads(raw);table=row.pop('table');operation=row.pop('operation','add')
                if table not in TABLES or operation not in ('add','set'):raise ValueError('Unknown native table operation')
                if operation=='add':
                    identifier=row['set']['ID']
                    if identifier in native_ids[table]:raise ValueError(f'Duplicate native ID: {table}/{identifier}')
                    native_ids[table].add(identifier)
                group=(table,operation)
                if group not in streams:
                    path=temporary/f'{len(paths)}.jsonl';paths[group]=path
                    streams[group]=stack.enter_context(path.open('w',encoding='utf8'))
                line(streams[group],row);counts[table][operation]+=1
        for table,ids in roots.items():
            if not ids<=native_ids[table]:raise ValueError(f'Supported root rows missing from native output: {table}')
        patch=ffr/'catalog.patch.json'
        with patch.open('w',encoding='utf8',newline='\n') as stream:
            header={'legacyRoot':str(ROOT/'extracted/legacy').replace('\\','/'),
                    'outRoot':str(out/'ffr-assets').replace('\\','/'),'runtimeValidation':'not_run',
                    'bindingsFile':'../catalog/bindings.jsonl','stringsFile':'../catalog/strings.jsonl'}
            stream.write(json.dumps(header,ensure_ascii=False)[:-1]+',"tables":[')
            for index,table in enumerate(sorted(counts)):
                if index:stream.write(',')
                stream.write('{"asset":'+json.dumps('FFRS/Content/Datatable/'+table))
                for operation in ('add','set'):
                    if (table,operation) not in paths:continue
                    stream.write(',"'+operation+'":[')
                    with paths[(table,operation)].open(encoding='utf8') as rows:
                        for ordinal,raw in enumerate(rows):
                            if ordinal:stream.write(',')
                            stream.write(raw.rstrip('\n'))
                    stream.write(']')
                stream.write('}')
            stream.write(']}\n')
    return {table:dict(value) for table,value in counts.items()}

def write_examples(catalog,out,converter,examples):
    target=out/'examples';target.mkdir(exist_ok=True);ledger=read(catalog/'ids.json');index=[]
    for label,record in examples.items():
        dump(target/(label+'.json'),record)
        item={'file':label+'.json','source':record['source']['key'],'name':record['name'],
              'classification':LABELS[record['status']],'changes':record['changes'],'reasons':record['issues']}
        if record['validation']['tableCompatible']:
            writer=TableWriter(converter.native,ledger)
            if writer.add(record)!=record['destinationId']:raise ValueError('Example ID changed')
            patch={**writer.patch(out/'example-assets'/label),'source':record['source'],
                   'strings':writer.strings,'classification':LABELS[record['status']]}
            dump(target/(label+'.patch.json'),patch);item['patch']=label+'.patch.json'
        index.append(item)
    dump(target/'index.json',index)
    return index

def readme(out,coverage,examples):
    counts=coverage['classifications'];baseline=coverage['reusedValidation']
    rows=[f"| {name} | {counts.get(name,0):,} | {meaning} |" for name,meaning in (
        ('direct','Existing direct adapter; no declared adaptation or replacement.'),
        ('adaptation','FFBE mechanics adjusted to FFR scales or data structures; changes are listed.'),
        ('replacement','One or more mechanics deliberately substituted; changes are listed.'),
        ('unsupported','No native root exported; every record has explicit reasons.'),
        ('no_op','Explicit source no-op; no native root exported.'))]
    example_rows=[f"| `{v['source']}` | {v['name']} | {v['classification']} | `examples/{v['file']}` |" for v in examples]
    text=f'''# FFBE → FFR converter delivery

Run from any directory on this configured workspace (Python 3.12+):

```powershell
python -X utf8 -B "{ROOT / 'tools/deliver_ability_converter.py'}"
```

This reads the existing FFBE source index and generated FFR/FFBE mapping artifacts, reconverts the full catalog, and writes `{out}` plus `{out.with_suffix('.zip')}`. It preserves the original source catalog and IDs. Optional `--catalog`, `--artifacts`, and `--out` select different input/output locations. Original source files must still match the indexed snapshot. No network, game launch, hook build, installation, or external Python package is required for this delivery command.

## Coverage

{coverage['records']:,} source records, including regions, historical revisions and individual LB levels—not unique abilities.

| Classification | Records | Meaning |
|---|---:|---|
{chr(10).join(rows)}

**{coverage['mechanicsExported']:,} records have exported mechanics rows. These are table-compatible conversion results, not verified gameplay-compatible abilities.** “Direct” describes the adapter, not a claim of perfect audiovisual or gameplay parity. Classification precedence is unsupported, then replacement, adaptation, direct; component-level outcomes remain in the full record.

## Output

- `ffr/catalog.patch.json`: one complete `ffr-dt` clone/set mechanics patch, covering supported active/passive/effect rows and general settings. Paths inside this patch refer to this workspace's extracted native tables and an uncreated output directory. This command does not cook or install it.
- `catalog/native-rows.jsonl`, `catalog/bindings.jsonl`, `catalog/strings.jsonl`: streaming rows, required actor/command/sequence binding recipes, and text.
- `supported.jsonl`: every exported source identity, its classification, native ID, and disclosed changes.
- `unsupported.jsonl`: every unsupported identity and its exact reasons. `noops.jsonl` separately explains every non-emitted no-op.
- `catalog/converted.jsonl`: full raw components, decoded mechanics, provenance, changes and validation state. Index files point to its one-based record line.
- `coverage.json`: exact counts, source/kind breakdowns, native row counts and overlapping blocker counts.
- `examples/`: complete conversion records and individual FFR patches where supported.
- `validation/`: reused native table round-trip evidence, input report, and focused existing test results. `manifest.json` records output hashes; `delivery.json` outside the zip reports workflow completion.

In `coverage.json`, a reason counts each unsupported record at most once; records with several reasons appear in several reason counts. The original `catalog/report.json` and `catalog/README.md` count individual issue occurrences, so their blocker frequencies can be higher.

To export another exact source identity from this completed delivery:

```powershell
python -X utf8 -B "{ROOT / 'tools/ability_import.py'}" export JP_2024/magic/20010 --out "{out / 'catalog'}" --output "{out / 'fire.patch.json'}"
```

Keep `catalog/ids.json` on reruns to retain assigned IDs. An interrupted run is marked incomplete and must not be consumed. The package is a mechanics/binding data export, not a ready-to-install mod; the full catalog is not a supported bulk gameplay installation.

## Examples

| Source identity | Name | Classification | Record |
|---|---|---|---|
{chr(10).join(example_rows)}

## Validation and limits

All records and emitted rows were reconciled for this delivery: every supported root exists in the patch, IDs are unique per table, and every unsupported/no-op record is accounted for. Conversion reuses the existing parameter/schema checks. Existing native serialization evidence covers {baseline['sourceAbilities']:,} representative abilities and {baseline['nativeRows']:,} rows; the regenerated native row stream matches that validated catalog byte for byte. It does not establish gameplay behavior for the exported catalog. No new native/game tests were run for this delivery.

Command/menu membership, animations and sequencers, actor ownership, resource/lifecycle handling and cooking/packaging still need integration for playable abilities. Cooldowns/limited uses/charges and automatic repeat/multicast identity remain held where required. Conditional linked actions, fields, mixed living/dead targeting, resource transfer, death-or-damage branches and undecoded parameters also retain explicit per-record holds. Missing references are listed in `catalog/graph.json`. Replacements can change source behavior substantially; review `changes` before using them.

Unfinished native research is preserved separately at `{ROOT / 'build/abilities/research-frozen-20260911'}` and in its original source/evidence locations. No research DLL or runtime hook is included in this delivery.
'''
    (out/'README.md').write_text(text,encoding='utf8')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--baseline',type=Path,required=True)
    parser.add_argument('--artifacts',type=Path,default=ARTIFACTS);args=parser.parse_args()
    out=args.out.resolve();catalog=out/'catalog';baseline=args.baseline.resolve();converter=Converter(args.artifacts)
    report=require_current_run(catalog,converter);original=require_current_run(baseline,converter)
    if report['records']!=original['indexedRecords']:raise ValueError('Incomplete source catalog conversion')
    coverage,roots,examples=audit_records(catalog,out)
    expected={LABELS[k]:v for k,v in report['statuses'].items()}
    if coverage['records']!=report['records'] or coverage['classifications']!=expected:raise ValueError('Coverage does not reconcile')
    coverage['mechanicsExported']=sum(coverage['classifications'].get(k,0) for k in ('direct','adaptation','replacement'))
    coverage['gameplayVerifiedForThisDelivery']=0
    coverage['supportDefinition']='mechanics table export; gameplay compatibility not verified'
    print('Assembling complete FFR patch',flush=True)
    coverage['nativeRowsByTable']=make_patch(catalog,out,roots)
    evidence=read(baseline/'verification.json')
    require_matching(original['implementation'],report['implementation'],'reused validation implementation')
    require_matching(original['artifacts'],report['artifacts'],'reused validation artifacts')
    if original['validation'].get('nativeRoundTrip')!={k:evidence[k] for k in ('sourceAbilities','nativeRows','tableRoundTrip')}:
        raise ValueError('Existing report does not attest to this serialization evidence')
    if evidence['tableRoundTrip']!='passed' or evidence['issues']:raise ValueError('Existing native table validation is not passing')
    native_hash=sha(catalog/'native-rows.jsonl')
    if native_hash!=sha(baseline/'native-rows.jsonl'):raise ValueError('Regenerated native rows differ from the validated baseline')
    coverage['reusedValidation']={'sourceAbilities':evidence['sourceAbilities'],'nativeRows':evidence['nativeRows'],
        'kind':'representative native table serialization only','reportSha256':sha(baseline/'verification.json'),
        'nativeRowStreamMatchesBaseline':True,'nativeRowStreamSha256':native_hash}
    coverage['graph']=report['graph']
    dump(out/'coverage.json',coverage)
    examples=write_examples(catalog,out,converter,examples)
    validation=out/'validation';validation.mkdir(exist_ok=True)
    for source,name in ((baseline/'verification.json','native-table-roundtrip.json'),(baseline/'report.json','source-catalog-report.json'),
        (ROOT/'build/abilities/bounded-delivery-cleanup.json','cleanup.json'),
        (ROOT/'build/abilities/bounded-delivery-catalog-tests.log','catalog-tests.txt'),
        (ROOT/'build/abilities/bounded-delivery-id-tests.log','id-tests.txt')):
        shutil.copyfile(source,validation/name)
    readme(out,coverage,examples)
    # Do not bundle old research companions accidentally retained by an earlier
    # invocation: only the documented delivery files are included.
    catalog_names=('converted.jsonl','native-rows.jsonl','bindings.jsonl','strings.jsonl','review.jsonl','graph.json','ids.json','registry.json','report.json','README.md','run.json')
    files=[catalog/name for name in catalog_names]
    files += [out/name for name in ('README.md','coverage.json','supported.jsonl','unsupported.jsonl','noops.jsonl')]
    files += [out/'ffr/catalog.patch.json',out/'examples/index.json']
    for example in examples:
        files.append(out/'examples'/example['file'])
        if 'patch' in example:files.append(out/'examples'/example['patch'])
    files += [validation/name for name in ('native-table-roundtrip.json','source-catalog-report.json','cleanup.json','catalog-tests.txt','id-tests.txt')]
    manifest={'schema':'ffbe-ffr-delivery/1','status':'data_verified','records':coverage['records'],
        'gameplayCompatibility':'not_verified','files':{p.relative_to(out).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}}
    dump(out/'manifest.json',manifest);files.append(out/'manifest.json')
    archive=out.with_suffix('.zip')
    print(f'Packaging {len(files)} files into {archive}',flush=True)
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as bundle:
        for path in files:bundle.write(path,arcname='FFBE-to-FFR/'+path.relative_to(out).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist())!=len(files):raise ValueError('Archive file inventory mismatch')
        if json.loads(bundle.read('FFBE-to-FFR/coverage.json'))!=coverage:raise ValueError('Packaged coverage mismatch')
    marker=read(out/'delivery.json')
    marker.update(status='complete',completedUtc=datetime.now(timezone.utc).isoformat(),records=coverage['records'],
        classifications=coverage['classifications'],mechanicsExported=coverage['mechanicsExported'],
        archive=str(archive),archiveBytes=archive.stat().st_size,archiveSha256=sha(archive),manifestSha256=sha(out/'manifest.json'))
    dump(out/'delivery.json',marker)
    print(json.dumps(marker,indent=2),flush=True)

if __name__=='__main__':main()
