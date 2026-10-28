// nova world model: static map facts (once), the per-turn snapshot, memory of unseen enemies, movement.
#include <algorithm>
#include <span>
#include "bot.h"

void Bot::init() {
    auto& me = bc::self();
    W = bc::map::width();
    H = bc::map::height();
    ally_spawn = bc::map::spawn_region(team::ally);
    enemy_spawn = bc::map::spawn_region(team::enemy);
    altars = bc::map::altars();
    altar_tiles = altars.positions();
    terrain = bc::map::walls() | bc::map::holes() | altars | enemy_spawn;
    for (auto a : altar_tiles) tribute |= square(a, static_cast<int>(bc::constants::submit_gems_range));
    tribute &= ~terrain;
    {
        bitboard v1, v2, v3;
        spawn_field.compute(terrain, ally_spawn, v1);
        enemy_field.compute(terrain & ~enemy_spawn, enemy_spawn, v2);
        altar_field.compute(terrain, tribute, v3);
    }

    group_at.assign(static_cast<std::size_t>(W * H), -1);
    for (const auto& h : bc::map::camp_groups()) {
        Group g{h, h.spawn_tiles(), {}};
        g.tiles = g.spawn.positions();
        if (g.tiles.empty()) continue;
        int sx = 0, sy = 0;
        for (auto t : g.tiles) sx += t.x, sy += t.y;
        g.center = vec2{sx / static_cast<int>(g.tiles.size()), sy / static_cast<int>(g.tiles.size())};
        g.gems = static_cast<int>(h.gem_value());
        g.gold = static_cast<int>(h.gold_value());
        for (const auto& c : h.camps()) {
            try {
                const auto st = c.base_stats();
                g.hp += st.base_health;
                g.strength += st.base_strength;
                if (st.base_strength > 0.f) g.reach = std::max(g.reach, static_cast<int>(st.base_attack_range));
            } catch (...) {
            }
            g.monolith = g.monolith || c.is_monolith();
            ++g.camps;
        }
        const float s = static_cast<float>(spawn_field.get(g.tiles.front())), e = static_cast<float>(enemy_field.get(g.tiles.front()));
        g.owner = s < Nv::OWN_RATIO * e ? 1 : e < Nv::OWN_RATIO * s ? -1 : 0;
        const auto id = static_cast<std::int16_t>(groups.size());
        for (auto t : g.tiles) group_at[static_cast<std::size_t>(t.y * W + t.x)] = id;
        groups.push_back(std::move(g));
    }

    gfield.resize(groups.size());
    if (Nv::MAP_MODES) {  // (only when used: its fuel would shift the timing of later field builds)
        const auto es = enemy_spawn.positions();
        const int walk = es.empty() ? UNREACH : static_cast<int>(spawn_field.get(es.front()));
        map_mode = walk <= Nv::MM_FIGHT_D ? 1 : walk >= Nv::MM_RACE_D && walk < UNREACH ? -1 : 0;
    }
    kind = me.champion_name();
    ranged = me.attack_range() > 1;
    std::vector<int> types;
    for (const auto& c : bc::champions(team::ally)) types.push_back(static_cast<int>(c.champion_name()));
    std::sort(types.begin(), types.end());
    bodies = static_cast<int>(types.size());
    body = std::min(static_cast<int>(std::find(types.begin(), types.end(), static_cast<int>(kind)) - types.begin()), Mem::BODIES - 1);
    ready_ = true;
}

int Bot::group_of(vec2 t) const {
    if (t.x < 0 || t.y < 0 || t.x >= W || t.y >= H) return -1;
    return group_at[static_cast<std::size_t>(t.y * W + t.x)];
}

void Bot::read_memory() {
    bc::shared_memory.read(0, std::span<std::byte>{reinterpret_cast<std::byte*>(mem.data()), mem.size()});
}

