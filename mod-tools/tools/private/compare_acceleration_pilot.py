"""Compare portable payloads, not ZIP compression/container layout."""
from pathlib import Path
import hashlib, json, zipfile
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/conversion-optimization-20260919'

def main():
    report=json.loads((WORK/'pilot/delivery/catalog-conversion.json').read_bytes())
    assert not report['errors'] and report['summary']['processedForms']==4
    comparisons=[]
    for result in report['results']:
        form=result['form']
        for extension in ('ffr','ffr-effects'):
            name=form+'.'+extension
            before=ROOT/'build/ffbe-all-animations/delivery'/name
            after=WORK/'pilot/delivery'/name
            with zipfile.ZipFile(before) as a,zipfile.ZipFile(after) as b:
                assert set(a.namelist())==set(b.namelist()),name
                for filename in a.namelist():
                    with a.open(filename) as left,b.open(filename) as right:
                        assert hashlib.file_digest(left,'sha256').digest()==hashlib.file_digest(right,'sha256').digest(),(name,filename)
                comparisons.append({'archive':name,'identicalExtractedFiles':len(a.namelist()),
                                    'oldBytes':before.stat().st_size,'newBytes':after.stat().st_size})
    out={'comparisons':comparisons,'runtime':report.get('runtime'),
         'result':'Every texture, animation, sound, report and manifest is byte-identical after extraction'}
    (WORK/'pilot-comparison.json').write_text(json.dumps(out,indent=2))
    print(json.dumps(out,indent=2))

if __name__=='__main__':main()
