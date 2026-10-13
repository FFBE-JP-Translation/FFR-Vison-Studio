from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'tools/ffbe_effects')]
import prepared_reuse


class PreparedReuse(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        directory=self.root/'assets/reviewed';directory.mkdir(parents=True)
        spec={'cellmaps':[{'textureFile':'a.bgra'},{'textureFile':'b.bgra'}],
              'conversionAudit':{'maxCellSize':128,'shrunkSpriteFrames':3}}
        (directory/'spec.json').write_text(json.dumps(spec))
        for name in ('a.bgra','b.bgra'): (directory/name).write_bytes(name.encode())
        checksums={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.iterdir()}
        sample=b'fixture recording';sample_digest=hashlib.sha256(sample).hexdigest()
        (self.root/'samples').mkdir();(self.root/'samples'/(sample_digest+'.hca')).write_bytes(sample)
        (self.root/'audio.json').write_text(json.dumps({'schema':'ffr-audio-1','cues':{'29':{'name':'fire'}},
            'waves':{'0':{'sha256':sample_digest}},'recordings':[{'sourceCueId':29,'sourceWaveId':0}],'omitted':{}}))
        caster={'phase':'action','anchor':'caster','layer':1,'file':'slash.bmb','frame':29,'x':0}
        self.previous={'sourceSha256':'a'*64,'sounds':[{'frame':293,'cueId':29}],
            'spawns':[caster],'audioBank':'audio.json',
            'visuals':[{'name':'reviewed','spec':'assets/reviewed','phase':'action','anchor':'caster','layer':1,
                        'frame':29,'frames':313,'checksums':checksums}],
            'issues':['slash.bmb: original decoder limitation','Group 5: screen overlay awaits an adapter']}
        self.fresh={'sourceSha256':'a'*64,'sounds':deepcopy(self.previous['sounds']),
            'spawns':[deepcopy(caster),{'anchor':'screen','layer':2,'file':'rear.bmb','frame':0,'groupId':'5'}]}

    def validate(self,profile=None):
        return prepared_reuse.validate(self.previous,self.fresh,self.root,profile)

    def test_preserves_exact_reviewed_group_while_new_source_group_remains_unretained(self):
        groups,evidence,issues=self.validate()
        self.assertEqual(groups,{('action','caster',1):self.previous['visuals'][0]})
        self.assertEqual(evidence['groups'][0]['originalSettings'],'unknown')
        self.assertFalse(evidence['freshCanonicalConversion'])
        self.assertEqual(issues,['slash.bmb: original decoder limitation'])
        self.assertEqual(evidence['groups'][0]['recordedConversionAudit']['shrunkSpriteFrames'],3)

    def test_selected_source_rebuilds_whole_group_and_preserves_audio_proof(self):
        groups,evidence,_=self.validate()
        old=deepcopy(evidence)
        retained,proof=prepared_reuse.rebuild_groups(groups,evidence,self.fresh['spawns'],['slash.bmb'])
        case_retained,case_proof=prepared_reuse.rebuild_groups(groups,evidence,self.fresh['spawns'],['SLASH.BMB'])
        self.assertEqual(case_retained,retained)
        self.assertEqual(case_proof,proof)
        self.assertEqual({},retained)
        self.assertEqual([],proof['groups'])
        self.assertEqual(['slash.bmb'],proof['rebuiltGroups'][0]['requestedSources'])
        self.assertEqual(old['audioBankSha256'],proof['audioBankSha256'])
        self.assertEqual(old,evidence)

    def test_unaffected_groups_remain_exact_and_source_paths_are_rejected(self):
        groups,evidence,_=self.validate()
        retained,proof=prepared_reuse.rebuild_groups(groups,evidence,self.fresh['spawns'],['rear.bmb'])
        self.assertEqual(groups,retained)
        self.assertEqual(evidence,proof)
        with self.assertRaisesRegex(ValueError,'basenames'):
            prepared_reuse.rebuild_groups(groups,evidence,self.fresh['spawns'],['../slash.bmb'])

    def test_rebuild_archives_only_obsolete_owned_issues(self):
        groups,evidence,issues=self.validate()
        _,proof=prepared_reuse.rebuild_groups(groups,evidence,self.fresh['spawns'],['slash.bmb'])
        export='caster/1: 0 sprite frames omitted; 3 oversized sprite frames scaled down'
        host='Area damage is intact; sprite impacts currently attach to the first selected target'
        issues += [export,host,'rear.bmb: retained source limitation']
        archived,current=prepared_reuse.archive_rebuilt_issues(proof,issues,self.fresh['spawns'])
        self.assertEqual(current,[host,'rear.bmb: retained source limitation'])
        self.assertEqual(archived['rebuiltGroups'][0]['historicalIssues'],
                         ['slash.bmb: original decoder limitation',export])
        self.assertNotIn('historicalIssues',proof['rebuiltGroups'][0])
        shared=[*self.fresh['spawns'],{**self.fresh['spawns'][1],'file':'slash.bmb'}]
        _,current=prepared_reuse.archive_rebuilt_issues(proof,issues,shared)
        self.assertIn('slash.bmb: original decoder limitation',current)

    def test_changed_source_snapshot_and_sound_schedule_are_rejected(self):
        self.fresh['sourceSha256']='b'*64
        with self.assertRaisesRegex(ValueError,'snapshot fingerprint'):self.validate()
        self.fresh['sourceSha256']='a'*64;self.fresh['sounds'][0]['frame']=303
        with self.assertRaisesRegex(ValueError,'sound timeline'):self.validate()

    def test_changed_or_incomplete_existing_group_cannot_be_silently_reused(self):
        self.fresh['spawns'][0]['x']=1
        with self.assertRaisesRegex(ValueError,'source group changed'):self.validate()
        self.fresh['spawns'][0]['x']=0
        self.fresh['spawns'].append({**self.fresh['spawns'][0],'frame':30})
        with self.assertRaisesRegex(ValueError,'previously incomplete'):self.validate()

    def test_all_atlas_pages_require_checksums(self):
        del self.previous['visuals'][0]['checksums']['b.bgra']
        with self.assertRaisesRegex(ValueError,'complete spec and atlas'):self.validate()

    def test_changed_bytes_are_rejected(self):
        (self.root/'assets/reviewed/a.bgra').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'checksum mismatch'):self.validate()

    def test_changed_explicit_export_settings_are_rejected(self):
        self.previous['reconstructionProfile']={'export':{'maxCellSize':128}}
        with self.assertRaisesRegex(ValueError,'changed explicit profile'):
            self.validate({'export':{'maxCellSize':512}})
        groups,evidence,_=self.validate(self.previous['reconstructionProfile'])
        self.assertEqual(evidence['groups'][0]['originalSettings'],'recorded_profile')

    def test_implicit_existing_profile_or_standalone_opening_is_rejected(self):
        self.previous['reconstructionProfile']={'opening':{'durationFrames':42}}
        with self.assertRaisesRegex(ValueError,'identical explicit profile'):self.validate()
        del self.previous['reconstructionProfile']
        self.previous['opening']={'durationFrames':42}
        with self.assertRaisesRegex(ValueError,'opening requires'):self.validate()

    def test_cue_metadata_does_not_prove_a_recording_is_available(self):
        path=self.root/'audio.json';audio=json.loads(path.read_text())
        audio['omitted']={'29':'Unroutable original recording'};path.write_text(json.dumps(audio))
        with self.assertRaisesRegex(ValueError,'omitted or missing recording'):self.validate()
        audio['omitted']={};audio['recordings'][0]['sourceWaveId']=1;path.write_text(json.dumps(audio))
        with self.assertRaisesRegex(ValueError,'omitted or missing recording'):self.validate()

    def test_unresolved_host_limitations_survive_reuse(self):
        limitation='Area damage is intact; sprite impacts currently attach to the first selected target'
        self.previous['issues'].append(limitation)
        _,_,issues=self.validate()
        self.assertIn(limitation,issues)
        self.assertNotIn('Group 5: screen overlay awaits an adapter',issues)

    def test_injected_cast_and_charge_cues_need_actual_recordings(self):
        self.fresh['cast']={'bank':'SE','frame':0}
        with self.assertRaisesRegex(ValueError,'recording for cue 100'):self.validate()
        del self.fresh['cast']
        self.previous['opening']={'chargeFrame':2,'durationFrames':42}
        self.previous['reconstructionProfile']={'opening':self.previous['opening']}
        with self.assertRaisesRegex(ValueError,'recording for cue 647'):
            self.validate(self.previous['reconstructionProfile'])

    def test_repeated_retention_does_not_invent_original_legacy_settings(self):
        _,evidence,_=self.validate()
        self.previous['retainedLegacyVisuals']=evidence
        self.previous['reconstructionProfile']={'export':{'maxCellSize':512}}
        _,again,_=self.validate(self.previous['reconstructionProfile'])
        self.assertEqual(again['groups'][0]['originalSettings'],'unknown')
        self.assertIsNone(again['groups'][0]['recordedProfile'])

    def test_retained_asset_paths_cannot_escape_the_workspace(self):
        self.previous['visuals'][0]['spec']='../outside'
        with self.assertRaisesRegex(ValueError,'escapes the project'):self.validate()


if __name__=='__main__':unittest.main()
