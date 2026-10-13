// Add card stats at the same native calculation stage as ordinary equipment.
// Both direct battle calls and reflected menu calls pass through this routine.
#include "bridge_core.hpp"
#include <Mod/CppUserModBase.hpp>
#include <LuaMadeSimple/LuaMadeSimple.hpp>
#include <MinHook.h>
#include <array>
#include <algorithm>
#include <cstdio>
#include <limits>
#include <unordered_map>
#include <shared_mutex>
#include <mutex>
#include <atomic>
#include <vector>

namespace {
using RC::LuaMadeSimple::Lua;
using EquipmentBonus = std::int32_t(*)(void*, std::uint8_t);
EquipmentBonus original{};
std::unordered_map<std::int32_t,std::array<std::int32_t,6>> bonuses;
std::shared_mutex bonusMutex;
// IDs must stay stable because existing saves already contain purchased cards.
// The demo classifies 12xxx by arithmetic, ignoring EquipmentType in the table.
std::array<std::atomic_bool,800> cardItems{};
std::atomic_bool selectorOpen{};
using DetailInput=void(*)(void*,const void*);
DetailInput originalDetail{},originalEquipmentDetail{};
void detail_input(void* manager,const void* value) {
    if(!selectorOpen.load(std::memory_order_relaxed)) originalDetail(manager,value);
}
void equipment_detail_input(void* manager,const void* value) {
    if(!selectorOpen.load(std::memory_order_relaxed)) originalEquipmentDetail(manager,value);
}
int set_selector_open(const Lua& lua) {
    if(lua.get_stack_size()!=1) throw std::runtime_error("Expected selector state");
    selectorOpen.store(lua.get_bool(1),std::memory_order_relaxed);return 0;
}
thread_local bool legacyAccess=false;
bool is_card(std::int32_t id) {
    return id>=12200 && id<13000 && cardItems[id-12200].load(std::memory_order_relaxed);
}
template<class T> struct NativeArray {T* data;std::int32_t count,capacity;};
struct TradeItem {std::int32_t id,num;};
using EquipmentType=std::uint8_t(*)(std::int32_t);
using InventoryList=NativeArray<std::int32_t>*(*)(NativeArray<std::int32_t>*,std::uint8_t,bool);
using EquipmentList=NativeArray<std::int32_t>*(*)(NativeArray<std::int32_t>*,std::uint8_t);
using ShopEquipment=NativeArray<TradeItem>*(*)(void*,NativeArray<TradeItem>*);
using SetEquipment=void(*)(std::int32_t,std::int32_t,std::int32_t);
EquipmentType originalType{};
InventoryList originalInventory{};
EquipmentList originalEquipmentList{};
ShopEquipment originalShop{};
SetEquipment originalSaveEquipment{},originalUnitEquipment{};

std::uint8_t card_type(std::int32_t id) {
    // None means outside the four built-in equipment categories. Cards use
    // their own slot and catalog, not the native accessory or vision slot.
    return is_card(id) && !legacyAccess ? 0 : originalType(id);
}
template<class T,class Id> void exclude_cards(NativeArray<T>* list,Id id) {
    if(list->count<=0) return;
    auto end=std::remove_if(list->data,list->data+list->count,[&](const T& v){return is_card(id(v));});
    // These are POD arrays allocated by Unreal. Retain its allocation/capacity.
    if(list->count) list->count=static_cast<std::int32_t>(end-list->data);
}
NativeArray<std::int32_t>* inventory_without_cards(NativeArray<std::int32_t>* out,std::uint8_t type,bool sort) {
    auto result=originalInventory(out,type,sort);
    exclude_cards(result,[](auto id){return id;});return result;
}
NativeArray<std::int32_t>* equipment_without_cards(NativeArray<std::int32_t>* out,std::uint8_t type) {
    auto result=originalEquipmentList(out,type);
    exclude_cards(result,[](auto id){return id;});return result;
}
NativeArray<TradeItem>* shop_without_cards(void* shop,NativeArray<TradeItem>* out) {
    auto result=originalShop(shop,out);
    exclude_cards(result,[](const auto& item){return item.id;});return result;
}
void save_equipment(std::int32_t unit,std::int32_t item,std::int32_t slot) {
    if(!is_card(item) || legacyAccess) originalSaveEquipment(unit,item,slot);
}
void unit_equipment(std::int32_t unit,std::int32_t item,std::int32_t slot) {
    if(!is_card(item) || legacyAccess) originalUnitEquipment(unit,item,slot);
}
int register_item(const Lua& lua) {
    if(lua.get_stack_size()!=1 || original) throw std::runtime_error("Register cards before attaching");
    const auto id=lua.get_integer(1);
    if(id<12200 || id>=13000) throw std::runtime_error("Card item ID outside reserved range");
    cardItems[id-12200].store(true,std::memory_order_relaxed);return 0;
}
int detach_legacy(const Lua& lua) {
    if(lua.get_stack_size()!=2) throw std::runtime_error("Expected unit and legacy card item");
    auto unit=static_cast<std::int32_t>(lua.get_integer(1));
    auto item=static_cast<std::int32_t>(lua.get_integer(1));
    if(unit<=0 || !is_card(item)) throw std::runtime_error("Not a legacy card assignment");
    legacyAccess=true;
    // Unit-level unequip updates both saved equipment and its live parameter
    // object, preventing the former accessory bonus from surviving the move.
    reinterpret_cast<void(*)(std::int32_t,std::int32_t)>(reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr))+0x5242c70)(unit,item);
    legacyAccess=false;return 0;
}
int seed_probe_accessory(const Lua& lua) {
    if(lua.get_stack_size()!=3) throw std::runtime_error("Expected probe unit, card, slot");
    auto unit=static_cast<std::int32_t>(lua.get_integer(1));
    auto item=static_cast<std::int32_t>(lua.get_integer(1));
    auto slot=static_cast<std::int32_t>(lua.get_integer(1));
    if(unit<=0 || !is_card(item) || slot<0 || slot>1) throw std::runtime_error("Invalid legacy probe");
    legacyAccess=true;originalUnitEquipment(unit,item,slot);legacyAccess=false;return 0;
}

