-- Cast one Fire, attempt the exhausted second cast, then use stock Defend.
local M={}
local phase,granted=0,false
local initial,accepted,cast_turn,denied_turn,defend_turn
local function emit(text) print('[FFRConvertedDriver] '..text..'\n') end
function M.setup() require('fire_driver').setup() end
function M.tick(units)
    local caster,enemy
    for _,unit in ipairs(units) do
        local p=unit.m_pUnitParameter
        if p and p:IsValid() then
            if p:GetUnitId()==1001 then caster=p elseif p:GetUnitId()==5 then enemy=p end
        end
    end
    if not caster or not enemy or phase==5 then return end
    local hp,mp,ehp,fire,turn=caster:GetHitPoint(),caster:GetMagicPoint(),enemy:GetHitPoint(),enemy:GetResistanceToElement(1),caster:GetActionCountInBattle()
    emit(string.format('limited_sample phase=%d turn=%d caster_hp=%d caster_mp=%d enemy_hp=%d enemy_fire=%d',phase,turn,hp,mp,ehp,fire))
    assert(hp>0 and ehp>0,'limited fixture lost a combatant')
    if accepted then assert(mp==accepted.mp and ehp==accepted.hp,'exhausted cast changed MP or enemy HP') end
    if phase==1 and mp==initial.mp-4 and ehp<initial.hp and fire==1 then
        accepted={mp=mp,hp=ehp};phase=2
        emit(string.format('limited_first_result caster_mp=%d enemy_hp=%d enemy_fire=%d',mp,ehp,fire))
    end
    if phase==4 and turn>defend_turn then
        phase=5
        emit(string.format('limited_complete initial_turn=%d final_turn=%d caster_mp=%d enemy_hp=%d enemy_fire=%d',cast_turn,turn,mp,ehp,fire))
        emit('converted_observation_complete');return
    end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if not granted then
        granted=true;battle:SetUsableActiveSkill(1001,{400010,900010});battle:RefreshCommandSkill(1001)
        emit('limited_transient_skill_list_requested unit=1001')
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    if FFRBattleProbeMenuLimited and phase==2 and turn>cast_turn then
        local available=models[1]:CanActivateAction({Category=1,ID=900010})
        assert(not available,'exhausted Fire stayed available in the command menu')
        emit(string.format('limited_menu_blocked owner=%d turn=%d caster_mp=%d enemy_hp=%d',owner,turn,mp,ehp))
        -- No Fire command is selected. Defend should use this same opportunity.
        phase=3;denied_turn=turn-1
    end
    if phase==0 or (phase==2 and turn>cast_turn) then
        local key={Category=1,ID=900010}
        if not models[1]:CanActivateAction(key) then return end
        local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,key.ID)
        assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,'limited target mismatch')
        local ordinal=phase==0 and 1 or 2
        if phase==0 then initial={mp=mp,hp=ehp};cast_turn=turn;phase=1 else denied_turn=turn;phase=3 end
        emit(string.format('limited_fire_requested ordinal=%d owner=%d target=%d turn=%d caster_mp=%d enemy_hp=%d',ordinal,owner,target,turn,mp,ehp))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
        emit('limited_fire_returned ordinal='..ordinal)
    elseif phase==3 and turn>denied_turn then
        local key={Category=1,ID=400010}
        if not models[1]:CanActivateAction(key) then return end
        phase=4;defend_turn=turn
        emit(string.format('limited_defend_requested owner=%d turn=%d target=%d',owner,turn,owner))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({owner},false)
        emit('limited_defend_returned')
    end
end
return M
