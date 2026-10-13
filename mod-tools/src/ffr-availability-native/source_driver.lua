-- Execute the retained FFBE Fill LB payload with its real one-use contract.
local M={}
local phase,granted=0,false
local before,cast_turn,defend_turn
local function emit(text) print('[FFRConvertedDriver] '..text..'\n') end
function M.setup()
    assert(FFRBattleProbeSourceAvailability and FFRBattleProbeConvertedCase=='limited')
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill')
    local row=library:GetSkillDataById(900010)
    for _,field in ipairs({'ID','Cost','magnification','hitCount','playSequencerId','parameterVariationType','DamageType','TargetType','defaultTargetRelation'}) do
        emit('source_loaded_row '..field..'='..tostring(row[field]))
    end
    assert(row.ID==900010 and row.Cost==0 and row.magnification==0 and row.hitCount==1
        and row.playSequencerId==900011 and row.parameterVariationType==0 and row.DamageType==0,
        'loaded Fill LB row differs from cooked fixture')
    emit('source_row_verified source=GL_2024/ability/150300')
end
function M.tick(units)
    local caster,enemy
    for _,unit in ipairs(units) do
        local p=unit.m_pUnitParameter
        if p and p:IsValid() then
            if p:GetUnitId()==1001 then caster=p elseif p:GetUnitId()==5 then enemy=p end
        end
    end
    if not caster or not enemy or phase==4 then return end
    local hp,mp,lb,ehp,turn=caster:GetHitPoint(),caster:GetMagicPoint(),caster:GetLimitBurstPoint(),enemy:GetHitPoint(),caster:GetActionCountInBattle()
    emit(string.format('source_sample phase=%d turn=%d caster_hp=%d caster_mp=%d caster_lb=%d enemy_hp=%d',phase,turn,hp,mp,lb,ehp))
    assert(hp>0 and ehp==200 and mp==43,'support fixture changed enemy HP/MP or lost Rain')
    if phase==1 then
        if lb==before.lb+20 then
            phase=2
            emit(string.format('source_first_result before_lb=%d after_lb=%d caster_mp=%d enemy_hp=%d turn=%d',before.lb,lb,mp,ehp,turn))
        else
            assert(lb==before.lb,'unexpected Fill LB amount')
        end
    end
    if phase==3 and turn>defend_turn then
        phase=4
        emit(string.format('source_complete initial_turn=%d final_turn=%d caster_mp=%d caster_lb=%d enemy_hp=%d',cast_turn,turn,mp,lb,ehp))
        emit('converted_observation_complete');return
    end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if not granted then
        granted=true;battle:SetUsableActiveSkill(1001,{400010,900010});battle:RefreshCommandSkill(1001)
        emit('source_transient_skill_list_requested unit=1001')
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    if phase==0 then
        local key={Category=1,ID=900010}
        if not models[1]:CanActivateAction(key) then return end
        local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,key.ID)
        assert(target==owner and lb<=80,'source fixture requires a self target and gauge headroom')
        before={lb=lb};cast_turn=turn;phase=1
        emit(string.format('source_cast_requested owner=%d target=%d turn=%d caster_lb=%d caster_mp=%d',owner,target,turn,lb,mp))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
        emit('source_cast_returned')
    elseif phase==2 and turn>cast_turn then
        assert(not models[1]:CanActivateAction({Category=1,ID=900010}),'spent source ability stayed available')
        local key={Category=1,ID=400010}
        assert(models[1]:CanActivateAction(key),'stock Defend became unavailable')
        emit(string.format('source_menu_blocked owner=%d turn=%d caster_lb=%d caster_mp=%d',owner,turn,lb,mp))
        defend_turn=turn;phase=3
        emit(string.format('source_defend_requested owner=%d target=%d turn=%d',owner,owner,turn))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({owner},false)
        emit('source_defend_returned')
    end
end
return M
