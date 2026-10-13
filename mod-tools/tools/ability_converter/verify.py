"""Round-trip representative conversions through the repository's FFR patcher."""
import json
from pathlib import Path
import subprocess

from .compiler import TableWriter
from .sources import ROOT, read
from .runs import require_current_run


def verify(converter, output, maximum=256):
    require_current_run(output, converter)
    import ffrenv
    from verify_mod import equivalent
    output = Path(output)
    work = output/"verification"
    work.mkdir(parents=True,exist_ok=True)
    writer = TableWriter(converter.native, read(output/"ids.json"))
    selected, covered, acceptance = [], set(), set()
    from .commands import damage_phase_evidence
    recovery_phases = damage_phase_evidence("Increase")
    with (output/"converted.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            result = json.loads(line)
            if not result["validation"]["tableCompatible"]:
                continue
            codes = {c.get("key") for c in result["components"]}
            for component in result["components"]:
                if (component.get("key") in ("passive:11","passive:75")
                        and len(component["semantic"].get("sourceEntries",[]))>1
                        and any(not isinstance(value,list) for value in
                            (component["params"][1:3] if component["key"]=="passive:11" else component["params"][2:4]))):
                    codes.add("killer-layout:shared-scalar:"+component["key"])
                semantic = component["semantic"]
                if semantic.get('kind') == 'imbue':
                    codes.update(('imbue:count:'+str(sum(bool(v) for v in semantic['chances'])),
                        'imbue:turns:'+str(semantic['turns']), 'imbue:layout:'+str(len(component['params'])),
                        'imbue:source-kind:'+result['source']['kind']))
                    codes.update('imbue:chance:'+str(v) for v in semantic['chances'] if v)
                if semantic.get("kind") == "stop":
                    codes.update(("stop:chance:"+str(semantic["chance"]),"stop:turns:"+str(semantic["turns"]),
                                  "stop:layout:"+str(len(component["params"]))))
                if semantic.get("kind") == "dispel" and semantic.get("replacement") == "native_status_allowlists":
                    codes.add("dispel:selection:"+str(semantic["selection"]))
                    codes.add("dispel:layout:"+str(len(component["params"])))
                if semantic.get("kind") == "reraise":
                    codes.update(("reraise:hp:"+str(semantic["hpPercent"]), "reraise:turns:"+str(semantic["turns"]),
                                  "reraise:layout:"+str(len(component["params"]))))
                if semantic.get("kind") == "random_status_selection" and semantic.get("selection"):
                    codes.add("random-ailments:"+semantic["selection"]+":"+str(sum(bool(v) for v in semantic["chances"])))
                    if semantic['selection']=='ordered_capped_outcomes':
                        codes.add('random-ailments:ordered-cap:'+str(semantic['maximum']))
                        codes.add('random-ailments:ordered-chance:'+('partial' if any(v not in (0,100) for v in semantic['chances']) else 'guaranteed'))
                        codes.add('random-ailments:ordered-source-kind:'+result['source']['kind'])
                    if semantic["chances"][6]:
                        codes.add("random-ailments:paired-disease:"+semantic["selection"])
                if semantic.get("kind") in ("encounter_rate","reward_multiplier","preemptive_protection","steal_success_bonus","item_drop_bonus"):
                    codes.add("passive-rate:"+component["key"]+":"+str(semantic.get("nativePercent",semantic.get("nativeParameter",semantic.get("nativeBonusPercent",semantic.get("chance"))))))
            codes.update(f"cost:{c['costType']}:{c['Cost']}" for c in result.get("resourceCosts", []))
            category = result["source"]["kind"]
            codes.add("source-kind:"+category)
            settings = result["native"]["set"]
            for index,job in enumerate([result['native'],*result['native'].get('applications',[])]):
                if tag := job.get('tagAttack'):
                    codes.update(('tag:bonus:'+str(tag['bonusPercent']),'tag:formula:'+job['set']['damageCalcType'],
                        'tag:source-kind:'+category,'tag:target:'+job['set']['TargetType'],
                        'tag:binding:'+('child' if index else 'primary')))
                    if any(g['source']!=result['source']['key'] for g in tag['sourceGrants']):codes.add('tag:source:proxy')
                if multiple := job.get('multipleElements'):
                    codes.update(("multiple-elements:count:"+str(len(multiple["elements"])),
                        "multiple-elements:formula:"+job['set']["damageCalcType"],
                        "multiple-elements:source-kind:"+category,
                        "multiple-elements:target:"+job['set']["TargetType"]))
                    if result['native'].get('applications'):
                        codes.add('multiple-elements:application:'+('child' if index else 'primary'))
            if settings.get("TargetType") == "All":
                codes.add("all-targets:"+settings["parameterVariationType"]+":"+settings["DamageType"])
                codes.add("all-targets:source-kind:"+category)
                for effect in result["native"]["effects"]:
                    if effect["target"]["shape"] == "All":
                        codes.add("all-targets:effect:"+effect["set"]["EffectType"])
            if applications := result["native"].get("applications"):
                rows = [settings, *[job["set"] for job in applications]]
                codes.add("composition:formulas:"+"+".join(sorted({r["damageCalcType"] for r in rows})))
                codes.add("composition:elements:"+"+".join(sorted({r["element"] for r in rows})))
                codes.add("composition:kind:"+category)
                codes.add("composition:hits:"+str(len(rows)))
                codes.add("composition:variations:"+"+".join(sorted({r["parameterVariationType"] for r in rows})))
                for r in rows:
                    codes.add("composition:recipients:"+r["parameterVariationType"]+":"+r["TargetType"]+":"+r["defaultTargetRelation"])
            if settings.get("hitCount",0) > 30:
                codes.add("extended-hit-count:"+str(settings["hitCount"]))
            for job in (result["native"].get("sequence") or {}).get("components",[]):
                binding = job.get("timingBinding") or {}
                if binding.get("layout"):
                    codes.add("timing-layout:"+binding["layout"])
            if settings.get("isTargetIgnoreSelf"):
                codes.add("target-filter:"+settings["TargetType"]+":"+settings["defaultTargetState"])
            if category != "passive" and settings["TargetType"] != "Self" and not settings["isSameRelationTargetingDisabled"] and not settings["isHostilityRelationTargetingDisabled"]:
                codes.add("target-side:both:"+settings["TargetType"]+":"+settings["defaultTargetState"])
            for effect in result["native"]["effects"]:
                from .automatic_passives import coverage as automatic_coverage
                codes.update(automatic_coverage(effect))
                from .delayed_actions import coverage as delayed_coverage
                if delayed_codes:=delayed_coverage(effect):
                    codes.update(delayed_codes)
                    codes.add('delayed:source-kind:'+category)
                if effect.get('tagAttack'):
                    codes.add('tag:filter-count:'+str(len(effect['tagAttack']['applicationIndices'])))
                phase = effect["set"]["EffectType"], effect.get("activeTiming", "AfterDamageCalculation")
                if settings.get("skillEffectType") == "DamageAndRecovery" and settings.get("parameterVariationType") == "Increase" and phase in recovery_phases:
                    codes.add("recovery-phase:"+":".join(phase))
                if effect.get("targetBinding"):
                    codes.add("target-binding:"+effect["targetBinding"]+":"+effect["target"]["shape"])
            if category=='passive':
                codes.add('passive-bundle-count:'+str(len(result['native']['effects'])))
                codes.add('passive-timings:'+'+'.join(sorted({e.get('passiveTiming','SpawnUnit') for e in result['native']['effects']})))
            forced = category == "lb" and result["source"]["id"] == "313000206" and "agnes" not in acceptance
            if not codes-covered and not forced:
                continue
            if forced:
                acceptance.add("agnes")
            writer.add(result)
            covered.update(codes)
            covered.add(category)
            selected.append(result["source"]["key"])
            if len(selected) >= maximum:
                break
    if not selected:
        raise ValueError("No compatible entries available for native verification")
    patch = writer.patch(work/"assets")
    recipe = work/"patch.json"
    recipe.write_text(json.dumps(patch,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    log = []
    def run(arguments):
        process = subprocess.run(ffrenv.FFRDT+arguments,capture_output=True,text=True,encoding="utf-8",errors="replace")
        log.append(process.stdout+process.stderr)
        (work/"patcher.log").write_text("\n".join(log),encoding="utf-8")
        if process.returncode:
            raise ValueError(f"ffr-dt failed; see {work/'patcher.log'}: {process.stderr[-700:]}")
    run(["patch",str(recipe),"--usmap",str(ROOT/"extracted/Mappings.usmap")])
    issues, checked = [], 0
    for changes in patch["tables"]:
        table = changes["asset"].removeprefix("FFRS/Content/Datatable/")
        dumped = work/(table.replace("/","_")+".json")
        asset = work/"assets/FFRS/Content/Datatable"/(table+".uasset")
        run(["rows",str(asset),str(dumped),"--usmap",str(ROOT/"extracted/Mappings.usmap")])
        actual = read(dumped)["rows"]
        original = read(ROOT/"extracted/rows"/(table+".json"))["rows"]
        modified = {r["row"]:r["set"] for r in changes.get("set", [])}
        for name, old in original.items():
            excluded = modified.get(name,{})
            untouched = {k:v for k,v in old.items() if k not in excluded}
            observed = {k:v for k,v in actual.get(name,{}).items() if k not in excluded}
            if name not in actual or not equivalent(untouched,observed):
                issues.append(f"Native row changed: {table}/{name}")
            # General-list updates must preserve every stock list entry before
            # appending converted IDs/costs. Other stock fields stay untouched.
            for field, expected in excluded.items():
                if not isinstance(old[field],list) or expected[:len(old[field])] != old[field]:
                    issues.append(f"Native general entries overwritten: {table}/{name}/{field}")
        for patch_row in changes.get("add", [])+changes.get("set", []):
            built = actual.get(patch_row["row"])
            if built is None:
                issues.append(f"Missing converted row: {patch_row['row']}")
                continue
            for key, expected in patch_row["set"].items():
                observed = built
                for segment in key.split("."):
                    observed = observed.get(segment) if isinstance(observed,dict) else None
                if key in ("Name","Description") and isinstance(observed,dict):
                    observed = observed.get("text")
                if not close(expected,observed):
                    issues.append(f"{table}/{patch_row['row']}/{key}: expected {expected!r}, got {observed!r}")
            checked += 1
    report = {"sourceAbilities":len(selected),"nativeRows":checked,"selected":selected,"acceptance":sorted(acceptance),
              "coveredOpcodes":sorted(v for v in covered if v and v.startswith(("active:","passive:","field:"))),
              "coveredCosts":sorted(v for v in covered if v and v.startswith("cost:")),"issues":issues,
              "coveredSourceKinds":sorted(v.removeprefix("source-kind:") for v in covered if v.startswith("source-kind:")),
              "coveredTargetBindings":sorted(v for v in covered if v.startswith(("target-filter:","target-binding:","target-side:"))),
              "coveredKillerLayouts":sorted(v for v in covered if v.startswith("killer-layout:")),
              "coveredRateCases":sorted(v for v in covered if v.startswith("passive-rate:")),
              "coveredTimingLayouts":sorted(v for v in covered if v.startswith("timing-layout:")),
              "coveredExtendedHitCounts":sorted(int(v.removeprefix("extended-hit-count:")) for v in covered if v.startswith("extended-hit-count:")),
              "coveredRecoveryPhases":sorted(v for v in covered if v.startswith("recovery-phase:")),
              "coveredCompositions":sorted(v for v in covered if v.startswith("composition:")),
              "coveredReraise":sorted(v for v in covered if v.startswith("reraise:")),
              "coveredStop":sorted(v for v in covered if v.startswith("stop:")),
              "coveredAllTargets":sorted(v for v in covered if v.startswith("all-targets:")),
              "coveredMultipleElements":sorted(v for v in covered if v.startswith("multiple-elements:")),
              "coveredImbues":sorted(v for v in covered if v.startswith('imbue:')),
              'coveredTagAttacks':sorted(v for v in covered if v.startswith('tag:')),
              'coveredDelayedActions':sorted(v for v in covered if v.startswith('delayed:')),
              'coveredAutomaticPassives':sorted(v for v in covered if v.startswith('automatic-passive:')),
              'coveredPassiveBundleCounts':sorted(int(v.removeprefix('passive-bundle-count:')) for v in covered if v.startswith('passive-bundle-count:')),
              'coveredPassiveTimings':sorted(v.removeprefix('passive-timings:') for v in covered if v.startswith('passive-timings:')),
              "coveredDispel":sorted(v for v in covered if v.startswith("dispel:")),
              "coveredRandomAilments":sorted(v for v in covered if v.startswith("random-ailments:")),
              "tableRoundTrip":"passed" if not issues else "failed","runtime":"not_run"}
    (output/"verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    summary_path = output/"report.json"
    if summary_path.exists():
        summary = read(summary_path)
        summary["validation"]["nativeRoundTrip"] = {k:report[k] for k in ("sourceAbilities","nativeRows","tableRoundTrip")}
        summary_path.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if issues:
        raise ValueError(f"Native round-trip failed: {len(issues)} differences; see {output/'verification.json'}")
    return report


def close(expected,observed):
    if isinstance(expected,dict) and isinstance(observed,dict):
        return expected.keys() == observed.keys() and all(close(v,observed[k]) for k,v in expected.items())
    if isinstance(expected,list) and isinstance(observed,list):
        return len(expected) == len(observed) and all(close(a,b) for a,b in zip(expected,observed))
    if type(expected) in (int,float) and type(observed) in (int,float):
        return abs(expected-observed) <= max(1e-6,abs(expected)*1e-6)
    if isinstance(observed,str) and observed in ("+0","-0") and type(expected) in (int,float):
        return expected == 0
    return expected == observed
