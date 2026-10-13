local once=false
local travelled=false
local function log(message) print('[VisionCardProbe] '..message..'\n') end
LoopInGameThreadWithDelay(2000,function()
    ExecuteInGameThread(function()
        if once then return end
        local ok,why=pcall(function()
            local map=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataMap')
            local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
            local list={};data:GetSaveDataUnitParameterList(list)
            if #list==0 then return end
            if not travelled then
                for _,world in ipairs(FindAllOf('World') or {}) do
                    if world:GetFullName():find('/Game/Map/Boot/MUCHA_Notify',1,true) then
                        travelled=true
                        map:SetMapIdAndMapUnitLocation(2000,{X=384,Y=3500,Z=300},0)
                        StaticFindObject('/Script/Engine.Default__GameplayStatics'):OpenLevel(world,FName('/Game/Map/Town/01Gra/01Gra_20/Town_01Gra_20_PL'),true,'')
                        log('mitra_level_requested')
                        return
                    end
                end
                return
            end
            map:SetGimmickState(771300,1001,401000401%65536)
            map:SetGimmickValue2(771300,1001,math.floor(401000401/65536))
            assert(map:GetGimmickState(771300,1001)+65536*map:GetGimmickValue2(771300,1001)==401000401,'Card slot storage failed')
            log('slot_storage=passed')
            local lib=StaticFindObject('/Script/mucha.Default__CPP_BFL_Unit')
            local parameter=lib:GetPlayableUnitParameterObj(1001)
            if not parameter or not parameter:IsValid() then
                parameter=StaticFindObject('/Script/mucha.Default__CPP_BFL_Btl_Result'):GetResultUnitParam({UnitId=1001,beforeBattleLevel=1,afterBattleLevel=1})
            end
            if not parameter or not parameter:IsValid() then
                for _,manager in ipairs(FindAllOf('CPP_UnitVMManager') or {}) do
                    local vm=manager:GetUnitParamVM(1001)
                    if vm and vm:IsValid() then parameter=vm.UnitParam end
                end
            end
            if not parameter or not parameter:IsValid() then
                local objects=FindAllOf('CPP_UnitParameter') or {}
                for _,p in ipairs(objects) do if p:GetUnitId()==1001 then parameter=p;break end end
            end
            if not parameter or not parameter:IsValid() then log('waiting_for_live_parameter');return end
            once=true
            log('parameter='..parameter:GetFullName())
            -- Exercise direct native calls using the genuine source-card values,
            -- without requiring a packaged inventory item for this adapter test.
            local enabled=false
            local liveResolver=FFRVisionCardBonus
            function FFRVisionCardBonus(unit,type)
                if enabled and unit==1001 then return ({[1]=100,[2]=20,[12]=60,[13]=30,[14]=60,[15]=40})[type] or 0 end
                return 0
            end
            local methods={'GetMaxHitPoint','GetMaxMagicPoint','GetPhysicalAttack','GetPhysicalDefense','GetMagicalAttack','GetMagicalDefense'}
            local expected={100,20,60,30,60,40}
            local before={}
            FFRVisionCardsSetBonus(1001,0,0,0,0,0,0)
            for i,name in ipairs(methods) do before[i]=parameter[name](parameter) end
            enabled=true
            FFRVisionCardsSetBonus(1001,100,20,60,30,60,40)
            for i,name in ipairs(methods) do
                local delta=parameter[name](parameter)-before[i]
                log(name..'_delta='..delta)
                assert(delta==expected[i],name..' bonus mismatch')
            end
            enabled=false
            FFRVisionCardsSetBonus(1001,0,0,0,0,0,0)
            for i,name in ipairs(methods) do assert(parameter[name](parameter)==before[i],'Unequip stacked stats') end
            log('stats=passed')
            FFRVisionCardBonus=liveResolver
            if FFRVisionCardsPackaged then
                local inventory=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataInventory')
                local items=StaticFindObject('/Script/mucha.Default__CPP_BFL_Item')
                for _,id in ipairs(FFRVisionCards.catalog.shop) do
                    local itemId=FFRVisionCards.cards[id].itemId
                    local item=items:GetItemDataById(itemId)
                    assert(item.ID==itemId and item.buyingPrice==1,'Packaged card lookup or price failed: '..id)
                    inventory:AddInventory(itemId,1)
                    assert(inventory:FindInventory(itemId)==1,'Card inventory failed')
                end
                local player=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataPlayer')
                player:SetCurrentMoney(100,false,false)
                local trade=StaticConstructObject(StaticFindObject('/Script/mucha.CPP_VM_Shop_TradeWindow'),parameter)
                trade:SetShopEntryInfo({ShopID=771301,IsTest=false})
                trade:SetIsBuy(true)
                local itemId=FFRVisionCards.cards[401000401].itemId
                trade:UpdateItemSelect({ID=itemId,Num=1})
                local function array(value)
                    if type(value)=='table' then
                        local result={}
                        for _,v in ipairs(value) do result[#result+1]=type(v)=='userdata' and v:get() or v end
                        return result
                    end
                    local result={};value:ForEach(function(_,v) result[#result+1]=v:get() end);return result
                end
                assert(#array(trade:GetSelectEquipItemList())==0,'Card purchase still opens native accessory equip prompt')
                assert(trade:GetTotalAmount()==1,'Shop total must be one gil')
                assert(trade:Trade(),'Native card purchase failed')
                assert(player:GetCurrentMoney()==99 and inventory:FindInventory(itemId)==2,'Card purchase did not exchange one gil for one card')
                log('one_gil_purchase=passed')
                inventory:AddInventory(12000,5)
                for _,card in ipairs(FFRVisionCards.catalog.cards) do
                    assert(items:GetEquipmentTypeById(card.itemId)==0,'Card classified as native gear')
                end
                for group,ids in ipairs({array(inventory:GetInventoryItemIdListByEquipType(3,true)),
                                      array(inventory:GetInventoryItemIdListByEquipType(3,false)),
                                      array(items:GetAllEquipIdListByType(3))}) do
                    local ordinary=false
                    for _,id in ipairs(ids) do
                        assert(not FFRVisionCards.items[id],'Card leaked into accessories')
                        if id==12000 then ordinary=true end
                    end
                    log('Accessory list '..group..' count='..#ids)
                    assert(ordinary,'Ordinary accessory disappeared from list '..group)
                end
                trade:UpdateItemSelect({ID=12000,Num=1})
                assert(#array(trade:GetSelectEquipItemList())==1,'Ordinary accessory equip prompt lost')
                data:SetEquipmentId(1001,12000,1)
                FFRVisionCards:equip(1001,0)
                local legacyCopies=inventory:FindInventory(itemId)
                local legacyAttack=parameter:GetPhysicalAttack()
                FFRVisionCardsSeedProbeAccessory(1001,itemId,0)
                assert(data:GetEquipmentId(1001,3,0)==itemId,'Legacy test setup failed')
                FFRVisionCards:refresh(true)
                assert(data:GetEquipmentId(1001,3,0)~=itemId,'Legacy card still in accessory slot')
                local accessorySlot=data:GetEquipmentId(1001,3,0)==12000 and 0 or 1
                assert(data:GetEquipmentId(1001,3,accessorySlot)==12000,'Legacy repair removed ordinary accessory')
                assert(FFRVisionCards:get(1001)==401000401,'Legacy card did not move to dedicated slot')
                assert(inventory:FindInventory(itemId)==legacyCopies,'Legacy repair lost purchased copies')
                assert(parameter:GetPhysicalAttack()==legacyAttack+60,'Legacy card retained an accessory stat bonus')
                data:SetEquipmentId(1001,itemId,accessorySlot)
                lib:SetEquipmentId(1001,itemId,accessorySlot)
                assert(data:GetEquipmentId(1001,3,accessorySlot)==12000,'Native equip can overwrite accessory with card')
                FFRVisionCards:refresh(true)
                assert(inventory:FindInventory(itemId)==legacyCopies,'Repeated repair changed copies')
                local second=FFRVisionCards.cards[100003801]
                local secondCopies=inventory:FindInventory(second.itemId)
                FFRVisionCardsSeedProbeAccessory(1001,second.itemId,0)
                FFRVisionCardsSeedProbeAccessory(1001,itemId,1)
                FFRVisionCards:refresh(true)
                for slot=0,1 do assert(not FFRVisionCards.items[data:GetEquipmentId(1001,3,slot)],'Two-card legacy repair left an accessory card') end
                assert(FFRVisionCards:get(1001)==401000401,'Repair overwrote an existing card selection')
                assert(inventory:FindInventory(itemId)==legacyCopies and inventory:FindInventory(second.itemId)==secondCopies,'Two-card repair changed purchased quantities')
                lib:SetEquipmentId(1001,12000,1)
                assert(parameter:GetPhysicalAttack()==legacyAttack+60,'Two-card repair doubled stats')
                log('classification_shop_accessory_guard_legacy_repair=passed')
                FFRVisionCards:equip(1001,0)
                local attack=parameter:GetPhysicalAttack()
                FFRVisionCards:equip(1001,401000401)
                assert(parameter:GetPhysicalAttack()==attack+60,'Azure actual stat bonus failed')
                FFRVisionCards:equip(1001,0)
                assert(parameter:GetPhysicalAttack()==attack,'Azure removal failed')
                log('catalog_inventory_equipment=passed')
                local ui=require('ui');ui.start(FFRVisionCards);ui.tick();ui.open(nil,1001)
                log('ui_open=passed')
                ExecuteInGameThreadWithDelay(4000,function()
                    ExecuteInGameThread(function()
                        local ok,why=pcall(function()
                            local found=false
                            for _,npc in ipairs(FindAllOf('CPP_MapUnit_NPC') or {}) do
                                log('npc='..npc:GetFullName()..' unique='..npc.m_UniqueId)
                                if npc.m_UniqueId==9470 then found=true;assert(npc.ShopEntry.ShopID==771301,'Merchant shop wrong') end
                            end
                            if not found then
                                for _,stream in ipairs(FindAllOf('LevelStreamingDynamic') or {}) do
                                    log('stream='..stream:GetFullName()..' loaded='..tostring(stream:IsLevelLoaded()))
                                end
                            end
                            assert(found,'Card merchant not present in live Mitra')
                            for _,head in ipairs(FindAllOf('CPP_WC_ObjectHead') or {}) do
                                local owner=head:GetOwner()
                                if owner and owner:IsValid() and owner:GetFullName():find('NPC_VisionCards',1,true) then
                                    local view=head:GetUserWidgetObject()
                                    log('merchant_head='..head:GetFullName()..' widget='..view:GetFullName())
                                    view:GetClass():ForEachProperty(function(prop) log('head_property='..prop:GetFullName()) end)
                                end
                            end
                            ui.probe_town()
                            ExecuteInGameThreadWithDelay(4000,function()
                                ExecuteInGameThread(function()
                                    local ok,why=pcall(ui.probe)
                                    if not ok then log('error='..tostring(why));return end
                                    log('merchant=passed')
                                    ExecuteInGameThreadWithDelay(4000,function()
                                        ExecuteInGameThread(function()
                                            local ok,why=pcall(ui.probe_live)
                                            if not ok then log('error='..tostring(why)) end
                                        end)
                                    end)
                                end)
                            end)
                        end)
                        if not ok then log('error='..tostring(why)) end
                    end)
                end)
            else log('complete') end
        end)
        if not ok then once=true;log('error='..tostring(why)) end
    end)
    return once
end)
