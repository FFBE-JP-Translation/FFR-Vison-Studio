#include "query_bridge.hpp"
#include <lua.hpp>
#include <array>
#include <cstring>
#include <stdexcept>
#include <thread>

namespace {
struct NativeCall { std::int32_t unique{},skill{};bool item{};void* selections{};bool option{}; };
NativeCall last{};
int nativeCalls{};
volatile bool nativeResult=true;
__declspec(noinline) bool fixture_query(std::int32_t unique,std::int32_t skill,bool item,void* selections,bool option) {
    ++nativeCalls;last={unique,skill,item,selections,option};return nativeResult;
}
ffr::Query volatile invokeQuery=&fixture_query;
__declspec(noinline) bool fixture_execution(void* raw) {
    volatile auto* bytes=static_cast<volatile unsigned char*>(raw);return bytes[0x340]!=0;
}
ffr::Guard volatile invokeGuard=&fixture_execution;
void run(lua_State* lua,const char* code) {
    if(luaL_dostring(lua,code)!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));
}
}

int run_query_tests() {
    int checks=0;
    const auto check=[&](bool value,const char* name){++checks;if(!value)throw std::runtime_error(name);};
    for(const auto* text: {"", "99999", "1000000", "1900010", "0", "-100000", "900010.5",
                          "900010,", ",900010", "900010,,900011", "900010,900010", "900010junk",
                          " 900010", "+900010", "2147483648", "900010, 900011"}) {
        bool rejected=false;
        try { ffr::parse_query_commands(text,true); } catch(const std::exception&) { rejected=true; }
        check(rejected,"malformed query binding rejected");
    }
    check(ffr::parse_query_commands("",false).empty(),"empty observer query list accepted");
    check(ffr::parse_query_commands("999999,100000,900010",true)==std::vector<std::int32_t>{100000,900010,999999},"active category boundaries and sorted binding");
    std::string capacity;
    for(int i=0;i<512;++i) {if(i)capacity+=',';capacity+=std::to_string(800000+i);}
    check(ffr::parse_query_commands(capacity,true).size()==512,"512 query IDs supported");
    bool overflow=false;
    try {ffr::parse_query_commands(capacity+",801000",true);} catch(const std::exception&) {overflow=true;}
    check(overflow,"query capacity overflow rejected");
    overflow=false;
    try {ffr::parse_query_commands(std::string(6145,'1'),true);} catch(const std::exception&) {overflow=true;}
    check(overflow,"query input size bounded");
    overflow=false;
    try {ffr::parse_query_commands(std::string("900010\0,900011",14),true);} catch(const std::exception&) {overflow=true;}
    check(overflow,"embedded null is not an ID terminator");

    ffr::QueryBridge bridge;std::string error;int callbacks=0;
    auto yes=[](const auto&){return true;};
    check(!bridge.attach(nullptr,{900010},true,yes,GetCurrentThreadId(),error),"missing query target rejected");
    check(!bridge.attach(&fixture_query,{900010},true,{},GetCurrentThreadId(),error),"missing query callback rejected");
    check(!bridge.attach(&fixture_query,{900010},true,yes,0,error),"missing query game thread rejected");
    check(!bridge.attach(&fixture_query,{},true,yes,GetCurrentThreadId(),error),"empty query enforcement rejected");
    for(auto id:{99999,1000000,1900010,-1})
        check(!bridge.attach(&fixture_query,{id},false,yes,GetCurrentThreadId(),error),"invalid category cannot bypass parser");
    check(!bridge.attach(&fixture_query,{900010,900010},true,yes,GetCurrentThreadId(),error),"duplicate query IDs cannot bypass parser");
    check(!bridge.attach(&fixture_query,std::vector<std::int32_t>(513,900010),true,yes,GetCurrentThreadId(),error),"oversize query IDs cannot bypass parser");
    ffr::QueryContext captured{};
    check(bridge.attach(&fixture_query,{900011,900010},true,[&](const auto& c){++callbacks;captured=c;return c.skillId==900010;},GetCurrentThreadId(),error),"multiple managed query IDs attached");
    check(!bridge.attach(&fixture_query,{900010},true,yes,GetCurrentThreadId(),error),"duplicate query attachment rejected");
    ffr::QueryBridge competitor;
    check(!competitor.attach(&fixture_query,{900010},true,yes,GetCurrentThreadId(),error),"second query bridge rejected");
    int selection=42;
    check(invokeQuery(7,900010,false,&selection,true),"managed available query");
    check(nativeCalls==1 && callbacks==1 && captured.uniqueId==7 && captured.skillId==900010 && captured.nativeAllowed
          && captured.selections==reinterpret_cast<std::uintptr_t>(&selection) && captured.option && captured.caller!=0,"query callback receives native context once");
    check(last.unique==7 && last.skill==900010 && !last.item && last.selections==&selection && last.option,"all native query arguments preserved");
    check(!invokeQuery(8,900011,false,nullptr,false) && callbacks==2,"second managed query has independent decision");
    nativeResult=false;
    check(!invokeQuery(-1,900010,false,&selection,false) && callbacks==3 && !captured.nativeAllowed,"native denial reaches callback and cannot be overridden");
    nativeResult=true;
    check(invokeQuery(7,900012,false,&selection,true) && callbacks==3,"unmanaged query preserved");
    check(invokeQuery(7,900011,true,&selection,true) && callbacks==3 && last.item,"item sharing managed numeric ID preserved");
    for(auto id:{0,99999,1000000,1900010})
        check(invokeQuery(7,id,false,nullptr,false) && callbacks==3,"non-active category query preserved");
    nativeResult=false;
    check(!invokeQuery(7,900012,false,nullptr,false) && callbacks==3,"unmanaged native denial preserved");
    check(!invokeQuery(7,900010,true,nullptr,false) && callbacks==3,"item native denial preserved");
    nativeResult=true;
    bool workerManaged=true,workerOther=false,workerItem=false;
    std::thread worker([&]{workerManaged=invokeQuery(7,900010,false,nullptr,false);workerOther=invokeQuery(7,900012,false,nullptr,false);workerItem=invokeQuery(7,900010,true,nullptr,false);});worker.join();
    check(!workerManaged && workerOther && workerItem && callbacks==3,"wrong thread denies only managed non-item queries");
    bridge.invalidate_callback();
    check(!invokeQuery(7,900010,false,nullptr,false) && !invokeQuery(7,900011,false,nullptr,false),"stopped query callback denies all configured IDs");
    check(invokeQuery(7,900012,false,nullptr,false) && invokeQuery(7,900011,true,nullptr,false),"stopped query preserves unmanaged skills and items");
    check(bridge.detach(error) && invokeQuery(7,900011,false,nullptr,false),"query detour removed and original restored");

    check(bridge.attach(&fixture_query,{900010},true,[](const auto&)->bool{throw std::runtime_error("query callback failure");},GetCurrentThreadId(),error),"throwing query attached");
    check(!invokeQuery(7,900010,false,nullptr,false),"query callback exception denies managed ability");
    check(bridge.detach(error),"throwing query detached");
    check(bridge.attach(&fixture_query,{900010},true,[&](const auto&){return invokeQuery(7,900010,false,nullptr,false);},GetCurrentThreadId(),error),"recursive query attached");
    check(!invokeQuery(7,900010,false,nullptr,false),"recursive managed query cannot reenter Lua");
    check(bridge.detach(error),"recursive query detached");

    std::array<std::byte,0x3b0> job{};
    const std::int32_t skill=900010;std::memcpy(job.data()+0x338,&skill,sizeof(skill));job[0x340]=std::byte{1};
    ffr::GuardBridge guard;int guardCalls=0;
    check(guard.attach(&fixture_execution,{900010},true,[&](const auto&){++guardCalls;return true;},GetCurrentThreadId(),error),"query cross-hook guard attached");
    check(bridge.attach(&fixture_query,{900010},true,[&](const auto&){return invokeGuard(job.data());},GetCurrentThreadId(),error),"query-to-guard callback attached");
    check(!invokeQuery(7,900010,false,nullptr,false) && guardCalls==0,"query callback cannot recursively authorize execution");
    check(bridge.detach(error) && guard.detach(error),"query-to-guard hooks detached");
    callbacks=0;
    check(bridge.attach(&fixture_query,{900010},true,[&](const auto&){++callbacks;return true;},GetCurrentThreadId(),error),"guard-to-query callback attached");
    check(guard.attach(&fixture_execution,{900010},true,[&](const auto&){return invokeQuery(7,900010,false,nullptr,false);},GetCurrentThreadId(),error),"guard-to-query guard attached");
    check(!invokeGuard(job.data()) && callbacks==0,"guard callback cannot recursively enter query Lua");
    check(guard.detach(error) && bridge.detach(error),"guard-to-query hooks detached");

    check(bridge.attach(&fixture_query,{},false,[](const auto&)->bool{throw std::runtime_error("observer failure");},GetCurrentThreadId(),error),"query observer attached");
    check(invokeQuery(7,900010,false,nullptr,false),"query observer exception preserves native success");
    nativeResult=false;check(!invokeQuery(7,900010,false,nullptr,false),"query observer preserves native denial");nativeResult=true;
    std::thread observerWorker([&]{workerManaged=invokeQuery(7,900010,false,nullptr,false);});observerWorker.join();
    check(workerManaged && bridge.observations()==2,"wrong-thread observer preserves native decision without Lua");
    check(invokeQuery(7,1900010,false,nullptr,false) && invokeQuery(7,900010,true,nullptr,false) && bridge.observations()==2,"unfiltered observer still excludes items and non-active categories");
    for(int i=0;i<20001;++i) if(!invokeQuery(7,900011,false,nullptr,false)) throw std::runtime_error("bounded query observer changed native decision");
    check(bridge.observations()==20000,"query observer callback capacity");
    bridge.invalidate_callback();check(invokeQuery(7,900010,false,nullptr,false),"stopped observer preserves native decision");
    check(bridge.detach(error),"query observer detached");

    auto* lua=luaL_newstate();check(lua!=nullptr,"query Lua created");luaL_openlibs(lua);
    const std::string file=std::string(FFR_ROOT)+"/tools/ability_converter/runtime/availability.lua";
    if(luaL_dofile(lua,file.c_str())!=LUA_OK) throw std::runtime_error(lua_tostring(lua,-1));lua_setglobal(lua,"availability");
    run(lua,R"lua(
        engine=availability.new({{key='ability',gates={{key='limit',kind='limited',owner='equipping_actor',maximumUses=1,singleCastWhenDualWielding=true,uniqueSelectionOnMulticast=false}}}})
        assert(engine:begin_battle('query-battle'))
        assert(engine:register_owner('query-battle','owner',{'ability'}))
        assert(engine:begin_turn('query-battle','owner',1))
        function allowed(unique,skill,native)
            if unique~=7 or skill~=900010 then return false end
            return engine:query('query-battle','owner','ability',native)
        end
    )lua");
    check(bridge.attach(&fixture_query,{900010},true,[&](const auto& c){
        lua_getglobal(lua,"allowed");lua_pushinteger(lua,c.uniqueId);lua_pushinteger(lua,c.skillId);lua_pushboolean(lua,c.nativeAllowed);
        if(lua_pcall(lua,3,1,0)!=LUA_OK) {lua_pop(lua,1);throw std::runtime_error("query Lua failure");}
        const bool result=lua_isboolean(lua,-1) && lua_toboolean(lua,-1);lua_pop(lua,1);return result;
    },GetCurrentThreadId(),error),"canonical availability query attached");
    check(!invokeQuery(8,900010,false,nullptr,false),"unresolved native query owner denied");
    for(int i=0;i<20001;++i) if(!invokeQuery(7,900010,false,nullptr,false)) throw std::runtime_error("query consumed availability or reached observer-only cap");
    check(bridge.observations()==20002,"enforcement remains active beyond observer cap without spending uses");
    nativeResult=false;check(!invokeQuery(7,900010,false,nullptr,false),"canonical query preserves native denial");nativeResult=true;
    run(lua,"assert(engine.owners.owner.gates.limit.used==0); assert(engine:authorize('query-battle','owner','ability','cast','group',true))");
    check(!invokeQuery(7,900010,false,nullptr,false),"canonical query reflects consumed limited use");
    run(lua,"function allowed() return 'true' end");check(!invokeQuery(7,900010,false,nullptr,false),"non-boolean Lua decision denied");
    run(lua,"function allowed() error('failed resolver') end");check(!invokeQuery(7,900010,false,nullptr,false),"Lua resolver exception denied");
    run(lua,"function allowed() return true end");check(invokeQuery(7,900010,false,nullptr,false),"query callback recovers after error without recursive flag leak");
    check(lua_gettop(lua)==0,"query Lua stack balanced");
    check(bridge.detach(error),"canonical query detached");lua_close(lua);
    return checks;
}
