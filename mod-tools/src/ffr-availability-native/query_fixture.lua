-- Exercise the native explicit-ID query attachment on a protected fresh game.
local M={}
function M.bind(skill)
    assert(type(skill)=='number' and skill==math.floor(skill) and skill>=100000 and skill<1000000)
    assert(type(FFRBattleFixtureBindQuery)=='nil','diagnostic query hook must be absent')
    assert(type(FFRAvailabilityNativeAttachQuery)=='function','production query API missing')
    local commands=tostring(skill)
    local invalid={{},{true},{true,true},{true,'99999'},{true,'1000000'},{true,'1900010'},{true,commands..','..commands}}
    for ordinal,args in ipairs(invalid) do
        local ok,reason=FFRAvailabilityNativeAttachQuery(table.unpack(args))
        assert(ok==false and type(reason)=='string' and #reason>0,'invalid native query attachment accepted')
        print(string.format('[FFRQueryFixture] rejected ordinal=%d reason=%s\n',ordinal,reason))
    end
    local ok,reason=FFRAvailabilityNativeAttachQuery(true,commands)
    assert(ok==true and reason=='native query attached','explicit native query attachment failed')
    local duplicate,why=FFRAvailabilityNativeAttachQuery(true,commands)
    assert(duplicate==false and type(why)=='string','duplicate native query attachment accepted')
    print(string.format('[FFRQueryFixture] attached skill=%d invalid_rejected=%d duplicate_rejected=true transport=runtime\n',skill,#invalid))
    return ok,reason
end
return M
