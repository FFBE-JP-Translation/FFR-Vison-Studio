import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[1]/'devui')]
import ffbe_presentation as p
import ffbe_audio
from ffbe_effects import catalog, to_ss6


class Presentation(unittest.TestCase):
    def test_reference_can_keep_source_colors_without_changing_other_fields(self):
        plan = {'duration': 50000, 'events': [
            {'time': 11999, 'set': {'EventType': 'PostSetColorGradingGlobalParameter'}},
            {'time': 12000, 'set': {'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'LB1'}},
            {'time': 45000, 'set': {'EventType': 'PostSetDefaultColorGrading'}}]}
        ordinary = p.apply(plan, {'visuals': []}, [], 7)
        self.assertEqual(plan, ordinary)
        result = p.apply(plan, {'visuals': [], 'reconstructionProfile': {'preserveSourceColor': True}}, [], 7)
        self.assertEqual([e for e in plan['events'] if e['time'] != 11999], result['events'])
        self.assertEqual(3, len(plan['events']))

    def test_action_art_replaces_borrowed_hit_flashes_at_every_source_anchor(self):
        self.assertFalse(p.has_target_visuals(None))
        self.assertFalse(p.has_target_visuals({'visuals': []}))
        self.assertFalse(p.has_target_visuals({'visuals': [{'anchor': 'caster', 'phase': 'cast'}]}))
        for anchor in ('caster', 'each_target', 'target_group', 'screen'):
            self.assertTrue(p.has_target_visuals({'visuals': [{'anchor': anchor}]}))

    def test_screen_reference_plane_requires_explicit_placement_and_stays_fixed(self):
        plan = {'duration': 50000, 'events': [{'time': 12000, 'set': {
            'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'LB1'}}]}
        fx = {'name':'screen', 'asset':'/Game/screen', 'anchor':'screen',
              'layer':2, 'frame':0, 'frames':90}
        with self.assertRaisesRegex(ValueError, 'placement profile'):
            p.apply(plan, {'visuals':[fx]}, [], 7)
        placement = {'mode':'frozen_caster_plane', 'sourceOffset':[-96,84]}
        result = p.apply(plan, {'visuals':[{**fx,'placement':placement}]}, [], 7)
        spawn = next(e for e in result['events'] if e['set']['EventType']=='SsActorSpawnSpriteStudioActor')
        fields=spawn['set']['SsActor_SsData']
        self.assertTrue(fields['bDisableFollowing'])
        self.assertFalse(fields['bSpawnRelativeTarget'])
        self.assertEqual('root', fields['PartName'])
        self.assertFalse(any(e['set']['EventType']=='SsActorMoveToTargetToSsID' for e in result['events']))
        with self.assertRaisesRegex(ValueError, 'finite'):
            p.validate_screen_placement({**placement,'sourceOffset':[0,float('nan')]})

    def test_native_subspace_is_opt_in_and_restores_after_all_source_layers(self):
        plan = {'duration': 50000, 'events': [
            {'time': 12000, 'set': {'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'LB1'}},
            {'time': 28000, 'set': {'EventType': 'OtherReaction'}},
            {'time': 45000, 'set': {'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'idle'}}]}
        placement = {'mode': 'frozen_caster_plane', 'sourceOffset': [-96, 84]}
        entry = {'visuals': [
            {'name': 'screen', 'asset': '/Game/screen', 'anchor': 'screen', 'placement': placement,
             'layer': 2, 'frame': 0, 'frames': 90},
            {'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster',
             'layer': 1, 'frame': 50, 'frames': 120}]}
        baseline = p.apply(plan, entry, [], 7)
        self.assertFalse(any(e['set']['EventType'].startswith(('BG', 'OtherChangeSubSpace')) for e in baseline['events']))
        candidate = copy.deepcopy(entry)
        candidate['reconstructionProfile'] = {'screenPlacement': {**placement, 'backdrop': 'native_subspace'}}
        before = copy.deepcopy(candidate)
        result = p.apply(plan, candidate, [], 7)
        self.assertEqual(candidate, before)
        env = [e for e in result['events'] if e['set']['EventType'].startswith(('BG', 'OtherChangeSubSpace'))]
        self.assertEqual([e['time'] for e in env[:6]], [0, 3200, 4000, 8000, 8001, 8002])
        self.assertEqual([e['set']['EventType'] for e in env], [
            'OtherChangeSubSpaceInitialize', 'OtherChangeSubSpace', 'BGChange',
            'OtherChangeSubSpaceGround', 'OtherChangeSubSpaceColor', 'OtherChangeSubSpaceEmissive', 'BGRevert'])
        self.assertEqual(env[2]['set']['BG_Change_BackgroundLevel'], p.NATIVE_SUBSPACE)
        ground = env[3]['set']
        for field in ('IsVisibility', 'IsParticleVisibility', 'IsFogVisibility'):
            self.assertFalse(ground['Other_ChangeSubSpaceGround_' + field])
        self.assertEqual(env[4]['set']['Other_ChangeSubSpaceColor_Color'], {'R': 0., 'G': 0., 'B': 0., 'A': 1.})
        self.assertEqual(env[5]['set']['Other_ChangeSubSpaceEmissive_Emissive'], 0.)
        destroyed = max(e['time'] for e in result['events'] if e['set']['EventType'] == 'SsActorDestroyToSsID')
        self.assertEqual(env[-1]['time'], destroyed + 400)
        self.assertLess(env[-1]['time'], result['duration'])
        self.assertEqual([e for e in result['events'] if e not in env], baseline['events'])
        self.assertEqual(28000, next(e['time'] for e in result['events'] if e['set']['EventType'] == 'OtherReaction'))

    def test_native_subspace_rejects_missing_screen_conflicts_and_extends_short_preroll(self):
        placement = {'mode': 'frozen_caster_plane', 'sourceOffset': [0, 0], 'backdrop': 'native_subspace'}
        with self.assertRaisesRegex(ValueError, 'backdrop'):
            p.validate_screen_placement({**placement, 'backdrop': 'invented'})
        plan = {'duration': 50000, 'events': [
            {'time': 12000, 'set': {'EventType': 'UnitPlayAnimByName', 'Unit_PlayAnimByName_AnimationName': 'LB1'}}]}
        entry = {'visuals': [], 'reconstructionProfile': {'screenPlacement': placement}}
        with self.assertRaisesRegex(ValueError, 'requires screen'):
            p.apply(plan, entry, [], 7)
        entry['visuals'] = [{'name': 'screen', 'asset': '/Game/screen', 'anchor': 'screen',
                            'placement': placement, 'layer': 2, 'frame': 0, 'frames': 90}]
        with self.assertRaisesRegex(ValueError, 'existing background'):
            p.apply({**plan, 'events': plan['events'] + [{'time': 1, 'set': {'EventType': 'BGChange'}}]}, entry, [], 7)
        early = copy.deepcopy(plan)
        early['events'][0]['time'] = 8000
        early['events'].append({'time': 12000, 'set': {'EventType': 'OtherReaction'}})
        original = copy.deepcopy(early)
        result = p.apply(early, entry, [{'frame': 10, 'bank': 'test', 'cueName': 'hit', 'durationMs': 100}], 7)
        self.assertEqual(early, original)
        start = p.action_start(result)
        self.assertEqual(start, 9200)
        self.assertEqual(next(e['time'] for e in result['events'] if e['set']['EventType'] == 'OtherReaction'), start + 4000)
        self.assertEqual(next(e['time'] for e in result['events'] if e['set']['EventType'] == 'SoundPlayHitSound'), start + 4000)
        self.assertGreater(next(e['time'] for e in result['events'] if e['set']['EventType'] == 'SsActorSpawnSpriteStudioActor'), 8002)

    def test_caster_target_placement_reuses_completed_vision_approach(self):
        import ffbe_resonance
        plan = ffbe_resonance.schedule(2., 1, 7, {'moveType': 1}, movement={'target_offset': [12., 34., 56.]})
        entry = {'visuals': [{'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster',
                             'layer': 1, 'frame': 0, 'frames': 60}],
                 'reconstructionProfile': {'casterPlacement': 'approach_target'}}
        before = copy.deepcopy(plan)
        result = p.apply(plan, entry, [], 7)
        self.assertEqual(plan, before)
        move = next(e for e in result['events'] if e['set']['EventType'] == 'UnitMoveToTarget')
        self.assertTrue(move['set']['Unit_MoveToTarget_IsDisableOffset'])
        spawn = next(e for e in result['events'] if e['set']['EventType'] == 'SsActorSpawnSpriteStudioActor')
        self.assertTrue(spawn['set']['SsActor_SsData']['bDisableFollowing'])
        attached = next(e for e in result['events'] if e['set']['EventType'] == 'SsActorMoveToTargetToSsID')
        self.assertEqual(attached['time'], spawn['time'] + 2)
        fields = attached['set']
        self.assertEqual(fields['SsActor_MoveToTarget_partName'], move['set']['Unit_MoveToTarget_PartName'])
        self.assertEqual(fields['SsActor_MoveToTarget_plusOffset'], {'x': 4., 'y': 34., 'z': 56.})
        self.assertEqual(fields['SsActor_MoveToTarget_targetPointID'], -1)
        self.assertEqual(fields['SsActor_MoveToTarget_frame'], 0)
        self.assertFalse(fields['SsActor_MoveToTarget_RelativeActionUnit'])
        self.assertEqual(fields['SsActor_MoveToTarget_Height'], 0.)
        self.assertEqual(fields['SsActor_MoveToTarget_Length'], 0.)
        self.assertEqual(p.action_start(result), p.action_start(plan))
        ordinary = p.apply(plan, {'visuals': entry['visuals']}, [], 7)
        self.assertFalse(any(e['set']['EventType'] == 'SsActorMoveToTargetToSsID' for e in ordinary['events']))
        self.assertFalse(next(e for e in ordinary['events'] if e['set']['EventType'] == 'UnitMoveToTarget')['set']['Unit_MoveToTarget_IsDisableOffset'])

    def test_caster_target_placement_rejects_missing_multiple_or_unfinished_approach(self):
        import ffbe_resonance
        entry = {'visuals': [{'name': 'caster', 'asset': '/Game/caster', 'anchor': 'caster',
                             'layer': 1, 'frame': 0, 'frames': 60}],
                 'reconstructionProfile': {'casterPlacement': 'approach_target'}}
        stationary = ffbe_resonance.schedule(2., 1, 7)
        with self.assertRaisesRegex(ValueError, 'one vision approach'):
            p.apply(stationary, entry, [], 7)
        moving = ffbe_resonance.schedule(2., 1, 7, {'moveType': 1})
        move = next(e for e in moving['events'] if e['set']['EventType'] == 'UnitMoveToTarget')
        with self.assertRaisesRegex(ValueError, 'one vision approach'):
            p.apply({**moving, 'events': moving['events'] + [move]}, entry, [], 7)
        move['time'] = p.action_start(moving)
        with self.assertRaisesRegex(ValueError, 'must finish'):
            p.apply(moving, entry, [], 7)

    def test_source_cast_motion_overrides_damage_derived_import_default(self):
        profile = {'set': {'DamageType': 'Physic'}}
        skill = {'motion': 'attack_A'}
        source = {'sourceKey': 'GL/ability/1', 'provenance': [
            {'source': 'GL/ability/2', 'catalog': {'motion': '1'}},
            {'source': 'GL/ability/1', 'catalog': {'motion': '2'}}]}
        self.assertEqual('magic_attack', p.command_motion(skill, profile, source))
        self.assertEqual('attack_A', p.command_motion(skill, profile, None))
        self.assertEqual('attack_A', p.command_motion({**skill, 'presentation_motion': 'attack_A'}, profile, source))

    def test_native_preparation_clock_is_separate_from_action_and_impact(self):
        from ability_converter import commands
        profile = {'supported': True, 'timeline': {'moveType': 4, 'hitFrames': [70, 76]},
                   'set': {'DamageType': 'Physic'}}
        plan = commands.schedule(profile, 7, 16/60, 'magic_attack', cast_frames=10, cast_motion='command')
        cast_start = p.phase_start(plan, 'cast')
        main = p.action_start(plan)
        self.assertEqual(10*400, main-cast_start)
        self.assertFalse(any(e['set']['EventType'] == 'UnitMoveToTarget' for e in plan['events']))
        entry = {'audioBank': 'prepared.json', 'cast': {'frame': 1, 'bank': 'SE'}, 'visuals': [
            {'name': 'cast', 'asset': '/Game/cast', 'anchor': 'caster', 'phase': 'cast',
             'layer': 1, 'frame': 1, 'frames': 20},
            {'name': 'hit', 'asset': '/Game/hit', 'anchor': 'each_target',
             'layer': 1, 'frame': 68, 'frames': 30}]}
        with patch.object(ffbe_audio, 'prepare_command', return_value=(None, [])) as prep:
            p.prepare_audio({}, {}, entry, object(), plan)
        self.assertEqual(-9, prep.call_args.args[2]['cast']['frame'])
        self.assertEqual(1, entry['cast']['frame'])
        result = p.apply(plan, entry, [], 7)
        spawn = [e['time'] for e in result['events'] if e['set']['EventType'] == 'SsActorSpawnSpriteStudioActor']
        self.assertEqual([cast_start+400-800, main+68*400-800], spawn)
        hits = [e['time'] for e in result['events'] if e['set']['EventType'] == 'OtherReaction']
        self.assertEqual([main+70*400, main+76*400], hits)

    def test_native_advancing_ability_prepares_then_approaches(self):
        from ability_converter import commands
        profile = {'supported': True, 'timeline': {'moveType': 1, 'hitFrames': [70]},
                   'set': {'DamageType': 'Physic'}}
        plan = commands.schedule(profile, 7, 1, 'attack_A', cast_frames=10, cast_motion='command')
        cast_start = p.phase_start(plan, 'cast')
        approach = next(e for e in plan['events'] if e['set']['EventType'] == 'UnitMoveToTarget')
        self.assertEqual(cast_start+10*400+1, approach['time'])
        self.assertGreater(p.action_start(plan), approach['time']+approach['set']['Unit_MoveToTarget_Frame']*400)
        profile['timeline']['moveType'] = 4
        stationary = commands.schedule(profile, 7, 1, 'attack_A', cast_frames=10, cast_motion='command')
        self.assertFalse(any(e['set']['EventType'] == 'UnitMoveToTarget' for e in stationary['events']))

    def test_source_component_separator_and_rotation(self):
        rows = {'F_ABILITY_MST':[{'ability_id':'1','effect_frames':'40:2:1:1:0@60:3:2:3:0'}],
                'F_EFFECT_GROUP_MST':[{'qIy86WvJ':'2','effect_frames':'0:4:99999999:1:2:2:0:0'},
                                      {'qIy86WvJ':'3','effect_frames':''}],
                'F_EFFECT_MST':[{'h5t4yBm2':'4','2HjxCGo6':'slash.bmb:0:0:45'}]}
        with patch.object(catalog,'table',side_effect=rows.__getitem__):
            result=catalog.skill_effects('ability',1)
        self.assertEqual([0,1],[g['component'] for g in result['groups']])
        self.assertEqual([['1','1','0'],['2','3','0']],[g['flags'] for g in result['groups']])
        self.assertEqual('slash.bmb',result['groups'][0]['group']['effects'][0]['file'])
        self.assertEqual([0,0,45],result['groups'][0]['group']['effects'][0]['rotation'])

    def test_command_audio_has_no_lb_opening(self):
        with patch.object(ffbe_audio,'_prepare_bank',return_value=('bank',[])) as prep, \
             patch.object(ffbe_audio,'prepare',side_effect=AssertionError('LB wrapper called')):
            self.assertEqual(('bank',[]),ffbe_audio.prepare_command({}, {'audio':'native'}, {}, object()))
            prep.assert_called_once()

    def test_exact_sound_clock_finite_effects_and_late_cleanup(self):
        original={'duration':60000,'events':[
            {'time':12000,'set':{'EventType':'UnitPlayAnimByName','Unit_PlayAnimByName_AnimationName':'attack_A'}},
            {'time':40000,'set':{'EventType':'OtherReaction','Other_Reaction_Id':7}},
            {'time':40999,'set':{'EventType':'CameraSetDefault'}},
            {'time':41000,'set':{'EventType':'UnitPlayAnimByName','Unit_PlayAnimByName_AnimationName':'step_back'}},
            {'time':42000,'set':{'EventType':'VisionStartFade','Vision_SpawnFade_bSpawnFade':False}}]}
        entry={'visuals':[{'name':'test','asset':'/Game/Chara/effect/test/test','anchor':'each_target',
                           'layer':1,'frame':40,'frames':130}]}
        before=copy.deepcopy(original)
        result=p.apply(original,entry,[{'frame':68,'cueName':'hit','bank':'SE','durationMs':900}],7)
        self.assertEqual(before,original)
        reaction=next(e for e in result['events'] if e['set']['EventType']=='OtherReaction')
        self.assertEqual(40000,reaction['time'])
        sound=next(e for e in result['events'] if e['set']['EventType']=='SoundPlayHitSound')
        self.assertEqual(12000+68*400,sound['time'])
        spawn=next(e for e in result['events'] if e['set']['EventType']=='SsActorSpawnSpriteStudioActor')
        destroy=next(e for e in result['events'] if e['set']['EventType']=='SsActorDestroyToSsID')
        self.assertTrue(spawn['set']['SsActor_SsData']['bSpawnRelativeTarget'])
        self.assertEqual(0,spawn['set']['SsActor_SsData']['addLocation']['y'])
        self.assertEqual(spawn['time']+130*400,destroy['time'])
        play=next(e for e in result['events'] if e['set']['EventType']=='SsActorPlayAnimToSsID')
        self.assertEqual(1,play['set']['SsActor_PlayAnim_LoopCount'])
        back=next(e for e in result['events'] if e['set'].get('Unit_PlayAnimByName_AnimationName')=='step_back')
        self.assertGreater(back['time'],destroy['time'])
        restore=next(e for e in result['events'] if e['set']['EventType']=='CameraSetDefault')
        self.assertGreater(restore['time'],destroy['time'])
        self.assertEqual(1,back['time']-restore['time'])
        self.assertLess(max(e['time'] for e in result['events']),result['duration'])

    def test_manifest_is_form_scoped_and_source_locked(self):
        snapshot={'root':'GL/ability/1','records':[{'source':'GL','kind':'ability','id':'1','data':{'name':'one'}}]}
        with tempfile.TemporaryDirectory() as d, patch.object(p,'BUNDLES',Path(d)):
            Path(d,'100.json').write_text(json.dumps({'schema':p.VERSION,'moves':{
                snapshot['root']:{'sourceSha256':p.source_fingerprint(snapshot),'visuals':[]}}}))
            unit={'id':13500,'ffbe':{'id':100}}; skill={'conversionSource':snapshot}
            self.assertIsNotNone(p.lookup(unit,skill))
            self.assertIsNone(p.lookup({'ffbe':{'id':101}},skill))
            self.assertIsNone(p.lookup(unit,{**skill,'ffbe_presentation':False}))
            snapshot['records'][0]['data']['name']='changed'
            with self.assertRaisesRegex(ValueError,'source changed'):p.lookup(unit,skill)

    def test_resized_atlas_preserves_world_size(self):
        from PIL import Image
        doc={'fps':60,'pixelsPerUnit':1,'textures':['t'], 'frames':[[{
            'tex':0,'uv':[0,0,512,256],'pos':[0,0],'scale':[2,3],'alpha':1,'rot':0,'blend':'mix'}]]}
        with tempfile.TemporaryDirectory() as d, patch.object(to_ss6,'load_texture',return_value=Image.new('RGBA',(512,256))):
            spec=to_ss6.convert(doc,d,'test',max_cell_size=128,max_units=9999)
        cell=spec['cells'][0]; part=spec['animations'][0]['parts']['mix_0']
        self.assertEqual(1024,cell['size'][0]*part['Sclx'][0][1])
        self.assertEqual(768,cell['size'][1]*part['Scly'][0][1])


if __name__=='__main__':unittest.main()
