-- Execute native death and revival after each owner spends its source use.
local M={}
local records={};local active_cast;local death_requested,dead_seen,raise_requested,revived,completed=false,false,false,false,false
local function emit(text) print('[FFRLifeDriver] '..text..'\n') end
function M.setup()
    assert(FFRBattleProbeLifeSource and not FFRBattleProbeVisionSource)
    require('owned_driver').setup()
    local library=StaticFindObject('/Script/mucha.Default__CPP_BFL_Skill')
    for _,id in ipairs({900030,900050}) do
        local row=library:GetSkillDataById(id)
        assert(row.ID==id and row.Cost==0 and row.playSequencerId==id+1,'native lifecycle control row missing')
    end
    emit('life_controls_verified death=900030 revival=900050')
end
function M.tick(units)
    if completed then return end
    local parameters={};local enemy
    for _,actor in ipairs(units) do
        local p=actor.m_pUnitParameter
        if p and p:IsValid() then
            local id=p:GetUnitId()
            if id==1001 or id==1002 then parameters[id]=p elseif id==5 then enemy=p end
        end
    end
    if not enemy or not parameters[1001] or not parameters[1002] then return end
    local rain,lasswell=parameters[1001],parameters[1002]
    assert(enemy:GetHitPoint()==200 and not lasswell:IsDead(),'unexpected enemy or reviver death')
    for _,unit in ipairs({1001,1002}) do
        local p=parameters[unit];local record=records[unit]
        if not record then record={mp=p:GetMagicPoint()};records[unit]=record end
        assert(p:GetMagicPoint()==record.mp,'lifecycle fixture spent unexpected MP')
        emit(string.format('life_sample unit=%d actor=%d turn=%d hp=%d max_hp=%d mp=%d lb=%d dead=%s',
            unit,p.m_pOwnerBtlUnit:GetAddress(),p:GetActionCountInBattle(),p:GetHitPoint(),p:GetMaxHitPoint(),p:GetMagicPoint(),p:GetLimitBurstPoint(),tostring(p:IsDead())))
    end
    if active_cast then
        local p=parameters[active_cast.unit];local lb=p:GetLimitBurstPoint()
        if lb==active_cast.before+20 then
            records[active_cast.unit].cast=true
            emit(string.format('life_source_result unit=%d before_lb=%d after_lb=%d mp=%d',active_cast.unit,active_cast.before,lb,p:GetMagicPoint()))
            active_cast=nil
        else assert(lb==active_cast.before,'unexpected source gauge amount') end
    end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    if rain:IsDead() and not dead_seen then
        assert(death_requested and not raise_requested and rain:GetHitPoint()==0,'unexpected owner death')
        dead_seen=true
        assert(not battle:CanUnitActivateSkill(records[1001].unique,900010,false,{},false),'dead owner was allowed to use the source')
        emit(string.format('life_dead unit=1001 unique=%d turn=%d hp=0',records[1001].unique,rain:GetActionCountInBattle()))
    elseif dead_seen and not rain:IsDead() and not revived then
        assert(raise_requested and rain:GetHitPoint()>0,'owner revived outside the native control')
        revived=true
        emit(string.format('life_revived unit=1001 unique=%d turn=%d hp=%d max_hp=%d',records[1001].unique,
            rain:GetActionCountInBattle(),rain:GetHitPoint(),rain:GetMaxHitPoint()))
    end
    if records[1001].post_defended then
        assert(revived and rain:GetHitPoint()>0,'owner did not survive the post-revival opportunity')
        completed=true;emit('life_complete source_casts=2 deaths=1 revivals=1')
        print('[FFRConvertedDriver] converted_observation_complete\n');return
    end
    if active_cast then return end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {};local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local unique=managers[1]:GetCurrentActionUnitUniqueId();if unique<0 then return end
    local unit=battle:GetUnitIdByUniqueId(unique);local p=parameters[unit];local record=records[unit]
    if not p or p:IsDead() or not record then return end
    local turn=p:GetActionCountInBattle()
    if record.selected_turn==turn then return end
    record.unique=unique
    local vm=models[1]
    local function select(skill,target,kind)
        local key={Category=1,ID=skill}
        assert(vm:CanActivateAction(key),'native '..kind..' command unavailable')
        record.selected_turn=turn
        emit(string.format('life_command unit=%d unique=%d skill=%d target=%d turn=%d kind=%s',unit,unique,skill,target,turn,kind))
        vm:DecideActionKey(key);vm:DecideTarget({target},false)
    end
    if not record.cast then
        assert(p:GetLimitBurstPoint()<=80,'source lacks gauge headroom')
        active_cast={unit=unit,before=p:GetLimitBurstPoint()}
        select(900010,unique,'source')
    else
        assert(not vm:CanActivateAction({Category=1,ID=900010}),'spent source became available')
        emit(string.format('life_source_blocked unit=%d turn=%d revived=%s',unit,turn,tostring(revived)))
        if unit==1001 and records[1002].cast and not death_requested then
            death_requested=true;select(900030,unique,'death')
        elseif unit==1002 and dead_seen and not raise_requested then
            assert(rain:IsDead(),'revival target must be dead')
            raise_requested=true;select(900050,records[1001].unique,'revival')
        else
            select(400010,unique,'defend')
            if unit==1001 and revived then record.post_defended=true end
        end
    end
end
return M
