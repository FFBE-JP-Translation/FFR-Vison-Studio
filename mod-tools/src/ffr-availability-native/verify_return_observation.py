"""Verify two native Escape/end cycles in the disposable field scaffold."""
import argparse
from collections import Counter
import json
import re
from verify_combat_observation import OUT, read_json, sha, verify_artifacts


def trace(directory, *, reset=False):
    log_path=directory/'collected-ue4ss/UE4SS.log'
    log=log_path.read_text(encoding='utf8',errors='replace');lines=log.splitlines()
    assert not any(s in log for s in ('combat_driver_failed=','turn_owner_failed=','owned_binding_failed'))
    events=[]
    for number,line in enumerate(lines,1):
        match=re.search(r'\[FFRAvailability(Native|Probe)\] (\{.*\})$',line)
        if match:events.append({**json.loads(match[2]),'logLine':number})
    counts=Counter(e['event'] for e in events)
    assert counts['native_attached']==1 and counts['registered']==13
    assert not any(counts[k] for k in ('native_attach_failed','registration_failed','read_failed',
        'trace_capacity','query_capacity','native_observation_capacity','owned_query_capacity'))
    assert log.count('field_bundle_prepared')==log.count('field_lighting_prepared key=-1 ')==1
    assert log.count('native_test_entry_returned')==log.count('escape_returned')==2
    assert log.count('second_battle_requested')==log.count('return_observation_complete')==1
    if 'escape_result battle=' in log:
        assert re.findall(r'escape_result battle=(\d+) success=(\w+)',log)==[('1','true'),('2','true')]
    ends=[e for e in events if e['event']=='battle_end'];assert len(ends)==2
    escaped=[e for e in events if e['event']=='command_decide' and any(a['skillId']==400020 for a in e['actions'])]
    assert len(escaped)==2
    owners=re.findall(r'fresh_owner battle=(\d+) actor=(\d+) parameter=(\d+) name=([^\r\n]+)',log)
    assert len(owners)==2 and [int(o[0]) for o in owners]==[1,2]
    assert all(len({o[index] for o in owners})==2 for index in (1,2,3))
    settled=[]
    for number,line in enumerate(lines,1):
        match=re.search(r'settled battle=(\d+) tick=(\d+) units=(\d+)',line)
        if match:settled.append((*map(int,match.groups()),number))
    n=2 if reset else 5
    assert [(b,t,u) for b,t,u,_ in settled]==[(b,t,0) for b in (1,2) for t in range(1,n+1)]
    assert ends[0]['logLine']<settled[0][3]<settled[n-1][3]<escaped[1]['logLine']
    assert ends[1]['logLine']<settled[n][3]<settled[-1][3]
    for index,(command,end,owner) in enumerate(zip(escaped,ends,owners),1):
        assert len(command['actions'])==1 and not command['actions'][0]['item'] and not command['notConsume']
        action=command['actions'][0];unique=action['uniqueId'];actor=int(owner[1])
        assert action['targets']==[unique] and command['logLine']<end['logLine']
        guards=[e for e in events if e['event']=='native_guard' and e['skillId']==400020
            and command['logLine']<e['logLine']<end['logLine']]
        # Enforcement forwards only its explicitly managed source ID to Lua.
        # Stock Escape retains its native result without a guard callback.
        if reset:
            assert not guards
            accepted_after=command['logLine']
        else:
            assert len(guards)==1;guard=guards[0]
            assert guard['nativeAllowed'] and guard['actor']==actor and guard['job']==guard['rootJob']
            assert guard['actionCount']==guard['targetCount']==1
            accepted_after=guard['logLine']
        starts=[e for e in events if e['event'] in ('skill_begin_message','skill_begin_libra')
            and e['skillId']==400020 and accepted_after<e['logLine']<end['logLine']]
        assert len(starts)==4 and len({e['payload'] for e in starts})==1
        assert all(e['uniqueId']==unique and e['targets']==[unique] and e['owner']['actorAddress']==actor for e in starts)
    return log,events,{'nativeBattles':2,'nativeEscapes':2,'nativeEnds':2,'actorsRemovedAfterEachEnd':True,
        'settledSamples':len(settled),'fieldScaffold':{'emptyLevelBundle':True,'lighting':'native Plain stage lighting'},
        'escapeOwners':[{'battle':int(b),'actor':int(a),'parameter':int(p),'name':name} for b,a,p,name in owners],
        'logSha256':sha(log_path)}


def verify(directory,build):
    run=verify_artifacts(directory,build,return_test=True)
    assert not run.get('convertedAbilityRequested')
    assert run.get('fixtureCompleted') and run.get('fixtureTerminated') and not run.get('fixtureFailed')
    log,events,report=trace(directory)
    assert not any(e['event'].startswith('owned_') for e in events)
    assert len([e for e in events if e['event']=='command_decide'])==2
    assert len([e for e in events if e['event']=='native_guard'])==2
    report.update(status='passed',scope='two_stock_battles_in_disposable_field_scaffold',run=directory.name,
        runSha256=sha(directory/'run.json'),originalSaveFilesUnchanged=True,temporaryInstallationRemoved=True,
        limitations=['The debug arena has a supplied empty field bundle and native stage lighting; ordinary field travel is not certified.'])
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('run');args=parser.parse_args()
    assert re.fullmatch(r'\d{8}_\d{6}_\d{3}',args.run)
    report=verify(OUT/'native-battle-runs'/args.run,read_json(OUT/'native-bridge-validation.json'))
    (OUT/'native-battle-return-validation.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf8')
    print(json.dumps(report,indent=2))
