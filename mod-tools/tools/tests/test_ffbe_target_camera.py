from copy import deepcopy
import unittest
import numpy as np
from tools.tests import test_ffbe_native_participant_focus as focus
from tools.tests import test_ffbe_attack_director as previous
import ffbe_target_camera as target
import ffbe_cast_camera
import ffbe_attack_director
import ffbe_resonance
from tools.tests.fixtures.participant_camera_vm import CameraVM, vector


class TargetTimeline(unittest.TestCase):
    def test_waits_for_target_shot_without_changing_cast_follow_or_hit_spacing(self):
        for moving in (False,True):
            source=ffbe_cast_camera.lb_source({'moveType':int(moving),'hitFrames':[5,15,40]})
            before=ffbe_attack_director.direct(ffbe_resonance.schedule(2,3,123,source),
                {'_hostVisionUnitId':13503},ffbe_attack_director.DEFAULTS)
            after=target.direct(before,13503)
            by=lambda p,k:[e for e in p['events'] if e['set']['EventType']==k]
            old_cameras=by(before,'NativeParticipantCamera'); cameras=by(after,'NativeParticipantCamera')
            lead=min(e['time'] for e in before['events'] if e['set']['EventType']=='UnitPlayAnimByName')-target.HOLD_TICKS
            self.assertEqual(cameras[:-2],[{**e,'time':e['time']-lead} for e in old_cameras])
            self.assertEqual([{**e,'time':e['time']-lead} for e in by(before,'NativeGroundApproach')],by(after,'NativeGroundApproach'))
            action=lambda p:next(e['time'] for e in by(p,'UnitPlayAnimByName') if e['set']['Unit_PlayAnimByName_AnimationName']=='LB1')
            self.assertEqual(action(after),cameras[-1]['time']+target.ZOOM_FRAMES*800)
            self.assertEqual(cameras[-2]['time'],max(action(before),max(e['time']+e['set']['NativeParticipantCamera_Frame']*800 for e in old_cameras))+2400-lead)
            self.assertEqual(cameras[-1]['time'],cameras[-2]['time']+target.PAN_FRAMES*800)
            subject='targets' if moving else 'participants'
            self.assertEqual([e['set']['NativeParticipantCamera_Shot'] for e in cameras[-2:]],[subject+'_pan',subject+'_zoom'])
            self.assertEqual([e['time']-action(before) for e in by(before,'OtherReaction')],
                             [e['time']-action(after) for e in by(after,'OtherReaction')])
            self.assertEqual(after['duration']-before['duration'],action(after)-action(before))


