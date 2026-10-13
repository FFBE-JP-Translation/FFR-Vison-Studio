-- Converted Fire diagnostic, including optional phase controls and expiry observation.
local M = {}
local phase, granted = 0, false
local before
local cast_caster_turn, cast_enemy_turn, cast_battle_turn, last_defend_turn
local skill_id = 900010
local function emit(text) print("[FFRConvertedDriver] "..text.."\n") end

local function state(parameter)
    return {hp=parameter:GetHitPoint(),mp=parameter:GetMagicPoint(),lb=parameter:GetLimitBurstPoint(),
        fire=parameter:GetResistanceToElement(1)}
end

local function battle_turn()
    for _,ai in ipairs(FindAllOf("CPP_BtlUnitAI") or {}) do
        local owner=ai.m_pOwnerUnit
        if owner and owner:IsValid() and owner.m_pUnitParameter:GetUnitId()==5 then
            return ai:GetTurnNum()
        end
    end
    error("enemy AI battle-turn accessor unavailable")
end

local function effects(parameter, role)
    local list=parameter:GetContEffectList()
    local life=-1
    for _,entry in ipairs(list) do
        local effect=entry:get()
        local row=effect:GetEffectData()
        if row.ID>=skill_id*100 and row.ID<skill_id*100+100 then
            if row.ID==skill_id*100 then life=effect:GetLifeTurn() end
            emit(string.format("effect role=%s id=%d life=%d actor=%d target=%d",role,row.ID,effect:GetLifeTurn(),
                effect.m_pActionUnitParameter:GetUnitId(),effect:GetTargetUnitParameter():GetUnitId()))
        end
    end
    return life
end

function M.setup()
    assert(FFRBattleProbeConvertedAbility==skill_id and FFRBattleProbeConvertedCase=="fire")
    local library=StaticFindObject("/Script/mucha.Default__CPP_BFL_Skill")
    local category=library:GetSkillCategory(skill_id)
    emit(string.format('loaded_category id=%d category=%d',skill_id,category))
    assert(category==2,'converted Fire is not a native ActiveSkill')
    local row=library:GetSkillDataById(skill_id)
    for _,field in ipairs({"ID","Cost","magnification","hitCount","playSequencerId","parameterVariationType","DamageType","TargetType","defaultTargetRelation"}) do
        emit("loaded_row "..field.."="..tostring(row[field]))
    end
    assert(row.ID==skill_id and row.Cost==4 and row.magnification==15 and row.hitCount==1
        and row.playSequencerId==skill_id+1 and row.parameterVariationType==1
        and row.DamageType==2 and row.TargetType==1 and row.defaultTargetRelation==2,
        "loaded experimental Fire row differs from cooked fixture")
    emit("fire_row_verified")
    if FFRBattleProbeConvertedExpiry then
        local pre,post=RegisterHook("/Script/mucha.CPP_UI_BattleSubsystem:HandleBeginTurn",function(_,remote)
            if phase~=2 then return end
            local ok,reason=pcall(function()
                local battle=StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
                local enemy=battle:GetBattleUnitParameterByUnitId(5,false)
                local life=effects(enemy,"enemy")
                emit(string.format("expiry_turn unique=%d battle_turn=%d enemy_counter=%d life=%d fire=%d",remote:get().UniqueID,
                    battle_turn(),enemy:GetActionCountInBattle(),life,enemy:GetResistanceToElement(1)))
            end)
            if not ok then emit("expiry_read_failed="..tostring(reason)) end
        end)
        assert(type(pre)=="number" and type(post)=="number","expiry observer registration failed")
    end
end

