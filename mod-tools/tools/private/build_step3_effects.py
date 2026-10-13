"""Build the focused effect trial on the accepted cast -> pause -> pan -> zoom camera."""
from copy import deepcopy
from pathlib import Path
import os, sys, json, shutil
ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT/'build/effects-step3'
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).parent)]
from prepare_step3_effects import SELECTED, read, write

def roster():
    units = read(ROOT/'mods/EstherTsukiko/units.json')
    # Rebuilds always start from the immutable accepted roster.
    checkpoint = ROOT/'checkpoints/ffbe-camera-step2/source/mods/EstherTsukiko/units.json'
    if checkpoint.exists(): units = read(checkpoint)
    keep = {13500:['485005'], 13501:['485130','485115','485133'],
            13502:['485203','485220','485204'], 13503:['485301','485305','485300']}
    for u in units:
        u['skills'] = {k:v for k,v in u['skills'].items() if k in keep[u['id']]}
        u.update(presentationStep='target_camera', testingMPCost=1, fullKit=False, cameraTestMissing=False)
        u['convertedPassives'] = {}
        u['awakening'] = [[['ActiveSkill', int(k)] for k in u['skills']], [], [], []]
        u['synchro'] = [[] for _ in u['synchro']]
        for s in u['skills'].values(): s.setdefault('set', {})['Cost'] = 1
        u['lb_custom'].setdefault('set', {})['Cost'] = 1
    u = units[0]
    assert u['id'] == 13500
    u.update(key='esther', jp='Esther_FFBE_13500', en='Esther', desc='Original Esther. Raikiri animation test.',
             ffbe={'dir':'units/ffbe/esther/sprites/401006807', 'id':'401006807', 'source':'GL', 'base':'401006805'})
    u['command'].update(en='Esther', desc='Raegen Blast testing command.')
    u['master'].update(en='Esther', desc='Original Esther.')
    for key in ('ffbeMap','ffbeKit','ffbeLibrary','step1Passives','step1AutomaticActions','nativeEdits',
                'conversionReview','conversionArchive','nativeImports','effectPolicy','nativeLibraryVersion'):
        u.pop(key, None)
    native = read(ROOT/'data/ffbe/native_kits/401006807.json')['profiles'][SELECTED['401006807'][0]]
    lb = {k:deepcopy(v) for k,v in u['lb_custom'].items() if not k.startswith('conversion') and k not in ('effectPolicy','nativeEdits')}
    lb.update(mechanics='custom', jp='Esther_Raikiri_444010', en='Raikiri', descAuto=False,
              desc='Deals 30 hits of physical Thunder damage to all enemies. Costs 1 MP for testing.',
              ffbe_lb_id='401006807', conversionSource=native['snapshot'],
              ffbe={'id':401006807, 'kind':'LB', 'source':SELECTED['401006807'][0], 'name':'Raikiri'})
    lb['set'] = {**native['set'], 'element':'Thunder', 'DamageType':'Physic', 'damageCalcType':'Physic',
                 'TargetType':'Group', 'Cost':1, 'effectBundleList':[], 'SkillIcon.TagName':'UI.Skill.Action.Icon.Thunder'}
    # The generic LB resolver holds mixed damage/buff roots. This user-requested
    # damage-only adaptation takes its 30 frames from the reviewed source profile.
    weights = native['set']['hitDamageRatioList'][:30]
    percents = [round(w*100) for w in weights]
    assert sum(percents)==100 and len(native['timeline']['hitFrames'])==30
    WORK.mkdir(parents=True,exist_ok=True)
    write(WORK/'esther-raikiri-source.json', {'schema':2,'unitId':'401006807','fps':60,
        'lbId':'401006807','availableLbIds':['401006807'],'name':'Raikiri',
        'hitFrames':native['timeline']['hitFrames'],'hitPercents':percents,'moveType':4,
        'elements':['Thunder'],'damageComponent':0,
        'components':[{'type':1,'target':1,'range':2,'multiplier':36}], 'sounds':[],
        'adaptation':'User-selected physical Thunder AoE damage only; source hit timing and weights preserved',
        'sourceKey':SELECTED['401006807'][0]})
    lb['ffbe_lb'] = (WORK/'esther-raikiri-source.json').relative_to(ROOT).as_posix()
    u['lb_custom'] = lb
    return units

