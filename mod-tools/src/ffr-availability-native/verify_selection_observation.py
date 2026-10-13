"""Correlate native source-entry addresses with jobs without inferring repeat identity."""
import argparse
import json
from pathlib import Path
import re
from verify_combat_observation import ROOT,OUT,read_json as read,sha
from verify_multicommand_observation import verify as multi
from verify_repeat_observation import verify as repeat

HERE=Path(__file__).resolve().parent
def verify(directory,build,mode):
    assert mode in ('multi','cancel','repeat','control')
    run=read(directory/'run.json');assert run.get('nativeSelectionJobsRequested') is True
    semantic=multi(directory,build,cancel=mode=='cancel') if mode in ('multi','cancel') else repeat(directory,build,control=mode=='control')
    observer=read(directory/'selection-build.json')
    assert observer==read(OUT/'native-selection-build.json')
    assert sha(directory/'Mods/FFRSelectionProbe/dlls/main.dll')==observer['dllSha256']
    for path,digest in observer['inputs'].items():assert sha(ROOT/path)==digest,path
    assert sha(directory/'Mods/FFRBattleProbe/Scripts/selection_driver.lua')==sha(HERE/'selection_driver.lua')
    log=(directory/'collected-ue4ss/UE4SS.log').read_text(encoding='utf8')
    assert 'selection_decide_failed=' not in log
    events=[]
    for number,line in enumerate(log.splitlines(),1):
        found=re.search(r'\[FFRSelectionProbe\] (\{.*\})$',line)
        if found:
            event=json.loads(found[1]);event['logLine']=number;events.append(event)
    assert events and all(e['event'] in ('native_selection_decide','native_selection_append') for e in events)
    for kind in ('native_selection_decide','native_selection_append'):
        values=[e['sequence'] for e in events if e['event']==kind]
        assert values==list(range(1,len(values)+1))
    ids={400710,900010} if mode in ('multi','cancel') else {900010}
    appends=[e for e in events if e['event']=='native_selection_append' and e['selectedSkill'] in ids]
    assert appends and len({(e['receiver'],e['delegate'],e['entries']) for e in appends})==1
    first=appends[0]
    decisions=[e for e in events if e['event']=='native_selection_decide' and e['delegate']==first['delegate'] and e['receiver']==first['receiver']]
    assert len(decisions)==1
    decision=decisions[0];source=semantic['commandDecision'];actions=source['actions']
    assert decision['count']==first['entryCount']==len(actions)
    assert decision['logLine']<first['logLine'] and source['logLine']<first['logLine']
    guards={e['job']:e for e in semantic['nativeGuards']}
    mapped={}
    for event in appends:
        ordinal=event['entryOrdinal']
        assert 0<=ordinal<len(actions)
        assert event['entry']==event['entries']+ordinal*0x38
        action=actions[ordinal]
        assert event['selectedSkill']==action['skillId'] and event['selectedUnique']==action['uniqueId']
        assert event['skill']==event['sourceSkill']==event['selectedSkill']
        assert event['item']==action['item'] and event['notConsume']==source['notConsume']
        assert event['command']==source['commandId'] and event['control']==-1
        assert event['callerRva']==0x4f4aa81 and len(event['jobs'])==1
        for job in event['jobs']:
            assert job['job'] in guards and job['job'] not in mapped
            guard=guards[job['job']]
            assert event['logLine']<guard['logLine']
            for left,right in (('skill','skillId'),('objectIndex','objectIndex'),('rootJob','rootJob'),('actor','actor'),('actions','actionCount'),('targets','targetCount')):
                assert job[left]==guard[right],(left,job,guard)
            mapped[job['job']]={'sourceEntryOrdinal':ordinal,'sourceEntryAddress':event['entry'],
                'nativeSelectionSequence':decision['sequence'],'delegateAddress':decision['delegate'],
                'jobObjectIndex':job['objectIndex'],'job':job['job'],'skillId':job['skill']}
    if mode in ('multi','cancel'):
        assert [e['entryOrdinal'] for e in appends]==[0,1,2]
        assert len(mapped)==len(guards)==3
    elif mode=='control':assert len(mapped)==len(guards)==1
    else:assert 1<=len(mapped)<=len(guards)==2 and all(e['entryOrdinal']==0 for e in appends)
    if mode=='cancel':
        assert len(semantic['cancellations'])==1
        assert semantic['cancellations'][0]['logLine']<decision['logLine']
    unmapped=[g for job,g in guards.items() if job not in mapped]
    return {'status':'passed','scope':'native_selection_entry_job_observation','mode':mode,'run':directory.name,
        'runSha256':sha(directory/'run.json'),'logSha256':sha(directory/'collected-ue4ss/UE4SS.log'),
        'observerDllSha256':observer['dllSha256'],'nativeBridgeDllSha256':build['dllSha256'],
        'semanticCase':semantic,'decision':decision,'appends':appends,'bindings':list(mapped.values()),
        'unmappedExecutionJobs':unmapped,'allSelectedExecutionJobsMapped':not unmapped,
        'availabilityHoldsReleased':0,'productionBindingEnabled':False,
        'limitations':['Read-only observation at native append function 0x144f3efd0; no production tokens or reservations are created.',
            'An unmapped automatic repeat must remain unbound; cast order and independent root pointers do not establish its source entry.']}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');parser.add_argument('--mode',required=True,choices=['multi','cancel','repeat','control']);args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read(OUT/'native-bridge-validation.json'),args.mode)
    (OUT/('native-selection-'+args.mode+'-validation.json')).write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'status':'passed','mode':args.mode,'run':args.run,'mappedJobs':len(report['bindings']),
        'unmappedJobs':len(report['unmappedExecutionJobs']),'productionBindingEnabled':False},indent=2))

if __name__=='__main__':main()
