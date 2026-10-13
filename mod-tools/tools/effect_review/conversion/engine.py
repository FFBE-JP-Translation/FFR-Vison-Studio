"""Whole-record drafts with independent component retention and full trace."""
from copy import deepcopy
from dataclasses import replace
import re
from tools.ability_converter.compiler import Converter, TableWriter
from tools.ability_converter.adapters import integer
from .adapters import ReviewedAdapter

ERRORS = (ValueError, TypeError, KeyError, IndexError, OverflowError)
# Structured source opcodes with direct damage/recovery timing, including held
# formulas. Keeping these slots avoids shifting compact frames after an omission.
ACTION_CODES = {1,2,9,10,11,13,15,21,22,23,25,38,39,40,41,42,43,72,74,79,80,83,86,102,103,105,113,124,126,131,134,159,169,1007,1016,1024}


def useful(component):
    return bool(component['effects'] or component['actions'])


def discard(component, reasons, kind='unsupported'):
    component.setdefault('omissions',[]).extend({'kind':kind,'reason':reason} for reason in reasons)
    if useful(component):
        component.setdefault('discardedCandidate',{'effects':component['effects'],'actions':component['actions']})
    component['effects']=[];component['actions']=[];component['issues']=[];component['status']='noop'


class ReviewedConverter(Converter):
    def __init__(self, rules, **kwargs):
        super().__init__(**kwargs)
        self.rules=rules
        self.adapters=ReviewedAdapter(self.native,self.registry,rules)

    def convert(self, record, _stack=()):
        # Item-heal notes remove inventory costs only when every active
        # non-placeholder component belongs to the reviewed item-heal family.
        original=record
        raws=record.data.get('effects_raw') or []
        item_heal=bool(raws) and all(isinstance(r,list) and len(r)==4 and r[2] in (0,16,17) for r in raws)
        if item_heal and isinstance(record.data.get('cost'),dict):
            data=deepcopy(record.data)
            data['cost']={k:v for k,v in data['cost'].items() if k in ('MP','LB','EV','EP')}
            record=replace(record,data=data)
        result=super().convert(record,_stack)
        # The inherited compiler records component problems before assembly.
        # Keep them in the component trace, not as an ability-wide veto.
        result['issues']=[i for i in result['issues'] if not i.startswith('Component ')]
        for component in result['components']:
            if component['issues']:discard(component,list(component['issues']))
            for dep in component['dependencies']:
                if not dep.get('resolved') and self.resolver:
                    try:dep['resolved']=self.resolver.resolve(original.provenance(),dep).key
                    except ERRORS as ex:dep['resolutionIssue']=str(ex)
        result['sourceMetadata']={k:deepcopy(v) for k,v in original.data.items() if k not in ('effects_raw','levels')}
        result['sourceRaw']=deepcopy(original.data.get('effects_raw'))
        if item_heal and record is not original:
            result['changes'].append('Inventory item consumption is removed per the fixed-recovery notes; MP/LB/esper costs remain separately accounted for.')
        # Charge metadata governs the same body; removing only that clause
        # would inadvertently make an otherwise limited skill unlimited.
        for c in result['components']:
            if c.get('key')=='active:1014' and c.get('params') and str(c['params'][0])==original.id:
                result['issues'].append('The move has a self charge/use gate; no reviewed rule authorizes removing this non-cooldown restriction.')
        if original.kind=='field':
            result['issues'].append('Standalone field has no recipient-side and aura-removal binding; see decoded components.')
        omissions=[{'component':c['index'],'effect':c.get('key'),**o} for c in result['components'] for o in c.get('omissions',[])]
        result['omissions']=omissions
        result['changes']=list(dict.fromkeys([*result['changes'],*[v for c in result['components'] for v in c['changes']]]))
        result['issues']=list(dict.fromkeys(result['issues']))
        has_output=bool(result['native']) and any(useful(c) for c in result['components'])
        good=has_output and not result['issues']
        if not has_output and not result['issues']:
            result['issues'].append('No useful compatible component remains after the reviewed drops and conversion checks.')
        result['outcome']='good' if good else 'bad'
        result['partial']=good and bool(omissions)
        result['status']='partial' if result['partial'] else 'adapted' if good else 'blocked'
        result['validation'].update(tableCompatible=good,runtime='not_run',finalUnitIntegration='not_created')
        result['componentAccounting']={'total':len(result['components']),
            'retained':sum(useful(c) for c in result['components']),
            'omitted':sum(not useful(c) for c in result['components']),
            'withOmissions':sum(bool(c.get('omissions')) for c in result['components'])}
        result['summary']=describe(result)
        return result

    def expand(self, record, component, stack):
        super().expand(record,component,stack)
        child=component.get('expanded')
        if child and child.get('omissions') and not component['issues']:
            component.setdefault('omissions',[]).extend({'kind':'child_subpart','reason':f"Child {child['source']['key']} / {o.get('effect')}: {o['reason']}"} for o in child['omissions'])
        if component['issues']:discard(component,list(component['issues']))

    def assemble(self,record,result):
        components=result['components']
        for c in components:
            for spec in list(c['effects']):
                automatic=spec.get('automaticPassive')
                if automatic and automatic['code']==66 and has_recovery(automatic['child']):
                    child=automatic['child']
                    effects=[e for part in child['components'] for e in part['effects']]
                    pure=effects and all(e['set']['EffectType']=='ParameterVariation' and e['set']['ParamList'][1] in (2,4) for e in effects) and not any(part['actions'] for part in child['components'])
                    if pure and spec['set']['activationProbability']==100:
                        from tools.ability_converter.automatic_passives import decode,bind
                        scratch=deepcopy(c);scratch['code']=103;scratch['params']=[int(automatic['parameters'][0]),0,0]
                        scratch['semantic'],scratch['issues']=decode(103,scratch['params']);scratch['effects']=[]
                        bind(self,record,scratch,(record.key,))
                        if scratch['issues']:discard(c,scratch['issues'])
                        else:
                            c['effects']=scratch['effects']
                            c['changes'].append('Recurring MP/resonance autocast becomes one battle-start action; source trigger remains in the raw trace.')
                    else:
                        discard(c,['Recurring automatic recovery has mixed payload or a conditional trigger; a one-shot split is not bound.'],'unsupported_trigger')
        original_actions=[a for c in components for a in c['actions']]
        # Synthetic immediate replacements and already expanded timelines
        # must not change how the remaining source compact arrays are indexed.
        known={a['component'] for a in original_actions}
        slots=[*original_actions]
        for c in components:
            if c['index'] not in known and c.get('namespace')=='active' and c.get('code') in ACTION_CODES:
                slots.append({'component':c['index']})
        slots.sort(key=lambda a:a['component'])
        # Compute all bindings before adding timing to any action: adding one
        # at a time changes the inherited compact-array ambiguity checks.
        naked=[{k:v for k,v in a.items() if k!='timing'} for a in slots]
        bindings={id(a):deepcopy(a['timing']) if 'timing' in a else self.action_timing(record,naked,naked[pos]) for pos,a in enumerate(slots)}
        for a in original_actions:a['timing']=bindings[id(a)]
        for c in components:
            if c['issues']:
                discard(c,list(c['issues']));continue
            try:
                for a in c['actions']:self.timing(record,[a])
                for e in c['effects']:self.native.validate_effect(e)
            except ERRORS as ex:discard(c,[str(ex)],'invalid_component')
        if not any(useful(c) for c in components):raise ValueError('No useful compatible component remains after conversion checks.')
        try:
            return super().assemble(record,result)
        except ERRORS as initial:
            # A malformed or independently incompatible component cannot
            # erase its siblings. Check each independently, then compose in
            # original order. Every combination failure is visible as a drop.
            selected=[];native=None
            for c in components:
                if not useful(c):continue
                trial={**result,'components':[*selected,c]}
                try:
                    candidate=super().assemble(record,trial)
                except ERRORS as ex:
                    discard(c,[f'Cannot compose this component with the retained move: {ex}'],'composition')
                else:
                    selected.append(c);native=candidate
            if native is None:
                result.setdefault('assemblyDiagnostics',[]).append(str(initial))
                raise ValueError('No independently valid component could be assembled.')
            return native


def describe(result):
    if result.get('native') and any(useful(c) for c in result['components']):
        try:
            description=TableWriter.description(result)
            if any(e.get('nativeSkillEvidence')==400660 for c in result['components'] for e in c['effects']):
                description=description.replace('Reduces MP costs for the user by -50%.','')
                description='Magic Boost: the next magic attack deals 100% more damage, with its native 150% MP-cost modifier. '+description
            description=re.sub(r'Reduces (.*?) by -(\d+)%\.',r'Increases \1 by \2%.',description)
            return description.strip()
        except ERRORS:pass
    reasons=[*[i for i in result['issues'] if not i.startswith('No useful') and not i.startswith('No independently')],
             *[o['reason'] for o in result.get('omissions',[])],*result['issues']]
    return reasons[0] if reasons else 'No useful native output.'


def has_recovery(value):
    if isinstance(value,dict):
        row=value.get('set',{})
        if row.get('EffectType')=='ParameterVariation' and row.get('ParamList',[0,0])[1] in (2,4):return True
        return any(has_recovery(v) for v in value.values())
    if isinstance(value,list):return any(has_recovery(v) for v in value)
    return False
