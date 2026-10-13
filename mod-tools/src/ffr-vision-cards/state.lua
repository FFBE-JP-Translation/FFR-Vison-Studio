-- The card slot is stored inside each game's save, in a reserved map-state
-- namespace. Legacy cards in accessory slots are repaired without changing
-- inventory counts, other equipment or permanent/base stats.
local M={}
local NAMESPACE=771300
local PARAM={[1]='hp',[2]='mp',[12]='atk',[13]='def',[14]='mag',[15]='spr'}
local function library(name) return StaticFindObject('/Script/mucha.Default__'..name) end
function M.new(catalog)
    local self={catalog=catalog,cards={},items={}}
    for _,card in ipairs(catalog.cards) do self.cards[card.id]=card;self.items[card.itemId]=card end
    function self:get(unit)
        local map=library('CPP_BFL_SaveDataMap')
        -- The native fields are float32. Split IDs into exact 16-bit halves.
        local low=map:GetGimmickState(NAMESPACE,unit)
        local high=map:GetGimmickValue2(NAMESPACE,unit)
        local id=low+high*65536
        return self.cards[id] and id or 0
    end
    function self:owned(id)
        local card=self.cards[id]
        return card and library('CPP_BFL_SaveDataInventory'):FindInventory(card.itemId) or 0
    end
    function self:owners(id)
        local result,list={},{}
        library('CPP_BFL_SaveDataUnit'):GetSaveDataUnitParameterList(list)
        for _,entry in ipairs(list) do
            local row=type(entry)=='table' and entry or entry:get()
            if self:get(row.UnitId)==id then result[#result+1]=row.UnitId end
        end
        return result
    end
    function self:equip(unit,id)
        if id~=0 then
            assert(self.cards[id],'Unknown vision card')
            if self:get(unit)==id then return end
            assert(self:owned(id)>#self:owners(id),'All copies of this card are equipped')
        end
        local map=library('CPP_BFL_SaveDataMap')
        map:SetGimmickState(NAMESPACE,unit,id%65536)
        map:SetGimmickValue2(NAMESPACE,unit,math.floor(id/65536))
        assert(self:get(unit)==id,'The card slot could not be saved')
        self:sync(unit)
    end
    function self:sync(unit)
        local card=self.cards[self:get(unit)]
        local s=card and self:owned(card.id)>0 and card.stats or {hp=0,mp=0,atk=0,def=0,mag=0,spr=0}
        FFRVisionCardsSetBonus(unit,s.hp,s.mp,s.atk,s.def,s.mag,s.spr)
    end
    function self:refresh(updateViews)
        FFRVisionCardsClearBonuses()
        local list={}
        library('CPP_BFL_SaveDataUnit'):GetSaveDataUnitParameterList(list)
        for _,entry in ipairs(list) do
            local row=type(entry)=='table' and entry or entry:get()
            local repaired=false
            local data=library('CPP_BFL_SaveDataUnit')
            for _=1,2 do
                -- Native unequip compacts the accessory array. Re-read both
                -- slots after each removal so a second card cannot be skipped.
                local id,card
                for slot=0,1 do
                    local item=data:GetEquipmentId(row.UnitId,3,slot)
                    if self.items[item] then id=item;card=self.items[item];break end
                end
                if card then
                    local copies=self:owned(card.id)
                    local function assignments()
                        local n=0
                        for slot=0,1 do if data:GetEquipmentId(row.UnitId,3,slot)==id then n=n+1 end end
                        return n
                    end
                    local before=assignments()
                    FFRVisionCardsDetachLegacy(row.UnitId,id)
                    assert(assignments()<before,'Could not detach legacy accessory card')
                    assert(self:owned(card.id)==copies,'Legacy repair changed card inventory')
                    if self:get(row.UnitId)==0 and copies>#self:owners(card.id) then self:equip(row.UnitId,card.id) end
                    repaired=true
                    print('[FFRVisionCards] Repaired accessory card '..id..' for unit '..row.UnitId..'\n')
                else break end
            end
            self:sync(row.UnitId)
            if updateViews or repaired then library('CPP_BFL_Unit'):ExecuteUnitActionUpdate(row.UnitId) end
        end
    end
    function self:bonus(unit,parameter)
        local card=self.cards[self:get(unit)]
        if not card or self:owned(card.id)<=0 then return 0 end
        return card.stats[PARAM[parameter]] or 0
    end
    function self:available(unit)
        local cards={}
        for _,card in ipairs(self.catalog.cards) do
            if self:owned(card.id)>0 then cards[#cards+1]=card end
        end
        return cards
    end
    return self
end
return M