def main():
    WORK.mkdir(parents=True, exist_ok=True)
    units = roster(); write(WORK/'units.json', units)
    previous = read(ROOT/'checkpoints/ffbe-camera-step2/source/mods/EstherTsukiko/units.json')
    selected_ids = {int(k) for u in units for k in u['skills']}
    write(WORK/'focused-selection.json', {
        'retiredSkills':sorted({int(k) for u in previous for k in u['skills']}-selected_ids),
        'retainCheckpointAssets':'checkpoints/ffbe-camera-step2/archives/workspace-inputs.zip'})
    if not (WORK/'units-before.json').exists(): shutil.copy2(ROOT/'mods/EstherTsukiko/units.json', WORK/'units-before.json')
    if not (WORK/'installation.json').exists():
        shutil.copy2(ROOT/'build/target-camera-step2-retry/installation.json', WORK/'installation.json')
    os.environ['FFR_UNIT_SPEC'] = str(WORK/'units.json')
    os.environ['FFR_PRESENTATION_DIR'] = str(WORK/'presentation')
    os.environ['FFR_MOD_STEM'] = 'zzzzzzz_FFBE_CastCamera_9_P'
    os.environ['FFR_EFFECT_WORKERS'] = '4'
    import make_vision_mod as b
    import ffbe_presentation as presentation
    import ffbe_audio
    b.BUILD = str(WORK); b.OUT = str(WORK/'assets')
    # The general builder recreates its output. Assert its precise sandbox before it runs.
    assert Path(b.OUT).resolve() == (ROOT/'build/effects-step3/assets').resolve()
    camera_plans, plans = [], []
    def decorate(original):
        def prepare(u, s, sid, tbl, clones, jobs):
            original(u, s, sid, tbl, clones, jobs)
            job = jobs[-1]
            camera_plans.append({'vision':u['id'], 'skill':sid, 'asset':job['asset'], 'plan':deepcopy(job['plan'])})
            key = (s.get('conversionSource') or {}).get('root')
            if key in SELECTED.get(u['ffbe']['id'], []):
                entry = deepcopy(read(WORK/'presentation'/(u['ffbe']['id']+'.json'))['moves'][key])
                assert entry['sourceSha256'] == presentation.source_fingerprint(s['conversionSource'])
                assert entry['visuals'], key
                # Common casting sound is already present on the accepted camera plan.
                entry.pop('cast', None); entry.pop('opening', None)
                entry.update(_hostVisionUnitId=u['id'], _hostResonance=bool(s.get('resonance')))
                profile = entry['reconstructionProfile']
                profile['allTargetEffects'] = True
                for field in ('attackDirector','resonanceCamera','resonanceMovement'): profile.pop(field, None)
                # Existing source-sized flash layers use the same projection as their owning screen art.
                for fx in entry['visuals']:
                    if fx.get('placement', {}).get('mode') == 'camera_plane':
                        fx['placement']['fit'] = profile['screenPlacement']['fit']
                if entry.get('backgroundDetection', {}).get('kind') == 'replacement_background':
                    # The native empty backdrop prevents terrain occluding authored rear artwork.
                    profile['screenPlacement']['backdrop'] = 'native_subspace'
                    profile['screenPlacement']['backdropTiming'] = 'action'
                audio, sounds = presentation.prepare_audio(u, s, entry, tbl, job['plan'])
                job['plan'] = presentation.apply(job['plan'], entry, sounds, sid)
                job['audio'], _ = ffbe_audio.combine(job.get('audio'), [], audio, [])
                job['presentation'] = entry
                for row in tbl('Battle/Sequencer/DT_BtlHitEffectData')['add']:
                    if row['set'].get('ID') == sid:
                        # Keep the mechanical command's damage/recovery shake
                        # choice while replacing only its donor effect artwork.
                        settings = b.ffbe_resonance.reaction_settings(sid)
                        settings.pop('PlayShakeID', None)
                        row['set'].update(settings)
                job['effectTrial'] = {'source':key, 'visuals':len(entry['visuals']), 'sounds':sounds}
            plans.append({'vision':u['id'], 'skill':sid, **deepcopy(job)})
            write(WORK/'camera-plans.json', camera_plans); write(WORK/'plans.json', plans)
        return prepare
    for name in ('prepare_ffbe_resonance','prepare_converted_command','prepare_native_camera_command'):
        setattr(b, name, decorate(getattr(b, name)))
    sys.argv = [sys.argv[0], '--no-install']
    b.main()
    import stage_cast_camera as stage
    stage.WORK = WORK; stage.ASSETS = Path(b.OUT)
    stage.stage()
    runtime = WORK/'runtime'; runtime.mkdir(exist_ok=True)
    for name in ('run.ps1','main.lua','stage.lua'):
        shutil.copy2(ROOT/'build/target-camera-step2-retry/runtime'/name, runtime/name)
    from step3_runtime import configure
    configure(runtime)
    print('Focused candidate built and staged; installation requires verified cooked/mounted readback.', flush=True)

if __name__ == '__main__': main()
