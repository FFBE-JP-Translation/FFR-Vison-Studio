#pragma once
#include "bridge_core.hpp"
#include <string_view>

namespace ffr {
struct QueryContext {
    std::int32_t uniqueId{}, skillId{};
    std::uintptr_t selections{}, caller{};
    bool option{}, nativeAllowed{};
};
using Query = bool (*)(std::int32_t, std::int32_t, bool, void*, bool);
using QueryDecision = std::function<bool(const QueryContext&)>;

// Active skills use the shipping game's category bank. Items and command,
// passive and master IDs never become managed query entries.
bool active_skill_id(std::int32_t id);
std::vector<std::int32_t> parse_query_commands(std::string_view text, bool enforce);

// This transport does not reserve or consume uses. A host must resolve the
// native unit and selection context before consulting availability state.
class QueryBridge {
public:
    bool attach(Query target, std::vector<std::int32_t> commands, bool enforce,
                QueryDecision callback, DWORD gameThread, std::string& error);
    void invalidate_callback();
    // Controlled tests only; prevent new callers first. The game pins its
    // hook and module until process exit, including after Lua is stopped.
    bool detach(std::string& error);
    bool installed() const { return target_ != nullptr; }
    std::uint64_t observations() const { return observations_.load(); }
private:
    static bool intercepted(std::int32_t unique, std::int32_t skill, bool item, void* selections, bool option);
    bool decide(const QueryContext& context, bool item);
    static QueryBridge* active_;
    Query target_{}, original_{};
    std::vector<std::int32_t> commands_;
    bool enforce_{};
    DWORD gameThread_{};
    QueryDecision callback_;
    std::recursive_mutex callbackMutex_;
    std::atomic<std::uint32_t> activeCalls_{};
    std::atomic<std::uint64_t> observations_{};
};
}
