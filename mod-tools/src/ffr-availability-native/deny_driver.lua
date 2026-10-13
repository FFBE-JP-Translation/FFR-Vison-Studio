-- Request Fire under native denial, then a stock Defend to verify continuation.
local M={}
local phase,granted=0,false
local before,cast_turn,defend_turn
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
    if not caster or not enemy or phase==3 then return end
    local hp,mp,ehp,fire,turn=caster:GetHitPoint(),caster:GetMagicPoint(),enemy:GetHitPoint(),enemy:GetResistanceToElement(1),caster:GetActionCountInBattle()
    emit(string.format('denial_sample phase=%d turn=%d caster_hp=%d caster_mp=%d enemy_hp=%d enemy_fire=%d',phase,turn,hp,mp,ehp,fire))
    if before then
        assert(hp>0 and ehp>0,'denial fixture lost a combatant')
        assert(mp==before.mp and ehp==before.hp and fire==before.fire,'denied skill changed resources or enemy effects')
    end
    if phase==2 and turn>defend_turn then
        phase=3
        emit(string.format('denial_complete initial_turn=%d final_turn=%d caster_mp=%d enemy_hp=%d enemy_fire=%d',cast_turn,turn,mp,ehp,fire))
        emit('converted_observation_complete')
        return
    end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if not granted then
        granted=true
        battle:SetUsableActiveSkill(1001,{400010,900010})
        battle:RefreshCommandSkill(1001)
        emit('denial_transient_skill_list_requested unit=1001')
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {}
    local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    if phase==0 then
        local key={Category=1,ID=900010}
        if not models[1]:CanActivateAction(key) then return end
        local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,key.ID)
        assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,'denial target mismatch')
        phase=1;cast_turn=turn;before={mp=mp,hp=ehp,fire=fire}
        emit(string.format('denial_fire_requested owner=%d target=%d turn=%d caster_mp=%d enemy_hp=%d enemy_fire=%d',owner,target,turn,mp,ehp,fire))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
        emit('denial_fire_returned')
    elseif phase==1 and turn>cast_turn then
        local key={Category=1,ID=400010}
        if not models[1]:CanActivateAction(key) then return end
        phase=2;defend_turn=turn
        emit(string.format('denial_defend_requested owner=%d turn=%d target=%d',owner,turn,owner))
        models[1]:DecideActionKey(key);models[1]:DecideTarget({owner},false)
        emit('denial_defend_returned')
    end
end
return M