void Bot::write_byte(int at, std::uint8_t v) {
    if (mem[static_cast<std::size_t>(at)] == v) return;
    mem[static_cast<std::size_t>(at)] = v;
    bc::shared_memory.write(static_cast<std::size_t>(at), std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

namespace {
Unit unit_of(const bc::champion& c, int index, int round, bool spells = true) {
    Unit u;
    u.pos = c.position();
    u.hp = c.health();
    u.max_hp = std::max(c.max_health(), 1.f);
    u.dps = c.strength();
    u.type = static_cast<int>(c.champion_name());
    u.gems = static_cast<int>(c.gem_count());
    u.reach = static_cast<int>(c.attack_range());
    u.index = index;
    u.seen = round;
    try {
        u.tributing = c.is_submitting_gems();
        if (spells)
            for (const auto& ab : c.abilities())
                if (ab.is_ready() && (ab.is_damage() || ab.is_aoe_damage())) u.spell = std::max(u.spell, ab.damage_amount());
    } catch (...) {
    }
    return u;
}
}  // namespace

void Bot::observe() {
    auto& me = bc::self();
    round = static_cast<int>(bc::round_number());
    pos = me.position();
    last_hp = my_hp;
    my_hp = me.health();
    my_max = std::max(me.max_health(), 1.f);
    read_memory();

    ally_handles.clear();
    allies.clear();
    for (const auto& c : bc::vision::champions(team::ally)) {
        try {
            if (c.champion_name() == kind || !c.is_alive()) continue;
            ally_handles.push_back(c);
            allies.push_back(unit_of(c, static_cast<int>(ally_handles.size()) - 1, round, false));  // ally spells: not worth the fuel
        } catch (...) {
        }
    }
    enemy_handles.clear();
    enemies.clear();
    for (const auto& c : bc::vision::champions(team::enemy)) {
        try {
            if (!c.is_alive()) continue;
            enemy_handles.push_back(c);
            enemies.push_back(unit_of(c, static_cast<int>(enemy_handles.size()) - 1, round));
        } catch (...) {
        }
    }
    // Memory of unseen enemies: refresh what we see, fade the rest, drop the dead and the stale.
    for (const auto& e : enemies) {
        auto it = std::find_if(ghosts.begin(), ghosts.end(), [&](const Unit& g) { return g.type == e.type; });
        if (it == ghosts.end()) ghosts.push_back(e);
        else *it = e;
    }
    if (round % 4 == 0 || dead_types.empty()) {  // every enemy handle costs fuel: refresh the dead list now and then
        enemies_dead = 0;
        dead_types.assign(1, -1);
        for (const auto& c : bc::champions(team::enemy)) {
            try {
                if (!c.is_alive()) dead_types.push_back(static_cast<int>(c.champion_name())), ++enemies_dead;
            } catch (...) {
            }
        }
    }
    const auto& dead = dead_types;
    std::erase_if(ghosts, [&](const Unit& g) {
        return round - g.seen > Nv::GHOST_ROUNDS || std::find(dead.begin(), dead.end(), g.type) != dead.end();
    });
    for (auto& g : ghosts) g.weight = g.seen == round ? 1.f : Nv::GHOST_W;

    // Camps from two bitboards (live camp tiles, awake camp tiles): every per-camp engine query costs ~500 fuel and a
    // pack of 40+ camps in sight used to empty the turn. Health is read only for our target's camps close by.
    vis = bc::vision::visible_tiles();
    const bitboard occupied = bc::vision::camp_tiles(), awake_at = bc::vision::awake_camp_tiles();
    std::vector<int> seen_n(groups.size(), 0);
    for (std::size_t gi = 0; gi < groups.size(); ++gi) {
        auto& g = groups[gi];
        g.live_hp = -1.f, g.alive_seen = 0;
        for (auto t : g.tiles) seen_n[gi] += vis.is_set(t) ? 1 : 0;
        seen_n[gi] = std::min(seen_n[gi], g.camps);
    }
    cv.clear();
    for (auto p : occupied.positions()) {
        int gi = group_of(p);
        if (gi < 0) {  // an awake camp off its spawn tiles: the nearest group within 4
            int best = 5;
            for (std::size_t k = 0; k < groups.size(); ++k) {
                if (cheb(groups[k].center, p) > 12) continue;
                for (auto t : groups[k].tiles)
                    if (cheb(t, p) < best) best = cheb(t, p), gi = static_cast<int>(k);
            }
        }
        if (gi < 0) continue;
        auto& g = groups[static_cast<std::size_t>(gi)];
        CampView v;
        v.pos = p;
        v.group = gi;
        v.dead = false;
        v.awake = awake_at.is_set(p);
        v.hp = g.hp / static_cast<float>(std::max(g.camps, 1));
        if (gi == target && cheb(p, pos) <= 6) try {
            v.hp = bc::vision::camp_at(p).health();
        } catch (...) {
        }
        cv.push_back(v);
        g.live_hp = std::max(g.live_hp, 0.f) + v.hp;
        ++g.alive_seen;
        auto& n = seen_n[static_cast<std::size_t>(gi)];
        n = std::max(n, std::min(g.alive_seen, g.camps));
    }
    // Partial sight: camps we cannot see count at full health (seeing one camp of four is not a weak group).
    for (std::size_t i = 0; i < groups.size(); ++i) {
        auto& g = groups[i];
        const int unseen = g.camps - seen_n[i];
        if (g.live_hp >= 0.f && unseen > 0) g.live_hp += static_cast<float>(unseen) * g.hp / static_cast<float>(std::max(g.camps, 1));
    }
    const auto& visible = vis;
    for (auto& g : groups) {
        bool seen = false;
        for (auto t : g.tiles)
            if (visible.is_set(t)) { seen = true; break; }
        if (!seen) continue;  // state() throws out of sight (~2K fuel per group): keep what we last knew
        if (g.alive_seen > 0) {
            g.reward = false;
            g.respawn_at = 0;
            continue;
        }
        // No living camp in sight: either a reward to capture or the group is gone until it respawns.
        if (g.respawn_at > round) continue;  // timer already known: no state() query (it costs fuel every turn)
        g.reward = false;
        if (!Nv::ALIVE_STATE) g.respawn_at = std::max(g.respawn_at, round + 10);  // unknown timer: assume it is away a while
        try {
            const auto st = g.handle.state();
            if (std::holds_alternative<bc::map::camp_group_reward_available>(st)) {
                g.reward = true;
                g.respawn_at = 0;
            } else if (const auto* r = std::get_if<bc::map::camp_group_respawning>(&st)) {
                g.respawn_at = round + std::max(r->timer, 1);
            } else if (Nv::ALIVE_STATE) {  // alive: its camps wandered off the spawn tiles (chasing someone)
                g.respawn_at = 0;
                g.alive_seen = std::max(g.alive_seen, 1);
                if (g.live_hp < 0.f) g.live_hp = g.hp;
            }
        } catch (...) {
            if (Nv::ALIVE_STATE) g.respawn_at = round + 10;
        }
    }

    const auto owned = me.item_count();
    using I = bc::item_type;
    has_jungle = owned[I::jungle_emblem_of_strength] + owned[I::jungle_emblem_of_focus] + owned[I::jungle_emblem_of_health] > 0;
    gem_gap = static_cast<int>(bc::global_submitted_gems(team::ally)) - static_cast<int>(bc::global_submitted_gems(team::enemy));

    // Broadcast: an enemy on our half.
    for (const auto& e : enemies)
        if (spawn_field.get(e.pos) < enemy_field.get(e.pos)) write_byte(Mem::INVADE, static_cast<std::uint8_t>(std::min(254, round / 8) + 1));
}

bitboard Bot::blocked() const {
    auto b = terrain | bc::vision::champion_tiles() | bc::vision::camp_tiles() | bc::vision::teleport_tiles();
    b.set(pos, false);
    return b;
}

float Bot::burst_at(vec2 p) const {
    float total = 0.f;
    auto add = [&](const Unit& u, float w) {
        const int d = cheb(u.pos, p);
        float best = 0.f;
        if (d <= u.reach + 1) best = u.dps;
        if (u.spell > 0.f && d <= 5) best = std::max(best, u.spell + (d <= u.reach ? u.dps : 0.f));
        total += w * best;
    };
    for (const auto& e : enemies) add(e, 1.f);
    for (const auto& g : ghosts)
        if (g.seen != round) add(g, g.weight);
    return total;
}

bool Bot::mono_danger(vec2 p) const {
    if (!Nv::MONO_AVOID) return false;
    for (const auto& v : cv) {
        const auto& g = groups[static_cast<std::size_t>(v.group)];
        if (g.monolith && v.awake && v.group != target && cheb(v.pos, p) <= g.reach + 1) return true;
    }
    return false;
}

bool Bot::move_to(bitboard goals, bool flee, const bc::distance_field* far) {
    auto& me = bc::self();
    if (!me.can_move()) return false;
    const auto block = blocked();
    goals &= ~block;
    if (goals.is_empty() || goals.is_set(pos)) return false;
    auto steps = block.reachable_tiles(pos, static_cast<std::uint16_t>(me.base_stats().base_move_speed)).positions();
    // Far from the goal: step down a cached static field (a fresh path search over a big map costs most of a turn's fuel).
    const bool use_far = far && far->get(pos) != UNREACH && far->get(pos) > 5;
    bc::distance_field local;
    if (!use_far) {
        if (bc::fuel_remaining() < 20000) return false;  // never risk the turn on a search
        bitboard origin, visited;
        origin.set(pos, true);
        local.compute_to(block, goals, origin, visited);
        if (local.get(pos) == UNREACH && bc::fuel_remaining() >= 20000) {  // walled in by units: route around terrain
            bitboard v2;
            local.compute_to(terrain, goals, origin, v2);
        }
    }
    const bc::distance_field& field = use_far ? *far : local;
    const auto cur = field.get(pos);
    if (cur == UNREACH) return false;
    auto progress = steps;
    std::erase_if(progress, [&](vec2 t) { return t == pos || field.get(t) >= cur; });
    if (progress.empty() && use_far)  // a unit on the route: sidestep along it (no search)
        std::erase_if(steps, [&](vec2 t) { return t == pos || field.get(t) > cur; });
    else
        steps = std::move(progress);
    if (steps.empty()) return false;
    // Among steps that make progress, prefer the least exposed one (always when fleeing, else only to avoid lethal tiles).
    std::vector<std::pair<float, vec2>> ranked;
    const bool in_danger = mono_danger(pos);
    for (auto t : steps) {
        if (!in_danger && mono_danger(t)) continue;  // only ever step out of an awake monolith's reach
        const float b = burst_at(t);
        float key = flee ? b * 100.f + field.get(t) : static_cast<float>(field.get(t)) + (b >= 0.6f * my_hp ? 1000.f : 0.f);
        ranked.push_back({key, t});
    }
    std::sort(ranked.begin(), ranked.end(), [](const auto& a, const auto& b) { return a.first < b.first; });
    int tries = 0;
    for (const auto& [k, t] : ranked) {
        if (++tries > 3) break;
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
