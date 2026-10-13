-- Real FFBE five-turn cooldown: cast, defend through the wait, cast again.
local M={}
local phase,granted,casts=0,false,0
local before_hp,cast_turn,last_defend,final_defend
local function emit(text) print('[FFRConvertedDriver] '..text..'\n') end
function M.setup()
    assert(FFRBattleProbeSourceAvailability and FFRBattleProbeConvertedCase=='cooldown')
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill')
    local row=library:GetSkillDataById(900010)
    assert(row.ID==900010 and row.Cost==0 and row.magnification==0 and row.hitCount==1
        and row.playSequencerId==900011 and row.parameterVariationType==0 and row.DamageType==0
        and row.TargetType==0 and row.defaultTargetRelation==1,'loaded cooldown source row differs from fixture')
    emit('cooldown_row_verified source=JP_2022/ability/1007200')
end
function M.tick(units)
    local caster,enemy
    for _,unit in ipairs(units) do
        local p=unit.m_pUnitParameter
        if p and p:IsValid() then
            if p:GetUnitId()==1001 then caster=p elseif p:GetUnitId()==5 then enemy=p end
        end
    end
    if not caster or not enemy or phase==5 then return end
    local hp,maxhp,mp,ehp,turn=caster:GetHitPoint(),caster:GetMaxHitPoint(),caster:GetMagicPoint(),enemy:GetHitPoint(),caster:GetActionCountInBattle()
    emit(string.format('cooldown_sample phase=%d turn=%d caster_hp=%d max_hp=%d caster_mp=%d enemy_hp=%d',phase,turn,hp,maxhp,mp,ehp))
    assert(hp>0 and ehp==200 and mp==43,'cooldown support changed enemy HP/MP or lost Rain')
    if phase==1 and hp==maxhp then
        assert(before_hp<maxhp,'source cast had no observable healing')
        emit(string.format('cooldown_result ordinal=%d turn=%d before_hp=%d after_hp=%d caster_mp=%d',casts,turn,before_hp,hp,mp))
        phase=casts==1 and 2 or 3
    end
    if phase==4 and turn>final_defend then
        phase=5
        emit(string.format('cooldown_complete casts=%d first_turn=1 second_turn=%d final_turn=%d caster_mp=%d enemy_hp=%d',casts,cast_turn,turn,mp,ehp))
        emit('converted_observation_complete');return
    end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if not granted then
        granted=true;battle:SetUsableActiveSkill(1001,{400010,900010});battle:RefreshCommandSkill(1001)
        emit('cooldown_transient_skill_list_requested unit=1001')
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    if phase==1 or phase==4 or turn==last_defend then return end
    if phase==0 or (phase==2 and turn==6) then
        local key={Category=1,ID=900010}
        assert(models[1]:CanActivateAction(key),'cooldown failed to become available on its exact owner turn')
        local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,key.ID)
        assert(target==owner and (turn==1 or turn==6),'cooldown cast target or turn mismatch')
        casts=casts+1;before_hp=hp;cast_turn=turn;phase=1
        emit(string.format('cooldown_cast_requested ordinal=%d owner=%d target=%d turn=%d caster_hp=%d caster_mp=%d',casts,owner,target,turn,hp,mp))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
        emit('cooldown_cast_returned ordinal='..casts)
    elseif (phase==2 and turn>cast_turn and turn<6) or (phase==3 and turn>cast_turn) then
        assert(not models[1]:CanActivateAction({Category=1,ID=900010}),'cooldown became available before its deadline')
        emit(string.format('cooldown_menu_blocked turn=%d after_cast=%d',turn,casts))
        local key={Category=1,ID=400010}
        assert(models[1]:CanActivateAction(key),'stock Defend became unavailable during cooldown')
        last_defend=turn
        if phase==3 then phase=4;final_defend=turn end
        emit(string.format('cooldown_defend_requested owner=%d target=%d turn=%d',owner,owner,turn))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({owner},false)
        emit('cooldown_defend_returned turn='..turn)
    end
end
return M
