"""Disposable native controls for the owner death/revival observation."""
from copy import deepcopy
import make_vision_mod as generator
import ffbe_resonance as sequence
from ability_converter import commands


def add_controls(table, clones, profile, *, skill_id=900010):
    controls=[]
    for skill,template,effect,name,owner in ((skill_id+20,220320,1357,'Death',1001),(skill_id+40,210140,1367,'Revival',1002)):
        row_name='FFROwnerLife'+name+'Control'
        template_row,native=generator.row_by('Skill/DT_SkillData','ID',template)
        bundles=deepcopy(native['effectBundleList']);bundles[0]['effectId']=effect
        settings={'ID':skill,'SortId':skill,'Name':f'Owner {name.lower()} control','Description':'Temporary native lifecycle fixture.',
            'Cost':0,'belongCommandList':[1],'commandIdBelongDebuggingAllSkills':[-1,-1],
            'playSequencerId':skill+1,'sequencerIdWhenTargetFriendlies':skill+1,'effectBundleList':bundles}
        if name=='Death':settings.update(TargetType='Self',defaultTargetRelation='Friendlies')
        table('Skill/DT_SkillData')['add'].append({'row':row_name,'cloneFrom':template_row,'set':settings})
        destination=f'FFRS/Content/Sequencer/Battle/Skill/{skill}/{skill+1}/SEQ_Battle_{skill+1}_Master'
        clones.append({'from':sequence.SHELL,'to':destination,'rename':[['SEQ_Battle_440111_Cut_000',f'SEQ_Battle_{skill+1}_Master']]})
        for relative in ('Asset/Skill/DT_SkillAsset','Asset/Skill/CDT_SkillAsset_Demo'):
            donor=generator.row_by(relative,'ID',440111)[0]
            for offset in (1,2):
                table(relative)['add'].append({'row':row_name+str(offset),'cloneFrom':donor,'set':{'ID':skill+offset,
                    'LevelSequence':destination.replace('FFRS/Content/','/Game/'),'soundSequence':'None','bChangeNearClipPlane':False}})
        donor=generator.row_by('Battle/Sequencer/DT_BtlHitEffectData','ID',449999)[0]
        table('Battle/Sequencer/DT_BtlHitEffectData')['add'].append({'row':row_name,'cloneFrom':donor,'set':{'ID':skill}})
        controls.append({'skillId':skill,'ownerUnitId':owner,'templateId':template,'effectId':effect,'rowName':row_name,
            'set':settings,'asset':destination,'plan':commands.schedule(profile,skill,3.0,'magic_attack')})
    return controls
