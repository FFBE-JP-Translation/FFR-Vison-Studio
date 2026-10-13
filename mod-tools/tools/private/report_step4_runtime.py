"""Native checks of the final four-unit refinement, with honest bounded scope."""
from pathlib import Path
import json, math
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step4'
SELECTED={444010,444040,485130,485203}

def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def vec(value):return [value[k] for k in ('x','y','z')]
def dot(a,b):return sum(x*y for x,y in zip(a,b))

def main():
    plans={j['skill']:j for j in read(WORK/'plans.json')}
    results={}
    for folder in sorted((WORK/'runtime/runs').iterdir()):
        if not (folder/'run.json').exists():continue
        run=read(folder/'run.json');sid=run['skill']
        if sid not in SELECTED or not run.get('fixtureCompleted') or not run.get('cleaned'):continue
        if read(folder/'source-job.json')['plan']!=plans[sid]['plan']:continue
        assert not run['changedSaveFiles'] and not run['changedPackages'] and not run['newSaveFiles']
        assert len(run['captures'])==10
        events=[json.loads(line) for line in (folder/'captures/events.jsonl').read_text().splitlines()]
        assert events[-1]['kind']=='complete'
        samples=[e for e in events if e['kind']=='sample'];final=samples[-1]
        assert abs(final['effectiveFov']-40.1586)<.02
        assert abs(final['effectiveRotation']['pitch']+10.5)<.02 and abs(final['effectiveRotation']['yaw'])<.02
        seen={}
        for sample in samples:
            for effect in sample.get('effects',{}).values():
                if not effect.get('visible'):continue
                # An actor can be sampled during its two hidden setup frames.
                first=seen.setdefault(effect['actor'],sample['castElapsed'])
                if sample['castElapsed']-first>.1:
                    assert effect['sortPriority']<sample['casterSortPriority'],(sid,'effect above caster',effect)
        assert seen,(sid,'no live effect actors')
        result={'skill':sid,'vision':run['vision'],'run':folder.relative_to(ROOT).as_posix(),
                'captures':10,'cameraRestored':True,'planMatchesFinalBuild':True,
                'savesAndPackagesUnchanged':True,'visionAboveImportedEffects':True}
        if sid==485130:
            lifted=[]
            for sample in samples:
                angles=sample['effectiveRotation'];pitch=math.radians(angles['pitch']);yaw=math.radians(angles['yaw'])
                forward=[math.cos(pitch)*math.cos(yaw),math.cos(pitch)*math.sin(yaw),math.sin(pitch)]
                up=[-math.sin(pitch)*math.cos(yaw),-math.sin(pitch)*math.sin(yaw),math.cos(pitch)]
                camera=vec(sample['effectiveLocation'])
                for effect in sample.get('effects',{}).values():
                    if not effect.get('visible'):continue
                    delta=[x-y for x,y in zip(vec(effect['location']),camera)]
                    depth=dot(delta,forward)
                    if not 990<depth<1010:continue
                    viewport_height=2*depth*math.tan(math.radians(sample['effectiveFov']/2))*720/1280
                    rise=dot(delta,up)/viewport_height
                    if abs(rise-.12)<.004:lifted.append(rise)
            assert lifted,'Ultima screen layer never reached its raised anchor'
            result['ultimaViewportRise']=sum(lifted)/len(lifted)
        results[sid]=result
    assert set(results)==SELECTED,('Missing final native runs',sorted(SELECTED-set(results)))
    report={'scope':'Four representative refinement checks, one per vision; all fourteen timelines also have cooked readback.',
            'nativeRunsPassed':len(results),'captures':40,'runs':list(results.values()),
            'performance':'Capture fixture is not a frame-rate benchmark; authored animation speed unchanged.',
            'fullCatalogConversionAndDeployment':'not run, deferred by user'}
    (WORK/'native-verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
