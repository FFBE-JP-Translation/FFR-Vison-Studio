-- Pure event-driven battle state. No UE object discovery, ticking, save writes,
-- hook registration or command execution occurs in this module. A host must
-- supply authoritative owner IDs, turn ordinals and unique action tokens.
local M = {}
local Engine = {}
Engine.__index = Engine
local MAX_EVENTS = 8192 -- Per owner/battle; overflow denies further actions.
local MAX_OWNERS = 128

local function integer(value, minimum, maximum)
    assert(type(value) == "number" and value == math.floor(value)
        and value >= minimum and value <= (maximum or 2147483647), "invalid integer")
    return value
end
local function identity(value)
    assert(type(value) == "string" and #value > 0 and #value <= 512, "invalid identity")
    return value
end
local function flag(value)
    assert(type(value) == "boolean", "invalid boolean")
    return value
end
local function gate_copy(g)
    assert(g.owner == "equipping_actor", "availability must belong to the equipping actor")
    local d = {key=identity(g.key), kind=g.kind}
    if g.kind == "cooldown" then
        d.cooldownTurns = integer(g.cooldownTurns, 1)
        d.availableOnTurn = integer(g.availableOnTurn, 1, d.cooldownTurns)
        d.singleCastWhenDualWielding = flag(g.singleCastWhenDualWielding)
    elseif g.kind == "limited" then
        d.maximumUses = integer(g.maximumUses, 1)
        d.singleCastWhenDualWielding = flag(g.singleCastWhenDualWielding)
        d.uniqueSelectionOnMulticast = flag(g.uniqueSelectionOnMulticast)
    elseif g.kind == "charges" then
        assert(g.appliesToSelf == true, "external charge pools are not bound")
        d.maximumCharges = integer(g.maximumCharges, 1)
        d.startingCharges = integer(g.startingCharges, 0, d.maximumCharges)
        d.chargeCost = integer(g.chargeCost, 1, d.maximumCharges)
        d.rechargeable = flag(g.rechargeable)
    else
        error("unknown availability rule")
    end
    return d
end

function M.new(commands)
    assert(type(commands) == "table" and #commands > 0 and #commands <= 512, "invalid command list")
    local self = setmetatable({commands={}, rules={}, owners={}, active=false}, Engine)
    for _, command in ipairs(commands) do
        local key = identity(command.key)
        assert(not self.commands[key], "duplicate command identity")
        assert(type(command.gates) == "table" and #command.gates > 0 and #command.gates <= 32, "invalid gate list")
        local gates, seen = {}, {}
        for _, original in ipairs(command.gates) do
            local gate = gate_copy(original)
            assert(not seen[gate.key], "duplicate gate in one command")
            seen[gate.key] = true
            local existing = self.rules[gate.key]
            if existing then
                for k,v in pairs(gate) do assert(existing[k] == v, "conflicting shared gate") end
                for k,v in pairs(existing) do assert(gate[k] == v, "conflicting shared gate") end
            else
                self.rules[gate.key] = gate
            end
            gates[#gates+1] = gate.key
        end
        self.commands[key] = gates
    end
    return self
end

function Engine:begin_battle(battle)
    identity(battle)
    if self.active then return false, "battle_already_active" end
    if self.battle == battle then return false, "battle_token_reused" end
    self.battle, self.owners, self.active, self.ownerCount = battle, {}, true, 0
    return true, "started"
end

function Engine:end_battle(battle)
    if not self.active or self.battle ~= battle then return false, "stale_battle" end
    self.active, self.owners = false, {}
    return true, "ended"
end

local function command_set(self, commands)
    assert(type(commands) == "table" and #commands <= 512, "invalid owner loadout")
    local result, count = {}, 0
    for index,key in pairs(commands) do
        integer(index, 1, #commands)
        identity(key)
        assert(self.commands[key] and not result[key], "invalid owner command")
        result[key], count = true, count+1
    end
    assert(count == #commands, "invalid owner loadout")
    return result
end

local function initialize_gates(self, state, commands)
    for key in pairs(commands) do
        for _,gkey in ipairs(self.commands[key]) do
            if not state.gates[gkey] then
                local rule = self.rules[gkey]
                state.gates[gkey] = {used=0, held=0, charges=rule.startingCharges or 0, readyTurn=rule.availableOnTurn or 1}
            end
        end
    end
end

function Engine:register_owner(battle, owner, commands)
    identity(owner)
    if not self.active or self.battle ~= battle then return false, "stale_battle" end
    if self.owners[owner] then return false, "owner_already_registered" end
    if self.ownerCount >= MAX_OWNERS then return false, "owner_capacity" end
    local granted = command_set(self, commands)
    local state = {turn=0, alive=true, present=true, commands=granted, gates={}, transactions={}, groups={}, events=0}
    initialize_gates(self, state, granted)
    self.owners[owner] = state
    self.ownerCount = self.ownerCount+1
    return true, "registered"
end

function Engine:owner(battle, owner)
    if not self.active or self.battle ~= battle then return nil, "stale_battle" end
    local state = self.owners[owner]
    if not state then return nil, "unbound_owner" end
    if not state.present then return nil, "owner_departed" end
    return state
end

local function release(self, state, transaction, status)
    for _,key in ipairs(self.commands[transaction.command]) do
        state.gates[key].held = state.gates[key].held - 1
    end
    transaction.status = status
end

-- The host supplies the complete, authoritative loadout after a native change.
-- An empty loadout still tracks owner opportunities for later grants. Gates
-- belong to this actor/battle, so removal/regrant never replenishes resources
-- or restarts an initial cooldown. Aliases retain their shared gate balance.
function Engine:sync_loadout(battle, owner, commands)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    local granted = command_set(self, commands) -- Validate before any mutation.
    for _,t in pairs(state.transactions) do
        if t.status == "reserved" and not granted[t.command] then
            release(self, state, t, "cancelled")
        end
    end
    initialize_gates(self, state, granted)
    state.commands = granted
    return true, "loadout_updated"
end

function Engine:begin_turn(battle, owner, ordinal)
    integer(ordinal, 1)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    if ordinal == state.turn then return false, "duplicate_turn" end
    if ordinal ~= state.turn+1 then return false, "turn_out_of_order" end
    for _,t in pairs(state.transactions) do
        if t.status == "reserved" then return false, "pending_action" end
    end
    state.turn = ordinal
    return true, "turn_started"
end

function Engine:set_alive(battle, owner, alive)
    flag(alive)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    state.alive = alive
    if not alive then
        for _,t in pairs(state.transactions) do
            if t.status == "reserved" then release(self, state, t, "cancelled") end
        end
    end
    return true, "updated" -- Death/revival never restores spent uses or charges.
end

function Engine:depart(battle, owner)
    local ok, reason = self:set_alive(battle, owner, false)
    if not ok then return false, reason end
    self.owners[owner].present = false
    return true, "departed"
end

local function available(self, state, command, group, own_reservation)
    if not state.alive then return false, "owner_dead" end
    if state.turn == 0 then return false, "turn_not_started" end
    if state.events >= MAX_EVENTS and not own_reservation then return false, "event_capacity" end
    if not state.commands[command] then return false, "unbound_command" end
    local selected = state.groups[group]
    if selected and selected.closed then return false, "group_closed" end
    for _,key in ipairs(self.commands[command]) do
        local rule, data = self.rules[key], state.gates[key]
        local held = data.held - (own_reservation and 1 or 0)
        if state.turn < data.readyTurn then return false, "cooldown" end
        if rule.kind == "cooldown" and held > 0 then return false, "cooldown_reserved" end
        if rule.kind == "limited" and data.used + held >= rule.maximumUses then return false, "uses_exhausted" end
        if rule.kind == "charges" and data.charges - held*rule.chargeCost < rule.chargeCost then return false, "charges_exhausted" end
        if rule.uniqueSelectionOnMulticast and selected then
            if selected.used[key] then return false, "unique_selection" end
            for _,t in pairs(state.transactions) do
                if t.status == "reserved" and t.group == group and t ~= own_reservation then
                    for _,other in ipairs(self.commands[t.command]) do
                        if other == key then return false, "unique_selection" end
                    end
                end
            end
        end
    end
    return true, "available"
end

function Engine:query(battle, owner, command, native_allowed, group)
    flag(native_allowed)
    if not native_allowed then return false, "native_unavailable" end
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    return available(self, state, command, group)
end

function Engine:reserve(battle, owner, command, token, group, native_allowed)
    identity(token); identity(group)
    local ok, reason = self:query(battle, owner, command, native_allowed, group)
    if not ok then return false, reason end
    local state = self.owners[owner]
    if state.transactions[token] then return false, "duplicate_action" end
    state.transactions[token] = {command=command, group=group, turn=state.turn, status="reserved"}
    state.groups[group] = state.groups[group] or {used={}, closed=false}
    state.events = state.events + 1
    for _,key in ipairs(self.commands[command]) do state.gates[key].held = state.gates[key].held + 1 end
    return true, "reserved"
end

function Engine:cancel(battle, owner, token)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    local t = state.transactions[token]
    if not t or t.status ~= "reserved" then return false, "not_reserved" end
    release(self, state, t, "cancelled")
    return true, "cancelled"
end

function Engine:commit(battle, owner, token, native_allowed)
    flag(native_allowed)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    local t = state.transactions[token]
    if not t or t.status ~= "reserved" then return false, "not_reserved" end
    local ok
    if native_allowed then ok, reason = available(self, state, t.command, t.group, t)
    else ok, reason = false, "native_unavailable" end
    if not ok then release(self, state, t, "cancelled"); return false, reason end
    -- All gates pass before any cost is spent. A commit is the logical cast,
    -- not each animation/hit callback. Replayed tokens never authorize twice.
    for _,key in ipairs(self.commands[t.command]) do
        local rule, data = self.rules[key], state.gates[key]
        if rule.kind == "cooldown" then data.readyTurn = state.turn + rule.cooldownTurns end
        if rule.kind == "limited" then data.used = data.used + 1 end
        if rule.kind == "charges" then data.charges = data.charges - rule.chargeCost end
        state.groups[t.group].used[key] = true
    end
    release(self, state, t, "committed")
    return true, "committed"
end

-- Single entry for the eventual native pre-execution adapter. A selection
-- may already have reserved this cast; automatic selections may arrive here
-- without one. In either case the same token can authorize only one cast.
-- The host must resolve the logical owner/cast first, and call this only for
-- managed commands, after the native guard and before costs/effects.
function Engine:authorize(battle, owner, command, token, group, native_allowed)
    identity(command); identity(token); identity(group); flag(native_allowed)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    local transaction = state.transactions[token]
    if transaction then
        -- Never let a reused callback spend a reservation for another command
        -- or selection group. Leave that legitimate reservation untouched.
        if transaction.command ~= command or transaction.group ~= group then
            return false, "action_identity_mismatch"
        end
        return self:commit(battle, owner, token, native_allowed)
    end
    local reserved
    reserved, reason = self:reserve(battle, owner, command, token, group, native_allowed)
    if not reserved then
        -- This is an execution attempt, not a UI query. Remember a cancelled
        -- managed job even when it had no earlier selection reservation, so a
        -- delayed duplicate cannot revive it after native/cooldown state changes.
        if state.commands[command] and state.events < MAX_EVENTS then
            state.transactions[token] = {command=command, group=group, turn=state.turn, status="cancelled"}
            state.events = state.events + 1
        end
        return false, reason
    end
    return self:commit(battle, owner, token, native_allowed)
end

function Engine:finish_group(battle, owner, group)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    local selected = state.groups[group]
    if not selected or selected.closed then return false, "unknown_or_closed_group" end
    for _,t in pairs(state.transactions) do
        if t.group == group and t.status == "reserved" then return false, "pending_action" end
    end
    selected.closed, selected.used = true, {}
    return true, "closed"
end

function Engine:refill(battle, owner, gate, amount, token)
    integer(amount, 1); identity(token)
    local state, reason = self:owner(battle, owner)
    if not state then return false, reason end
    if not state.alive then return false, "owner_dead" end
    if state.events >= MAX_EVENTS then return false, "event_capacity" end
    if state.transactions[token] then return false, "duplicate_action" end
    local rule, data = self.rules[gate], state.gates[gate]
    if not rule or not data or rule.kind ~= "charges" or not rule.rechargeable then return false, "not_rechargeable" end
    data.charges = math.min(rule.maximumCharges, data.charges + amount)
    state.transactions[token], state.events = {status="refilled"}, state.events + 1
    return true, "refilled"
end

return M