function M.tick(units)
    if #units~=2 or phase==3 or (phase==2 and not FFRBattleProbeConvertedExpiry) then return end
    local battle=StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
    local caster=battle:GetBattleUnitParameterByUnitId(1001,true)
    local enemy=battle:GetBattleUnitParameterByUnitId(5,false)
    if not caster or not caster:IsValid() or not enemy or not enemy:IsValid() then return end
    local c,e=state(caster),state(enemy)
    if phase==2 then
        local life=effects(enemy,"enemy")
        local caster_turn,enemy_turn=caster:GetActionCountInBattle(),enemy:GetActionCountInBattle()
        local round=battle_turn()
        emit(string.format("expiry_sample battle_turn=%d caster_counter=%d enemy_counter=%d caster_hp=%d enemy_hp=%d life=%d fire=%d",
            round,caster_turn,enemy_turn,c.hp,e.hp,life,e.fire))
        assert(c.hp>0 and e.hp>0,"expiry fixture lost a combatant")
        if life==-1 and e.fire==before.enemy.fire then
            assert(round-cast_battle_turn==5,"weakness did not expire on the fifth native battle turn")
            phase=3
            emit(string.format("expiry_complete initial_battle_turn=%d final_battle_turn=%d initial_enemy_counter=%d final_enemy_counter=%d caster_hp=%d enemy_hp=%d",
                cast_battle_turn,round,cast_enemy_turn,enemy_turn,c.hp,e.hp))
            emit("converted_observation_complete")
            return
        end
        local managers=FindAllOf("CPP_UI_BtlCmdManager") or {}
        local models=FindAllOf("CPP_VM_BtlCmd") or {}
        if #managers~=1 or #models~=1 then return end
        local owner=managers[1]:GetCurrentActionUnitUniqueId()
        if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 or caster_turn<=cast_caster_turn or caster_turn==last_defend_turn then return end
        local key={Category=1,ID=400010}
        if not models[1]:CanActivateAction(key) then return end
        last_defend_turn=caster_turn
        emit(string.format("expiry_defend_requested owner=%d turn=%d target=%d",owner,caster_turn,owner))
        models[1]:DecideActionKey(key)
        models[1]:DecideTarget({owner},false)
        emit("expiry_defend_returned")
        return
    end
    emit(string.format("fire_sample caster_hp=%d caster_mp=%d caster_lb=%d caster_fire=%d enemy_hp=%d enemy_mp=%d enemy_lb=%d enemy_fire=%d",
        c.hp,c.mp,c.lb,c.fire,e.hp,e.mp,e.lb,e.fire))
    effects(caster,"caster")
    effects(enemy,"enemy")
    if phase==1 then
        if e.hp>0 and e.hp<before.enemy.hp and e.fire==1 and c.fire==before.caster.fire and c.mp==before.caster.mp-4 and c.lb>before.caster.lb then
            phase=2
            emit(string.format("fire_result before_hp=%d after_hp=%d before_mp=%d after_mp=%d before_lb=%d after_lb=%d before_fire=%d after_fire=%d",
                before.enemy.hp,e.hp,before.caster.mp,c.mp,before.caster.lb,c.lb,before.enemy.fire,e.fire))
            if FFRBattleProbeConvertedExpiry then
                emit(string.format("expiry_started battle_turn=%d caster_counter=%d enemy_counter=%d",cast_battle_turn,cast_caster_turn,cast_enemy_turn))
            else
                emit("converted_observation_complete")
            end
        end
        return
    end
    if not granted then
        granted=true
        battle:SetUsableActiveSkill(1001,FFRBattleProbeConvertedExpiry and {400010,401010,skill_id} or {401010,skill_id})
        battle:RefreshCommandSkill(1001)
        emit("transient_skill_list_requested unit=1001")
    end
    local managers=FindAllOf("CPP_UI_BtlCmdManager") or {}
    local models=FindAllOf("CPP_VM_BtlCmd") or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    local key={Category=1,ID=skill_id}
    if not models[1]:CanActivateAction(key) then return end
    local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,skill_id)
    assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,"Fire target mismatch")
    assert(e.hp>0 and c.hp>0 and c.mp>=4 and e.fire~=1,"Fire requires a living neutral target and sufficient MP")
    emit(string.format("fire_combat_stats caster_level=%d caster_magic=%d caster_intelligence=%d enemy_level=%d enemy_magic_defense=%d enemy_mind=%d caster_dying=%s enemy_dying=%s",
        caster:GetLevel(),caster:GetMagicalAttack(),caster:GetIntelligence(),enemy:GetLevel(),enemy:GetMagicalDefense(),enemy:GetMind(),
        tostring(caster:IsDying()),tostring(enemy:IsDying())))
    before={caster=c,enemy=e}
    cast_caster_turn,cast_enemy_turn=caster:GetActionCountInBattle(),enemy:GetActionCountInBattle()
    if FFRBattleProbeConvertedExpiry then cast_battle_turn=battle_turn() end
    phase=1
    emit(string.format("fire_command_requested owner=%d skill=%d target=%d hp=%d mp=%d lb=%d fire=%d",owner,skill_id,target,e.hp,c.mp,c.lb,e.fire))
    models[1]:DecideActionKey(key)
    models[1]:DecideTarget({target},false)
    emit("fire_command_returned")
end

return M