std::wstring module_path(HMODULE module) {
    std::array<wchar_t,32768> path{};
    auto size=GetModuleFileNameW(module,path.data(),static_cast<DWORD>(path.size()));
    if(!size || size>=path.size()) throw std::runtime_error("Cannot resolve game module");
    return {path.data(),size};
}

std::int32_t with_card(void* parameter,std::uint8_t type) {
    const auto native=original(parameter,type);
    if(!(type==1 || type==2 || (type>=12 && type<=15))) return native;
    // GetUnitId's generated thunk reads this same field in the pinned binary.
    std::int32_t unit{}; SIZE_T read{};
    if(!ReadProcessMemory(GetCurrentProcess(),static_cast<char*>(parameter)+0xd0,&unit,sizeof(unit),&read) || read!=sizeof(unit)) return native;
    if(unit<=0) return native;
    std::int64_t bonus{};
    {
        std::shared_lock lock(bonusMutex);
        const auto found=bonuses.find(unit);
        if(found!=bonuses.end()) bonus=found->second[type==1 ? 0 : type==2 ? 1 : type-10];
    }
    return static_cast<std::int32_t>(std::min<std::int64_t>(static_cast<std::int64_t>(native)+bonus,std::numeric_limits<std::int32_t>::max()));
}

int set_bonus(const Lua& lua) {
    if(lua.get_stack_size()!=7) throw std::runtime_error("Expected unit ID and six card stats");
    const auto unit=lua.get_integer(1);
    if(unit<=0 || unit>std::numeric_limits<std::int32_t>::max()) throw std::runtime_error("Invalid card owner");
    std::array<std::int32_t,6> values{};
    for(int i=0;i<6;++i) {
        const auto value=lua.get_integer(1);
        if(value<0 || value>999999) throw std::runtime_error("Invalid card stat");
        values[i]=static_cast<std::int32_t>(value);
    }
    std::unique_lock lock(bonusMutex);
    bonuses[static_cast<std::int32_t>(unit)]=values;
    return 0;
}
int clear_bonuses(const Lua&) {
    std::unique_lock lock(bonusMutex);bonuses.clear();return 0;
}

