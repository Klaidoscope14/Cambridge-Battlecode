// Champion logic: farm camp groups, capture, tribute, shop, survive.
//
// Each turn: refresh knowledge from vision and shared memory, then walk a
// priority chain - retreat when hurt, deny enemy tributes, fight enemies in
// range, finish an active camp fight, bank gems, shop, and otherwise farm the
// best-scoring camp group. Allies coordinate through the 8-byte shared memory
// (target claims plus capture broadcasts); vision is never shared.
#include "bot.h"
#include <algorithm>
#include <array>
#include <cmath>
#include <iostream>
#include <span>
#include <variant>

namespace {

int W = 0, H = 0;
bitboard ally_spawn, enemy_spawn;
std::vector<vec2> altar_tiles;

struct CampSpec {
    float hp, strength;
};

CampSpec spec_of(const bc::camp& c) {
    if (c.is_monolith()) return {20000.f, 200.f};
    if (c.is_elk()) return {2400.f, 60.f};
    if (c.is_wolf()) return {1350.f, 20.f};
    return {500.f, 0.f};  // gem / gold cluster
}

bool has_passive(bc::passive_type p) { return bc::self().passive() == p; }

}  // namespace

// ---------------------------------------------------------------- setup ----

void Bot::init() {
    auto& me = bc::self();
    W = bc::map::width();
    H = bc::map::height();
    ally_spawn = bc::map::spawn_region(team::ally);
    enemy_spawn = bc::map::spawn_region(team::enemy);
    altar_tiles = bc::map::altars().positions();

    terrain = bc::map::walls() | bc::map::holes() | bc::map::altars() | enemy_spawn;

    group_at.assign(static_cast<std::size_t>(W * H), -1);
    const auto raw = bc::map::camp_groups();  // expensive: call once
    groups.reserve(raw.size());
    for (const auto& h : raw) {
        Group g{h, h.spawn_tiles(), {}};
        g.tiles = g.spawn.positions();
        g.gems = static_cast<int>(h.gem_value());
        g.gold = static_cast<int>(h.gold_value());
        g.max_respawn = h.max_respawn_timer();
        for (const auto& c : h.camps()) {
            const auto s = spec_of(c);
            g.hp += s.hp;
            g.strength += s.strength;
            g.monolith = g.monolith || c.is_monolith();
            ++g.camp_count;
        }
        const auto id = static_cast<std::int16_t>(groups.size());
        for (auto t : g.tiles) group_at[static_cast<std::size_t>(tile_index(t))] = id;
        groups.push_back(std::move(g));
    }

    bitboard tribute;
    for (auto a : altar_tiles) tribute |= square(a, bc::constants::submit_gems_range);
    tribute &= ~terrain;
    bitboard visited;
    altar_field.compute(terrain, tribute, visited);
    bitboard visited2;
    spawn_field.compute(terrain, ally_spawn, visited2);

    // Stable body index: rank of our champion type among allies.
    kind = me.champion_name();
    std::vector<int> types;
    for (const auto& c : bc::champions(team::ally)) types.push_back(static_cast<int>(c.champion_name()));
    std::sort(types.begin(), types.end());
    body = static_cast<int>(std::find(types.begin(), types.end(), static_cast<int>(kind)) - types.begin());
    body = std::min(body, Mem::MAX_BODIES - 1);
    bodies = static_cast<int>(types.size());

    ranged = me.attack_range() > 1;
    last_gems = me.gem_count();
    ready = true;
}

int Bot::tile_index(vec2 p) const { return p.y * W + p.x; }

int Bot::group_of(vec2 p) const {
    if (p.x < 0 || p.y < 0 || p.x >= W || p.y >= H) return -1;
    return group_at[static_cast<std::size_t>(tile_index(p))];
}

// ------------------------------------------------------- shared memory ----

void Bot::read_memory() {
    bc::shared_memory.read(0, std::span<std::byte>{reinterpret_cast<std::byte*>(mem), 8});
    static int seen_group = -1, seen_round = -1;
    const int g = mem[Mem::CAPTURE_GROUP] - 1;
    const int r8 = mem[Mem::CAPTURE_ROUND];
    if (g < 0 || g >= static_cast<int>(groups.size()) || (g == seen_group && r8 == seen_round)) return;
    seen_group = g, seen_round = r8;
    const int age = (round - r8) & 0xFF;
    if (age > 60) return;  // stale broadcast
    auto& grp = groups[static_cast<std::size_t>(g)];
    grp.respawn_at = std::max(grp.respawn_at, round - age + grp.max_respawn);
    grp.reward = false;
}

