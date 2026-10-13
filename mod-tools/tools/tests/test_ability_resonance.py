"""Shared mechanics reach the existing cooked LB sequencer and effect tables."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
from ability_converter import resonance as converted
from ability_converter import Converter,SourceRecord
from ability_converter.catalog import SourceCatalog
import ffbe_lb as lb
import ffbe_resonance as sequence
import make_vision_mod as generator
import test_lb_support as support_tests
import test_ffbe_resonance as sequence_tests


def hybrid():
    return {"schema":2, "lbId":"200", "name":"Hybrid fixture", "moveType":0, "elements":["Light"],
            "rawAttackFrames":"12:25-36:75", "components":[{"index":0,"range":2,"target":1,"type":40,
                "params":[0,0,0,0,0,0,0,0,500,500]}]}


def racial():
    return {"schema":2, "lbId":"201", "name":"Race fixture", "moveType":0, "elements":["Light"],
            "rawAttackFrames":"12:100@36:100", "components":[
                {"index":0,"range":2,"target":1,"type":22,"params":[8,0,0,20000]},
                {"index":1,"range":2,"target":1,"type":1,"params":[0,0,0,0,0,0,16000]}]}


def prefix_timing():
    return {"schema":2,"lbId":"202","name":"Prefix timing fixture","moveType":0,"elements":[],
            "rawAttackFrames":"16:20-58:80@120:100","components":[
                {"index":0,"range":2,"target":1,"type":1,"params":[0,0,0,0,0,0,1000]},
                {"index":1,"range":0,"target":3,"type":3,"params":[0,60,0,0,3,1]},
                {"index":2,"range":0,"target":3,"type":3,"params":[0,0,60,0,3,1]}]}


def extended_hits():
    return {"schema":2,"lbId":"203","name":"Extended hit fixture","moveType":0,"elements":[],
            "rawAttackFrames":"-".join(f"{12+i*4}:{1 if i<59 else 61}" for i in range(60)),
            "components":[{"index":0,"range":2,"target":1,"type":1,"params":[0,0,0,0,0,0,1000]}]}


def recovery():
    return {"schema":2,"lbId":"204","name":"Recovery fixture","moveType":0,"elements":[],
            "rawAttackFrames":"160:100@180:100","components":[
                {"index":0,"range":2,"target":2,"type":2,"params":[0,0,3000,1800,100]},
                {"index":1,"range":2,"target":2,"type":111,"params":[0,0,0,0,1,0]}]}


def composite():
    return {"schema":2,"lbId":"205","name":"Mixed formula fixture","moveType":0,"elements":[],
            "rawAttackFrames":"12:20-24:80@18:50-36:50","components":[
                {"index":0,"range":2,"target":1,"type":1,"params":[0,0,0,0,0,0,500]},
                {"index":1,"range":2,"target":1,"type":15,"params":[0,0,0,0,0,1000,0]}]}


def attack_recovery():
    source=composite()
    source['rawAttackFrames']='12:20-24:80@30:100@18:100'
    source['components'][0]['range']=1
    source['components'].append({'index':2,'range':0,'target':3,'type':2,'params':[0,0,1000,200,100]})
    return source


def reraise():
    return {'schema':2,'lbId':'206','name':'Reraise LB','moveType':0,'elements':[],
            'rawAttackFrames':'24:100','components':[{'index':0,'range':2,'target':2,'type':27,'params':[100,3,0]}]}


def dispel():
    return {'schema':2,'lbId':'207','name':'Dispel LB','moveType':0,'elements':[],
            'rawAttackFrames':'24:100','components':[{'index':0,'range':2,'target':1,'type':59,'params':[0,0]}]}


def stop():
    return {'schema':2,'lbId':'208','name':'Stop LB','moveType':0,'elements':[],
            'rawAttackFrames':'24:100','components':[{'index':0,'range':2,'target':1,'type':88,'params':[75,5]}]}


def everyone():
    return {'schema':2,'lbId':'209','name':'Universal Dispel LB','moveType':0,'elements':[],
            'rawAttackFrames':'24:100','components':[{'index':0,'range':2,'target':4,'type':59,'params':[0]}]}


def elemental():
    return {'schema':2,'lbId':'210','name':'Elemental LB','moveType':0,'elements':['Fire','Ice','Dark'],
            'rawAttackFrames':'12:25-36:75','components':[{'index':0,'range':2,'target':1,'type':15,'params':[0,0,0,0,0,600]}]}


def elemental_composition():
    source=composite();source.update(lbId='211',name='Elemental composition',elements=['Fire','Ice','Dark'])
    return source


def tag_composition():
    source=composite();source.update(lbId='212',name='Tag composition')
    source['components'].append({'index':2,'range':0,'target':3,'type':165,'params':[212,2,1,1,1,1]})
    source['rawAttackFrames']+='@48:100'
    return source


class ProfileTests(unittest.TestCase):
    def test_attack_recovery_lb_distinguishes_unweighted_healing_from_cloud_budget(self):
        timeline,p=converted.profile(attack_recovery())
        self.assertTrue(p['supported'],p['issues'])
        self.assertEqual(timeline['applicationKinds'],['damage','recovery','damage','damage'])
        self.assertEqual(timeline['hitPercents'][1],0.)
        self.assertAlmostEqual(sum(timeline['hitPercents']),100.)
        self.assertEqual(p['hits'],4)
        self.assertIn('Restores HP to the user.',p['description'])

    def test_recovery_lb_uses_recovery_phase_and_one_application(self):
        timeline,p=converted.profile(recovery())
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(timeline["hitFrames"],[160])
        self.assertEqual((p["set"]["parameterVariationType"],p["totalPower"],p["hits"]),("Increase",330,1))
        self.assertEqual(timeline["effectPhases"][0]["timing"],"AfterDamageCalculation")
        self.assertIn("before/after recovery phases",p["warnings"][-1])

    def test_race_lb_keeps_base_portions_and_one_shared_damage_budget(self):
        timeline,p=converted.profile(racial())
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(timeline["hitFrames"],[12,36])
        self.assertAlmostEqual(timeline["hitPercents"][0],100/161)
        self.assertAlmostEqual(timeline["hitPercents"][1],16000/161)
        self.assertEqual(p["totalPower"],converted.converter().native.cloud["magnification"])
        self.assertEqual(p["conversion"]["native"]["effects"][0]["target"]["shape"],"Self")

    def test_hybrid_uses_shared_magic_conversion_and_original_hits(self):
        timeline, p = converted.profile(hybrid())
        self.assertTrue(p["supported"],p["issues"])
        self.assertEqual(p["set"]["DamageType"],"Magic")
        self.assertEqual(p["conversion"]["components"][0]["replacement"],"Hybrid to magic")
        self.assertEqual(timeline["hitFrames"],[12,36])
        self.assertEqual(timeline["hitPercents"],[25,75])
        self.assertEqual(p["binding"]["gaugePolicy"],"native_finish_blow")

    def test_native_damage_phases_and_unknowns_do_not_fall_back_to_damage(self):
        s = hybrid()
        s["components"].append({"index":1,"range":2,"target":2,"type":3,"params":[100,0,0,0,3,1]})
        _, p = converted.profile(s)
        self.assertTrue(p["supported"],p["issues"])
        self.assertIn("native before/after damage phases",p["warnings"][-1])
        s["components"][0]["type"] = 999999
        _, p = converted.profile(s)
        self.assertFalse(p["supported"])
        self.assertNotIn("fallback",p)

    def test_effect_ids_are_skill_owned_and_collisions_do_not_partially_append(self):
        _, p = converted.profile(support_tests.agnes())
        tables = {}
        def tbl(rel):
            return tables.setdefault(rel,{"add":[],"set":[]})
        first = converted.materialize(p,444010,"First",tbl,generator.row_by)
        second = converted.materialize(p,444020,"Second",tbl,generator.row_by)
        a = {b["effectId"] for b in first["effectBundleList"]}
        b = {b["effectId"] for b in second["effectBundleList"]}
        self.assertFalse(a & b)
        self.assertTrue(all(44401000 <= v < 44401100 for v in a))
        owners = tables["Skill/Other/DT_SkillGeneralData"]["set"][0]["set"]["equipperActionVisionSkills"]
        self.assertEqual(owners,[414610,444010,444020])
        before = json.dumps(tables,sort_keys=True)
        with self.assertRaisesRegex(ValueError,"Duplicate"):
            converted.materialize(p,444010,"First",tbl,generator.row_by)
        self.assertEqual(json.dumps(tables,sort_keys=True),before)


class CookedConvertedTests(unittest.TestCase):
    run_dt = staticmethod(sequence_tests.CookedResonanceTests.run_dt)
    dump = classmethod(sequence_tests.CookedResonanceTests.dump.__func__)

    @classmethod
    def setUpClass(cls):
        if not Path(generator.LEGACY, sequence.SHELL+".uasset").is_file():
            raise unittest.SkipTest("Native resonance shell must be extracted first")
        cls.temp = tempfile.TemporaryDirectory(prefix="converted-lb-",dir=ROOT/"build")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.work = Path(cls.temp.name).resolve()
        out = cls.work/"assets"
        tables, clones, jobs = {}, [], []
        def tbl(rel):
            return tables.setdefault(rel,{"asset":generator.DT+rel,"add":[],"set":[]})
        donor = generator.row_by("Skill/DT_SkillData","ID",440110)[0]
        mixed = hybrid()
        mixed["components"].append({"index":1,"range":2,"target":2,"type":3,"params":[100,0,0,0,3,1]})
        for sid, name, source in ((444010,"ConvertedSupport",support_tests.agnes()),(444020,"ConvertedHybrid",hybrid()),(444030,"ConvertedMixed",mixed),(444040,"ConvertedRace",racial()),(444050,"ConvertedPrefix",prefix_timing()),(444060,"ConvertedExtended",extended_hits()),(444070,"ConvertedRecovery",recovery()),(444080,"ConvertedComposite",composite()),(444090,"ConvertedAttackRecovery",attack_recovery()),(444100,"ConvertedReraise",reraise()),(444110,"ConvertedDispel",dispel()),(444120,"ConvertedStop",stop()),(444130,"ConvertedEveryone",everyone()),(444140,"ConvertedElements",elemental()),(444150,'ConvertedElementApplications',elemental_composition()),(444160,'ConvertedTagApplications',tag_composition())):
            tbl("Skill/DT_SkillData")["add"].append({"row":name,"cloneFrom":donor,"set":{"ID":sid}})
            skill = {"jp":name,"from":440110,"mechanics":"converted"}
            with patch.object(generator,"lb_motion_seconds",return_value=6), patch.object(lb,"resolve",return_value=source):
                generator.prepare_ffbe_resonance({"key":"converted-test","ffbe":{"id":"313000206"}},skill,sid,tbl,clones,jobs)
        delayed={'schema':2,'lbId':'213','name':'Delayed ward','moveType':0,'elements':[],
            'rawAttackFrames':'24:100','components':[{'index':0,'range':0,'target':3,'type':132,'params':[900,0,2,100,0,9]}]}
        future=SourceRecord('GL_2024','ability','900',{'name':'Future ward','mp_cost':0,
            'effects_raw':[[0,3,3,[100,0,0,0,2,1,0]]],'attack_frames':[[90]],'attack_damage':[[100]]})
        with SourceCatalog() as catalog:
            from ability_converter.lb_sources import attach
            from dataclasses import replace
            catalog.add(future);catalog.finish()
            delayed=attach(delayed,replace(converted.source_record(delayed),source='GL_2024'),catalog)
            tbl('Skill/DT_SkillData')['add'].append({'row':'ConvertedDelayedSupport','cloneFrom':donor,'set':{'ID':444170}})
            skill={'jp':'ConvertedDelayedSupport','from':440110,'mechanics':'converted'}
            with patch.object(generator,'lb_motion_seconds',return_value=6), patch.object(lb,'resolve',return_value=delayed):
                generator.prepare_ffbe_resonance({'key':'converted-test','ffbe':{'id':'313000206'}},skill,444170,tbl,clones,jobs)
        path = cls.work/"patch.json"
        path.write_text(json.dumps({"legacyRoot":generator.LEGACY,"outRoot":str(out),
                                    "tables":list(tables.values()),"clones":clones}),encoding="utf8")
        cls.run_dt([*generator.FFRDT,"patch",str(path),"--usmap",generator.USMAP])
        cls.assets = []
        for index,job in enumerate(jobs):
            work = cls.work/str(index); work.mkdir()
            sequence.build(job,out,work,generator.FFRDT,generator.USMAP,cls.run_dt)
            cls.assets.append((cls.dump(out/(job["asset"]+".uasset"),"tojson"),
                               cls.dump(out/(job["asset"]+".uasset"),"seqdump"),job["plan"]))
        cls.skills = cls.dump(out/(generator.DT+"Skill/DT_SkillData.uasset"),"rows")["rows"]
        cls.effects = cls.dump(out/(generator.DT+"Skill/DT_SkillEffectData.uasset"),"rows")["rows"]
        cls.general = cls.dump(out/(generator.DT+"Skill/Other/DT_SkillGeneralData.uasset"),"rows")["rows"]

    def test_delayed_lb_cooks_private_support_without_donor_damage(self):
        root=self.skills['ConvertedDelayedSupport'];effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        grant=effects[root['effectBundleList'][0]['effectId']];private=skills[grant['ParamList'][1]]
        self.assertEqual((root['magnification'],private['magnification']),(0,0))
        self.assertEqual((grant['applyTiming'],grant['proceedTiming'],grant['effectEndActionNum']),('BeginTurn','BeginTurn',2))
        self.assertEqual((private['Cost'],private['playSequencerId'],private['belongCommandList']),(0,-1,[]))
        self.assertTrue(private['isParallelExecutable']);self.assertFalse(private['isMimicEnabled'])
        self.assertEqual(effects[private['effectBundleList'][0]['effectId']]['ParamList'][:3],[20,5,2])

    def test_support_remains_support_and_effects_use_converted_values(self):
        row = self.skills["ConvertedSupport"]
        self.assertEqual((row["magnification"],row["DamageType"],row["skillEffectType"]),(0,"None","None"))
        bundles = row["effectBundleList"]
        self.assertEqual([b["targetRelation"] for b in bundles],["Enemies","Friendlies","Friendlies","Friendlies"])
        effects = [next(e for e in self.effects.values() if e["ID"] == b["effectId"]) for b in bundles]
        self.assertEqual(effects[1]["ParamList"][:3],[20,6,2])
        self.assertEqual(effects[2]["ParamList"][:3],[20,8,2])
        self.assertEqual(effects[3]["ParamList"][3],9)

    def test_hybrid_cooks_as_magic_with_one_total_budget(self):
        row = self.skills["ConvertedHybrid"]
        self.assertEqual(row["DamageType"],"Magic")
        self.assertEqual(row["hitCount"],2)
        self.assertEqual(row["hitDamageRatioList"][:2],[.25,.75])
        self.assertEqual(row["magnification"],converted.converter().native.cloud["magnification"])

    def test_native_actor_bindings_keep_both_skills_and_original_settings(self):
        native = converted.converter().native
        row = self.general[native.general_name]
        self.assertEqual(row["equipperActionVisionSkills"][:-1],[414610,444010,444020,444030,444040,444050,444060,444070,444080,444090,444100,444110,444120,444130,444140,444150,444160,444170])
        child = row['equipperActionVisionSkills'][-1]
        self.assertTrue(600000 <= child < 900000)
        self.assertEqual(sum(r['ID']==child for r in self.skills.values()),1)
        for key,value in native.general.items():
            if key != "equipperActionVisionSkills":
                self.assertEqual(row[key],value,key)

    def test_multiple_elements_lb_cooks_final_skill_filter_and_cloud_budget(self):
        root=self.skills['ConvertedElements'];effects={e['ID']:e for e in self.effects.values()}
        bundles=[b for b in root['effectBundleList'] if b['effectId']>=0]
        self.assertEqual(root['magnification'],converted.converter().native.cloud['magnification'])
        self.assertEqual(root['hitDamageRatioList'][:2],[.25,.75])
        self.assertEqual([effects[b['effectId']]['ParamList'][:2] for b in bundles],[[2,444140],[8,444140]])
        self.assertTrue(all(b['TargetType']=='Self' and b['activeSkillAddTiming']=='BeforeDamageCalculation' for b in bundles))

    def test_appended_lb_elements_cook_each_child_filter_with_one_cloud_budget(self):
        root=self.skills['ConvertedElementApplications'];effects={e['ID']:e for e in self.effects.values()}
        skills={s['ID']:s for s in self.skills.values()}
        fx=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
        ids=[444150,*[e['ParamList'][0] for e in fx if e['EffectType']=='AppendDamage']]
        self.assertEqual([e['ParamList'][:2] for e in fx if e['EffectType']=='AddElement'],[[el,sid] for sid in ids for el in (2,8)])
        rows=[skills[sid] for sid in ids]
        self.assertTrue(all(r['magnification']==converted.converter().native.cloud['magnification'] for r in rows))
        self.assertAlmostEqual(sum(sum(r['hitDamageRatioList']) for r in rows),1.)
        self.assertTrue(all(r['Cost']==0 and not r['belongCommandList'] and r['playSequencerId']==-1 for r in rows[1:]))

    def test_tag_lb_cooks_private_scope_without_changing_cloud_damage_budget(self):
        root=self.skills['ConvertedTagApplications'];effects={e['ID']:e for e in self.effects.values()};skills={s['ID']:s for s in self.skills.values()}
        fx=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
        ids=[444160,*[e['ParamList'][0] for e in fx if e['EffectType']=='AppendDamage']]
        tag=next(e for e in fx if e['EffectType']=='MulBaseBreakBySkill')
        self.assertEqual(tag['ParamList'][:5],[20,*ids]);self.assertEqual(tag['ParamList'][5:],[-1]*10)
        self.assertEqual(tag['proceedTiming'],'SkillEnd')
        self.assertTrue(all(skills[sid]['magnification']==converted.converter().native.cloud['magnification'] for sid in ids))
        self.assertAlmostEqual(sum(sum(skills[sid]['hitDamageRatioList']) for sid in ids),1.)

    def test_cooked_hit_events_match_both_authored_timelines(self):
        sequence_tests.CookedResonanceTests.test_cooked_schedule_matches_channel(self)

    def test_partial_timing_cooks_lb_hits_and_keeps_one_damage_budget(self):
        row=self.skills["ConvertedPrefix"]
        self.assertEqual(row["magnification"],converted.converter().native.cloud["magnification"])
        self.assertEqual((row["DamageType"],row["hitCount"]),("Physic",2))
        self.assertAlmostEqual(row["hitDamageRatioList"][0],.2)
        self.assertAlmostEqual(row["hitDamageRatioList"][1],.8)
        self.assertEqual([e["time"] for e in self.assets[4][2]["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+16*400,12000+58*400])

    def test_extended_lb_cooks_all_sixty_hits_and_retains_finisher_share(self):
        row=self.skills["ConvertedExtended"]
        self.assertEqual(row["hitCount"],60)
        self.assertEqual(len(row["hitDamageRatioList"]),60)
        self.assertAlmostEqual(sum(row["hitDamageRatioList"]),1.,places=6)
        self.assertAlmostEqual(row["hitDamageRatioList"][-1],61/120,places=6)
        self.assertEqual(row["magnification"],converted.converter().native.cloud["magnification"])
        self.assertEqual([e["time"] for e in self.assets[5][2]["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+(12+i*4)*400 for i in range(60)])

    def test_recovery_lb_cooks_recovery_power_and_cure_without_cloud_damage(self):
        row=self.skills["ConvertedRecovery"]
        self.assertEqual((row["parameterVariationType"],row["magnification"],row["hitCount"]),("Increase",330,1))
        self.assertEqual((row["Cost"],row["TargetType"],row["defaultTargetRelation"]),(0,"Group","Friendlies"))
        bundles=[b for b in row["effectBundleList"] if b["effectId"]>=0]
        self.assertEqual(len(bundles),1)
        self.assertEqual(bundles[0]["activeSkillAddTiming"],"AfterDamageCalculation")
        effect=next(e for e in self.effects.values() if e["ID"]==bundles[0]["effectId"])
        self.assertEqual((effect["EffectType"],effect["ParamList"][3]),("CureStatusCondition",9))
        self.assertEqual([e["time"] for e in self.assets[6][2]["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+160*400])

    def test_composite_lb_cooks_distinct_formulas_and_one_cloud_budget(self):
        row=self.skills["ConvertedComposite"]
        rows=[row]
        for bundle in row["effectBundleList"]:
            if bundle["effectId"]<0:continue
            effect=next(e for e in self.effects.values() if e["ID"]==bundle["effectId"])
            rows.append(next(r for r in self.skills.values() if r["ID"]==effect["ParamList"][0]))
        self.assertEqual([r["DamageType"] for r in rows],["Physic","Magic","Physic","Magic"])
        power=converted.converter().native.cloud["magnification"]
        self.assertTrue(all(r["magnification"]==power for r in rows))
        self.assertAlmostEqual(sum(r["magnification"]*sum(r["hitDamageRatioList"]) for r in rows),power,places=5)
        self.assertEqual([e["time"] for e in self.assets[7][2]["events"] if e["set"]["EventType"]=="OtherReaction"],
                         [12000+f*400 for f in (12,18,24,36)])

    def test_attack_recovery_lb_cooks_full_self_heal_outside_cloud_damage_budget(self):
        root=self.skills['ConvertedAttackRecovery'];by_id={r['ID']:r for r in self.skills.values()}
        effects={e['ID']:e for e in self.effects.values()}
        bundles=[b for b in root['effectBundleList'] if b['effectId']>=0]
        rows=[root,*[by_id[effects[b['effectId']]['ParamList'][0]] for b in bundles]]
        self.assertEqual([(b['TargetType'],b['targetRelation']) for b in bundles],
                         [('Self','Friendlies'),('SkillTarget','Enemies'),('Group','Enemies')])
        self.assertEqual(rows[1]['parameterVariationType'],'Increase')
        self.assertEqual(rows[1]['magnification'],50)
        self.assertEqual(rows[1]['hitDamageRatioList'][:4],[0.,1.,0.,0.])
        damage=[r for r in rows if r['parameterVariationType']=='Decrease']
        cloud=converted.converter().native.cloud['magnification']
        self.assertTrue(all(r['magnification']==cloud for r in damage))
        self.assertAlmostEqual(sum(r['magnification']*sum(r['hitDamageRatioList']) for r in damage),cloud,places=5)
        self.assertTrue(all(r['Cost']==0 for r in rows))
        self.assertEqual([e['time'] for e in self.assets[8][2]['events'] if e['set']['EventType']=='OtherReaction'],
                         [12000+f*400 for f in (12,18,24,30)])

    def test_mixed_resonance_uses_stock_damage_phase_and_one_damage_budget(self):
        row = self.skills["ConvertedMixed"]
        self.assertEqual(row["magnification"],converted.converter().native.cloud["magnification"])
        self.assertEqual(row["DamageType"],"Magic")
        bundle = row["effectBundleList"][0]
        self.assertEqual((bundle["TargetType"],bundle["targetRelation"]),("Group","Friendlies"))
        self.assertEqual(bundle["activeSkillAddTiming"],"AfterDamageCalculation")
        effect = next(e for e in self.effects.values() if e["ID"] == bundle["effectId"])
        self.assertEqual(effect["ParamList"][:3],[20,5,2])

    def test_race_resonance_cooks_its_base_damage_and_offensive_self_reward(self):
        row=self.skills["ConvertedRace"]
        self.assertEqual(row["magnification"],converted.converter().native.cloud["magnification"])
        self.assertEqual(row["DamageType"],"Physic")
        self.assertAlmostEqual(row["hitDamageRatioList"][0],1/161)
        self.assertAlmostEqual(row["hitDamageRatioList"][1],160/161)
        bundle=row["effectBundleList"][0]
        self.assertEqual((bundle["TargetType"],bundle["activeSkillAddTiming"]),("Self","BeforeDamageCalculation"))
        effect=next(e for e in self.effects.values() if e["ID"]==bundle["effectId"])
        self.assertEqual(effect["ParamList"][:3],[20,7,2])
        self.assertEqual((effect["proceedTiming"],effect["effectEndActionNum"]),("BeginTurn",2))

    def test_reraise_lb_cooks_private_revival_without_a_second_gauge_cost(self):
        root=self.skills['ConvertedReraise'];effects={r['ID']:r for r in self.effects.values()}
        skills={r['ID']:r for r in self.skills.values()};grant=effects[root['effectBundleList'][0]['effectId']]
        child=skills[grant['ParamList'][1]]
        self.assertEqual((root['magnification'],root['DamageType']),(0,'None'))
        self.assertEqual((child['Cost'],child['belongCommandList'],child['playSequencerId']),(0,[],-1))
        self.assertTrue(child['isAvailableWhenDead'])
        self.assertEqual(effects[child['effectBundleList'][0]['effectId']]['ParamList'][0],100)
        self.assertEqual(effects[child['effectBundleList'][1]['effectId']]['ParamList'][0],grant['ID'])
        self.assertEqual([e['time'] for e in self.assets[9][2]['events'] if e['set']['EventType']=='OtherReaction'],[12000+24*400])

    def test_stop_lb_cooks_distinct_status_and_one_support_event(self):
        root=self.skills['ConvertedStop'];effects={r['ID']:r for r in self.effects.values()}
        self.assertEqual((root['magnification'],root['DamageType']),(0,'None'))
        effect=effects[root['effectBundleList'][0]['effectId']]
        self.assertEqual((effect['statusCondition'],effect['addProbability'],effect['effectEndActionNum']),('Stop',75,5))
        self.assertEqual(effect['ParamList'][:3],[3,-1,-1])
        self.assertEqual([e['time'] for e in self.assets[11][2]['events'] if e['set']['EventType']=='OtherReaction'],[12000+24*400])

    def test_all_side_lb_cooks_one_event_retaining_both_removal_operations(self):
        root=self.skills['ConvertedEveryone']
        self.assertEqual((root['TargetType'],root['DamageType'],root['magnification']),('All','None',0))
        self.assertFalse(root['isSameRelationTargetingDisabled']);self.assertFalse(root['isHostilityRelationTargetingDisabled'])
        self.assertEqual([b['TargetType'] for b in root['effectBundleList'] if b['effectId']>=0],['SkillTarget']*2)
        self.assertEqual([e['time'] for e in self.assets[12][2]['events'] if e['set']['EventType']=='OtherReaction'],[12000+24*400])

    def test_combined_dispel_lb_cooks_both_lists_without_inheriting_damage(self):
        root=self.skills['ConvertedDispel'];effects={r['ID']:r for r in self.effects.values()}
        self.assertEqual((root['magnification'],root['DamageType']),(0,'None'))
        rows=[effects[b['effectId']] for b in root['effectBundleList'] if b['effectId']>=0]
        self.assertEqual(len(rows),2);self.assertEqual(rows[0]['ParamList'][1],1);self.assertEqual(rows[1]['ParamList'][10],1)
        self.assertEqual([e['time'] for e in self.assets[10][2]['events'] if e['set']['EventType']=='OtherReaction'],[12000+24*400])


if __name__ == "__main__":
    unittest.main()
