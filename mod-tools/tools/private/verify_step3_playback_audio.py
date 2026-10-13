"""Correlate representative imported LB cues with the bounded native recording."""
from pathlib import Path
import json, sys
ROOT=Path(__file__).resolve().parents[2]
WORK=ROOT/'build/effects-step3'
sys.path[:0]=[str(ROOT/'tools'),str(Path(__file__).parent)]
import ffbe_audio, ffbe_audio_assets
from ffbe_effects.acb_native import awb_files
from ffbe_effects.acb_cues import utf
from ffbe_effects.hca_transcode import codec
from match_loopback_audio import read_wave, match

def main():
    job=next(j for j in json.loads((WORK/'plans.json').read_text(encoding='utf-8')) if j['skill']==444030)
    folder=WORK/'audio-reference';folder.mkdir(exist_ok=True)
    rate,capture=read_wave(WORK/'sora-native-audio.wav')
    results=[]
    for bank in ffbe_audio.banks(job['audio']):
        if bank.get('audioManifest'):
            waves=ffbe_audio_assets.waves(bank['path'],bank['audioManifest'])
        else:
            waves=awb_files(utf(Path(bank['path']).read_bytes())[1][0]['AwbFile'])
        rec=bank['recordings'][0]
        path=folder/(rec['name']+'.wav')
        path.write_bytes(codec().decode(waves[rec['sourceWaveId']]))
        source_rate,source=read_wave(path)
        result={'cue':rec['name'],'bank':bank['name'],**match(capture,rate,source,source_rate)}
        results.append(result)
        print(json.dumps(result),flush=True)
    (WORK/'audio-playback-verification.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
