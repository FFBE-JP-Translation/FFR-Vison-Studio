-- Disposable stock lifecycle experiment. Never certifies source conversion.
local M={}
local requested,ended,settled=false,false,0
local generation,lighting,identities=1,false,{}
local owned=FFRBattleProbeResetSource and require('owned_driver') or nil
local function emit(text) print('[FFRReturnDriver] '..text..'\n') end
function M.setup()
    if owned then owned.setup() end
    local maps=FindAllOf('CPP_MapManager') or {};assert(#maps==1,'expected disposable map manager')
    local loader=maps[1].m_pSublevelLoadManager
    assert(loader and loader:IsValid(),'field loader unavailable')
    assert(not loader.m_pLoadSubLevel or not loader.m_pLoadSubLevel:IsValid(),'unexpected existing field bundle')
    local bundle=StaticConstructObject(StaticFindObject('/Script/mucha.CPP_LevelBundle'),loader)
    assert(bundle and bundle:IsValid() and bundle.m_Levels:GetArrayNum()==0,'empty field bundle unavailable')
    loader.m_pLoadSubLevel=bundle
    emit('field_bundle_prepared')
    local pre,post=RegisterHook('/Script/mucha.CPP_UI_BattleSubsystem:HandleEndBtl',function(_,remote)
        ended=true;emit('native_end payload='..remote:get():GetFullName())
    end)
    assert(type(pre)=='number' and type(post)=='number','return observer registration failed')
    local escape_pre,escape_post=RegisterHook('/Script/mucha.CPP_BtlDelEventCmd:OnExcuteBeginEscape',function(_,remote)
        emit(string.format('escape_result battle=%d success=%s',generation,tostring(remote:get().isSuccessEscape)))
    end)
    assert(type(escape_pre)=='number' and type(escape_post)=='number','escape result observer registration failed')
end
function M.tick(units)
    if ended then
        assert(#units==0,'native battle end retained combat actors')
        settled=settled+1
        emit(string.format('settled battle=%d tick=%d units=%d',generation,settled,#units))
        if settled==(owned and 2 or 5) then
            if generation==1 then
                generation=2;ended=false;requested=false;settled=0
                if owned then owned.reset_battle() end
                emit('second_battle_requested');M.restart()
            else emit('return_observation_complete') end
        end
        return
    end
    if requested or #units~=(owned and 3 or 2) then return end
    if owned and not owned.is_complete() then owned.tick(units);return end
    local managers=FindAllOf('CPP_UI_BtlCmdManager') or {}
    local models=FindAllOf('CPP_VM_BtlCmd') or {}
    if #managers~=1 or #models~=1 then return end
    local battle=StaticFindObject('/Script/mucha.Default__CPP_BFL_Battle')
    local unique=managers[1]:GetCurrentActionUnitUniqueId()
    if unique<0 then return end
    local unit_id=battle:GetUnitIdByUniqueId(unique)
    if unit_id~=1001 and not (owned and unit_id==1002) then return end
    local parameter=battle:GetBattleUnitParameterWithVision(unique,false)
    local actor=parameter.m_pOwnerBtlUnit
    assert(actor and actor:IsValid(),'escape owner missing')
    assert(parameter:GetActionCountInBattle()==(owned and 3 or 1),'escape owner is not on the expected command opportunity')
    local name=actor:GetFullName()
    assert(not identities[name],'new battle reused prior actor identity');identities[name]=true
    emit(string.format('fresh_owner battle=%d actor=%d parameter=%d name=%s',generation,actor:GetAddress(),parameter:GetAddress(),name))
    if not lighting then
    local maps=FindAllOf('CPP_MapManager') or {};assert(#maps==1)
    local collector=maps[1].m_pLightingLevelCollect
    assert(collector and collector:IsValid() and #collector.m_LevelMap==0,'unexpected existing field lighting')
    local key,reason=FFRBattleFixtureLightingKey(collector:GetAddress());assert(type(key)=='number',reason)
    local battles=FindAllOf('CPP_BtlManager') or {};assert(#battles==1)
    local stream
    battles[1].m_pBattleLevelManager.m_BattleLevelInstanceList:ForEach(function(id,value)
        if id:get()==5 then stream=value:get().pLightingLevel end
    end)
    assert(stream and stream:IsValid() and stream:IsLevelLoaded(),'native stage lighting unavailable')
    local level=StaticConstructObject(StaticFindObject('/Script/mucha.CPP_Level'),collector)
    assert(level and level:IsValid(),'field lighting wrapper unavailable')
    level.m_pLevelStreaming=stream
    collector.m_LevelMap:Add(key,level)
    assert(collector.m_LevelMap:Contains(key),'field lighting registration failed')
    emit(string.format('field_lighting_prepared key=%d level=%s stream=%s',key,level:GetFullName(),stream:GetFullName()))
    lighting=true
    end
    local action={Category=1,ID=400020} -- Native Escape, entry success probability 100.
    assert(battle:CanEscape() and models[1]:CanActivateAction(action),'native Escape unavailable')
    requested=true
    emit(string.format('escape_requested battle=%d unique=%d skill=%d',generation,unique,action.ID))
    models[1]:DecideActionKey(action);models[1]:DecideTarget({unique},false)
    emit('escape_returned')
end
return M
