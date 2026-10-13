-- Optional UE4SS observation mod. Generated outside the installed game; enable
-- manually for a bounded battle trace. No availability rule is enabled here.
local Probe = require("availability_probe")
if _G.FFRAvailabilityProbe then return end
local battle_library
local function owner(unique_id)
    if not battle_library or not battle_library:IsValid() then
        battle_library = StaticFindObject("/Script/mucha.Default__CPP_BFL_Battle")
    end
    assert(battle_library and battle_library:IsValid(), "battle function library unavailable")
    local parameter = battle_library:GetBattleUnitParameterWithVision(unique_id, false)
    assert(parameter and parameter:IsValid(), "battle parameter unavailable")
    local actor = parameter.m_pVisionOwner
    if not actor or not actor:IsValid() then actor = parameter.m_pOwnerBtlUnit end
    assert(actor and actor:IsValid(), "equipping actor unavailable")
    local actor_parameter = actor.m_pUnitParameter
    assert(actor_parameter and actor_parameter:IsValid(), "owner parameter unavailable")
    local source_actor = parameter.m_pOwnerBtlUnit
    assert(source_actor and source_actor:IsValid(), "source actor unavailable")
    return {actor=actor:GetFullName(), unitId=actor_parameter:GetUnitId(),
            sourceParameter=parameter:GetFullName(), actorAddress=actor:GetAddress(),
            sourceActorAddress=source_actor:GetAddress(), sourceParameterAddress=parameter:GetAddress()}
end
_G.FFRAvailabilityProbe = Probe.install({
    register=RegisterHook, unregister=UnregisterHook, owner=owner,
    emit=function(record) print("[FFRAvailabilityProbe] "..Probe.json(record).."\n") end
})
