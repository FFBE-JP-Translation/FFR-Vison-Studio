"""Reviewed opcode overrides layered on the complete existing decoders."""
from copy import deepcopy
from tools.ability_converter.adapters import ComponentAdapter, Context, integer, number, target
from tools.ability_converter.availability import decode
from tools.ability_converter import multicast


def omit_part(c, reason):
    c.r.setdefault('omissions', []).append({'kind':'subpart', 'reason':reason})


def magic_type(record):
    values = [record.kind, record.data.get('type'), record.data.get('attack_type'), record.data.get('damage_type'), record.data.get('magic_type')]
    return 'Magic' if any(isinstance(v,str) and v.lower() in ('magic','magical','black','white','green','blue') for v in values) else 'Physic'


class ReviewedAdapter(ComponentAdapter):
    def __init__(self, native, registry, rules):
        super().__init__(native, registry)
        self.rules = rules

    def convert(self, record, raw, index):
        key = None
        if isinstance(raw,list) and len(raw)==(3 if record.namespace=='field' else 4) and type(raw[-2]) is int:
            key = f'{record.namespace}:{raw[-2]}'
        rule = self.rules.get(key)
        if multicast.component(record.namespace, raw):
            result = {'index':index,'raw':deepcopy(raw),'key':key,'namespace':record.namespace,'code':raw[-2],
                'params':raw[-1], 'status':'noop', 'effects':[], 'actions':[], 'dependencies':[],
                'issues':[], 'changes':[multicast.REASON], 'semantic':{'kind':'disabled_multicast'},
                'omissions':[{'kind':'disabled_multicast','reason':multicast.REASON}]}
        elif rule and rule['mode'] in ('drop','drop_unused','unresolved') or key == 'active:73':
            requested = key == 'active:73'
            unresolved = requested or rule['mode']=='unresolved'
            reason = rule['implementation'] if requested else 'Other has no executable mapping or notes.' if unresolved else 'Dropped by your saved effect choice.'
            result = {'index':index,'raw':deepcopy(raw),'key':key,'namespace':record.namespace,'code':raw[-2],
                'params':raw[-1], 'status':'blocked' if unresolved else 'noop', 'effects':[], 'actions':[], 'dependencies':[],
                'issues':[reason] if unresolved else [], 'changes':[], 'semantic':{'kind':'requested_random_ffr_skill' if requested else 'review_choice'},
                'omissions':[] if unresolved else [{'kind':'chosen_drop','reason':reason}]}
        elif rule and rule['effectiveTargets'] != rule['defaultTargets'] and rule['mode'] != 'override':
            result = super().convert(record,raw,index)
            result['issues'].append('Changed destination needs a specific parameter adapter; the old proposal was not substituted.')
            result['status']='blocked'
        else:
            result = super().convert(record, raw, index)
        if rule:
            result['review'] = {'targets':rule['effectiveTargets'], 'notes':rule['savedDecision']['notes'], 'mode':rule['mode']}
        else:
            result['issues'].append('No reviewed rule matches this raw component.')
            result['status']='blocked'
        # Never let a legacy helper accidentally retain repeating MP/LB ticks.
        for spec in result['effects']:
            self.instant_resources(spec, record, result)
        return result

    def instant_resources(self, spec, record, component):
        settings = spec['set']; p = settings['ParamList']
        if (settings['EffectType']=='LimitBurstPointDistribute' or settings['EffectType']=='ParameterVariation' and p[1]==4) and spec['target']['relation']=='Enemies':
            spec['target']['relation']='Friendlies'
            component['changes'].append('Enemy-targeted source LB refill is routed to main-cast allies, preserving single/group scope, per the all-LB-refill rule.')
        if settings['EffectType']=='ParameterVariation' and p[1] in (1,2,4) and p[0]==0:
            # Context.recover emits nothing for an actual source zero. A row
            # reaching here was a nonzero normalized fraction rounded to zero.
            p[0]=1
            component['changes'].append('Nonzero recovery that rounds below one native point uses a minimum of one; it cannot become a misleading zero-recovery output.')
        if settings['EffectType']=='ParameterVariation' and p[1] in (2,4):
            repeated = settings['applyTiming'] in ('EndTurn','BeginTurn') or settings['proceedTiming'] in ('EndTurn','BeginTurn')
            settings.update(applyTiming='AddEffect',proceedTiming='AddEffect',effectEndActionNum=1)
            if record.namespace=='passive':
                spec['passiveTiming']='BeginBattle'
            spec['resourceBinding']={'resource':'resonance' if p[1]==4 else 'MP', 'owner':'equipping_main_cast',
                'recipients':'main_cast_in_source_scope' if p[1]==4 else 'source_recipients', 'activation':'battle_start_once' if record.namespace=='passive' else 'once_on_use'}
            if repeated:
                component['changes'].append('Repeated MP/resonance recovery becomes one immediate recovery; passive activation is battle start only.')
        if settings['EffectType']=='LimitBurstPointDistribute':
            spec['resourceBinding']={'resource':'resonance','owner':'equipping_main_cast','recipients':'main_cast_in_source_scope','activation':'once_on_use','donorPays':True}
        for child in [*spec.get('children',[]),*spec.get('randomChoices',[])]:
            self.instant_resources(child,record,component)

    def active(self, c):
        code,p = c.code,c.p
        if code == 130:
            gate=decode(130,p,c.record.id)
            c.r['semantic']={'kind':'normal_cooldown','mode':'inline','removedAvailability':gate}
            c.r['dependencies']=[{'id':gate['childId'],'kind':'skill','relation':'child','condition':{},'removedRelation':'cooldown'}]
            c.change('Cooldown and initial-turn availability are removed; this is an ordinary move.')
            # Some exports attach self cooldown metadata to the body itself.
            if gate['childId']==c.record.id:
                c.r['dependencies']=[];c.r['semantic'].pop('mode');c.r['status']='noop'
        elif code in (8,56):
            integer(c.n(3),'source recovery duration',-1);c.heal(c.n(2),c.n(0)/100)
            c.change('Recovery is applied once on use; duration and song/dance channel lock are removed.')
            omit_part(c,'Requested consecutive-use healing growth has no verified native recovery-scaling binding; the initial heal is retained.')
        elif code in (30,57):
            integer(c.n(3),'source recovery duration',-1);c.recover(c.n(2),2,ratio=False)
            c.change('One immediate recovery uses the source total fixed MP amount, normalized by / 2. Repeated ticks and channel lock are removed.')
            if c.n(0):omit_part(c,'MAG/SPR scaling of MP recovery has no verified native formula; only the fixed MP part remains.')
            if code==57:omit_part(c,'Requested consecutive-use MP growth is not bound; the initial fixed recovery is retained.')
        elif code == 131:
            turns=c.turn(3)
            if c.n(1):c.damage(c.n(1)*turns/100,'Magic')
            c.change('Damage song applies its total source modifier immediately; channel lock and repeated turns are removed.')
            if c.r['actions']:c.r['actions'][-1]['timing']={'frames':[0],'weights':[1.0],'binding':{'layout':'reviewed_immediate_song'}}
            omit_part(c,'Requested consecutive-use growth requires a destination skill reference and a reviewed scaling curve; initial damage is retained.')
        elif code in (36,58):
            super().active(c)
            if c.r['effects']:omit_part(c,'Requested consecutive-use buff/debuff growth has no verified native stat-effect scaling binding; the initial effect is retained.')
        elif code == 9:
            fraction=c.percent(0)/100
            c.damage(fraction,magic_type(c.record))
            c.r['actions'][-1]['timing']={'frames':[0],'weights':[1.0],'binding':{'layout':'reviewed_normal_damage_fallback'}}
            c.replace('Ordinary damage','Percentage-HP damage becomes an ordinary attack. Source fraction becomes its base multiplier; magic/physical follows structured skill type.')
        elif code == 13:
            if len(p)!=6 or p[1:3]!=[0,0] or p[3] not in (1,2):raise ValueError('Unknown delayed-damage parameter controls')
            c.damage(c.n(5)/100,magic_type(c.record))
            c.r['actions'][-1]['timing']={'frames':[0],'weights':[1.0],'binding':{'layout':'reviewed_immediate_delayed_damage'}}
            c.replace('Damage on use','Delayed damage uses the reviewed ordinary-damage fallback immediately, with its decoded source multiplier.')
        elif code == 20:
            c.r['target']=target([0,3],'active')
            row=c.native.skills[c.native.skill_ids[400660]]
            for bundle in row['effectBundleList']:
                if bundle['effectId']<0:continue
                spec=c.effect(bundle['effectId'])
                spec['activeTiming']=bundle['activeSkillAddTiming'];spec['nativeSkillEvidence']=400660
            c.replace('Magic Boost','Uses native Fina Magic Boost: next magic damage +100% with its native 150% MP-cost modifier. Original charge formula is replaced.')
        elif code == 21:
            c.damage(c.n(2)/100,'Physic');c.change('Ignore-DEF clause removed; normal physical defense calculation applies.')
        elif code in (22,23):
            if len(p)!=4:raise ValueError('Race damage requires four parameters')
            c.damage(1,'Physic' if code==22 else 'Magic')
            c.change('Keeps the ordinary 1x base attack; race checks and race-only bonuses are removed per your note.')
        elif code == 27:
            super().active(c)
            if c.r['issues']:
                reasons=list(c.r['issues']);c.r['issues']=[];c.r['effects']=[]
                c.effect(1063,[c.percent(0)],state='Dead')
                c.r['semantic']={'kind':'revival','reraiseFallbackReasons':reasons}
                c.replace('Raise','Auto-raise uses the reviewed normal Raise fallback and retains the decoded recovery percentage.')
        elif code == 31:
            if p not in (['none'],[0],[]):raise ValueError('Unknown Entrust parameter layout')
            c.effect(1003)
            c.change('Native Entrust transfers the equipping main-cast actor’s resonance to the selected recipient, consuming the donor gauge.')
        elif code == 74:
            c.damage(1,'Magic')
            c.r['actions'][-1]['timing']={'frames':[0],'weights':[1.0],'binding':{'layout':'reviewed_magic_replacement'}}
            c.replace('Magic attack','Your magical-damage replacement uses an explicit 1x base and one hit; source parameters have no established damage decoder.')
        elif code == 1003:
            if len(p)!=2 or p[0]!=0:raise ValueError('Unknown percentage gauge-change controls')
            c.recover(c.percent(1),4)
            c.change('LB gauge recovery becomes one percentage recovery of main-cast resonance.')
        elif code in (64,65):
            if len(p)!=2:raise ValueError('Combined HP/MP recovery requires two independent resource amounts')
            for i,label in enumerate(('HP','MP')):
                try:c.recover(c.n(i),i+1,ratio=code==64)
                except (ValueError,TypeError,IndexError) as ex:omit_part(c,f'{label} portion omitted: {ex}')
        else:
            super().active(c)

    def passive(self,c):
        if c.code in (32,33):
            c.recover(min(5,c.n(0)/(100 if c.code==33 else 1)),4 if c.code==33 else 2)
            for effect in c.r['effects']:effect['passiveTiming']='BeginBattle'
            c.change('Recovery occurs once at battle start, capped at 5%; no per-turn MP or resonance regeneration.')
        else:
            super().passive(c)
