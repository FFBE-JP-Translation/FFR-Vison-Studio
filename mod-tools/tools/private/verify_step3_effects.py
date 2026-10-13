"""Independent cooked event/readback and checkpoint-camera comparisons for the trial."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys, json, shutil, math, subprocess, zipfile
ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).parent)]
from prepare_step3_effects import WORK, read, write
import ffrenv, ffbe_resonance as sequence, ffbe_presentation as presentation, ffbe_audio
from ffbe_effects.acb_cues import cues
with zipfile.ZipFile(ROOT/'checkpoints/ffbe-camera-step2/archives/workspace-inputs.zip') as archive:
    ACCEPTED = {j['skill']:j['plan'] for j in json.loads(archive.read('build/target-camera-step2-retry/plans.json'))}

def contains(actual, expected):
    if isinstance(expected, dict):
        if set(expected)=={'path','class'}:
            return actual=='import:'+Path(expected['path']).name
        if actual in (None, 0): actual = {}  # Cooked zero vectors/rotators may be omitted entirely.
        if not isinstance(actual, dict): return False
        fields = {k.lower():v for k,v in actual.items()}
        return all(contains(fields.get(k.lower(), 0),v) for k,v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual,list) and len(actual)==len(expected) and all(contains(a,b) for a,b in zip(actual,expected))
    if isinstance(expected, (float,int)) and not isinstance(expected,bool):
        return isinstance(actual,(float,int)) and math.isclose(actual,expected,abs_tol=1e-5)
    if isinstance(expected,str) and expected.startswith('/Game/'):
        return actual in (expected, 'soft:'+expected)
    return actual == expected

def verify(job, *, compare_checkpoint=True):
    sid=job['skill']; folder=WORK/'cooked'/str(sid); folder.mkdir(parents=True,exist_ok=True)
    mapping=folder/'Mappings.usmap'; shutil.copy2(ffrenv.USMAP,mapping)
    path=WORK/'assets'/(job['asset']+'.uasset')
    def dump(verb):
        output=folder/(verb+'.json')
        p=subprocess.run([*ffrenv.FFRDT,verb,str(path),str(output),'--usmap',str(mapping)],capture_output=True,text=True,encoding='utf-8')
        if p.returncode: raise RuntimeError(p.stdout+p.stderr)
        return read(output)
    doc=dump('tojson'); functions={int(k.split(':')[0]):v for k,v in dump('seqdump').items()}
    observed=[]
    for export in doc['Exports']:
        for prop in export.get('Data',[]):
            if prop['Name']!='EventChannel': continue
            for tick,key in zip(sequence.child(prop['Value'],'KeyTimes'),sequence.child(prop['Value'],'KeyValues')):
                while not isinstance(tick,(int,float)): tick=tick[0] if isinstance(tick,list) else tick['Value']
                observed.append({'time':tick,'set':functions[sequence.child(key['Value'],'Ptrs','Function')]})
    expected=sorted(job['plan']['events'],key=lambda e:e['time']); observed.sort(key=lambda e:e['time'])
    assert len(expected)==len(observed),(sid,len(expected),len(observed))
    for actual,wanted in zip(observed,expected):
        if not contains(actual,wanted):
            write(folder/'mismatch.json',{'actual':actual,'expected':wanted})
            raise AssertionError((sid,wanted['time'],wanted['set']['EventType'],'see mismatch.json'))
    for event in expected:
        data=event['set'].get('SsActor_SsData')
        if not data: continue
        reference=data['ssPlayerAsset']; package=reference['path']; name=Path(package).name
        imported=[i for i in doc['Imports'] if i['ObjectName']==name and i['ClassName']==reference['class']]
        assert len(imported)==1 and imported[0]['OuterIndex']<0,(sid,'sprite import class')
        assert doc['Imports'][-imported[0]['OuterIndex']-1]['ObjectName']==package,(sid,'sprite import package')
    for bank in ffbe_audio.banks(job.get('audio')):
        acb=WORK/(bank['name']+'.acb')
        names={c['name'] for c in cues(str(acb)).values()}
        raw=acb.read_bytes(); cooked=WORK/'assets'/(bank['asset']+'.uexp')
        assert raw in cooked.read_bytes(),(sid,'rebuilt audio payload missing from cooked bank')
        for event in observed:
            values=event['set']
            if values.get('Sound_PlayHitSound_CueSheetName')==bank['name']:
                assert values['Sound_PlayHitSound_playLabel'] in names,(sid,'missing cooked cue')
    available_banks = {b['name'] for b in ffbe_audio.banks(job.get('audio'))}
    for event in observed:
        bank_name = event['set'].get('Sound_PlayHitSound_CueSheetName', '')
        if bank_name.startswith('FFBE_'):
            assert bank_name in available_banks, (sid, 'sound event bank absent from dependency closure', bank_name)
    for fx in job.get('presentation',{}).get('visuals',[]):
        spec=read(ROOT/fx['spec']/'spec.json')
        base=WORK/'assets/FFRS/Content/Chara/effect'/fx['name']
        assert (base/(fx['name']+'.uasset')).is_file()
        for index,page in enumerate(spec.get('cellmaps',[spec])):
            suffix='_'+str(index) if index else ''
            assert (base/(fx['name']+'_tex'+suffix+'.uasset')).is_file(),(sid,'missing atlas page')
    base=next(j['plan'] for j in read(WORK/'camera-plans.json') if j['skill']==sid)
    cameras=lambda plan:[e for e in plan['events'] if e['set']['EventType']=='NativeParticipantCamera']
    assert cameras(job['plan'])==cameras(base),(sid,'camera changed during effect import')
    action=presentation.action_start(base)
    assert action==presentation.action_start(job['plan']),(sid,'action origin changed')
    hits=lambda plan:[e for e in plan['events'] if e['set']['EventType']=='OtherReaction']
    assert hits(base)==hits(job['plan']),(sid,'effects moved mechanical hit timing')
    core=lambda plan:[e for e in plan['events'] if e['set']['EventType'] in ('NativeParticipantCamera','OtherReaction')]
    if compare_checkpoint and sid != 444010:
        assert core(base)==core(ACCEPTED[sid]),(sid,'camera or hits differ from sealed accepted checkpoint')
    cast=[e for e in base['events'] if e['set']['EventType']=='SoundPlayHitSound']
    assert len(cast)==1 and cast[0] in job['plan']['events'],(sid,'cast cue changed')
    for sound in job.get('effectTrial',{}).get('sounds',[]):
        assert {'time':action+sound['frame']*400,'set':{'EventType':'SoundPlayHitSound',
                'Sound_PlayHitSound_CueSheetName':sound['bank'],'Sound_PlayHitSound_playLabel':sound['cueName']}} in expected
    if sid==444030:
        routed=[s for s in job['effectTrial']['sounds'] if s['cueId']==95]
        assert len(routed)==12 and all(s['sourceBank']=='System' and s['sourceCueName']=='se_event_puppet_bethink' for s in routed)
    indexed=[e for e in expected if 'NativeActorRootSnapshot_TargetIndex' in e['set']]
    if indexed: assert {e['set']['NativeActorRootSnapshot_TargetIndex'] for e in indexed}==set(range(16))
    if sid==444010:
        assert len(hits(base))==30
        assert [e['time']-action for e in hits(base)]==[400*(42+4*i) for i in range(30)]
        assert not any(e['set']['EventType'] in ('NativeGroundApproach','UnitMoveToTarget') for e in expected)
    reset=max(e['time'] for e in expected if e['set']['EventType']=='CameraSetDefault')
    destroys=[e['time'] for e in expected if e['set']['EventType']=='SsActorDestroyToSsID']
    assert not destroys or reset>max(destroys),(sid,'camera restores before effects finish')
    return {'skill':sid,'events':len(observed),'hits':len(hits(base)), 'castTick':cast[0]['time'],
            'actionTick':action,'restoreTick':reset,'cameraAndHitClocksUnchanged':True,
            'matchesAcceptedCheckpointCameraAndHits':(True if sid!=444010 else 'new Esther source timing') if compare_checkpoint else None,
            'effectInstances':len(destroys),'indexedTargetInstances':len(indexed),
            'soundEvents':sum(e['set']['EventType']=='SoundPlayHitSound' for e in observed),
            'allCookedParametersMatch':True}

def main():
    jobs=read(WORK/'plans.json'); assert len(jobs)==14
    with ThreadPoolExecutor(max_workers=3) as pool: result=list(pool.map(verify,jobs))
    write(WORK/'cooked-verification.json',result)
    print('All 14 cooked commands verified, including unchanged cast/camera/hit clocks and effect cleanup.')

if __name__=='__main__': main()
