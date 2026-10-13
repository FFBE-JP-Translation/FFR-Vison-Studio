// Read-only diagnostic of native selection-entry to created-job identity.
// No availability decisions or command/resource mutations are made here.
#include "bridge_core.hpp"
#include <Mod/CppUserModBase.hpp>
#include <LuaMadeSimple/LuaMadeSimple.hpp>
#include <MinHook.h>
#include <intrin.h>
#include <array>
#include <sstream>
#include <cstdio>

namespace {
using RC::LuaMadeSimple::Lua;
using Append=void*(*)(void*,void*,void*,std::int32_t,std::int32_t,std::int32_t,void*,void*,void*,bool,bool,bool,std::int32_t);
Append original{};
const Lua* observer{};
DWORD gameThread{};
std::uint32_t serial{};
struct NativeArray { std::uintptr_t data{};std::int32_t count{},capacity{}; };
static_assert(sizeof(NativeArray)==0x10);
std::wstring module_path(HMODULE module) {
    std::array<wchar_t,32768> path{};const auto count=GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if(!count || count>=path.size()) throw std::runtime_error("module path unavailable");return {path.data(),count};
}
template<class T> T read(std::uintptr_t address) {
    T value{};SIZE_T count{};
    if(!ReadProcessMemory(GetCurrentProcess(),reinterpret_cast<void*>(address),&value,sizeof(value),&count) || count!=sizeof(value))
        throw std::runtime_error("selection observation unreadable");
    return value;
}
void emit(const std::string& line) {
    if(!observer || GetCurrentThreadId()!=gameThread) return;
    const auto stack=observer->get_stack_size();
    try {
        if(observer->is_global_function("FFRSelectionProbeOnObservation")) {
            observer->prepare_function_call("FFRSelectionProbeOnObservation");observer->set_string(line);observer->call_function(1,0);
        }
    } catch(...) { std::printf("[FFRSelectionProbe] Lua observer failed.\n"); }
    while(observer && observer->get_stack_size()>stack) observer->discard_value(-1);
}
void* observed_append(void* receiver,void* output,void* entry,std::int32_t skill,std::int32_t sourceSkill,
    std::int32_t control,void* actions,void* targets,void* parameters,bool item,bool all,bool notConsume,std::int32_t command) {
    const auto caller=reinterpret_cast<std::uintptr_t>(_ReturnAddress())-reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
    const bool enabled=observer && GetCurrentThreadId()==gameThread && serial<2000;
    std::uintptr_t delegate{};NativeArray entries{};std::int32_t ordinal=-1,selectedSkill{},unique{};
    bool readable=enabled;
    if(enabled) try {
        delegate=read<std::uintptr_t>(reinterpret_cast<std::uintptr_t>(receiver)+0x28);
        entries=read<NativeArray>(delegate+0x40);
        if(entries.count<0 || entries.count>256 || entries.capacity<entries.count) throw std::runtime_error("invalid source entry array");
        const auto address=reinterpret_cast<std::uintptr_t>(entry);
        if(address>=entries.data && (address-entries.data)%0x38==0 && (address-entries.data)/0x38<static_cast<std::uintptr_t>(entries.count))
            ordinal=static_cast<std::int32_t>((address-entries.data)/0x38);
        selectedSkill=read<std::int32_t>(address);unique=read<std::int32_t>(address+4);
    } catch(...) { readable=false; }
    // Preserve all thirteen native arguments and the exact output pointer.
    auto* result=original(receiver,output,entry,skill,sourceSkill,control,actions,targets,parameters,item,all,notConsume,command);
    if(!enabled) return result;
    ++serial;
    try {
        if(!readable || result!=output) throw std::runtime_error("selection input/output observation mismatch");
        const auto jobs=read<NativeArray>(reinterpret_cast<std::uintptr_t>(output));
        if(jobs.count<0 || jobs.count>64 || jobs.capacity<jobs.count) throw std::runtime_error("invalid returned job array");
        std::ostringstream line;
        line<<"{\"event\":\"native_selection_append\",\"sequence\":"<<serial
            <<",\"receiver\":"<<reinterpret_cast<std::uintptr_t>(receiver)<<",\"delegate\":"<<delegate
            <<",\"entry\":"<<reinterpret_cast<std::uintptr_t>(entry)<<",\"entries\":"<<entries.data
            <<",\"entryCount\":"<<entries.count<<",\"entryOrdinal\":"<<ordinal
            <<",\"selectedSkill\":"<<selectedSkill<<",\"selectedUnique\":"<<unique
            <<",\"skill\":"<<skill<<",\"sourceSkill\":"<<sourceSkill<<",\"control\":"<<control
            <<",\"item\":"<<(item?"true":"false")<<",\"all\":"<<(all?"true":"false")
            <<",\"notConsume\":"<<(notConsume?"true":"false")<<",\"command\":"<<command
            <<",\"callerRva\":"<<caller<<",\"jobs\":[";
        for(std::int32_t index=0;index<jobs.count;++index) {
            const auto job=read<std::uintptr_t>(jobs.data+static_cast<std::uintptr_t>(index)*8);
            ffr::GuardContext snapshot;
            if(!ffr::GuardBridge::snapshot(reinterpret_cast<void*>(job),snapshot)) throw std::runtime_error("created job unreadable");
            if(index)line<<',';
            line<<"{\"job\":"<<job<<",\"skill\":"<<snapshot.skillId<<",\"objectIndex\":"<<snapshot.objectIndex
                <<",\"rootJob\":"<<snapshot.rootJob<<",\"actor\":"<<snapshot.actor
                <<",\"actions\":"<<snapshot.actionCount<<",\"targets\":"<<snapshot.targetCount<<'}';
        }
        line<<"]}";emit(line.str());
        if(serial==2000)emit("{\"event\":\"selection_observation_capacity\"}");
    } catch(...) { emit("{\"event\":\"selection_observation_failed\"}"); }
    return result;
}
int attach(const Lua& lua) {
    try {
        if(original || lua.get_stack_size()!=0) throw std::runtime_error("selection observer attaches once without arguments");
        if(!lua.is_global_function("FFRSelectionProbeOnObservation")) throw std::runtime_error("selection observer callback missing");
        lua.prepare_function_call("IsInGameThread");lua.call_function(0,1);
        if(!lua.get_bool(-1)) throw std::runtime_error("selection observer requires game thread");
        const auto target=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))+0x4f3efd0;
        constexpr std::array<unsigned char,20> expected{0x44,0x89,0x4c,0x24,0x20,0x55,0x53,0x56,0x41,0x54,0x41,0x57,0x48,0x8d,0xac,0x24,0x30,0xfe,0xff,0xff};
        if(read<std::array<unsigned char,20>>(target)!=expected) throw std::runtime_error("selection append prologue changed");
        HMODULE pinned{};
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&attach),&pinned))
            throw std::runtime_error("cannot pin selection observer");
        auto status=MH_Initialize();if(status!=MH_OK && status!=MH_ERROR_ALREADY_INITIALIZED)throw std::runtime_error(MH_StatusToString(status));
        status=MH_CreateHook(reinterpret_cast<void*>(target),reinterpret_cast<void*>(&observed_append),reinterpret_cast<void**>(&original));
        if(status!=MH_OK)throw std::runtime_error(MH_StatusToString(status));
        observer=&lua;gameThread=GetCurrentThreadId();
        status=MH_EnableHook(reinterpret_cast<void*>(target));
        if(status!=MH_OK) {MH_RemoveHook(reinterpret_cast<void*>(target));original=nullptr;observer=nullptr;throw std::runtime_error(MH_StatusToString(status));}
        lua.set_bool(true);lua.set_string("selection observer attached");return 2;
    } catch(const std::exception& error) {lua.set_bool(false);lua.set_string(error.what());return 2;}
}
class SelectionMod final:public RC::CppUserModBase {
public:
    SelectionMod() {ModName=STR("FFRSelectionProbe");ModVersion=STR("0.1.0");ModDescription=STR("Read-only native selection/job diagnostic");}
    void on_lua_start(RC::StringViewType name,Lua&,Lua& main,Lua&,Lua*) override {
        if(name==STR("FFRBattleProbe"))main.register_function("FFRSelectionProbeAttach",attach);
    }
    void on_lua_stop(RC::StringViewType name,Lua&,Lua&,Lua&,Lua*) override {if(name==STR("FFRBattleProbe"))observer=nullptr;}
    ~SelectionMod() override {observer=nullptr;}
};
static_assert(sizeof(RC::CppUserModBase)==0xc0);
}
extern "C" __declspec(dllexport) RC::CppUserModBase* start_mod() {
    try {
        auto ue4ss=GetModuleHandleW(L"UE4SS.dll");
        if(!ue4ss || ffr::file_sha256(module_path(ue4ss))!="7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d" ||
           ffr::file_sha256(module_path(GetModuleHandleW(nullptr)))!="e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad")
            throw std::runtime_error("selection observer binary fingerprint mismatch");
        return new SelectionMod();
    } catch(const std::exception& error) {std::printf("[FFRSelectionProbe] %s\n",error.what());return nullptr;}
}
extern "C" __declspec(dllexport) void uninstall_mod(RC::CppUserModBase* mod) {delete mod;}
