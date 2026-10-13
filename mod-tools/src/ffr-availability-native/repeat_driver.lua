-- Observe native automatic repeats; no availability rule is installed here.
local M={}
local phase=0
local baseline,last,stable
local begun,begin_count={},0
local skill_id=900010
local function emit(text) print('[FFRRepeatDriver] '..text..'\n') end
local function integers(list)
    local values={}
    for _,v in ipairs(list) do values[#values+1]=type(v)=='number' and v or v:get() end
    table.sort(values);return values
end
local function contains(values,id)
    for _,v in ipairs(values) do if v==id then return true end end
    return false
end
function M.setup()
    assert(FFRBattleProbeRepeatCommand and FFRBattleProbeProtectedSaves)
    require('fire_driver').setup()
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill')
    assert(library:GetSkillCategory(90000)==3,'repeat passive has incorrect native category')
    local passive=library:GetPassiveSkillDataById(90000)
    local bundles=passive.effectBundleList
    emit(string.format('passive_row id=%s bundles_type=%s count=%s',tostring(passive.ID),type(bundles),tostring(#bundles)))
    for key,value in pairs(bundles) do
        emit(string.format('passive_bundle index=%s effect=%s',tostring(key),tostring(value:get().effectId)))
    end
    assert(passive.ID==90000 and #bundles==1 and bundles[1]:get().effectId==1012,'native repeat passive row mismatch')
    emit('passive_row_verified id=90000 effect=1012 category=3')
    local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
    local units={};data:GetSaveDataUnitParameterList(units)
    assert(#units==8,'repeat fixture requires fresh initial units')
    local before={};data:GetMasterPassiveSkillList(before,1001);before=integers(before)
    assert(not contains(before,90000),'repeat passive already mastered')
    if not FFRBattleProbeRepeatControl then data:AddMasterSkill(1001,90000) end
    local after={};data:GetMasterPassiveSkillList(after,1001);after=integers(after)
    emit('master_passive_grants unit=1001 before='..table.concat(before,',')..' after='..table.concat(after,','))
    assert(#after==#before+(FFRBattleProbeRepeatControl and 0 or 1)
        and contains(after,90000)==(not FFRBattleProbeRepeatControl),'native passive master grant failed')
    local pre,post=RegisterHook('/Script/mucha.CPP_VM_BtlLibra:HandleSkillBegin',function(_,remote)
        local value=remote:get()
        if value.SkillId==skill_id then
            local payload=value:GetFullName()
            if not begun[payload] then
                begun[payload]=true;begin_count=begin_count+1
                emit(string.format('cast_begin ordinal=%d unique=%d payload=%s',begin_count,value.actionUnitUniqueId,payload))
            end
        end
    end)
    assert(type(pre)=='number' and type(post)=='number','repeat observer registration failed')
end
function M.tick(units)
    if #units~=2 or phase==2 then return end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local caster=battle:GetBattleUnitParameterByUnitId(1001,true)
    local enemy=battle:GetBattleUnitParameterByUnitId(5,false)
    if not caster or not caster:IsValid() or not enemy or not enemy:IsValid() then return end
    local current={hp=caster:GetHitPoint(),mp=caster:GetMagicPoint(),lb=caster:GetLimitBurstPoint(),
        enemyHp=enemy:GetHitPoint(),turn=caster:GetActionCountInBattle(),fire=enemy:GetResistanceToElement(1)}
    if phase==1 then
        emit(string.format('sample begins=%d hp=%d mp=%d lb=%d enemy_hp=%d turn=%d fire=%d',
            begin_count,current.hp,current.mp,current.lb,current.enemyHp,current.turn,current.fire))
        assert(current.hp>0 and current.enemyHp>0,'repeat fixture lost a combatant')
        local expected=(FFRBattleProbeRepeatControl or FFRBattleProbeRepeatSuppressed) and 1 or 2
        assert(begin_count<=expected,'unexpected additional repeat')
        if begin_count==expected and current.enemyHp<baseline.enemyHp and current.fire==1 then
            if last and last.hp==current.hp and last.mp==current.mp and last.lb==current.lb
                and last.enemyHp==current.enemyHp and last.turn==current.turn then stable=(stable or 0)+1 else stable=0 end
            if stable>=2 then
                phase=2
                emit(string.format('repeat_complete begins=%d before_mp=%d after_mp=%d before_lb=%d after_lb=%d before_hp=%d after_hp=%d before_enemy_hp=%d after_enemy_hp=%d before_turn=%d after_turn=%d',
                    begin_count,baseline.mp,current.mp,baseline.lb,current.lb,baseline.hp,current.hp,
                    baseline.enemyHp,current.enemyHp,baseline.turn,current.turn))
                print('[FFRConvertedDriver] converted_observation_complete\n')
            end
        end
        last=current;return
    end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {}
    local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local owner=managers[1]:GetCurrentActionUnitUniqueId()
    if owner<0 or battle:GetUnitIdByUniqueId(owner)~=1001 then return end
    local active,passives={},{};caster:GetActiveSkillListWithVision(active);caster:GetPassiveSkillList(passives)
    active=integers(active);passives=integers(passives)
    emit('native_owned active='..table.concat(active,',')..' passives='..table.concat(passives,','))
    assert(contains(active,skill_id),'converted Fire not natively learned')
    assert(contains(passives,90000)==(not FFRBattleProbeRepeatControl),'unexpected passive ownership')
    local repeat_count=0
    for _,v in ipairs(caster:GetContEffectList()) do
        local effect=v:get();local row=effect:GetEffectData()
        if row.ID==1012 then
            repeat_count=repeat_count+1
            emit(string.format('repeat_effect id=%d life=%d actor=%d target=%d type=%s',row.ID,effect:GetLifeTurn(),
                effect.m_pActionUnitParameter:GetUnitId(),effect:GetTargetUnitParameter():GetUnitId(),effect:GetFullName()))
        end
    end
    assert(repeat_count==(FFRBattleProbeRepeatControl and 0 or 1),'native repeat effect not applied from passive')
    local key={Category=1,ID=skill_id}
    assert(models[1]:CanActivateAction(key),'native repeat Fire unavailable')
    local target=battle:GetDefaultSkillTargetUnitUniqueId(owner,skill_id)
    assert(target>=0 and battle:GetUnitIdByUniqueId(target)==5,'repeat target mismatch')
    assert(current.enemyHp==200 and current.mp>=8 and current.fire==0 and current.turn==1,'unexpected repeat baseline')
    baseline=current;phase=1
    emit(string.format('command_requested owner=%d skill=%d target=%d hp=%d mp=%d lb=%d enemy_hp=%d turn=%d',
        owner,skill_id,target,current.hp,current.mp,current.lb,current.enemyHp,current.turn))
    models[1]:DecideActionKey(key);models[1]:DecideTarget({target},false)
    emit('command_returned')
end
return M
