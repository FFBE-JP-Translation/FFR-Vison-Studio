-- Runs only in a separate test process. It never loads or saves a user slot.
local count,done=0,false
local function emit(value) print('[VisionCardProbe] '..value..'\n') end
LoopAsync(2000,function()
    count=count+1
    ExecuteInGameThread(function()
        if done then return end
        local ok,why=pcall(function()
            local data=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataUnit')
            local inventory=StaticFindObject('/Script/mucha.Default__CPP_BFL_SaveDataInventory')
            local item=StaticFindObject('/Script/mucha.Default__CPP_BFL_Item')
            if not data:IsValid() or not inventory:IsValid() then return end
            local units={};data:GetSaveDataUnitParameterList(units)
            emit('initial_units='..#units)
            if #units==0 then return end
            done=true
            local a=data:GetEquipmentId(1001,3,0)
            local b=data:GetEquipmentId(1001,3,1)
            local c=data:GetEquipmentId(1001,3,2)
            emit(string.format('before=%d,%d,%d',a,b,c))
            inventory:AddInventory(12000,1)
            data:SetEquipmentId(1001,12000,2)
            emit(string.format('after=%d,%d,%d',data:GetEquipmentId(1001,3,0),data:GetEquipmentId(1001,3,1),data:GetEquipmentId(1001,3,2)))
            local bonus=item:GetAllEquippableEquipmentVariationParameter(-1,-1,{-1,-1,12000},-1,1)
            emit('third_slot_hp='..bonus)
            local save={};data:GetSaveDataUnitParameter(save,1001)
            emit('save='..tostring(save.EquipAccessoryIdList))
            local settings=StaticFindObject('/Script/SQEXSaveGameSystemModule.Default__SQEXSaveGameSystemSettings')
            emit('save_title='..settings.GameTitle:ToString())
            emit('complete')
        end)
        if not ok then done=true;emit('error='..tostring(why)) end
    end)
    return count>=15
end)
