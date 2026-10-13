local catalog=require('catalog')
local State=require('state')
FFRVisionCards=State.new(catalog)
for _,card in ipairs(catalog.cards) do FFRVisionCardsRegisterItem(card.itemId) end
function FFRVisionCardsIsProbe() return FFRVisionCardsProbe==true end
function FFRVisionCardBonus(unit,parameter) return FFRVisionCards:bonus(unit,parameter) end
ExecuteInGameThread(function()
    local ok,why=FFRVisionCardsAttach()
    print('[FFRVisionCards] '..tostring(why)..'\n')
    if not ok then return end
    FFRVisionCards:refresh()
    -- Native delegates can fire while another reflected call is on the Lua
    -- stack. Queue work; never re-enter the engine from the delegate callback.
    RegisterHook('/Script/mucha.CPP_UnitVMManager:HandleLoadEnd',function() FFRVisionCardsNeedsRefresh=true end)
    if FFRVisionCardsProbe then require('probe') else require('ui').start(FFRVisionCards) end
end)