int attach(const Lua& lua) {
    try {
        if(original || lua.get_stack_size()!=0) throw std::runtime_error("Card stat adapter already attached or invalid arguments");
        if(!lua.is_global_function("FFRVisionCardBonus")) throw std::runtime_error("Card stat resolver missing");
        lua.prepare_function_call("IsInGameThread");lua.call_function(0,1);
        if(!lua.get_bool(-1)) throw std::runtime_error("Card stat adapter requires the game thread");
        auto base=reinterpret_cast<std::uintptr_t>(GetModuleHandleW(nullptr));
        auto target=base+0x522e0f0;
        constexpr std::array<unsigned char,20> expected{0x48,0x89,0x5c,0x24,0x08,0x48,0x89,0x6c,0x24,0x10,0x48,0x89,0x74,0x24,0x18,0x57,0x48,0x83,0xec,0x30};
        if(!std::equal(expected.begin(),expected.end(),reinterpret_cast<unsigned char*>(target))) throw std::runtime_error("Equipment calculation changed");
        HMODULE pinned{};
        if(!GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_PIN,reinterpret_cast<LPCWSTR>(&attach),&pinned)) throw std::runtime_error("Cannot pin card adapter");
        auto status=MH_Initialize();
        if(status!=MH_OK && status!=MH_ERROR_ALREADY_INITIALIZED) throw std::runtime_error(MH_StatusToString(status));
        struct Hook {std::uintptr_t rva;void* detour;void** trampoline;};
        const Hook hooks[]={
            {0x522e0f0,reinterpret_cast<void*>(&with_card),reinterpret_cast<void**>(&original)},
            {0x5016e60,reinterpret_cast<void*>(&card_type),reinterpret_cast<void**>(&originalType)},
            {0x510f120,reinterpret_cast<void*>(&inventory_without_cards),reinterpret_cast<void**>(&originalInventory)},
            {0x50137a0,reinterpret_cast<void*>(&equipment_without_cards),reinterpret_cast<void**>(&originalEquipmentList)},
            {0x51ffbc0,reinterpret_cast<void*>(&shop_without_cards),reinterpret_cast<void**>(&originalShop)},
            {0x511e370,reinterpret_cast<void*>(&save_equipment),reinterpret_cast<void**>(&originalSaveEquipment)},
            {0x523df30,reinterpret_cast<void*>(&unit_equipment),reinterpret_cast<void**>(&originalUnitEquipment)},
            // These global detail shortcuts bypass per-widget input flags.
            // Suppress only while the custom card selector owns input.
            {0x51cd3b0,reinterpret_cast<void*>(&detail_input),reinterpret_cast<void**>(&originalDetail)},
            {0x51cdde0,reinterpret_cast<void*>(&equipment_detail_input),reinterpret_cast<void**>(&originalEquipmentDetail)}};
        std::vector<void*> installed;
        try {
            for(const auto& hook:hooks) {
                auto address=reinterpret_cast<void*>(base+hook.rva);
                status=MH_CreateHook(address,hook.detour,hook.trampoline);
                if(status!=MH_OK) throw std::runtime_error(MH_StatusToString(status));
                installed.push_back(address);
                status=MH_EnableHook(address);
                if(status!=MH_OK) throw std::runtime_error(MH_StatusToString(status));
            }
        } catch(...) {
            for(auto address:installed) {MH_DisableHook(address);MH_RemoveHook(address);}
            original=nullptr;throw;
        }
        if(lua.is_global_function("FFRVisionCardsIsProbe")) {
            lua.prepare_function_call("FFRVisionCardsIsProbe");lua.call_function(0,1);
            if(lua.get_bool(-1)) {
                lua.register_function("FFRVisionCardsSeedProbeAccessory",seed_probe_accessory);
            }
        }
        lua.set_bool(true);lua.set_string("Independent card classification, shop, equipment guards and stats attached");return 2;
    } catch(const std::exception& error) {lua.set_bool(false);lua.set_string(error.what());return 2;}
}

class CardMod final:public RC::CppUserModBase {
public:
    CardMod() {ModName=STR("FFRVisionCards");ModVersion=STR("0.3.0");ModDescription=STR("Independent vision card equipment and native stat bonuses");}
    void on_lua_start(RC::StringViewType name,Lua&,Lua& main,Lua&,Lua*) override {
        if(name==STR("FFRVisionCards")) {
            main.register_function("FFRVisionCardsAttach",attach);
            main.register_function("FFRVisionCardsSetBonus",set_bonus);
            main.register_function("FFRVisionCardsClearBonuses",clear_bonuses);
            main.register_function("FFRVisionCardsRegisterItem",register_item);
            main.register_function("FFRVisionCardsDetachLegacy",detach_legacy);
            main.register_function("FFRVisionCardsSetSelectorOpen",set_selector_open);
        }
    }
    void on_lua_stop(RC::StringViewType name,Lua&,Lua&,Lua&,Lua*) override {if(name==STR("FFRVisionCards")){selectorOpen=false;std::unique_lock lock(bonusMutex);bonuses.clear();}}
    ~CardMod() override {selectorOpen=false;std::unique_lock lock(bonusMutex);bonuses.clear();}
};
}
extern "C" __declspec(dllexport) RC::CppUserModBase* start_mod() {
    try {
        const auto ue=GetModuleHandleW(L"UE4SS.dll");
        if(!ue || ffr::file_sha256(module_path(ue))!="7082324aa440169fc992c02812a10f5c68a975d83f95273134c1c7ccddbe4b2d" ||
           ffr::file_sha256(module_path(GetModuleHandleW(nullptr)))!="e06401cdf4e64d55f652043bdd2012267d5529a00c3dbc36ee4365e0ce49caad") throw std::runtime_error("Unsupported game or UE4SS build");
        return new CardMod();
    } catch(const std::exception& error) {std::printf("[FFRVisionCards] %s\n",error.what());return nullptr;}
}
extern "C" __declspec(dllexport) void uninstall_mod(RC::CppUserModBase* mod) {delete mod;}
