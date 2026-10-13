"""Cook a bounded converted-ability experiment; never install or release holds."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = ROOT / "build/abilities"
sys.path.insert(0, str(ROOT / "tools"))
from ability_converter import commands
from ability_converter.catalog import SourceCatalog
from ability_converter.compiler import TableWriter
from ability_converter.runs import implementation_hashes, require_current_run
import make_vision_mod as generator
import ffbe_resonance as sequence
import ffrenv

SKILL_ID = 900010
SOURCE = "JP_2024/magic/10020"
STEM = "zzzzzz_FFRConvertedAbilityProbe_100_P"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def input_hashes():
    inputs = {"tools/ability_converter/"+name: value for name, value in implementation_hashes().items()}
    for path in (Path(__file__), HERE/'source_availability.py', HERE/'life_controls.py', ROOT/"tools/make_vision_mod.py", ROOT/"tools/ffbe_resonance.py", Path(generator.FFRDT[-1]), Path(generator.USMAP), Path(ffrenv.RETOC)):
        inputs[path.relative_to(ROOT).as_posix()] = sha(path)
    return inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=("cure", "fire", "limited", "cooldown"), default="cure")
    parser.add_argument("--fire-phase", choices=("after", "before"), default="after",
                        help="Experimental weakness phase control; never changes the saved source profile")
    parser.add_argument('--owned-source',action='store_true',help='Grant the limited-use fixture through native Rain/Lasswell level tables')
    parser.add_argument('--vision-source',action='store_true',help='Use equipped Amelia/Lia awakening grants instead of actor learning slots')
    parser.add_argument('--life-source',action='store_true',help='Add native death/revival controls to the ordinary ownership fixture')
    parser.add_argument('--multi-command',action='store_true',help='Grant production Fire to Rain for native W Action observation')
    parser.add_argument('--repeat-command',action='store_true',help='Observe native automatic RepeatAction on production Fire')
    parser.add_argument('--repeat-control',action='store_true',help='Build the matching automatic-repeat control without granting its passive')
    parser.add_argument('--repeat-suppressed',action='store_true',help='Keep the repeat passive and exclude Fire through native nonRepeatSkillsIds')
    args = parser.parse_args()
    if args.case != "fire" and args.fire_phase != "after":
        parser.error("--fire-phase applies only to the Fire experiment")
    if args.owned_source and args.case!='limited':parser.error('--owned-source requires the limited-use source case')
    if args.vision_source and not args.owned_source:parser.error('--vision-source requires --owned-source')
    if args.life_source and (not args.owned_source or args.vision_source):parser.error('--life-source requires ordinary --owned-source')
    if args.multi_command and (args.case!='fire' or args.fire_phase!='after' or args.owned_source):parser.error('--multi-command requires ordinary production Fire')
    if args.repeat_command and (args.case!='fire' or args.fire_phase!='after' or args.owned_source or args.multi_command):parser.error('--repeat-command requires ordinary production Fire without another grant fixture')
    if args.repeat_control and not args.repeat_command:parser.error('--repeat-control requires --repeat-command')
    if args.repeat_suppressed and (not args.repeat_command or args.repeat_control):parser.error('--repeat-suppressed requires the active repeat passive')
    source = {'cure':SOURCE,'fire':'JP_2024/magic/20010','limited':'GL_2024/ability/150300','cooldown':'JP_2022/ability/1007200'}[args.case]
    source_case=args.case in ('limited','cooldown')
    row_name = f"FFRConverted{args.case.title()}Probe"
    inputs = input_hashes()
    directory = OUT / (f"converted-{args.case}-fixture-" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f"))
    directory.mkdir()
    manifest_path = OUT / "converted-ability-fixture.json"
    manifest_path.write_text(json.dumps({"status": "building", "directory": str(directory)}), encoding="utf8")
    compiler = commands.converter()
    require_current_run(OUT / "v1", compiler)
    fixture_ids=[SKILL_ID]+([900030,900050] if args.life_source else [])
    assert all(skill not in compiler.native.skill_ids for skill in fixture_ids)
    ledger = json.loads((OUT / "v1/ids.json").read_text(encoding="utf8"))
    assert all(skill not in entries.values() for skill in fixture_ids for entries in ledger.values() if isinstance(entries, dict))
    if args.repeat_command:
        assert 90000 not in compiler.native.passive_ids and 90000 not in ledger['passives'].values()
    with SourceCatalog.open_existing(OUT / "v1/source-index.sqlite") as catalog:
        if source_case:
            from source_availability import source_profile
            original,profile,availability_contract=source_profile(catalog.get(source),catalog,directory)
        else:
            profile = commands.profile(catalog.get(source), catalog)
            original=profile
    (directory / "profile.json").write_text(json.dumps(original, ensure_ascii=False, indent=2), encoding="utf8")
    experiment = None
    if source_case:
        gate=availability_contract['gates']
        assert len(gate)==1 and gate[0]['kind']==args.case
        if args.case=='limited':
            assert gate[0]['maximumUses']==1 and gate[0]['singleCastWhenDualWielding'] and not gate[0]['uniqueSelectionOnMulticast']
        else:
            assert gate[0]['cooldownTurns']==5 and gate[0]['availableOnTurn']==1 and not gate[0]['singleCastWhenDualWielding']
        assert profile['set']['TargetType']=='Self' and profile['set']['DamageType']=='None'
        effects=profile['conversion']['native']['effects']
        assert all(e['set']['EffectType']=='ParameterVariation' for e in effects)
        assert [e['set']['ParamList'][:5] for e in effects]==([[20,4,2,-1,0]] if args.case=='limited' else [[2000,1,0,-1,0],[500,2,0,-1,0]])
        experiment={'productionHold':availability_contract['bindingHold'],'productionSupported':False,
            'releaseAuthorized':False,'sourceRule':gate[0],
            'payloadBinding':'Exact candidate payload, original root cost and generated runtime contract; fixture-only.'}
        profile['fixtureExperiment']=experiment
        (directory/'experimental-profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    if args.case == "fire":
        assert profile["supported"] and not profile["issues"], profile["issues"]
        assert profile["conversion"]["validation"]["tableCompatible"]
        effects = profile["conversion"]["native"]["effects"]
        assert [(e["set"]["EffectType"], e["activeTiming"]) for e in effects] == [
            ("AddElementResistance", "AfterDamageCalculation"), ("ParameterVariation", "AfterDamageCalculation")]
        assert ("ParameterVariation", "AfterDamageCalculation") in commands.damage_phase_evidence()
        # The default Fire fixture now uses the production command profile.
        # The before-damage control remains a disposable, explicit override.
        experiment = {"productionHold": None, "productionSupported": True,
                      "hypothesis": "Enemy fire weakness applies after damage; LB gain targets the caster.",
                      "releaseAuthorized": False, "weaknessPhase": args.fire_phase}
        profile = deepcopy(profile)
        if args.fire_phase == "before":
            profile["conversion"]["native"]["effects"][0]["activeTiming"] = "BeforeDamageCalculation"
        profile["fixtureExperiment"] = experiment
        (directory / "experimental-profile.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf8")
    assert profile["supported"], profile["issues"]
    assert profile["set"]["Cost"] == (0 if source_case else 4)
    assert profile["timeline"]["hitFrames"] == {'cure':[90],'fire':[80],'limited':[10],'cooldown':[60]}[args.case]
    assert profile["set"]["parameterVariationType"] == ("Decrease" if args.case == "fire" else "Increase")
    tables = {}

    def table(relative):
        return tables.setdefault(relative, {"asset": generator.DT + relative, "add": [], "set": []})

    settings = commands.materialize(profile, SKILL_ID, row_name, table, generator.row_by)
    settings.update(ID=SKILL_ID, SortId=SKILL_ID, Name=f"FFBE {'Fill LB' if args.case=='limited' else args.case.title()} — test", Description=profile["description"],
                    belongCommandList=[-1], commandIdBelongDebuggingAllSkills=[-1, -1],
                    playSequencerId=SKILL_ID+1, sequencerIdWhenTargetFriendlies=SKILL_ID+1)
    native_grants=[]
    if args.owned_source or args.multi_command or args.repeat_command:
        # The ordinary command category already exists on both native actors.
        # This replaces an empty learning slot, retaining their stock skills.
        settings['belongCommandList']=[1]
        for unit,name in (((1001,'Rain'),) if args.multi_command or args.repeat_command else ((1001,'Rain'),(1002,'Lasswell'))):
            if args.vision_source:
                vision={1001:13017,1002:13045}[unit]
                relative='Item/Vision/DT_VisionAwakeningMasteryData'
                matches=[(k,v) for k,v in generator.rows(relative).items() if v['ID']==vision and v['Level']==0]
                assert len(matches)==1
                row,data=matches[0];details=deepcopy(data['detailData'])
                assert details[-1]=={'parameterType':'None','params':[-1,-1]}
                details[-1]={'parameterType':'ActiveSkill','params':[SKILL_ID,-1]}
                table(relative)['set'].append({'row':row,'set':{'detailData':details}})
                native_grants.append({'unitId':unit,'visionId':vision,'kind':'vision_mastery','table':relative,
                    'row':row,'level':0,'before':data['detailData'],'after':details})
                continue
            relative=f'Unit/LevelParameter/Playable/DT_UnitLevelParameter{name}'
            row,data=generator.row_by(relative,'Level',1)
            skills=list(data['AddSkills']);assert skills[-1]==-1 and SKILL_ID not in skills
            skills[-1]=SKILL_ID
            if args.life_source:skills.append({1001:900030,1002:900050}[unit])
            if args.repeat_command and not args.repeat_control:skills.append(90000)
            table(relative)['set'].append({'row':row,'set':{'AddSkills':skills}})
            native_grants.append({'unitId':unit,'table':relative,'row':row,'level':1,'before':data['AddSkills'],'after':skills})
    repeat_passive=None
    if args.repeat_command:
        donor,original=generator.row_by('Skill/DT_PassiveSkillData','ID',1414)
        bundle=deepcopy(original['effectBundleList'][0]);bundle['effectId']=1012
        repeat_passive={'id':90000,'templateId':1414,'templateEffectId':1012,'row':'FFRNativeRepeatProbe',
            'set':{'ID':90000,'SortId':90000,'Name':'Native repeat observation',
                   'Description':'Temporary automatic-repeat diagnostic.','effectBundleList':[bundle]}}
        table('Skill/DT_PassiveSkillData')['add'].append({'row':repeat_passive['row'],
            'cloneFrom':donor,'set':repeat_passive['set']})
    if args.repeat_suppressed:
        relative='Skill/Other/DT_SkillGeneralData'
        ids=list(generator.rows(relative)['NewRow']['nonRepeatSkillsIds'])
        assert SKILL_ID not in ids
        table(relative)['set'].append({'row':'NewRow','set':{'nonRepeatSkillsIds':ids+[SKILL_ID]}})
    table("Skill/DT_SkillData")["add"].append({"row": row_name,
        "cloneFrom": profile["conversion"]["native"]["cloneFrom"], "set": settings})
    destination = f"FFRS/Content/Sequencer/Battle/Skill/{SKILL_ID}/{SKILL_ID+1}/SEQ_Battle_{SKILL_ID+1}_Master"
    clones = [{"from": sequence.SHELL, "to": destination,
               "rename": [["SEQ_Battle_440111_Cut_000", f"SEQ_Battle_{SKILL_ID+1}_Master"]]}]
    for relative in ("Asset/Skill/DT_SkillAsset", "Asset/Skill/CDT_SkillAsset_Demo"):
        donor = generator.row_by(relative, "ID", 440111)[0]
        for offset in (1, 2):
            table(relative)["add"].append({"row": f"{row_name}_{offset}", "cloneFrom": donor,
                "set": {"ID": SKILL_ID+offset, "LevelSequence": destination.replace("FFRS/Content/", "/Game/"),
                        "soundSequence": "None", "bChangeNearClipPlane": False}})
    donor = generator.row_by("Battle/Sequencer/DT_BtlHitEffectData", "ID", 449999)[0]
    table("Battle/Sequencer/DT_BtlHitEffectData")["add"].append({"row": row_name, "cloneFrom": donor, "set": {"ID": SKILL_ID}})
    # This fixture uses native Rain's magic_attack motion in a three-second
    # window. It tests the converted reaction frame, not FFBE sprite timing.
    plan = commands.schedule(profile, SKILL_ID, 3.0, "magic_attack")
    life_controls=[]
    if args.life_source:
        from life_controls import add_controls
        life_controls=add_controls(table,clones,profile)
    assets = directory / "assets"
    patch = directory / "patch.json"
    patch.write_text(json.dumps({"legacyRoot": generator.LEGACY, "outRoot": str(assets),
        "tables": [value for value in tables.values() if value["add"] or value["set"]],
        "clones": clones}, ensure_ascii=False, indent=2), encoding="utf8")
    with (directory / "build.log").open("w", encoding="utf8") as log:
        def run(arguments):
            subprocess.run(arguments, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
        run([*generator.FFRDT, "patch", str(patch), "--usmap", generator.USMAP])
        sequence.build({"asset": destination, "plan": plan, "profile": profile, "audio": None},
                       assets, directory, generator.FFRDT, generator.USMAP, run)
        for control in life_controls:
            sequence.build({'asset':control['asset'],'plan':control['plan'],'profile':profile,'audio':None},
                assets,directory,generator.FFRDT,generator.USMAP,run)
        dumped = directory / "cooked-skill-rows.json"
        run([*generator.FFRDT, "rows", str(assets / (generator.DT + "Skill/DT_SkillData.uasset")), str(dumped), "--usmap", generator.USMAP])
        rows = json.loads(dumped.read_text(encoding="utf-8-sig"))["rows"]
        cooked = rows[row_name]
        for field, expected in settings.items():
            if field in ("Name", "Description") or "." in field:
                continue
            assert cooked[field] == expected, (field, cooked[field], expected)
        assert len(rows) == len(compiler.native.skills) + 1 + len(life_controls)
        for control in life_controls:
            expected=deepcopy(generator.row_by('Skill/DT_SkillData','ID',control['templateId'])[1])
            expected.update(control['set'])
            assert all(rows[control['rowName']][key]==value for key,value in expected.items() if key not in ('Name','Description'))
        effect_table = tables.get("Skill/DT_SkillEffectData", {})
        if effect_table.get("add"):
            effect_dump = directory / "cooked-effect-rows.json"
            run([*generator.FFRDT, "rows", str(assets / (generator.DT + "Skill/DT_SkillEffectData.uasset")), str(effect_dump), "--usmap", generator.USMAP])
            effect_rows = json.loads(effect_dump.read_text(encoding="utf-8-sig"))["rows"]
            for added in effect_table["add"]:
                for field, expected in added["set"].items():
                    assert effect_rows[added["row"]][field] == expected, (added["row"], field)
        for grant in native_grants:
            dump=directory/f"cooked-grant-{grant['unitId']}.json"
            run([*generator.FFRDT,'rows',str(assets/(generator.DT+grant['table']+'.uasset')),str(dump),'--usmap',generator.USMAP])
            field='detailData' if args.vision_source else 'AddSkills'
            assert json.loads(dump.read_text(encoding='utf-8-sig'))['rows'][grant['row']][field]==grant['after']
            grant['cookedSha256']=sha(dump)
        if repeat_passive:
            passive_dump=directory/'cooked-repeat-passive.json'
            run([*generator.FFRDT,'rows',str(assets/(generator.DT+'Skill/DT_PassiveSkillData.uasset')),str(passive_dump),'--usmap',generator.USMAP])
            observed=json.loads(passive_dump.read_text(encoding='utf-8-sig'))['rows']
            original=deepcopy(generator.rows('Skill/DT_PassiveSkillData'))
            expected=deepcopy(compiler.native.passives[compiler.native.passive_ids[1414]])
            expected.update(repeat_passive['set'])
            assert all(observed[repeat_passive['row']][k]==v for k,v in expected.items() if k not in ('Name','Description'))
            assert {k:v for k,v in observed.items() if k!=repeat_passive['row']}==original
            repeat_passive['cookedSha256']=sha(passive_dump)
        if args.vision_source or args.repeat_suppressed:
            relative='Skill/Other/DT_SkillGeneralData'
            general_dump=directory/'cooked-general.json'
            run([*generator.FFRDT,'rows',str(assets/(generator.DT+relative+'.uasset')),str(general_dump),'--usmap',generator.USMAP])
            expected=deepcopy(generator.rows(relative))
            for change in tables[relative]['set']:expected[change['row']].update(change['set'])
            assert json.loads(general_dump.read_text(encoding='utf-8-sig'))['rows']==expected
            assert SKILL_ID in expected['NewRow']['equipperActionVisionSkills' if args.vision_source else 'nonRepeatSkillsIds']
        package = directory / (STEM + ".utoc")
        run([ffrenv.RETOC, "to-zen", "--version", "UE5_6", str(assets), str(package)])
    assert input_hashes() == inputs, "Fixture inputs changed during the build"
    files = {str(directory / (STEM+extension)): sha(directory / (STEM+extension)) for extension in (".utoc", ".ucas", ".pak")}
    manifest = {"status": "built", "scope": f"temporary_converted_{args.case}_fixture", "source": source,
        "case": args.case, "experiment": experiment,
        "nativeOwnedSource":args.owned_source,"nativeGrants":native_grants,
        "nativeVisionSource":args.vision_source,
        "nativeLifeSource":args.life_source,"lifeControls":life_controls,
        "nativeMultiCommand":args.multi_command,
        "nativeRepeatCommand":args.repeat_command,"nativeRepeatControl":args.repeat_control,"nativeRepeatPassive":repeat_passive,
        "nativeRepeatSuppressed":args.repeat_suppressed,
        "cookedGeneralSha256":sha(general_dump) if args.vision_source or args.repeat_suppressed else None,
        "skillId": SKILL_ID, "nativeSkillCategory": "ActiveSkill", "rowName": row_name, "directory": str(directory), "inputs": inputs,
        "profileSha256": sha(directory / "profile.json"), "cookedRowsSha256": sha(dumped),
        "availabilityPlanSha256":sha(directory/'availability-plan.json') if source_case else None,
        "sourceContractSha256":sha(directory/'source_contract.lua') if source_case else None,
        "experimentalProfileSha256":sha(directory/'experimental-profile.json') if experiment else None,
        "cookedEffectsSha256": sha(effect_dump) if effect_table.get("add") else None,
        "files": files, "expectedRow": settings, "plan": plan,
        "presentation": "Native Rain magic_attack in a three-second test window; source reaction frame retained.",
        "nativeBattle": "not_run"}
    manifest_path.write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf8")
    print(json.dumps({"status": "built", "source": source, "skillId": SKILL_ID, "cost": settings["Cost"], "files": list(files)}))


if __name__ == "__main__":
    main()