void Bot::write_claim(int group) {
    const std::uint8_t v = static_cast<std::uint8_t>(group + 1);
    if (mem[Mem::CLAIMS + body] == v) return;
    mem[Mem::CLAIMS + body] = v;
    bc::shared_memory.write(static_cast<std::size_t>(Mem::CLAIMS + body),
                            std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

void Bot::broadcast_capture(int group) {
    const std::array<std::uint8_t, 2> v{static_cast<std::uint8_t>(group + 1), static_cast<std::uint8_t>(round & 0xFF)};
    bc::shared_memory.write(Mem::CAPTURE_GROUP, std::span<const std::byte>{reinterpret_cast<const std::byte*>(v.data()), 2});
}

// -------------------------------------------------------------- vision ----

void Bot::observe() {
    auto& me = bc::self();
    round = static_cast<int>(bc::round_number());
    pos = me.position();
    camps = bc::vision::camps();
    // Dead or hidden champions throw on position reads, so keep only live, visible ones.
    enemies.clear();
    for (const auto& c : bc::vision::champions(team::enemy))
        if (c.is_alive() && c.is_visible()) enemies.push_back(c);
    allies.clear();
    for (const auto& c : bc::vision::champions(team::ally))
        if (c.champion_name() != kind && c.is_alive() && c.is_visible()) allies.push_back(c);
    // Snapshot allies now: once we move, some may drop out of our vision.
    mates.clear();
    for (std::size_t i = 0; i < allies.size(); ++i) {
        const auto& a = allies[i];
        mates.push_back({a.position(), a.health(), std::max(a.max_health(), 1.f), a.strength() + 0.25f * a.focus(),
                         static_cast<int>(i)});
    }

    my_hp = me.health();
    my_max = me.max_health();
    enemy_pos.clear();
    for (const auto& e : enemies) enemy_pos.push_back(e.position());

    std::vector<int> living(groups.size(), 0);
    live_hp.assign(groups.size(), -1.f);
    for (const auto& c : camps)
        if (!c.is_dead()) {
            const int gid = group_of(c.spawn_position());
            if (gid < 0) continue;
            auto& hp = live_hp[static_cast<std::size_t>(gid)];
            hp = std::max(hp, 0.f) + c.health();
            ++living[static_cast<std::size_t>(gid)];
        }

    const auto visible = bc::vision::visible_tiles();
    for (std::size_t i = 0; i < groups.size(); ++i) {
        auto& g = groups[i];
        bool seen = false;
        for (auto t : g.tiles)
            if (visible.is_set(t)) { seen = true; break; }
        if (!seen) continue;
        if (living[i] > 0) {
            g.respawn_at = 0;
            g.reward = false;
            continue;
        }
        try {
            const auto st = g.handle.state();
            if (std::holds_alternative<bc::map::camp_group_reward_available>(st)) {
                g.reward = true;
                g.respawn_at = 0;
            } else if (const auto* r = std::get_if<bc::map::camp_group_respawning>(&st)) {
                g.reward = false;
                g.respawn_at = round + r->timer;
            }
        } catch (...) {
        }
    }
}

// ------------------------------------------------------------ shopping ----

std::optional<bc::item_type> Bot::next_item() const {
    using I = bc::item_type;
    const bool focus = kind == bc::champion_type::stellar || kind == bc::champion_type::prism
        || kind == bc::champion_type::cassi;
    struct Step { I shard, emblem; };
    std::vector<Step> plan;
    if (kind == bc::champion_type::vesper_vale)
        plan.push_back({I::treasure_shard_of_strength, I::treasure_emblem_of_strength});
    if (focus) {
        plan.push_back({I::monster_shard_of_focus, I::monster_emblem_of_focus});
        plan.push_back({I::jungle_shard_of_health, I::jungle_emblem_of_health});
    } else {
        plan.push_back({I::monster_shard_of_strength, I::monster_emblem_of_strength});
        plan.push_back({I::jungle_shard_of_health, I::jungle_emblem_of_health});
    }
    const auto owned = bc::self().item_count();
    for (const auto& s : plan)
        if (owned[s.emblem] == 0) return s.shard;
    return focus ? I::power_shard_of_focus : I::power_shard_of_strength;
}

void Bot::shop() {
    auto& me = bc::self();
    const auto lock = bc::consumable_type::altar_lock;
    if (me.gold_count() >= static_cast<unsigned>(Cfg::LOCK_MIN_GOLD) && me.consumables()[lock].count() == 0
        && me.can_buy(lock))
        me.buy(lock);
    for (int i = 0; i < 12; ++i) {
        const auto item = next_item();
        if (!item || me.gold_count() < item->cost() || !me.can_buy(*item)) break;
        me.buy(*item);
    }
}

bool Bot::wants_shop() const {
    return bc::self().gold_count() >= static_cast<unsigned>(Cfg::SHOP_TRIP_GOLD) && kind != bc::champion_type::tavi;
}

// ---------------------------------------------------------- navigation ----

bitboard Bot::blocked_now() const {
    auto b = terrain | bc::vision::champion_tiles() | bc::vision::camp_tiles() | bc::vision::teleport_tiles();
    b.set(pos, false);
    return b;
}

bool Bot::move_to(bitboard goals, bool allow_dash) {
    auto& me = bc::self();
    if (!me.can_move()) return false;
    const auto blocked = blocked_now();
    goals &= ~blocked;
    if (goals.is_empty() || goals.is_set(pos)) return false;

    bc::distance_field field;
    bitboard origin;
    origin.set(pos, true);
    auto here_d = UNREACH;
    // Route around tiles inside enemy burst range when a safe path exists.
    ensure_danger();
    if (!danger.is_empty()) {
        bitboard visited;
        field.compute_to(blocked | (danger & ~goals), goals, origin, visited);
        here_d = field.get(pos);
    }
    if (here_d == UNREACH) {
        bitboard visited;
        field.compute_to(blocked, goals, origin, visited);
        here_d = field.get(pos);
    }
    if (here_d == UNREACH) return false;

    // A dash is compatible with walking: take it first on long trips.
    if (allow_dash && here_d > 3 && me.can_cast()) {
        for (const auto& ab : me.abilities()) {
            if (!ab.is_dash() || !ab.is_ready()) continue;
            const auto tiles = ab.valid_tiles() & ~blocked;
            vec2 best = pos;
            auto best_d = here_d;
            for (auto t : tiles.positions()) {
                const auto d = field.get(t);
                if (d + 1 < best_d) best_d = d, best = t;
            }
            if (best != pos) {
                try {
                    if (ab.use(best)) pos = best;
                } catch (...) {
                }
            }
            break;
        }
    }

    // Walk to the best neighbour; a hidden bush occupant returns false, so retry.
    auto steps = blocked.reachable_tiles(pos, static_cast<std::uint16_t>(me.base_stats().base_move_speed)).positions();
    std::sort(steps.begin(), steps.end(), [&](vec2 a, vec2 b) { return field.get(a) < field.get(b); });
    const auto cur = field.get(pos);
    int tries = 0;
    for (auto t : steps) {
        if (field.get(t) >= cur || ++tries > 3) break;
        try {
            if (me.move_absolute(t)) {
                pos = t;
                return true;
            }
        } catch (...) {
        }
    }
    return false;
}

bool Bot::step_away(const std::vector<vec2>& threats) {
    auto& me = bc::self();
    if (!me.can_move() || threats.empty()) return false;
    const auto blocked = blocked_now();
    vec2 best = pos;
    int best_gap = 99;
    for (auto t : threats) best_gap = std::min(best_gap, cheb(pos, t));
    int best_home = spawn_field.get(pos);
    for (auto t : blocked.reachable_tiles(pos, 1).positions()) {
        int gap = 99;
        for (auto th : threats) gap = std::min(gap, cheb(t, th));
        const int home = spawn_field.get(t);
        if (gap > best_gap || (gap == best_gap && home < best_home)) best = t, best_gap = gap, best_home = home;
    }
    if (best == pos) return false;
    try {
        if (me.move_absolute(best)) {
            pos = best;
            return true;
        }
    } catch (...) {
    }
    return false;
}

// ----------------------------------------------------------- targeting ----

void Bot::estimate_dps() {
    auto& me = bc::self();
    const float str = me.strength();
    float single = str, multi = str;
    for (const auto& ab : me.abilities()) {
        if (ab.is_attack_reset()) single += str / 8.f, multi += str / 8.f;
        else if (ab.is_damage()) single += ab.damage_amount() / 8.f, multi += ab.damage_amount() / 8.f;
        else if (ab.is_aoe_damage()) single += ab.damage_amount() / 8.f, multi += ab.damage_amount() * 2.f / 8.f;
    }
    if (has_passive(bc::passive_type::splash_attack)) multi += str * 0.6f;
    if (has_passive(bc::passive_type::reset_cooldowns_on_kill)) single *= 1.1f, multi *= 1.1f;
    dps_single = std::max(single, 1.f);
    dps_multi = std::max(multi, 1.f);
}

float Bot::my_dps(const Group& g) const { return g.camp_count >= 2 ? dps_multi : dps_single; }

float Bot::group_hp(int id) const {
    const float seen = live_hp[static_cast<std::size_t>(id)];
    return seen >= 0.f ? seen : groups[static_cast<std::size_t>(id)].hp;
}

int Bot::claims_on(int id) const {
    int n = 0;
    for (int b = 0; b < Mem::MAX_BODIES; ++b)
        if (b != body && mem[Mem::CLAIMS + b] == id + 1) ++n;
    return n;
}

// Fewest allies that must fight beside us for the group to be safe; -1 if never.
// Incoming damage scales with 1 / (1 + helpers), so solve for helpers directly.
int Bot::required_helpers(const Group& g) const {
    if (g.strength <= 0.f) return 0;
    const float allowance = my_hp - Cfg::FIGHT_HP_MARGIN * my_max;
    if (allowance <= 0.f) return -1;
    const float hp = group_hp(static_cast<int>(&g - groups.data()));
    const float solo = g.strength * (g.camp_count > 1 ? 0.65f : 1.f) * hp / my_dps(g);
    const int h = std::max(0, static_cast<int>(std::ceil(solo / allowance)) - 1);
    return h < bodies ? h : -1;
}

int Bot::allies_near(const Group& g) const {
    int n = 0;
    for (const auto& a : mates) {
        const auto p = a.pos;
        for (auto t : g.tiles)
            if (cheb(p, t) <= Cfg::SQUAD_WAIT_RING + 1) { ++n; break; }
    }
    return n;
}

float Bot::group_score(int id, int dist, int* req_out) const {
    const auto& g = groups[static_cast<std::size_t>(id)];
    if (g.monolith || round < g.skip_until) return -1.f;
    if (g.respawn_at > round + dist) return -1.f;
    const int req = g.reward ? 0 : required_helpers(g);
    if (req < 0) return -1.f;
    if (req_out) *req_out = req;
    const int claims = claims_on(id);
    const int crew = std::max(req, claims);  // bodies sharing the fight and the reward

    const float hp = g.reward ? 0.f : group_hp(id);
    const float kill = hp / (my_dps(g) * (1 + crew));
    float value = g.gems + Cfg::GOLD_WEIGHT * g.gold;
    if (g.strength <= 0.f && claims > 0) value *= Cfg::CLAIMED_PENALTY;
    else if (crew > 0) value /= static_cast<float>(1 + crew);
    if (req > 0) value *= 1.f + Cfg::SQUAD_CLAIM_BONUS * std::min(claims, req);  // converge on one squad target
    for (const auto& f : foes)
        if (cheb(f.pos, g.tiles.front()) <= 5) {
            // Never walk into a stronger enemy group; share a contested camp reluctantly.
            if (side_power(g.tiles.front(), true) > Cfg::OUTMATCHED * side_power(g.tiles.front(), false)) return -1.f;
            value *= Cfg::ENEMY_NEAR_PENALTY;
            break;
        }
    const float time = dist + kill + bc::constants::capture_time + std::max(0, g.respawn_at - round - dist);
    return value / (time + 4.f);
}

int Bot::choose_target() {
    // Keep the current target between re-scores unless it has gone stale.
    if (target >= 0 && round < next_eval) {
        const auto& g = groups[static_cast<std::size_t>(target)];
        if (g.respawn_at <= round + 2 && round >= g.skip_until) return target;
    }
    next_eval = round + Cfg::RETARGET_EVERY;
    {
        bitboard visited, origin;
        origin.set(pos, true);
        here.compute(terrain, origin, visited);
    }
    int best = -1, best_req = 0, current_req = 0;
    float best_s = 0.f, current = -1.f;
    for (std::size_t i = 0; i < groups.size(); ++i) {
        int dist = UNREACH;
        for (auto t : groups[i].tiles) dist = std::min<int>(dist, here.get(t));
        if (dist >= UNREACH) continue;
        int req = 0;
        const float s = group_score(static_cast<int>(i), dist, &req);
        if (static_cast<int>(i) == target) current = s, current_req = req;
        if (s > best_s) best_s = s, best = static_cast<int>(i), best_req = req;
    }
    if (target >= 0 && current > 0.f && best_s < current * Cfg::SWITCH_MARGIN) best = target, best_req = current_req;

    // Squad deadlock breaker: after waiting a while, join whichever squad target
    // has the most committed allies; after waiting too long, give up on it.
    if (best >= 0 && best == target && best_req > 0 && wait_turns > Cfg::SQUAD_REGROUP_TURNS) {
        int join = -1, join_claims = claims_on(best), join_req = 0;
        for (std::size_t i = 0; i < groups.size(); ++i) {
            const int id = static_cast<int>(i);
            const int c = claims_on(id);
            if (id == best || c <= join_claims || here.get(groups[i].tiles.front()) >= UNREACH) continue;
            const int req = required_helpers(groups[i]);
            if (req < 0 || groups[i].monolith || groups[i].respawn_at > round) continue;
            join = id, join_claims = c, join_req = req;
        }
        if (join >= 0) {
            best = join, best_req = join_req, wait_turns = 0;
        } else if (wait_turns > Cfg::SQUAD_GIVE_UP_TURNS) {
            groups[static_cast<std::size_t>(best)].skip_until = round + 40;
            best = -1, best_req = 0, wait_turns = 0;
        }
    }
    if (best != target) wait_turns = 0;
    target = best;
    need = best < 0 ? 0 : best_req;
    write_claim(target);
    return target;
}

// -------------------------------------------------------------- threat ----

void Bot::assess_threat() {
    foes.clear();
    danger = bitboard{};
    danger_ready = true;
    burst_here = 0.f;
    outmatched = false;
    for (std::size_t i = 0; i < enemies.size(); ++i) {
        const auto& e = enemies[i];
        Foe f;
        f.pos = enemy_pos[i];
        f.hp = e.health();
        f.max_hp = std::max(e.max_health(), 1.f);
        f.strength = e.strength();
        f.ranged = e.attack_range() > 1;
        f.gems = static_cast<int>(e.gem_count());
        f.index = static_cast<int>(i);
        for (const auto& ab : e.abilities()) {
            if (ab.is_on_cooldown()) continue;
            if (ab.is_attack_reset()) f.reset = true;
            else if (ab.is_dash()) f.dash = true;
            if (ab.is_cc()) f.stun = true;
            if (ab.is_damage() || ab.is_aoe_damage()) f.spell = std::max(f.spell, ab.damage_amount());
        }
        foes.push_back(f);
    }
    if (foes.empty()) return;
    burst_here = burst_at(pos);
    int nearest = 99;
    for (const auto& f : foes) nearest = std::min(nearest, cheb(f.pos, pos));
    outmatched = nearest <= Cfg::SKIRMISH_RANGE && side_power(pos, true) > Cfg::OUTMATCHED * side_power(pos, false);
    danger_ready = false;
}

// Tiles near us where the visible enemies could take most of our health.
// Built lazily on the first walk of the turn: it is the costly part.
void Bot::ensure_danger() {
    if (danger_ready) return;
    danger_ready = true;
    const float limit = Cfg::DANGER_TILE * my_hp;
    float peak = 0.f;
    for (const auto& f : foes) peak += std::max({f.strength * (f.reset ? 2.f : 1.f), f.spell + f.strength, 2.f * f.strength});
    if (peak < limit) return;  // no tile can reach the limit
    for (auto t : (square(pos, 4) & ~terrain).positions())
        if (burst_at(t) >= limit) danger.set(t, true);
    danger.set(pos, false);
}

// Damage the visible enemies could land on tile p in their next turns. Each
// gets one cast, so a reset, a dash and a spell are alternatives, not a sum.
float Bot::burst_at(vec2 p) const {
    float total = 0.f;
    for (const auto& f : foes) {
        const int d = cheb(f.pos, p);
        const int hit = f.ranged ? 3 : 1;
        const int walk = f.ranged ? 3 : 2;  // ranged champions cannot walk and attack
        float best = 0.f;
        if (d <= walk) best = f.strength * (f.reset ? 2.f : 1.f);
        if (f.dash && d <= walk + 2) best = std::max(best, f.strength);
        if (f.spell > 0.f && d <= 4) best = std::max(best, f.spell + (d <= hit ? f.strength : 0.f));
        if (f.stun && d <= 4) best = std::max(best, (d <= hit ? f.strength : 0.f) + f.strength);  // stunned, we eat another round
        total += best;
    }
    return total;
}

// Lanchester-style fight power of one side around a tile: total health times
// total damage per round. Our own body always counts.
float Bot::side_power(vec2 at, bool enemy) const {
    float hp = 0.f, dps = 0.f;
    if (enemy) {
        for (const auto& f : foes)
            if (cheb(f.pos, at) <= Cfg::SKIRMISH_RANGE) hp += f.hp, dps += f.strength + f.spell / 8.f;
    } else {
        auto& me = bc::self();
        hp = my_hp, dps = me.strength() + 0.25f * me.focus();
        for (const auto& a : mates)
            if (cheb(a.pos, at) <= Cfg::SKIRMISH_RANGE) hp += a.hp, dps += a.power;
    }
    return hp * dps;
}

// Damage we can put on one champion this turn.
float Bot::my_burst() const {
    auto& me = bc::self();
    const float str = me.strength();
    float best = me.can_attack() ? str : 0.f;
    if (!me.can_cast()) return best;
    for (const auto& ab : me.abilities()) {
        if (!ab.is_ready()) continue;
        if (ab.is_attack_reset()) best = std::max(best, me.can_attack() ? 2.f * str : str);
        else if (ab.is_damage() || ab.is_aoe_damage()) best = std::max(best, (me.can_attack() ? str : 0.f) + ab.damage_amount());
    }
    return best;
}

// Step (or dash) to the reachable tile with the least enemy burst, preferring
// home. Tribute first when an altar is in reach and the bag survives the wait.
bool Bot::escape() {
    auto& me = bc::self();
    const bool lethal = burst_here * Cfg::LETHAL_MARGIN >= my_hp;
    if (me.gem_count() > 0 && !lethal && me.gem_count() <= 20)
        for (auto a : altar_tiles)
            if (cheb(a, pos) <= bc::constants::submit_gems_range && !bc::vision::has_altar_lock(a)) {
                try {
                    me.submit_gems(a);
                    return true;
                } catch (...) {
                }
            }
    if (!me.can_move()) return false;
    const auto blocked = blocked_now();
    auto pick_from = [&](const bitboard& tiles, vec2& best, float& best_b, int& best_home) {
        for (auto t : tiles.positions()) {
            const float b = burst_at(t);
            const int home = spawn_field.get(t);
            if (b < best_b - 1.f || (b <= best_b + 1.f && home < best_home)) best = t, best_b = b, best_home = home;
        }
    };
    vec2 best = pos;
    float best_b = burst_here;
    int best_home = spawn_field.get(pos);
    auto steps = blocked.reachable_tiles(pos, 1);
    steps.set(pos, false);
    pick_from(steps, best, best_b, best_home);

    // Dash when walking still leaves us in kill range.
    if (best_b * Cfg::LETHAL_MARGIN >= my_hp && me.can_cast())
        for (const auto& ab : me.abilities()) {
            if (!ab.is_dash() || !ab.is_ready()) continue;
            vec2 jump = pos;
            float jb = best_b;
            int jh = best_home;
            pick_from(ab.valid_tiles() & ~blocked, jump, jb, jh);
            if (jump != pos && jb < best_b) {
                try {
                    if (ab.use(jump)) {
                        pos = jump;
                        return true;
                    }
                } catch (...) {
                }
            }
            break;
        }
    if (best == pos) return false;
    try {
        if (me.move_absolute(best)) {
            pos = best;
            return true;
        }
    } catch (...) {
    }
    return false;
}

// -------------------------------------------------------------- combat ----

// Focus fire: anything we can kill this turn first, then gem carriers, then the
// lowest health share. With kills_only, ignore targets that would survive.
bool Bot::fight_enemies(bool kills_only) {
    auto& me = bc::self();
    if (foes.empty()) return false;
    const float burst = my_burst();
    auto priority = [&](const Foe& f) {
        float s = 1.f - f.hp / f.max_hp + f.gems / 200.f;
        if (f.hp <= burst) s += 10.f;
        return s;
    };
    std::vector<const Foe*> order;
    for (const auto& f : foes)
        if (!kills_only || f.hp <= burst) order.push_back(&f);
    if (order.empty()) return false;
    std::sort(order.begin(), order.end(), [&](const Foe* a, const Foe* b) { return priority(*a) > priority(*b); });

    // Melee: close in on a target we can finish this turn when it is safe to.
    if (!ranged && me.can_move() && me.can_attack() && !outmatched) {
        const auto reach = me.attack_tiles();
        bool any = false;
        for (const auto* f : order) any = any || reach.is_set(f->pos);
        if (!any)
            for (const auto* f : order) {
                if (f->hp > burst || cheb(f->pos, pos) != 2) continue;
                bitboard goal = square(f->pos, 1);
                bool safe = false;
                for (auto t : goal.positions()) safe = safe || burst_at(t) < 0.5f * my_hp;
                if (safe && move_to(goal, false)) break;
            }
    }

    bool engaged = false;
    const bc::champion* hit = nullptr;
    if (me.can_attack()) {
        const auto reach = me.attack_tiles();
        for (const auto* f : order)
            if (reach.is_set(f->pos)) {
                try {
                    me.attack(enemies[static_cast<std::size_t>(f->index)]);
                } catch (...) {
                    continue;  // hidden since the snapshot (bush)
                }
                hit = &enemies[static_cast<std::size_t>(f->index)];
                acted_attack = engaged = true;
                break;
            }
    }
    // Attack reset on the same target if it is still standing.
    if (hit && me.can_cast())
        for (const auto& ab : me.abilities()) {
            if (!ab.is_attack_reset() || !ab.is_ready()) continue;
            try {
                if (hit->is_alive() && hit->is_visible() && ab.use() && me.can_attack()) me.attack(*hit);
            } catch (...) {
            }
            return true;
        }
    if (me.can_cast()) {
        for (const auto& ab : me.abilities()) {
            if (!ab.is_ready() || !(ab.is_damage() || ab.is_aoe_damage() || ab.is_cc())) continue;
            const bool unit = ab.can_target_enemies();
            if (!unit && !ab.can_target_ground()) continue;
            const auto tiles = ab.valid_tiles();
            for (const auto* f : order) {
                const auto& e = enemies[static_cast<std::size_t>(f->index)];
                if (!tiles.is_set(f->pos) || !e.is_alive() || !e.is_visible()) continue;
                if (!unit) {  // ground area: never splash a sleeping camp awake
                    bool wakes = false;
                    for (const auto& c : camps)
                        if (!c.is_dead() && !c.is_awake() && cheb(c.position(), f->pos) <= 1) wakes = true;
                    if (wakes) continue;
                }
                try {
                    if (unit ? ab.use(e) : ab.use(f->pos)) return true;
                } catch (...) {
                }
            }
        }
    }
    return engaged;
}

bool Bot::try_lock_altar() {
    auto& me = bc::self();
    auto& lock = me.consumables()[bc::consumable_type::altar_lock];
    if (lock.count() == 0) return false;
    for (const auto& f : foes) {
        const auto& e = enemies[static_cast<std::size_t>(f.index)];
        if (f.gems < 10) continue;
        try {
            if (!e.is_submitting_gems()) continue;
            for (auto a : altar_tiles) {
                if (cheb(a, f.pos) > bc::constants::submit_gems_range || cheb(a, pos) > 2) continue;
                if (bc::vision::has_altar_lock(a)) continue;
                if (lock.use(a)) return true;
            }
        } catch (...) {
        }
    }
    return false;
}

void Bot::cast_on_camps(int gid) {
    auto& me = bc::self();
    if (!me.can_cast()) return;
    auto relevant = [&](const bc::camp& c) {
        if (c.is_dead()) return false;
        const int g = group_of(c.spawn_position());
        return g == gid || c.is_awake();
    };
    for (const auto& ab : me.abilities()) {
        if (!ab.is_ready() || !ab.can_target_camps() && !ab.can_target_ground()) continue;
        if (!(ab.is_damage() || ab.is_aoe_damage() || ab.is_cc())) continue;
        const auto tiles = ab.valid_tiles();
        const bc::camp* pick = nullptr;
        int pick_score = -1;
        for (const auto& c : camps) {
            if (!relevant(c) || !tiles.is_set(c.position())) continue;
            int s = 0;
            if (ab.is_aoe_damage()) {
                for (const auto& o : camps)
                    if (relevant(o) && cheb(o.position(), c.position()) <= 1) ++s;
            } else if (ab.is_cc() && !ab.is_damage()) {
                if (spec_of(c).strength <= 0.f) continue;  // stunning a cluster is wasted
                s = static_cast<int>(spec_of(c).strength);
            } else {
                s = 100000 - static_cast<int>(c.health());  // finish the weakest
            }
            if (s > pick_score) pick_score = s, pick = &c;
        }
        if (!pick) continue;
        try {
            const bool ok = ab.can_target_camps() && !ab.is_aoe_damage() ? ab.use(*pick) : ab.use(pick->position());
            if (ok) return;
        } catch (...) {
        }
    }
}

bool Bot::attack_camp(int gid) {
    auto& me = bc::self();
    const auto reach = me.attack_tiles();
    auto best_in_range = [&]() -> const bc::camp* {
        const bc::camp* pick = nullptr;
        for (const auto& c : camps) {
            if (c.is_dead() || !reach.is_set(c.position())) continue;
            if (group_of(c.spawn_position()) != gid && !c.is_awake()) continue;  // never wake a new group
            if (!pick || c.health() < pick->health()) pick = &c;
        }
        return pick;
    };
    const auto* pick = best_in_range();
    if (!pick) return false;
    if (me.can_attack()) {
        me.attack(*pick);
        acted_attack = true;
        // Attack reset: refresh and swing again at whatever is still in range.
        for (const auto& ab : me.abilities()) {
            if (!ab.is_attack_reset() || !ab.is_ready() || !me.can_cast()) continue;
            camps = bc::vision::camps();
            if (const auto* again = best_in_range()) {
                try {
                    if (ab.use() && me.can_attack()) me.attack(*again);
                } catch (...) {
                }
            }
            break;
        }
    }
    camps = bc::vision::camps();
    cast_on_camps(gid);
    return true;
}

void Bot::use_support_abilities() {
    auto& me = bc::self();
    if (!me.can_cast()) return;
    bool pressured = false;
    for (const auto& c : camps)
        if (c.is_awake() && !c.is_dead() && cheb(c.position(), pos) <= 3) pressured = true;
    for (const auto& f : foes)
        if (cheb(f.pos, pos) <= 3) pressured = true;
    for (const auto& ab : me.abilities()) {
        if (!ab.is_ready()) continue;
        try {
            if (ab.is_shield() && pressured && me.health() < 0.85f * me.max_health()) {
                if (ab.use()) return;
            } else if (ab.is_heal()) {
                const auto tiles = ab.valid_tiles();
                const Mate* pick = nullptr;
                for (const auto& a : mates)
                    if (tiles.is_set(a.pos) && a.hp < 0.7f * a.max_hp && (!pick || a.hp / a.max_hp < pick->hp / pick->max_hp))
                        pick = &a;
                if (pick && ab.use(allies[static_cast<std::size_t>(pick->index)])) return;
            }
        } catch (...) {
        }
    }
}

// ------------------------------------------------------ economy & safety ----

bool Bot::retreat_if_hurt() {
    auto& me = bc::self();
    if (me.health() >= Cfg::RETREAT_HP * me.max_health()) return false;
    if (ally_spawn.is_set(pos)) return true;  // heal at turn end

    // Tribute ignores damage, so a bag next to an altar is banked even now.
    if (me.gem_count() > 0)
        for (auto a : altar_tiles)
            if (cheb(a, pos) <= bc::constants::submit_gems_range && !bc::vision::has_altar_lock(a)) {
                try {
                    me.submit_gems(a);
                    return true;
                } catch (...) {
                }
            }

    std::vector<vec2> threats;
    for (const auto& c : camps)
        if (c.is_awake() && !c.is_dead() && cheb(c.position(), pos) <= 4) threats.push_back(c.position());
    bool hunted = false;
    for (const auto& f : foes) hunted = hunted || cheb(f.pos, pos) <= 5;
    if (hunted) {
        if (!escape() && !fight_enemies()) step_away(enemy_pos);
        return true;
    }
    if (!threats.empty()) {
        step_away(threats);
        return true;
    }
    if (spawn_field.get(pos) <= 6 && move_to(ally_spawn)) return true;
    me.recall();
    return true;
}

bool Bot::should_bank() const {
    auto& me = bc::self();
    const int bag = static_cast<int>(me.gem_count());
    if (bag == 0) return false;
    if (bc::global_submitted_gems(team::ally) + bag >= bc::constants::winning_gems) return true;
    if (round + 40 >= static_cast<int>(bc::constants::max_rounds)) return true;
    if (bag >= Cfg::BANK_BAG) return true;
    if (altar_field.get(pos) <= Cfg::BANK_NEAR_DIST) return true;
    // Enemies nearby: a bag is a bounty. Bank small bags when they are close
    // or stronger, bigger bags as soon as anyone is in sight range.
    if (bag >= Cfg::THREAT_BANK_BAG) {
        if (outmatched) return true;
        const int range = bag >= Cfg::BANK_THREAT_BAG ? Cfg::THREAT_BANK_RANGE : 4;
        for (const auto& f : foes)
            if (cheb(f.pos, pos) <= range) return true;
    }
    return false;
}

bool Bot::bank() {
    auto& me = bc::self();
    bitboard goals;
    for (auto a : altar_tiles) {
        if (bc::vision::has_altar_lock(a) && bc::vision::altar_lock_at(a).is_enemy()) continue;
        if (cheb(a, pos) <= bc::constants::submit_gems_range) {
            try {
                me.submit_gems(a);
                return true;
            } catch (...) {
            }
            continue;
        }
        goals |= square(a, bc::constants::submit_gems_range);
    }
    move_to(goals);
    return true;
}

// ---------------------------------------------------------------- farm ----

bool Bot::farm() {
    auto& me = bc::self();
    const int gid = choose_target();
    if (gid < 0) {
        // Nothing worth doing: wait at the group that respawns soonest.
        int best = -1;
        for (std::size_t i = 0; i < groups.size(); ++i)
            if (!groups[i].monolith && (best < 0 || groups[i].respawn_at < groups[static_cast<std::size_t>(best)].respawn_at))
                best = static_cast<int>(i);
        if (best >= 0) {
            bitboard near;
            for (auto t : groups[static_cast<std::size_t>(best)].tiles) near |= square(t, 2);
            move_to(near);
        }
        return false;
    }
    auto& g = groups[static_cast<std::size_t>(gid)];

    bool alive = false;
    for (const auto& c : camps)
        if (!c.is_dead() && group_of(c.spawn_position()) == gid) alive = true;

    if (alive && need > 0) {
        bool started = false;
        for (const auto& c : camps)
            if (!c.is_dead() && c.is_awake() && group_of(c.spawn_position()) == gid) started = true;
        if (!started && allies_near(g) < need) {
            // Hold just outside monster reach until the squad has gathered,
            // topping up health first so we ask for fewer helpers.
            g_stage = "farm:wait";
            ++wait_turns;
            if (me.health() < Cfg::SQUAD_HEAL_FIRST * me.max_health()) {
                if (spawn_field.get(pos) <= 12 && move_to(ally_spawn)) return true;
                if (enemies.empty()) {
                    me.recall();
                    return true;
                }
            }
            bitboard ring, inner;
            for (auto t : g.tiles) ring |= square(t, Cfg::SQUAD_WAIT_RING), inner |= square(t, 3);
            ring &= ~inner;
            if (!ring.is_set(pos)) move_to(ring);
            return true;
        }
    }

    if (alive) {
        g_stage = "farm:fight";
        wait_turns = 0;
        if (attack_camp(gid) && (ranged || !me.can_move())) return true;
        bitboard goals;
        for (const auto& c : camps)
            if (!c.is_dead() && group_of(c.spawn_position()) == gid) goals |= square(c.position(), me.attack_range());
        if (!goals.is_set(pos)) move_to(goals);
        camps = bc::vision::camps();
        attack_camp(gid);
        return true;
    }

    if (g.reward) {
        if (g.spawn.is_set(pos)) {
            capture_group = gid;  // stand still: the capture timer runs
            return true;
        }
        for (const auto& a : mates)
            if (g.spawn.is_set(a.pos)) {  // an ally is already capturing
                g.skip_until = round + 8;
                target = -1;
                return false;
            }
        move_to(g.spawn);
        return true;
    }

    bitboard near;
    for (auto t : g.tiles) near |= square(t, 1);
    move_to(near);
    return true;
}

// ---------------------------------------------------------------- turn ----

void Bot::play_turn() {
    auto& me = bc::self();
    if (!ready) {
        init();
        // The first turn has double fuel; if setup ate most of it, start next turn.
        if (bc::fuel_remaining() < 60000) return;
    }
    // Dead champions only get to shop; most unit reads are invalid while dead.
    if (!me.is_alive()) {
        g_stage = "dead";
        shop();
        last_gems = 0;
        capture_group = -1;
        target = -1;
        return;
    }
    g_stage = "observe";
    observe();
    g_stage = "dps";
    estimate_dps();
    g_stage = "memory";
    read_memory();
    g_stage = "capture";

    // A reward landing while we stand on a group's spawn means we captured it.
    const unsigned gems = me.gem_count();
    if (gems > last_gems || (capture_group >= 0 && !groups[static_cast<std::size_t>(capture_group)].spawn.is_set(pos))) {
        const int g = group_of(pos);
        if (gems > last_gems && g >= 0) {
            auto& grp = groups[static_cast<std::size_t>(g)];
            grp.respawn_at = round + grp.max_respawn;
            grp.reward = false;
            broadcast_capture(g);
            if (target == g) target = -1;
        }
        capture_group = -1;
    }
    last_gems = gems;

    g_stage = "shop";
    if (me.is_recalling() || me.is_submitting_gems() || me.is_teleporting()) return;
    if (!me.can_move() && !me.can_attack() && !me.can_cast()) return;  // stunned

    const bool on_spawn = ally_spawn.is_set(pos);
    if (on_spawn || kind == bc::champion_type::tavi) shop();
    if (on_spawn && me.health() < 0.9f * me.max_health() && enemies.empty()) return;  // heal up

    acted_attack = false;

    g_stage = "threat";
    assess_threat();
    g_stage = "retreat";
    if (retreat_if_hurt()) return;

    // Under a lethal burst, or losing a skirmish we are part of, disengage:
    // take a free kill first, then step out of reach.
    if (!foes.empty()) {
        int nearest = 99;
        for (const auto& f : foes) nearest = std::min(nearest, cheb(f.pos, pos));
        const bool lethal = burst_here * Cfg::LETHAL_MARGIN >= my_hp;
        const bool losing = outmatched
            && (nearest <= 4 || (nearest <= 6 && me.gem_count() >= static_cast<unsigned>(Cfg::THREAT_BANK_BAG)));
        if (lethal || losing) {
            g_stage = "escape";
            fight_enemies(ranged);  // melee strikes then walks; ranged only for a kill
            std::erase_if(foes, [&](const Foe& f) {
                const auto& e = enemies[static_cast<std::size_t>(f.index)];
                return !e.is_visible() || !e.is_alive();
            });
            burst_here = burst_at(pos);
            if (burst_here * Cfg::LETHAL_MARGIN >= my_hp || outmatched) {
                if (escape()) return;
            }
        }
    }
    g_stage = "enemies";
    try_lock_altar();
    g_stage = "enemies:fight";
    const vec2 before_fight = pos;
    if (fight_enemies() || pos != before_fight) {  // kills leave vision; a chase step changes it
        // Anyone we just killed is gone from vision.
        std::erase_if(foes, [&](const Foe& f) {
            const auto& e = enemies[static_cast<std::size_t>(f.index)];
            return !e.is_visible() || !e.is_alive();
        });
        camps = bc::vision::camps();
    }
    g_stage = "enemies:support";
    use_support_abilities();

    // Never walk off a capture or out of a fight we are winning.
    g_stage = "hold";
    if (capture_group >= 0 && groups[static_cast<std::size_t>(capture_group)].spawn.is_set(pos)) {
        if (bc::global_submitted_gems(team::ally) + me.gem_count() < bc::constants::winning_gems) {
            attack_camp(capture_group);
            return;
        }
    }
    bool fighting = false;
    for (const auto& c : camps)
        if (!c.is_dead() && c.is_awake() && group_of(c.spawn_position()) == target && cheb(c.position(), pos) <= 3)
            fighting = true;

    g_stage = "bank";
    if (should_bank() && (!fighting || me.gem_count() >= 100)) {
        bank();
        return;
    }
    if (!fighting && me.gem_count() == 0 && wants_shop()) {
        if (spawn_field.get(pos) <= 10) {
            if (move_to(ally_spawn)) return;
        } else if (me.gold_count() >= static_cast<unsigned>(Cfg::RECALL_SHOP_GOLD) && enemies.empty()) {
            me.recall();
            return;
        }
    }
    g_stage = "farm";
    farm();
#ifdef KSK_TRACE
    {
        static std::uint64_t low = ~0ull;
        const auto f = bc::fuel_remaining();
        if (round > 1 && f < low) low = f, std::cout << "FUEL R" << round << " " << bc::to_string(kind) << " left=" << f << "\n";
    }
    if (round % 25 == 0) {
        std::cout << "R" << round << " " << bc::to_string(kind) << " body=" << body << " pos=" << pos.x << "," << pos.y
                  << " hp=" << me.health() << " gems=" << me.gem_count() << " gold=" << me.gold_count() << " tgt=" << target
                  << " need=" << need << " near=" << (target >= 0 ? allies_near(groups[static_cast<std::size_t>(target)]) : -1)
                  << " claims=";
        for (int b = 0; b < 6; ++b) std::cout << int(mem[b]) << ",";
        std::cout << " dps=" << dps_single << "/" << dps_multi << "\n";
    }
#endif
}
