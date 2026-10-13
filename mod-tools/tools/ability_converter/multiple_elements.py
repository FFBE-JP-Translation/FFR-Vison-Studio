"""One attack retains its elements through private, skill-bound native effects."""
from copy import deepcopy
from .native import ELEMENT_IDS

EVIDENCE = {"templateId":1021,"skillFilterParameter":1,"beforeDispatcher":"0x144f7cdd0",
    "insertionFunction":"0x145223540","elementQuery":"0x145139bf0",
    "elementList":"0x145231510","resistanceSelection":"0x145232a80",
    "expiryDispatcher":"0x144fbe420","runtime":"not_run"}
TARGET = {"shape":"Self","relation":"Friendlies","state":"Alive","ignoreSelf":False,"eitherSide":False}
CHANGE = "All damage elements are retained on one native attack. Temporary caster effects apply only to this skill and expire at skill end. FFR selects the first non-neutral resistance in its native element order; the source hit weights and one damage budget are preserved."


def elements(value):
    value = [value] if isinstance(value,str) else value or []
    return list(dict.fromkeys("Thunder" if e == "Lightning" else e for e in value if e not in ("None",None)))


def evidence(catalog):
    row = catalog.effects[1021]
    expected = {"EffectType":"AddElement","applyTiming":"None","proceedTiming":"None",
        "effectEndActionNum":-1,"statusCondition":"None","ParamList":[1]+[-1]*14,
        "isExecutingReaction":False,"isUnremovable":False,"addProbability":100,"activationProbability":100}
    if any(row[k] != v for k,v in expected.items()) or catalog.inventory["enums"]["eSkillTiming"]["SkillEnd"] != 18:
        raise ValueError("Native skill-bound element evidence changed")
    return deepcopy(EVIDENCE)


def effect(catalog, name, component):
    spec = catalog.effect(1021,[ELEMENT_IDS[name],-1],unremovable=True)
    spec["set"].update(proceedTiming="SkillEnd",effectEndActionNum=1)
    spec.update(component=component,target=deepcopy(TARGET),activeTiming="BeforeDamageCalculation",
                skillElement={"element":name,"binding":"owner_skill","nativeEvidence":evidence(catalog)})
    return spec


def prepare(catalog, result, primary, names):
    if len(names) <= 1:
        return None, []
    if primary["kind"] != "damage" or primary.get("calc",primary["damageType"]) not in ("Physic","Magic"):
        raise ValueError("Multiple elements require a native physical or magical damage formula")
    if any(name not in ELEMENT_IDS for name in names):
        raise ValueError("Unknown source element")
    binding = {"elements":deepcopy(names),"nativeEvidence":evidence(catalog)}
    if CHANGE not in result["changes"]:
        result["changes"].append(CHANGE)
    return binding,[effect(catalog,name,primary["component"]) for name in names[1:]]


def validate(catalog, result):
    native = result["native"]
    actions = [a for c in result["components"] for a in c["actions"]]
    lists = [elements(a.get("elements",result["sourceMetadata"].get("element_inflict"))) if a['kind'] == 'damage' else [] for a in actions]
    multiple = [names for names in lists if len(names)>1]
    specs = [e for e in native["effects"] if "skillElement" in e]
    jobs = [native, *native.get('applications', [])]
    if not multiple and not specs and not any(j.get('multipleElements') for j in jobs):
        return
    if not multiple:
        raise ValueError('Skill-bound elements require their source damage elements')
    if native.get('applications'):
        from .applications import source_owners
        owners=source_owners(result)
    else:
        if any(names != multiple[0] for names in lists):
            raise ValueError('One native damage row must share its source elements')
        owners = [0]
    expected = []
    for ordinal,(job,index) in enumerate(zip(jobs,owners)):
        names = lists[index]
        binding = {'elements':names,'nativeEvidence':evidence(catalog)} if len(names)>1 else None
        row = job['set']
        if (job.get('multipleElements') != binding or row['element'] != (names[0] if names else 'None')
                or binding and (row['parameterVariationType'] != 'Decrease' or row['damageCalcType'] not in ('Physic','Magic'))):
            raise ValueError('Multiple elements require the complete source application binding')
        for name in names[1:]:
            spec = effect(catalog,name,actions[index]['component'])
            if ordinal:
                spec['skillElement'].update(binding='application_skill',applicationIndex=ordinal)
            expected.append(spec)
    if specs != expected:
        raise ValueError("Multiple elements require their complete skill-bound, before-damage contract")
    # Generated element effects remain top-level; nested packing cannot hide a
    # skill-ID binding or change its application phase.
    def nested(spec):
        for child in [*spec.get("children",[]),*spec.get("randomChoices",[])]:
            if "skillElement" in child:
                raise ValueError("Skill-bound elements cannot be nested inside support effects")
            nested(child)
    for spec in native["effects"]:
        nested(spec)
