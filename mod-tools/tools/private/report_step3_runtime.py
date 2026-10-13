"""Summarize successful native effect checks against the final command plans."""
from pathlib import Path
import json
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step3'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))

def main():
    plans={j['skill']:j for j in read(WORK/'plans.json') if j.get('effectTrial')}
    assert len(plans)==10
    results={}
    for folder in sorted((WORK/'runtime/runs').iterdir()):
        path=folder/'run.json'
        if not path.exists():continue
        run=read(path);sid=run['skill']
        if sid not in plans or not run.get('fixtureCompleted') or not run.get('cleaned'):continue
        source=read(folder/'source-job.json')
        if source['plan']!=plans[sid]['plan']:continue
        assert not run['changedSaveFiles'] and not run['changedPackages'] and not run['newSaveFiles']
        assert len(run['captures'])==10
        events=[json.loads(line) for line in (folder/'captures/events.jsonl').read_text().splitlines()]
        assert events[-1]['kind']=='complete'
        samples=[e for e in events if e['kind']=='sample']
        final=samples[-1]
        assert abs(final['effectiveFov']-40.1586)<.02
        assert abs(final['effectiveRotation']['pitch']+10.5)<.02
        assert abs(final['effectiveRotation']['yaw'])<.02
        peak=max(sum(bool(v.get('visible')) for v in s.get('effects',{}).values()) for s in samples)
        assert peak>0,(sid,'no visible effect actors')
        results[sid]={'skill':sid,'vision':run['vision'],'run':folder.relative_to(ROOT).as_posix(),
                      'captures':10,'cameraRestored':True,'peakVisibleEffectActors':peak,
                      'planMatchesFinalBuild':True,'savesAndPackagesUnchanged':True,
                      'seconds':run['elapsedSeconds']}
    assert set(results)==set(plans),('missing final native checks',sorted(set(plans)-set(results)))
    result={'selectedMoves':10,'nativeRunsPassed':len(results),'captures':100,
            'audibleParity':'unverified; bounded offscreen recording was inconclusive',
            'runs':list(results.values())}
    (WORK/'native-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