class TargetFit(focus.NativeParticipantFocus):
    test_invalid_zoom_factor_is_not_reinterpreted_as_focal_mm = previous.AttackCamera.test_invalid_zoom_factor_is_not_reinterpreted_as_focal_mm
    def stage(self,targets,cam=None,shot='targets_fit',caster=None):
        op=deepcopy(self.ops[1]);op['set'].update(NativeParticipantCamera_Shot=shot,
            NativeParticipantCamera_CenterX=.5 if shot.startswith('participants') else target.TARGET_X,NativeParticipantCamera_CenterY=target.TARGET_Y,
            NativeParticipantCamera_HeightFraction=target.TARGET_HEIGHT,NativeParticipantCamera_ZoomFactor=target.MAX_TARGET_ZOOM)
        result=self.patch([op]);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        doc=self.dump('tojson'); fn=doc['Exports'][int(self.identifiers[1])-1]
        vm=CameraVM(doc,fn,self.vm_size,caster or focus.unit(),targets,cam or focus.camera(),(1280,720))
        calls=vm.run()
        self.assertEqual(next(v for k,v in self.dump('seqdump').items() if k.startswith(self.identifiers[1]+':')),op['set'])
        self.patch([self.ops[1]])
        return calls

    def test_stationary_caster_and_enemy_bodies_fit_including_wide_spacing(self):
        import math
        cam=focus.camera();cam['Cine']['CurrentFocalLength']=37.375
        caster=focus.unit((0,550,0),200,30)
        enemies=[focus.unit((-100,-350,0),450,34),focus.unit((200,-1000,0),742,34)]
        position=vector(self.stage(enemies,cam,'participants_pan',caster)[0][8])
        lens=self.stage(enemies,cam,'participants_zoom',caster)[0][27]
        p,y=map(math.radians,(-6.83,-6.15))
        forward=np.array([math.cos(p)*math.cos(y),math.cos(p)*math.sin(y),math.sin(p)])
        right=np.array([-math.sin(y),math.cos(y),0]);up=np.cross(forward,right)
        for body in [caster,*enemies]:
            feet=vector(body['location']);head=vector(body['m_pSsPlayerComponent']['sockets']['NULL_Head'])
            radius=max(body['m_pRootCapsuleComponent']['radius'],np.linalg.norm(head-feet)*.25)
            for point in (feet,head):
                for edge in (-radius,radius):
                    delta=point+right*edge-position;depth=delta@forward
                    x=.5+(delta@right)*lens/(23.76*depth)
                    y=.5-(delta@up)*lens*1280/(23.76*depth*720)
                    self.assertTrue(.03<x<.97,(x,y))
                    self.assertTrue(.03<y<.93,(x,y))

    def test_single_large_enemy_fits_and_small_enemy_zooms_in(self):
        small=self.stage([focus.unit((0,-700,0),250,75)])
        huge=self.stage([focus.unit((0,-700,0),1500,400)])
        self.assertGreater(small[1][27],32.5)
        self.assertLess(huge[1][27],32.5)

    def test_default_transform_origin_does_not_force_widest_lens(self):
        targets=[focus.unit((-100,-525,0),500,34),focus.unit((-100,-650,0),500,34)]
        cam=focus.camera()
        expected=self.stage(targets,cam)
        cam['defaultTransform']['location']=focus.xyz((0,0,0))
        actual=self.stage(targets,cam)
        self.assertEqual(actual,expected)
        self.assertGreater(actual[1][27],20)

    def test_pan_and_zoom_are_separate_and_never_widen_the_lens(self):
        cam=focus.camera();cam['Cine']['CurrentFocalLength']=37.375
        for height in (500,1500):
            targets=[focus.unit((-100,-525,0),height,34)]
            pan=self.stage(targets,cam,'targets_pan')
            zoom=self.stage(targets,cam,'targets_zoom')
            self.assertEqual(len(pan),1)
            self.assertEqual(len(zoom),1)
            self.assertEqual(pan[0][0],3)  # Camera position; no look-at/rotation event.
            self.assertEqual(zoom[0][0],6)
            self.assertEqual(float(pan[0][27]),0)
            self.assertEqual(vector(zoom[0][14]).tolist(),[0,0,0])
            self.assertGreaterEqual(zoom[0][27],37.375)
            if height==500: self.assertGreater(zoom[0][27],37.375)

    def test_staged_pan_preserves_depth_with_actual_battle_spacing(self):
        import math
        cam=focus.camera();cam['Cine']['CurrentFocalLength']=37.375
        cam['Cine']['rotation']={'Pitch':-14.42,'Yaw':15.91,'Roll':0}
        targets=[focus.unit((-100,-250,0),453,34),focus.unit((200,-800,0),742,34)]
        pan=self.stage(targets,cam,'targets_pan')[0]
        zoom=self.stage(targets,cam,'targets_zoom')[0]
        p,y=map(math.radians,(-14.42,15.91))
        forward=np.array([math.cos(p)*math.cos(y),math.cos(p)*math.sin(y),math.sin(p)])
        right=np.array([-math.sin(y),math.cos(y),0]);up=np.cross(forward,right)
        position=vector(pan[8]);old=vector(cam['location'])
        self.assertAlmostEqual(float((position-old)@forward),0,places=6)
        points=[]
        for enemy in targets:
            for point in (enemy['location'],enemy['m_pSsPlayerComponent']['sockets']['NULL_Head']):
                delta=vector(point)-position;depth=delta@forward
                points.append((.5+(delta@right)*zoom[27]/(23.76*depth),
                    .5-(delta@up)*zoom[27]*1280/(23.76*depth*720)))
        self.assertGreater(min(v[0] for v in points),.03)
        self.assertLess(max(v[0] for v in points),.65)
        self.assertGreater(min(v[1] for v in points),.03,points)
        self.assertLess(max(v[1] for v in points),.94)

    def test_target_union_projects_into_lower_left_with_clearance(self):
        targets=[focus.unit((0,-900,0),710,180),focus.unit((80,-1400,0),500,125)]
        calls=self.stage(targets); origin=vector(focus.camera()['location'])
        aim=vector(targets[0]['location'])+vector(calls[0][14])
        forward=aim-origin;forward/=np.linalg.norm(forward)
        right=np.cross([0.,0.,1.],forward);right/=np.linalg.norm(right);up=np.cross(forward,right)
        points=[]
        for enemy in targets:
            feet=vector(enemy['location']);head=vector(enemy['m_pSsPlayerComponent']['sockets']['NULL_Head'])
            radius=max(enemy['m_pRootCapsuleComponent']['radius'],np.linalg.norm(head-feet)*.25)
            for p in (feet,head):
                for edge in (-radius,radius):
                    delta=p+right*edge-origin; depth=delta@forward
                    points.append((.5+(delta@right)*calls[1][27]/(23.76*depth),
                                   .5-(delta@up)*calls[1][27]*1280/(23.76*depth*720)))
        self.assertGreater(min(p[0] for p in points),.03)
        self.assertLess(max(p[0] for p in points),.75)
        self.assertGreater(min(p[1] for p in points),.20)
        self.assertLess(max(p[1] for p in points),.94)


if __name__=='__main__': unittest.main()
