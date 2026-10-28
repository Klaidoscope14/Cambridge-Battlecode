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
    int reach;
};

// Camp stats come from the engine's design table (no vision needed), cached per type, so
// balance patches and new camp types (golem, 2026-10-21) are picked up automatically.
CampSpec spec_of(const bc::camp& c) {
    static std::array<CampSpec, 16> cache{};
    static std::array<bool, 16> known{};
    const auto k = static_cast<std::size_t>(c.kind());
    if (k < cache.size() && known[k]) return cache[k];
    CampSpec s{500.f, 0.f, 1};
    try {
        const auto st = c.base_stats();
        s = {st.base_health, st.base_strength, static_cast<int>(st.base_attack_range)};
    } catch (...) {
        if (c.is_monolith()) s = {20000.f, 200.f, 5};
        else if (c.is_golem()) s = {5000.f, 120.f, 4};
        else if (c.is_elk()) s = {2400.f, 60.f, 1};
        else if (c.is_wolf()) s = {1350.f, 20.f, 1};
        else s = {120.f, 0.f, 1};  // gem / gold cluster
    }
    if (k < cache.size()) cache[k] = s, known[k] = true;
    return s;
}

bool has_passive(bc::passive_type p) { return bc::self().passive() == p; }

// vision::camps() can throw (engine error 98) right after a camp dies this turn.
std::vector<bc::camp> safe_camps() {
    try {
        return bc::vision::camps();
    } catch (...) {
        return {};
    }
}

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
            if (s.strength > 0.f) g.reach = std::max(g.reach, s.reach);
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
    tribute_tiles = tribute.positions();
    bitboard visited;
    altar_field.compute(terrain, tribute, visited);
    bitboard visited2;
    spawn_field.compute(terrain, ally_spawn, visited2);

    int all_gems = 0, mono_gems = 0;
    if (Cfg::MONOLITH_WHEN_DOMINANT || Cfg::DASH_ISLANDS)  // skip the setup cost when both are off
    for (const auto& g : groups) {
        all_gems += g.gems;
        if (g.monolith) mono_gems += g.gems;
        bool reach = false;
        for (auto t : g.tiles) reach = reach || spawn_field.get(t) < UNREACH;
        islands = islands || !reach;
    }
    mono_dominant = all_gems > 0 && mono_gems >= Cfg::MONOLITH_DOMINANT_SHARE * all_gems;
    if (Cfg::DASH_ISLANDS)
        for (const auto& ab : me.abilities()) dasher = dasher || ab.is_dash();

    // Stable body index: rank of our champion type among allies.
    kind = me.champion_name();
    std::vector<int> types;
    for (const auto& c : bc::champions(team::ally)) types.push_back(static_cast<int>(c.champion_name()));
    std::sort(types.begin(), types.end());
    body = static_cast<int>(std::find(types.begin(), types.end(), static_cast<int>(kind)) - types.begin());
    // Cassi and Issac die together: remember the other half's claim slot.
    paired = kind == bc::champion_type::cassi || kind == bc::champion_type::issac;
    if (paired) {
        partner_type = static_cast<int>(kind == bc::champion_type::cassi ? bc::champion_type::issac : bc::champion_type::cassi);
        partner_body = std::min(static_cast<int>(std::find(types.begin(), types.end(), partner_type) - types.begin()), Mem::MAX_BODIES - 1);
    }
    body = std::min(body, Mem::MAX_BODIES - 1);
    bodies = static_cast<int>(types.size());
    if (Cfg::ITEM_ADAPT) {  // camp-gold income per champion (half the map's supply, ~1,200 rounds) and fighting-gem share
        float gold_rate = 0.f, gems = 0.f, fight_gems = 0.f;
        for (const auto& g : groups) {
            gold_rate += static_cast<float>(g.gold) * 1000.f / static_cast<float>(g.max_respawn + 60);
            gems += static_cast<float>(g.gems);
            if (g.strength > 0.f) fight_gems += static_cast<float>(g.gems);
        }
        const float income = gold_rate / (2.f * static_cast<float>(std::max(bodies, 1))) * 1.2f;
        ia_skip_treasure = income < Cfg::IA_MIN_INCOME;
        ia_skip_camp_items = gems > 0.f && fight_gems / gems < Cfg::IA_MIN_FIGHT;
    }
    {
        float gems = 0.f, cl = 0.f;
        for (const auto& g : groups) {
            gems += static_cast<float>(g.gems);
            if (g.strength <= 0.f) cl += static_cast<float>(g.gems);
        }
        cluster_rich = gems > 0.f && cl / gems >= Cfg::PM_MIN_CLUSTER;
        int walls = 0;
        for (auto t : bc::map::walls().positions()) (void)t, ++walls;
        wall_map = static_cast<float>(walls) >= Cfg::TP_MIN_WALLS * static_cast<float>(W * H);
    }

    ranged = me.attack_range() > 1;
    last_gems = me.gem_count();
    last_gold = me.gold_count();
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
    // Allies poll every round, so a changed capture byte is at most a round old.
    if (mem[Mem::CAPTURE] != seen_capture) {
        seen_capture = mem[Mem::CAPTURE];
        const int g = (seen_capture & 0x7F) - 1;
        if (g >= 0 && g < static_cast<int>(groups.size())) {
            auto& grp = groups[static_cast<std::size_t>(g)];
            grp.respawn_at = std::max(grp.respawn_at, round - 1 + grp.max_respawn);
            grp.reward = false;
        }
    }
    if (mem[Mem::HELP] != seen_help) {
        seen_help = mem[Mem::HELP];
        help_fresh = round;
        help_mine = false;
    }
}

// PAIRING: a visible enemy melee champion nearer our spawn than theirs is an invader; broadcast the round (in 8s).
void Bot::note_invaders() {
    if (!Cfg::PAIRING || foes.empty()) return;
    bool seen = false;
    for (const auto& f : foes) {
        if (f.weight < 1.f || f.ranged) continue;
        if (Cfg::PAIR_BRUISERS_ONLY && f.type != static_cast<int>(bc::champion_type::marcella)
            && f.type != static_cast<int>(bc::champion_type::heart_of_ruin) && f.type != static_cast<int>(bc::champion_type::ryth)
            && f.type != static_cast<int>(bc::champion_type::vendetta))
            continue;
        if (!enemy_field_ready) {
            bitboard visited;
            enemy_field.compute(terrain & ~enemy_spawn, enemy_spawn, visited);
            enemy_field_ready = true;
        }
        if (Cfg::PAIR_ANYWHERE || spawn_field.get(f.pos) < enemy_field.get(f.pos)) seen = true;
    }
    if (!seen) return;
    const std::uint8_t v = static_cast<std::uint8_t>(std::min(254, round >> 3) + 1);
    if (mem[Mem::HELP] == v) return;
    mem[Mem::HELP] = seen_help = v;
    bc::shared_memory.write(Mem::HELP, std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

bool Bot::invaders_recent() const {
    const int v = mem[Mem::HELP];
    return Cfg::PAIRING && v > 0 && (round >> 3) - (v - 1) <= Cfg::PAIR_WINDOW / 8;
}

void Bot::write_claim(int group) {
    const std::uint8_t v = static_cast<std::uint8_t>(group + 1);
    if (mem[Mem::CLAIMS + body] == v) return;
    mem[Mem::CLAIMS + body] = v;
    bc::shared_memory.write(static_cast<std::size_t>(Mem::CLAIMS + body),
                            std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

void Bot::broadcast_capture(int group) {
    if (group + 1 > 0x7F) return;  // only 7 bits of group id
    const std::uint8_t v = static_cast<std::uint8_t>((group + 1) | ((~mem[Mem::CAPTURE]) & 0x80));
    mem[Mem::CAPTURE] = seen_capture = v;
    bc::shared_memory.write(Mem::CAPTURE, std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

namespace {
// Map sectors on a 10x10 grid sized to the map: 1..100 fits in 7 bits.
int sector_cell() { return std::max(1, (std::max(W, H) + 9) / 10); }
std::uint8_t sector_of(vec2 p) { return static_cast<std::uint8_t>((p.x / sector_cell()) * 10 + p.y / sector_cell() + 1); }
vec2 sector_centre(std::uint8_t s) {
    const int c = sector_cell(), id = (s & 0x7F) - 1;
    return {std::min(W - 1, (id / 10) * c + c / 2), std::min(H - 1, (id % 10) * c + c / 2)};
}
}  // namespace

// In a contested skirmish, ask for backup: sector of the fight plus a heartbeat.
void Bot::call_help() {
    if (!Cfg::HELP_CALLS || foes.empty()) return;
    int nearest = 99;
    for (const auto& f : foes) nearest = std::min(nearest, cheb(f.pos, pos));
    if (nearest > Cfg::SKIRMISH_RANGE) return;
    const float ratio = side_power(pos, true) / std::max(side_power(pos, false), 1.f);
    if (ratio < Cfg::HELP_MIN_RATIO || ratio > Cfg::HELP_MAX_RATIO) return;
    // Do not override a live call from someone else in a different sector.
    const bool live = round - help_fresh <= 2 && (seen_help & 0x7F);
    if (live && !help_mine && (seen_help & 0x7F) != sector_of(pos)) return;
    const std::uint8_t v = static_cast<std::uint8_t>(sector_of(pos) | ((round & 1) << 7));
    mem[Mem::HELP] = seen_help = v;
    help_fresh = round;
    help_mine = true;
#ifdef KSK_TRACE
    std::cout << "CALL R" << round << " " << bc::to_string(kind) << " ratio=" << ratio << "\n";
#endif
    bc::shared_memory.write(Mem::HELP, std::span<const std::byte>{reinterpret_cast<const std::byte*>(&v), 1});
}

// Idle, healthy allies within reach walk to a live call.
bool Bot::answer_help() {
    if (!Cfg::HELP_CALLS || help_mine || !(seen_help & 0x7F) || round - help_fresh > 2) return false;
    auto& me = bc::self();
    if (my_hp < Cfg::HELP_MIN_HP * my_max || me.gem_count() >= static_cast<unsigned>(Cfg::BANK_BAG)) return false;
    const vec2 at = sector_centre(seen_help);
    const int d = cheb(at, pos);
    if (d > Cfg::HELP_RANGE || d <= 3) return false;
    g_stage = "help";
#ifdef KSK_TRACE
    std::cout << "ANSWER R" << round << " " << bc::to_string(kind) << " d=" << d << "\n";
#endif
    return move_to(square(at, 3));
}

// -------------------------------------------------------------- vision ----

void Bot::observe() {
    auto& me = bc::self();
    round = static_cast<int>(bc::round_number());
    pos = me.position();
    camps = safe_camps();
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
                         static_cast<int>(i), static_cast<int>(a.gem_count()), static_cast<int>(a.champion_name())});
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

    visible_now = bc::vision::visible_tiles();
    const auto& visible = visible_now;
    if constexpr (Cfg::BIG_GROUP_FULL_HP) {
        if (big_trap.empty()) {
            big_trap.assign(groups.size(), 0);
            for (std::size_t i = 0; i < groups.size(); ++i) {
                const auto& g = groups[i];
                if (g.monolith || g.camp_count < Cfg::BG_MIN_CAMPS || g.strength < Cfg::BG_MIN_STR) continue;
                int alt = 1 << 20;
                for (auto t : g.tiles)
                    for (auto a : tribute_tiles) alt = std::min(alt, cheb(t, a));
                big_trap[i] = alt <= Cfg::BG_ALTAR_D ? 1 : 0;
            }
        }
        for (std::size_t i = 0; i < groups.size(); ++i) {
            const auto& g = groups[i];
            if (!big_trap[i] || live_hp[i] < 0.f) continue;
            int unseen = 0;
            for (auto t : g.tiles) unseen += visible.is_set(t) ? 0 : 1;
            live_hp[i] += static_cast<float>(unseen) * g.hp / static_cast<float>(g.camp_count);
        }
    }
    // A group whose every tile is beyond our vision radius cannot be seen (we place no
    // wards), so skip the per-tile test. Geometry is static: filled on first use.
    if constexpr (Cfg::OBS_SKIP_FAR) {
        if (!geo_ready) {
            geo_ready = true;
            vision_r = static_cast<int>(me.base_stats().vision_radius);
            for (const auto& g : groups) {
                int x0 = 1 << 20, y0 = 1 << 20, x1 = -1, y1 = -1;
                for (auto t : g.tiles) x0 = std::min(x0, t.x), y0 = std::min(y0, t.y), x1 = std::max(x1, t.x), y1 = std::max(y1, t.y);
                const vec2 c{(x0 + x1) / 2, (y0 + y1) / 2};
                int r = 0;
                for (auto t : g.tiles) r = std::max(r, cheb(t, c));
                geo_centre.push_back(c), geo_radius.push_back(r);
            }
        }
    }
    for (std::size_t i = 0; i < groups.size(); ++i) {
        auto& g = groups[i];
        if constexpr (Cfg::OBS_SKIP_FAR)
            if (cheb(pos, geo_centre[i]) > vision_r + geo_radius[i] + 1) continue;
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
    if (Cfg::POWER_OPENER) {
        const auto owned = bc::self().item_count();
        const bool focus_po = kind == bc::champion_type::stellar || kind == bc::champion_type::prism
            || kind == bc::champion_type::cassi;
        if (Cfg::CAPTURE_FIRST && owned[focus_po ? I::capture_emblem_of_focus : I::capture_emblem_of_strength] == 0)
            return focus_po ? I::capture_shard_of_focus : I::capture_shard_of_strength;
        if (Cfg::PROSPECTOR_MAPS && cluster_rich && owned[focus_po ? I::prospector_emblem_of_focus : I::prospector_emblem_of_strength] == 0)
            return focus_po ? I::prospector_shard_of_focus : I::prospector_shard_of_strength;
        if (owned[focus_po ? I::jungle_emblem_of_focus : I::jungle_emblem_of_strength] == 0)
            return focus_po ? I::jungle_shard_of_focus : I::jungle_shard_of_strength;
        if (Cfg::PO_BRUISER) {
            const int atk = static_cast<int>(owned[I::bruiser_emblem_of_strength] + owned[I::bruiser_emblem_of_focus]) * 5
                + static_cast<int>(owned[I::bruiser_shard_of_strength] + owned[I::bruiser_shard_of_focus]);
            const int hp_sh = static_cast<int>(owned[I::bruiser_emblem_of_health]) * 5 + static_cast<int>(owned[I::bruiser_shard_of_health]);
            if (hp_sh * 100 < Cfg::PO_HEALTH_PCT * atk + 50) return I::bruiser_shard_of_health;
            return focus_po ? I::bruiser_shard_of_focus : I::bruiser_shard_of_strength;
        }
        const int atk = static_cast<int>(owned[I::power_emblem_of_strength] + owned[I::power_emblem_of_focus]) * 6
            + static_cast<int>(owned[I::power_shard_of_strength] + owned[I::power_shard_of_focus]);
        const int hp_sh = static_cast<int>(owned[I::power_emblem_of_health]) * 6 + static_cast<int>(owned[I::power_shard_of_health]);
        if (hp_sh * 100 < Cfg::PO_HEALTH_PCT * atk + 50) return I::power_shard_of_health;
        return focus_po ? I::power_shard_of_focus : I::power_shard_of_strength;
    }
    const bool melee = kind == bc::champion_type::varg || kind == bc::champion_type::vendetta || kind == bc::champion_type::ryth
        || kind == bc::champion_type::issac || kind == bc::champion_type::marcella || kind == bc::champion_type::heart_of_ruin
        || kind == bc::champion_type::ren;
    if (Cfg::TREASURE_FIRST) {
        if (!ia_skip_treasure) {
            if (focus) plan.push_back({I::treasure_shard_of_focus, I::treasure_emblem_of_focus});
            else if (melee) plan.push_back({I::treasure_shard_of_health, I::treasure_emblem_of_health});
            else plan.push_back({I::treasure_shard_of_strength, I::treasure_emblem_of_strength});
        }
        if (kind != bc::champion_type::ryth && !ia_skip_camp_items)  // Ryth's Jungle comes from RYTH_BUILD
            plan.push_back({I::jungle_shard_of_health, I::jungle_emblem_of_health});
    } else if (kind == bc::champion_type::vesper_vale && !ia_skip_treasure)
        plan.push_back({I::treasure_shard_of_strength, I::treasure_emblem_of_strength});
    if (kind == bc::champion_type::ryth && Cfg::RYTH_BUILD == 1)
        plan.push_back({I::durability_shard_of_health, I::durability_emblem_of_health});
    if (kind == bc::champion_type::ryth && Cfg::RYTH_BUILD == 2 && !ia_skip_camp_items)
        plan.push_back({I::jungle_shard_of_health, I::jungle_emblem_of_health});
    if (!Cfg::NO_MONSTER && !ia_skip_camp_items) {
        if (focus) plan.push_back({I::monster_shard_of_focus, I::monster_emblem_of_focus});
        else plan.push_back({I::monster_shard_of_strength, I::monster_emblem_of_strength});
    }
    if (!Cfg::TREASURE_FIRST && !(kind == bc::champion_type::ryth && Cfg::RYTH_BUILD == 2))
        plan.push_back({I::jungle_shard_of_health, I::jungle_emblem_of_health});
    // Tavi shops anywhere, so he rarely recalls: Home is wasted on him.
    if (Cfg::HOME_SLOT >= 0 && kind != bc::champion_type::tavi) {
        const auto at = std::min<std::size_t>(plan.size(), static_cast<std::size_t>(Cfg::HOME_SLOT) + (plan.size() > 2 ? 1 : 0));
        plan.insert(plan.begin() + static_cast<std::ptrdiff_t>(at), Step{I::home_shard_of_health, I::home_emblem_of_health});
    }
    const auto owned = bc::self().item_count();
    for (const auto& s : plan)
        if (owned[s.emblem] == 0) return s.shard;
    if (Cfg::BRUISER_ITEMS) {
        // Each Bruiser emblem is 5 of its stat plus 1 of each other; balance by the chosen stat.
        const int atk = static_cast<int>(owned[I::bruiser_emblem_of_strength] + owned[I::bruiser_emblem_of_focus]) * 5
            + static_cast<int>(owned[I::bruiser_shard_of_strength] + owned[I::bruiser_shard_of_focus]);
        const int hp_sh = static_cast<int>(owned[I::bruiser_emblem_of_health]) * 5 + static_cast<int>(owned[I::bruiser_shard_of_health]);
        const int pct = Cfg::VESPER_STR_STACK && kind == bc::champion_type::vesper_vale ? Cfg::VS_HEALTH_PCT : Cfg::HEALTH_PCT;
        if (pct > 0 && hp_sh * 100 < pct * atk + 50) return I::bruiser_shard_of_health;
        return focus ? I::bruiser_shard_of_focus : I::bruiser_shard_of_strength;
    }
    if (Cfg::HEALTH_PCT > 0) {
        const int atk = static_cast<int>(owned[I::power_emblem_of_strength] + owned[I::power_emblem_of_focus]) * 6
            + static_cast<int>(owned[I::power_shard_of_strength] + owned[I::power_shard_of_focus]);
        const int hp_sh = static_cast<int>(owned[I::power_emblem_of_health]) * 6 + static_cast<int>(owned[I::power_shard_of_health]);
        if (hp_sh * 100 < Cfg::HEALTH_PCT * atk + 50) return I::power_shard_of_health;
    }
    return focus ? I::power_shard_of_focus : I::power_shard_of_strength;
}

void Bot::set_owners() {
    owners_ready = true;
    if (!enemy_field_ready) {
        bitboard visited;
        enemy_field.compute(terrain & ~enemy_spawn, enemy_spawn, visited);
        enemy_field_ready = true;
    }
    for (auto& g : groups) {
        const float s = static_cast<float>(spawn_field.get(g.tiles.front())), e = static_cast<float>(enemy_field.get(g.tiles.front()));
        g.owner = s < Cfg::OWN_RATIO * e ? 1 : e < Cfg::OWN_RATIO * s ? -1 : 0;
    }
    int walk = UNREACH;
    for (auto t : enemy_spawn.positions()) walk = std::min(walk, static_cast<int>(spawn_field.get(t)));
    map_mode = walk <= Cfg::MM_FIGHT_D ? 1 : walk >= Cfg::MM_RACE_D && walk < UNREACH ? -1 : 0;
}

bool Bot::tp_shortcut() {
    if (!wall_map || target < 0 || !foes.empty()) return false;
    auto& me = bc::self();
    const auto t = static_cast<std::size_t>(target);
    if (t >= gfield_ok.size() || !gfield_ok[t]) return false;
    try {
        auto& tp = me.consumables()[bc::consumable_type::tp_crystal];
        if (tp.count() == 0) return false;
        const int now = static_cast<int>(gfield[t].get(pos));
        if (now >= UNREACH) return false;
        vec2 best = pos;
        int best_d = now;
        for (auto c : (square(pos, 3) & ~terrain).positions()) {
            if (bc::vision::has_champion(c)) continue;
            const int d = static_cast<int>(gfield[t].get(c));
            if (d < best_d) best_d = d, best = c;
        }
        if (best == pos || now - best_d < Cfg::TP_GAIN + bc::constants::tp_crystal_time) return false;
        return tp.use(best);
    } catch (...) {
        return false;
    }
}

void Bot::ward_scout() {
    if (target < 0 || !foes.empty() || round - last_ward_round < Cfg::WS_EVERY) return;
    auto& me = bc::self();
    if (!enemy_field_ready) {
        bitboard visited;
        enemy_field.compute(terrain & ~enemy_spawn, enemy_spawn, visited);
        enemy_field_ready = true;
    }
    const vec2 aim = groups[static_cast<std::size_t>(target)].tiles.front();
    try {
        vec2 best = pos;
        int best_d = UNREACH;
        for (auto c : (me.ward_placement_tiles() & ~terrain).positions()) {
            if (cheb(c, aim) > Cfg::WS_TARGET_R) continue;
            const int d = static_cast<int>(enemy_field.get(c));
            if (d < best_d) best_d = d, best = c;
        }
        if (best_d >= UNREACH) return;
        if (me.place_ward(best)) last_ward_round = round;
    } catch (...) {
        last_ward_round = round;  // no charge or a bad tile: try again later
    }
}

void Bot::shop() {
    auto& me = bc::self();
    const auto lock = bc::consumable_type::altar_lock;
    if (me.gold_count() >= static_cast<unsigned>(Cfg::LOCK_MIN_GOLD) && me.consumables()[lock].count() == 0
        && me.can_buy(lock))
        me.buy(lock);
    if (Cfg::TP_SHORTCUT && wall_map) {
        const auto tp = bc::consumable_type::tp_crystal;
        try {
            if (me.gold_count() >= static_cast<unsigned>(Cfg::TP_MIN_GOLD) && me.consumables()[tp].count() == 0 && me.can_buy(tp))
                me.buy(tp);
        } catch (...) {
        }
    }
    for (int i = 0; i < 12; ++i) {
        const auto item = next_item();
        if (!item || me.gold_count() < item->cost() || !me.can_buy(*item)) break;
        if (Cfg::FIX_TAVI_HP && kind == bc::champion_type::tavi && !ally_spawn.is_set(pos)
            && (*item == bc::item_type::bruiser_shard_of_health || *item == bc::item_type::power_shard_of_health
                || *item == bc::item_type::jungle_shard_of_health))
            break;
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

    std::optional<bc::distance_field> fresh;
    if constexpr (Cfg::MOVE_SCRATCH) {
        if (!move_field) move_field = std::make_unique<bc::distance_field>();  // one 20 KB buffer, reused
    } else {
        fresh.emplace();
    }
    bc::distance_field& field = Cfg::MOVE_SCRATCH ? *move_field : *fresh;
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
    const bool unsafe = here_d == UNREACH && !danger.is_empty();  // no safe route exists
    if (here_d == UNREACH) {
        bitboard visited;
        field.compute_to(blocked, goals, origin, visited);
        here_d = field.get(pos);
    }
    // Walled off by holes: plan as if holes were floor and let the dash hop them.
    bool crossing = false;
    if (here_d == UNREACH && Cfg::DASH_ISLANDS && dasher) {
        bitboard visited;
        field.compute_to(blocked & ~bc::map::holes(), goals, origin, visited);
        here_d = field.get(pos);
        crossing = here_d != UNREACH;
    }
    if (here_d == UNREACH) return false;

    // A dash is compatible with walking: take it first on long trips, or to hop a hole.
    if (allow_dash && (here_d > 3 || crossing) && me.can_cast()) {
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
    // Forced through danger: of the steps that make progress, take the least exposed.
    if (Cfg::SAFE_FALLBACK && unsafe) {
        std::erase_if(steps, [&](vec2 t) { return field.get(t) >= cur; });
        std::vector<float> burst;
        for (auto t : steps) burst.push_back(burst_at(t));
        std::vector<std::size_t> order(steps.size());
        for (std::size_t i = 0; i < order.size(); ++i) order[i] = i;
        std::stable_sort(order.begin(), order.end(), [&](std::size_t a, std::size_t b) { return burst[a] < burst[b]; });
        std::vector<vec2> sorted;
        for (auto i : order) sorted.push_back(steps[i]);
        steps = sorted;
    }
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

    using I = bc::item_type;
    const auto owned = me.item_count();
    has_monster = owned[I::monster_emblem_of_strength] + owned[I::monster_emblem_of_focus] + owned[I::monster_emblem_of_health] > 0;
    has_jungle = owned[I::jungle_emblem_of_strength] + owned[I::jungle_emblem_of_focus] + owned[I::jungle_emblem_of_health] > 0;
    if (has_monster) single *= Cfg::MONSTER_BONUS, multi *= Cfg::MONSTER_BONUS;
    dps_single = std::max(single, 1.f);
    dps_multi = std::max(multi, 1.f);
}

float Bot::my_dps(const Group& g) const { return g.camp_count >= 2 ? dps_multi : dps_single; }

float Bot::group_hp(int id) const {
    const float seen = live_hp[static_cast<std::size_t>(id)];
    return seen >= 0.f ? seen : groups[static_cast<std::size_t>(id)].hp;
}

// LETHAL_FULL_HP / RICH_SQUAD bookkeeping; runs after estimate_dps() so helpers_for() has our damage.
void Bot::apply_lethal_hp() {
    if (Cfg::RICH_SQUAD && rich.empty()) {
        std::vector<int> gems;
        for (const auto& g : groups)
            if (!g.monolith && g.gems > 0) gems.push_back(g.gems);
        rich.assign(groups.size(), 0);
        if (!gems.empty()) {
            std::nth_element(gems.begin(), gems.begin() + static_cast<std::ptrdiff_t>(gems.size() / 2), gems.end());
            const float median = static_cast<float>(gems[gems.size() / 2]);
            for (std::size_t i = 0; i < groups.size(); ++i)
                rich[i] = !groups[i].monolith && groups[i].strength > 0.f && groups[i].gems >= Cfg::RICH_MULT * median ? 1 : 0;
        }
    }
    if (!Cfg::LETHAL_FULL_HP || dps_single <= 0.f || dps_multi <= 0.f) return;
    for (std::size_t i = 0; i < groups.size(); ++i) {
        const auto& g = groups[i];
        if (live_hp[i] < 0.f || g.monolith || g.strength <= 0.f || g.camp_count < 2) continue;
        int unseen = 0;
        for (auto t : g.tiles) unseen += visible_now.is_set(t) ? 0 : 1;
        if (unseen == 0 || helpers_for(g, g.hp) == 0) continue;  // soloable at full strength: keep what we see
        live_hp[i] += static_cast<float>(unseen) * g.hp / static_cast<float>(g.camp_count);
    }
}

int Bot::claims_on(int id) const {
    int n = 0;
    for (int b = 0; b < Mem::MAX_BODIES; ++b)
        if (b != body && mem[Mem::CLAIMS + b] == id + 1) ++n;
    return n;
}

// Fewest allies that must fight beside us for the group to be safe; -1 if never.
// Incoming damage scales with 1 / (1 + helpers), so solve for helpers directly.
int Bot::required_helpers(const Group& g) const { return helpers_for(g, group_hp(static_cast<int>(&g - groups.data()))); }

int Bot::helpers_for(const Group& g, float hp) const {
    if (g.strength <= 0.f) return 0;
    const float taken = has_jungle ? Cfg::JUNGLE_TAKEN : 1.f;
    if (g.monolith) {
        // Pooled: (1 + h) bodies each absorb a share of their health, and the
        // fight is (1 + h) times shorter, so (1 + h)^2 >= total / pool.
        const float pool = Cfg::MONOLITH_POOL_SHARE * my_max;
        const float total = g.strength * taken * hp / my_dps(g);
        const int h = std::max(0, static_cast<int>(std::ceil(std::sqrt(total / pool))) - 1);
        const int cap = Cfg::MONOLITH_WHEN_DOMINANT && mono_dominant ? bodies - 1 : Cfg::MONOLITH_MAX_NEED;
        return h < bodies && h <= cap ? h : -1;
    }
    const float solo = g.strength * taken * (g.camp_count > 1 ? 0.65f : 1.f) * hp / my_dps(g);
    int best = -1;
    const float allowance = my_hp - Cfg::FIGHT_HP_MARGIN * my_max;
    if (allowance > 0.f) {
        const int h = std::max(0, static_cast<int>(std::ceil(solo / allowance)) - 1);
        if (h < bodies) best = h;
    }
    if (Cfg::POOLED_SQUADS && g.camp_count > 1) {
        // Tanks rotate out when hurt, so the squad shares the damage: (1+h)^2 >= solo / pool.
        const bool team = team_squad(static_cast<int>(&g - groups.data()));
        const float pool = (team ? Cfg::BG_POOL_SHARE : Cfg::SQUAD_POOL_SHARE) * my_max;
        const int h = std::max(1, static_cast<int>(std::ceil(std::sqrt(solo / pool))) - 1);
        const int cap = team ? bodies - 1 : Cfg::SQUAD_POOL_MAX_HELPERS;
        if (h < bodies && h <= cap && (best < 0 || h < best)) best = h;
    }
    return best;
}

int Bot::allies_near(const Group& g) const {
    int n = 0;
    for (const auto& a : mates) {
        const auto p = a.pos;
        for (auto t : g.tiles)
            if (cheb(p, t) <= wait_ring(g) + 1) { ++n; break; }
    }
    return n;
}

float Bot::group_score(int id, int dist, int* req_out, float* value_out, float* time_out) const {
    const auto& g = groups[static_cast<std::size_t>(id)];
    if (round < g.skip_until || (g.monolith && !Cfg::MONOLITH_FIGHTS && !(Cfg::MONOLITH_WHEN_DOMINANT && mono_dominant))) return -1.f;
    // Monolith fights get long and a camp kill destroys the bag: go in empty-handed.
    if (g.monolith && bc::self().gem_count() > static_cast<unsigned>(Cfg::MONOLITH_MAX_BAG)) return -1.f;
    if (g.respawn_at > round + dist) return -1.f;
    const int req = g.reward ? 0 : required_helpers(g);
    if (req < 0) return -1.f;
    if (req_out) *req_out = req;
    const int claims = claims_on(id);
    const int crew = std::max(req, claims);  // bodies sharing the fight and the reward

    const float hp = g.reward ? 0.f : group_hp(id);
    const float kill = hp / (my_dps(g) * (1 + crew));
    float value = g.gems + Cfg::GOLD_WEIGHT * g.gold;
    if (g.strength <= 0.f) value *= Cfg::CLUSTER_VALUE;  // 120-HP clusters (patch 3.0) kill fast but pay little
    if (g.strength <= 0.f && claims > 0) value *= Cfg::CLAIMED_PENALTY;
    else if (crew > 0) value /= static_cast<float>(1 + crew);
    if (req > 0) value *= 1.f + Cfg::SQUAD_CLAIM_BONUS * std::min(claims, req);  // converge on one squad target
    if (Cfg::PAIRING && ranged && invaders_recent()) {  // invaders about: ranged bodies farm next to an ally
        bool company = claims > 0;
        for (const auto& m : mates)
            for (auto t : g.tiles)
                if (!company && cheb(m.pos, t) <= Cfg::PAIR_RANGE) company = true;
        if (!company) value *= Cfg::PAIR_ALONE_MULT;
    }
    if (paired && Cfg::PAIR_TOGETHER_BONUS > 1.f && mem[Mem::CLAIMS + partner_body] == id + 1)
        value *= Cfg::PAIR_TOGETHER_BONUS;  // the two halves fight side by side
    for (const auto& f : foes)
        if (cheb(f.pos, g.tiles.front()) <= 5) {
            // Never walk into a stronger enemy group; share a contested camp reluctantly.
            if (side_power(g.tiles.front(), true) > Cfg::OUTMATCHED * side_power(g.tiles.front(), false)) return -1.f;
            value *= Cfg::ENEMY_NEAR_PENALTY;
            break;
        }
    float time = dist + kill + bc::constants::capture_time + std::max(0, g.respawn_at - round - dist);
    if (Cfg::LESS_WAIT && req > 0) time += Cfg::LW_TIME_PENALTY * std::max(0, req - allies_near(g));
    if (Cfg::NEAR_SWEEP && dist <= Cfg::NS_RANGE) value *= Cfg::NS_MULT;
    if (Cfg::MAP_MODES) {
        if (g.owner > 0) value *= map_mode > 0 ? 1.3f : map_mode < 0 ? 1.f : 1.15f;
        else if (g.owner < 0) value *= map_mode > 0 ? 0.6f : map_mode < 0 ? 1.f : 0.85f;
    }
    if (Cfg::RAID && enemies_dead >= Cfg::RAID_MIN_DEAD && g.owner <= 0) value *= Cfg::RAID_MULT;
    if (Cfg::OWN_HALF) {
        if (!enemy_field_ready) {
            bitboard visited;
            const_cast<Bot*>(this)->enemy_field.compute(terrain & ~enemy_spawn, enemy_spawn, visited);
            const_cast<Bot*>(this)->enemy_field_ready = true;
        }
        if (spawn_field.get(g.tiles.front()) < enemy_field.get(g.tiles.front())) value *= Cfg::OH_MULT;
    }
    if (value_out) *value_out = value;
    if (time_out) *time_out = time;
    return value / (time + 4.f);
}

// A big group the enemy has worn down: finishing blows and the capture are ours
// to take, provided we can kill it quickly and the enemy there is not stronger.
int Bot::vulture_target() const {
    if (!Cfg::VULTURE || foes.empty()) return -1;
    int best = -1;
    float best_s = 0.f;
    for (std::size_t i = 0; i < groups.size(); ++i) {
        const auto& g = groups[i];
        if (g.strength <= 0.f || !(g.monolith || g.hp >= Cfg::VULTURE_MIN_HP)) continue;
        const float live = live_hp[i];
        if (live <= 0.f || live > Cfg::VULTURE_HP_FRAC * g.hp) continue;
        bool awake = false;
        for (const auto& c : camps)
            if (!c.is_dead() && c.is_awake() && group_of(c.spawn_position()) == static_cast<int>(i)) awake = true;
        if (!awake) continue;
        const vec2 at = g.tiles.front();
        bool contested = false;
        for (const auto& f : foes) contested = contested || cheb(f.pos, at) <= 6;
        if (!contested) continue;
        const int d = cheb(pos, at);
        if (d > Cfg::VULTURE_RANGE) continue;
        const float t = live / my_dps(g);
        if (t > Cfg::VULTURE_MAX_TURNS) continue;
        if (side_power(at, true) > Cfg::OUTMATCHED * side_power(at, false)) continue;
        const float s = (g.gems + Cfg::GOLD_WEIGHT * g.gold) / (d + t + bc::constants::capture_time);
        if (s > best_s) best_s = s, best = static_cast<int>(i);
    }
    return best;
}

void Bot::ensure_here() {
    if (here_ready) return;
    here_ready = true;
    bitboard visited, origin;
    origin.set(pos, true);
    here.compute(terrain, origin, visited);
    if (Cfg::DASH_ISLANDS && dasher && islands) {
        bitboard visited2;
        here_dash.compute(terrain & ~bc::map::holes(), origin, visited2);
    }
}

// One BFS rooted at each camp group, cached for the game (terrain is static): the
// distance from any tile to the group is then a lookup. Built from spare fuel at the
// end of a turn, one at a time.
void Bot::build_group_fields() {
    if (!Cfg::GROUP_FIELDS || !ready) return;
    if (gfield.size() != groups.size()) {
        gfield.resize(groups.size()), gfield_ok.assign(groups.size(), 0);
        if constexpr (Cfg::FIELDS_NEAREST_FIRST) {  // the groups we will score first get their field first
            field_order.clear();
            for (std::size_t i = 0; i < groups.size(); ++i) field_order.push_back(static_cast<int>(i));
            std::vector<int> d(groups.size(), UNREACH);
            for (std::size_t i = 0; i < groups.size(); ++i)
                for (auto t : groups[i].tiles) d[i] = std::min<int>(d[i], spawn_field.get(t));
            std::stable_sort(field_order.begin(), field_order.end(), [&](int a, int b) { return d[static_cast<std::size_t>(a)] < d[static_cast<std::size_t>(b)]; });
        }
    }
    [[maybe_unused]] int built = 0;
    while (gfield_next < static_cast<int>(groups.size()) && bc::fuel_remaining() >= static_cast<std::uint64_t>(Cfg::FIELD_BUILD_MIN)) {
        if constexpr (Cfg::FIELD_BUILD_ONE) {  // one BFS per turn unless there is plenty left (~33K each at 100x100)
            if (built > 0 && bc::fuel_remaining() < static_cast<std::uint64_t>(Cfg::FIELD_BUILD_MORE)) break;
            ++built;
        }
        std::size_t i = static_cast<std::size_t>(gfield_next++);
        if constexpr (Cfg::FIELDS_NEAREST_FIRST) i = static_cast<std::size_t>(field_order[i]);
        bitboard visited;
        gfield[i].compute(terrain, groups[i].spawn & ~terrain, visited);
        gfield_ok[i] = 1;
    }
}

int Bot::choose_target() {
    // Keep the current target between re-scores unless it has gone stale.
    if (target >= 0 && round < next_eval) {
        const auto& g = groups[static_cast<std::size_t>(target)];
        if (g.respawn_at <= round + 2 && round >= g.skip_until) return target;
    }
    // A re-score walks the whole map (~45K fuel on 100x100): when this turn cannot
    // afford it, keep a still-valid target and try again next turn.
    if (Cfg::FUEL_GUARD && target >= 0 && bc::fuel_remaining() < static_cast<std::uint64_t>(Cfg::FUEL_RESCORE_MIN)) {
        const auto& g = groups[static_cast<std::size_t>(target)];
        if (g.respawn_at <= round + 2 && round >= g.skip_until) return target;
    }
    next_eval = round + (W * H >= Cfg::BIG_MAP_AREA ? Cfg::RETARGET_EVERY_BIG : Cfg::RETARGET_EVERY);
    // The full-map field from us is only needed when a group has no cached field yet,
    // for the detour test, the regroup check and island dashing (algorithm review item 2).
    here_ready = false;
    const bool use_dash = Cfg::DASH_ISLANDS && dasher && islands;
    auto dist_to = [&](const Group& g) {
        const auto gi = static_cast<std::size_t>(&g - groups.data());
        if (Cfg::GROUP_FIELDS && !use_dash && gi < gfield_ok.size() && gfield_ok[gi]) return static_cast<int>(gfield[gi].get(pos));
        ensure_here();
        int d = UNREACH;
        for (auto t : g.tiles) d = std::min<int>(d, here.get(t));
        if (d >= UNREACH && use_dash)
            for (auto t : g.tiles)
                if (here_dash.get(t) < UNREACH) d = std::min<int>(d, here_dash.get(t) + Cfg::DASH_TRIP_PENALTY);
        return d;
    };
    int best = -1, best_req = 0, current_req = 0;
    float best_s = 0.f, current = -1.f;
    struct Cand { int id, req; float s, v, t; };
    std::vector<Cand> cands;
    for (std::size_t i = 0; i < groups.size(); ++i) {
        const int dist = dist_to(groups[i]);
        if (dist >= UNREACH) continue;
        int req = 0;
        float v = 0.f, t = 0.f;
        const float s = group_score(static_cast<int>(i), dist, &req, &v, &t);
        if (static_cast<int>(i) == target) current = s, current_req = req;
        if (s > best_s) best_s = s, best = static_cast<int>(i), best_req = req;
        if (s > 0.f) cands.push_back({static_cast<int>(i), req, s, v, t});
    }
    // Tour planner (algorithm review item 3): look three legs ahead over the best groups,
    // with exact group-to-group distances and respawn windows, and take the first leg of
    // the tour with the best value per round. The switch margin below keeps us committed.
    bool all_fields = Cfg::GROUP_FIELDS && gfield_ok.size() == groups.size() && groups.size() <= 64;
    for (std::size_t i = 0; all_fields && i < gfield_ok.size(); ++i) all_fields = gfield_ok[i];
    if (Cfg::TOUR_PLAN && all_fields && cands.size() > 1) {
        std::sort(cands.begin(), cands.end(), [](const Cand& a, const Cand& b) { return a.s > b.s; });
        if (cands.size() > static_cast<std::size_t>(Cfg::TOUR_CANDIDATES)) cands.resize(static_cast<std::size_t>(Cfg::TOUR_CANDIDATES));
        struct Node { int first, last; float t, v; std::uint64_t used; };
        std::vector<Node> beam, next;
        std::vector<float> rate_of(groups.size(), -1.f);
        auto rate = [](const Node& n) { return n.v / (n.t + 4.f); };
        auto note = [&](const Node& n) { auto& r = rate_of[static_cast<std::size_t>(n.first)]; r = std::max(r, rate(n)); };
        for (const auto& c : cands) {
            beam.push_back({c.id, c.id, c.t, c.v, std::uint64_t{1} << c.id});
            note(beam.back());
        }
        for (int depth = 1; depth < Cfg::TOUR_DEPTH; ++depth) {
            next.clear();
            for (const auto& n : beam) {
                const vec2 from = groups[static_cast<std::size_t>(n.last)].tiles.front();
                for (const auto& c : cands) {
                    if (n.used >> c.id & 1) continue;
                    const int d = static_cast<int>(gfield[static_cast<std::size_t>(c.id)].get(from));
                    if (d >= UNREACH) continue;
                    float v = 0.f, t = 0.f;
                    if (group_score(c.id, static_cast<int>(n.t) + d, nullptr, &v, &t) <= 0.f) continue;
                    next.push_back({n.first, c.id, t, n.v + v, n.used | std::uint64_t{1} << c.id});
                    note(next.back());
                }
            }
            std::sort(next.begin(), next.end(), [&](const Node& a, const Node& b) { return rate(a) > rate(b); });
            if (next.size() > static_cast<std::size_t>(Cfg::TOUR_BEAM)) next.resize(static_cast<std::size_t>(Cfg::TOUR_BEAM));
            beam.swap(next);
            if (beam.empty()) break;
        }
        int tour_best = -1;
        for (std::size_t i = 0; i < rate_of.size(); ++i)
            if (rate_of[i] > 0.f && (tour_best < 0 || rate_of[i] > rate_of[static_cast<std::size_t>(tour_best)])) tour_best = static_cast<int>(i);
        if (tour_best >= 0) {
            best = tour_best;
            best_s = rate_of[static_cast<std::size_t>(tour_best)];
            for (const auto& c : cands) if (c.id == best) best_req = c.req;
            if (target >= 0 && target < static_cast<int>(rate_of.size()) && rate_of[static_cast<std::size_t>(target)] > 0.f)
                current = rate_of[static_cast<std::size_t>(target)];
        }
    }
#ifdef KSK_TRACE
    if (round == 100 || round == 300) {
        std::cout << "SCORES R" << round << " " << bc::to_string(kind) << " gems=" << bc::self().gem_count() << "\n";
        for (std::size_t i = 0; i < groups.size(); ++i) {
            int dist = UNREACH;
            for (auto t : groups[i].tiles) dist = std::min<int>(dist, here.get(t));
            int req = -9;
            const float sc = dist < UNREACH ? group_score(static_cast<int>(i), dist, &req) : -2.f;
            std::cout << "  g" << i << " gems=" << groups[i].gems << " gold=" << groups[i].gold << " hp=" << groups[i].hp << " str=" << groups[i].strength
                      << " dist=" << dist << " req=" << req << " helpers_needed=" << (dist < UNREACH ? required_helpers(groups[i]) : -9) << " claims=" << claims_on(static_cast<int>(i))
                      << " resp=" << groups[i].respawn_at << " skip=" << groups[i].skip_until << " score=" << sc << "\n";
        }
    }
#endif
    if (target >= 0 && current > 0.f && best_s < current * Cfg::SWITCH_MARGIN) best = target, best_req = current_req;

    // Squad deadlock breaker: after waiting a while, join whichever squad target
    // has the most committed allies; after waiting too long, give up on it.
    if (best >= 0 && best == target && best_req > 0 && wait_turns > Cfg::regroup_turns() * (team_squad(best) ? Cfg::BG_WAIT_MULT : 1)) {
        int join = -1, join_claims = claims_on(best), join_req = 0;
        for (std::size_t i = 0; i < groups.size(); ++i) {
            const int id = static_cast<int>(i);
            const int c = claims_on(id);
            if (id == best || c <= join_claims) continue;
            ensure_here();
            if (here.get(groups[i].tiles.front()) >= UNREACH) continue;
            const int req = required_helpers(groups[i]);
            if (req < 0 || groups[i].respawn_at > round) continue;
            join = id, join_claims = c, join_req = req;
        }
        if (join >= 0) {
            best = join, best_req = join_req, wait_turns = 0;
        } else if (wait_turns > Cfg::give_up_turns() * (team_squad(best) ? Cfg::BG_WAIT_MULT : 1)) {
            groups[static_cast<std::size_t>(best)].skip_until = round + 40;
            best = -1, best_req = 0, wait_turns = 0;
        }
    }
    if (best != target) wait_turns = 0;
    target = best;
    need = best < 0 ? 0 : best_req;
    write_claim(target);

    // How far off the route to the target is the best altar? `here` is fresh.
    detour = 1 << 20;
    if (Cfg::DETOUR_BANKING && target >= 0 && bc::self().gem_count() >= static_cast<unsigned>(Cfg::DETOUR_MIN_BAG)
        && (!Cfg::FUEL_GUARD || detour_group == target || bc::fuel_remaining() >= static_cast<std::uint64_t>(Cfg::FUEL_DETOUR_MIN))) {
        const auto& g = groups[static_cast<std::size_t>(target)];
        ensure_here();
        int direct = UNREACH;
        for (auto t : g.tiles) direct = std::min<int>(direct, here.get(t));
        if (direct < UNREACH) {
            // Terrain is static, so the field from a target is reused until the target changes.
            if (!Cfg::DETOUR_CACHE || detour_group != target) {
                bitboard visited;
                detour_field.compute(terrain, g.spawn & ~terrain, visited);
                detour_group = Cfg::DETOUR_CACHE ? target : -1;
            }
            const auto& from_target = detour_field;
            int via = 1 << 20;
            for (auto x : tribute_tiles) {
                const int a = here.get(x), b = from_target.get(x);
                if (a < UNREACH && b < UNREACH) via = std::min(via, a + b);
            }
            detour = via - direct;
            detour_round = round;
        }
    }
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
        f.type = static_cast<int>(e.champion_name());
        f.seen = round;
        if (e.is_recalling()) f.channel = Channel::RECALL;
        else if (e.is_submitting_gems()) f.channel = Channel::TRIBUTE;
        else if (e.is_teleporting()) f.channel = Channel::TELEPORT;
        for (const auto& ab : e.abilities()) {
            if (ab.is_on_cooldown()) continue;
            if (ab.is_attack_reset()) f.reset = true;
            else if (ab.is_dash()) f.dash = true;
            if (ab.is_cc()) f.stun = true;
            if (ab.is_damage() || ab.is_aoe_damage()) f.spell = std::max(f.spell, ab.damage_amount());
        }
        foes.push_back(f);
    }
    if (altar_hot.size() != altar_tiles.size()) altar_hot.assign(altar_tiles.size(), -1000);
    for (std::size_t i = 0; i < altar_tiles.size(); ++i)
        for (const auto& f : foes)
            if (cheb(f.pos, altar_tiles[i]) <= Cfg::ALTAR_THREAT_RANGE) altar_hot[i] = round;
    // Ghosts: refresh from what we see, age the rest, drop cleared or stale ones.
    if (Cfg::GHOSTS) {
        for (const auto& f : foes) {
            auto it = std::find_if(ghosts.begin(), ghosts.end(), [&](const Foe& g) { return g.type == f.type; });
            if (it == ghosts.end()) ghosts.push_back(f);
            else *it = f;
        }
        for (auto& g : ghosts) {
            if (g.seen == round) continue;
            const int age = round - g.seen;
            g.slack = std::min(age, Cfg::TRACKING ? Cfg::TR_SLACK : Cfg::GHOST_MAX_SLACK);
            g.weight = 1.f - static_cast<float>(age) / ((Cfg::TRACKING ? Cfg::TR_ROUNDS : Cfg::GHOST_ROUNDS) + 1);
        }
        // Alive state is readable out of vision: a dead enemy is not lurking.
        std::vector<int> dead;
        if (!ghosts.empty())
            for (const auto& e : bc::champions(team::enemy))
                if (!e.is_alive()) dead.push_back(static_cast<int>(e.champion_name()));
        std::erase_if(ghosts, [&](const Foe& g) {
            if (g.seen == round) return false;
            if (round - g.seen > (Cfg::TRACKING ? Cfg::TR_ROUNDS : Cfg::GHOST_ROUNDS)) return true;
            if (std::find(dead.begin(), dead.end(), g.type) != dead.end()) return true;
            if (Cfg::TRACKING) return (terrain.reachable_tiles(g.pos, static_cast<std::uint16_t>(g.slack)) & ~visible_now).is_empty();
            return (square(g.pos, g.slack) & ~visible_now & ~terrain).is_empty();  // area seen, nobody there
        });
        use_ghosts = bc::self().gem_count() >= static_cast<unsigned>(Cfg::GHOST_MIN_BAG);
        bool any_ghost = false;
        for (const auto& g : ghosts) any_ghost = any_ghost || g.seen != round;
#ifdef KSK_TRACE
        if (use_ghosts && any_ghost) g_ghost_turns++;
#endif
        if (use_ghosts && any_ghost && foes.empty()) {
            danger_ready = false;
            return;
        }
    }
    if (foes.empty()) return;
    last_foe_round = round;
    burst_here = burst_at(pos);
    int nearest = 99;
    for (const auto& f : foes) nearest = std::min(nearest, cheb(f.pos, pos));
    outmatched = nearest <= Cfg::SKIRMISH_RANGE && side_power(pos, true) > Cfg::OUTMATCHED * side_power(pos, false);
    if constexpr (Cfg::FIT_FIGHT) {
        if (nearest <= Cfg::SKIRMISH_RANGE) {
            float ohp = my_hp, odps = bc::self().strength() + 0.25f * bc::self().focus(), ehp = 0.f, edps = 0.f, emax = 0.f;
            int on = 1, en = 0, stun = 0, dash = 0, reset = 0, rng = 0;
            for (const auto& m : mates)
                if (cheb(m.pos, pos) <= Cfg::SKIRMISH_RANGE) ohp += m.hp, odps += m.power, ++on;
            for (const auto& f : foes)
                if (cheb(f.pos, pos) <= Cfg::SKIRMISH_RANGE) {
                    ehp += f.hp, emax += f.max_hp, edps += f.strength + f.spell / 8.f, ++en;
                    stun += f.stun, dash += f.dash, reset += f.reset, rng += f.ranged;
                }
            auto lg = [](float x) { return std::log(std::max(x, 1e-3f)); };
            const float x[12] = {lg(ohp / std::max(ehp, 1.f)), lg(odps / std::max(edps, 1.f)), static_cast<float>(on - en),
                                 static_cast<float>(stun), static_cast<float>(dash), static_cast<float>(reset), my_hp / my_max,
                                 std::min(burst_here / std::max(my_hp, 1.f), 3.f), emax > 0.f ? ehp / emax : 1.f,
                                 static_cast<float>(std::min(nearest, 7)) / 7.f, static_cast<float>(rng),
                                 static_cast<float>(std::min<unsigned>(bc::self().gem_count(), 100u)) / 100.f};
            float z = Cfg::FIT_B;
            for (int k = 0; k < 12; ++k) z += Cfg::FIT_W[k] * (x[k] - Cfg::FIT_MU[k]) / Cfg::FIT_SD[k];
            outmatched = 1.f / (1.f + std::exp(-z)) >= Cfg::FIT_THRESHOLD;
        } else {
            outmatched = false;
        }
    }
    if (Cfg::HP_RATIO_GUARD && nearest <= Cfg::HR_RANGE && !outmatched) {
        float theirs = 0.f, ours = my_hp;
        for (const auto& f : foes)
            if (f.weight >= 1.f && cheb(f.pos, pos) <= 6) theirs += f.hp;
        for (const auto& m : mates)
            if (cheb(m.pos, pos) <= 6) ours += m.hp;
        if (theirs > Cfg::HR_K * ours) outmatched = true;
    }
    exchange_lost = false;
    if (Cfg::EXCHANGE_GUARD) {
        HpSnap now{round, my_hp / std::max(my_max, 1.f), {}};
        now.foe.fill(-1.f);
        for (const auto& f : foes)
            if (f.weight >= 1.f && f.type >= 0 && f.type < 16) now.foe[static_cast<std::size_t>(f.type)] = f.hp / f.max_hp;
        std::erase_if(hp_hist, [&](const HpSnap& h) { return h.round < round - Cfg::EG_WINDOW; });
        if (!hp_hist.empty() && nearest <= Cfg::EG_RANGE) {
            const auto& then = hp_hist.front();
            const float lost = then.mine - now.mine;
            float dealt = 0.f;
            for (const auto& f : foes) {
                const auto t = static_cast<std::size_t>(f.type);
                if (f.weight >= 1.f && t < 16 && cheb(f.pos, pos) <= 4 && then.foe[t] >= 0.f) dealt += std::max(0.f, then.foe[t] - now.foe[t]);
            }
            if (lost >= Cfg::EG_MIN_LOSS && dealt < Cfg::EG_RATIO * lost) exchange_lost = outmatched = true;
        }
        hp_hist.push_back(now);
    }
    if (Cfg::FIGHT_SIM_OUTMATCHED && nearest <= Cfg::SKIRMISH_RANGE) {
        const auto f = simulate_fight(pos, Cfg::FIGHT_SIM_ROUNDS, false);
        const float ours = f.ours0 > 0.f ? f.ours_left / f.ours0 : 0.f;
        const float theirs = f.theirs0 > 0.f ? f.theirs_left / f.theirs0 : 0.f;
        outmatched = f.me_dies_at >= 0 || theirs > ours + Cfg::FIGHT_SIM_MARGIN;
    }
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
    if (use_ghosts)
        for (const auto& g : ghosts)
            if (g.seen != round) peak += g.weight * std::max(g.strength * (g.reset ? 2.f : 1.f), g.spell);
    if (peak < limit) return;  // no tile can reach the limit
    for (auto t : (square(pos, 4) & ~terrain).positions())
        if (burst_at(t) >= limit) danger.set(t, true);
    danger.set(pos, false);
}

// Damage the visible enemies could land on tile p in their next turns. Each
// gets one cast, so a reset, a dash and a spell are alternatives, not a sum.
float Bot::burst_at(vec2 p) const {
    float total = 0.f;
    if (Cfg::MONO_AVOID)
        for (const auto& c : camps)
            if (c.is_monolith() && c.is_awake() && !c.is_dead() && group_of(c.spawn_position()) != target
                && cheb(c.position(), p) <= spec_of(c).reach + 1)
                total += c.strength();
    if (use_ghosts)
        for (const auto& g : ghosts) {
            if (g.seen == round) continue;  // visible: counted below
            const int d = std::max(0, cheb(g.pos, p) - g.slack);
            const int walk = g.ranged ? 3 : 2;
            float best = 0.f;
            if (d <= walk) best = g.strength * (g.reset ? 2.f : 1.f);
            if (g.spell > 0.f && d <= 4) best = std::max(best, g.spell);
            total += g.weight * best;
        }
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
        // Enemies that just stepped out of sight still join the fight, faded by age.
        if (Cfg::GHOST_POWER == 2 || (Cfg::GHOST_POWER == 1 && use_ghosts))
            for (const auto& g : ghosts)
                if (g.seen != round && cheb(g.pos, at) <= Cfg::SKIRMISH_RANGE + g.slack)
                    hp += g.weight * g.hp, dps += g.weight * (g.strength + g.spell / 8.f);
    } else {
        auto& me = bc::self();
        hp = my_hp, dps = me.strength() + 0.25f * me.focus();
        for (const auto& a : mates)
            if (cheb(a.pos, at) <= Cfg::SKIRMISH_RANGE) hp += a.hp, dps += a.power;
    }
    return hp * dps;
}

// Bounded focus-fire simulation (algorithm review item 6): the visible skirmish around
// `at` for `rounds` rounds. Each unit hits the lowest-health enemy it can reach, closing one
// tile a round (melee walks and hits in a round, ranged must stand); ready spells land in
// round 0; a ready stun skips the strongest reachable enemy's next round. `me_passive`: we
// stand still and do not attack (a tribute channel). Ghosts count, faded by age.
Bot::FightOutcome Bot::simulate_fight(vec2 at, int rounds, bool me_passive) const {
    struct U { vec2 p; float hp, dps, spell; int reach; bool stun, ally, me, passive; int stunned = -1; };
    std::vector<U> u;
    auto& me = bc::self();
    float my_spell = 0.f;
    bool my_stun = false;
    if (me.can_cast())
        for (const auto& ab : me.abilities()) {
            if (!ab.is_ready()) continue;
            if (ab.is_damage() || ab.is_aoe_damage()) my_spell = std::max(my_spell, ab.damage_amount());
            if (ab.is_cc()) my_stun = true;
        }
    u.push_back({pos, my_hp, me.strength(), my_spell, static_cast<int>(me.attack_range()), my_stun, true, true, me_passive});
    auto ranged_type = [](int t) {
        using C = bc::champion_type;
        const auto c = static_cast<C>(t);
        return c == C::vesper_vale || c == C::cassi || c == C::stellar || c == C::prism || c == C::willow || c == C::tavi;
    };
    for (const auto& m : mates)
        if (cheb(m.pos, at) <= Cfg::SKIRMISH_RANGE) u.push_back({m.pos, m.hp, m.power, 0.f, ranged_type(m.type) ? 3 : 1, false, true, false, false});
    for (const auto& f : foes)
        if (cheb(f.pos, at) <= Cfg::SKIRMISH_RANGE) u.push_back({f.pos, f.hp, f.strength, f.spell, f.ranged ? 3 : 1, f.stun, false, false, false});
    if (use_ghosts)
        for (const auto& g : ghosts)
            if (g.seen != round && cheb(g.pos, at) <= Cfg::SKIRMISH_RANGE + g.slack)
                u.push_back({g.pos, g.weight * g.hp, g.weight * g.strength, g.weight * g.spell, g.ranged ? 3 : 1, false, false, false, false});
    FightOutcome out;
    for (const auto& x : u) (x.ally ? out.ours0 : out.theirs0) += x.hp;
    auto reachable = [&](const U& a, const U& b, int r, int extra) {
        if (a.passive) return false;
        const int closing = a.reach > 1 ? r : r + 1;  // ranged cannot walk and fire in one round
        return cheb(a.p, b.p) - closing <= a.reach + extra;
    };
    std::vector<float> dmg(u.size());
    for (int r = 0; r < rounds; ++r) {
        std::fill(dmg.begin(), dmg.end(), 0.f);
        for (std::size_t i = 0; i < u.size(); ++i) {
            auto& a = u[i];
            if (a.hp <= 0.f || a.stunned >= r) continue;
            int pick = -1, strongest = -1;
            for (std::size_t j = 0; j < u.size(); ++j) {
                const auto& b = u[j];
                if (b.hp <= 0.f || b.ally == a.ally) continue;
                if (reachable(a, b, r, 0) && (pick < 0 || b.hp < u[static_cast<std::size_t>(pick)].hp)) pick = static_cast<int>(j);
                if (a.stun && reachable(a, b, r, 1) && (strongest < 0 || b.dps > u[static_cast<std::size_t>(strongest)].dps)) strongest = static_cast<int>(j);
            }
            if (a.stun && strongest >= 0) {
                u[static_cast<std::size_t>(strongest)].stunned = r + 1;
                a.stun = false;
            }
            if (pick < 0) continue;
            dmg[static_cast<std::size_t>(pick)] += a.dps + (a.spell > 0.f ? a.spell : 0.f);
            a.spell = 0.f;
        }
        for (std::size_t j = 0; j < u.size(); ++j) {
            if (u[j].hp <= 0.f) continue;
            u[j].hp -= dmg[j];
            if (u[j].hp <= 0.f && u[j].me && out.me_dies_at < 0) out.me_dies_at = r;
        }
    }
    for (const auto& x : u)
        if (x.hp > 0.f) (x.ally ? out.ours_left : out.theirs_left) += x.hp;
    return out;
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
// A step away does not get us out of any chaser's next-turn reach (walk + attack, plus a dash
// or an attack reset), and home is not one step off: running only forfeits our own damage.
bool Bot::flight_futile() const {
    if (spawn_field.get(pos) <= 2) return false;
    for (const auto& f : foes) {
        const int reach = f.ranged ? 3 + (f.reset ? 1 : 0) : 2 + (f.dash ? 2 : 0);
        if (cheb(f.pos, pos) + 1 <= reach) return true;
    }
    return false;
}

bool Bot::converge() {
    auto& me = bc::self();
    if (my_hp < 0.5f * my_max || me.gem_count() >= 30 || foes.empty()) return false;
    const Foe* best = nullptr;
    for (const auto& f : foes) {
        if (cheb(f.pos, pos) > 9) continue;
        if (Cfg::CONVERGE_FIX && enemy_spawn.is_set(f.pos)) continue;  // unreachable and healed every turn
        bool mate_in = false, rescue = false;
        for (const auto& m : mates) {
            mate_in = mate_in || cheb(m.pos, f.pos) <= 4;
            if (Cfg::RESCUE && cheb(m.pos, f.pos) <= 2 && m.hp < 0.7f * m.max_hp) rescue = true;
        }
        if (rescue) {
            int near_f = 0;
            for (const auto& o : foes) near_f += cheb(o.pos, f.pos) <= 4 ? 1 : 0;
            rescue = near_f <= 2 && side_power(f.pos, false) >= Cfg::RESCUE_RATIO * side_power(f.pos, true);
        }
        if (!mate_in || (side_power(f.pos, true) > side_power(f.pos, false) && !rescue)) continue;
        if (!best || cheb(f.pos, pos) < cheb(best->pos, pos)) best = &f;
    }
    if (!best) return false;
    const vec2 at = best->pos, from = pos;
    fight_enemies();
    if (me.can_move()) move_to(square(at, static_cast<int>(me.attack_range())) & ~terrain);
    if (!acted_attack) fight_enemies();
    if constexpr (Cfg::CONVERGE_ACT_ONLY) return acted_attack || pos != from;  // nothing done: let the turn go on
    return true;
}

bool Bot::escape() {
    auto& me = bc::self();
    const bool lethal = burst_here * Cfg::LETHAL_MARGIN >= my_hp;
    if constexpr (Cfg::STAND_SHOOT)
        if (!acted_attack && flight_futile() && fight_enemies()) return true;
    if constexpr (Cfg::DUEL_STAND) {
        const Foe* lone = nullptr;
        int near = 0;
        for (const auto& f : foes)
            if (f.weight >= 1.f && cheb(f.pos, pos) <= 6) ++near, lone = &f;
        if (!acted_attack && !exchange_lost && near == 1 && !lone->ranged && cheb(lone->pos, pos) <= 2 && lone->hp <= Cfg::DUEL_HP_RATIO * my_hp
            && flight_futile() && fight_enemies())
            return true;
    }
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
    std::vector<vec2> refuge;  // FLEE_TO_ALLY: healthy allies to run to
    if (Cfg::FLEE_TO_ALLY)
        for (const auto& m : mates)
            if (cheb(m.pos, pos) <= 10 && m.hp >= 0.4f * m.max_hp) refuge.push_back(m.pos);
    auto home_of = [&](vec2 t) {
        if (refuge.empty()) return static_cast<int>(spawn_field.get(t));
        int d = 1 << 20;
        for (auto r : refuge) d = std::min(d, cheb(t, r));
        return d;
    };
    auto pick_from = [&](const bitboard& tiles, vec2& best, float& best_b, int& best_home) {
        for (auto t : tiles.positions()) {
            const float b = burst_at(t);
            const int home = home_of(t);
            if (b < best_b - 1.f || (b <= best_b + 1.f && home < best_home)) best = t, best_b = b, best_home = home;
        }
    };
    vec2 best = pos;
    float best_b = burst_here;
    int best_home = home_of(pos);
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
// Dashes with a landing effect (cambc 3.0: damage and/or stun in a radius, e.g. Heart of Ruin)
// are worth aiming: land where the most targets are caught, on a tile that is not deadly.
// `targets` are enemy or camp positions; returns true if we dashed.
bool Bot::dash_strike(const std::vector<vec2>& targets, int min_hits) {
    auto& me = bc::self();
    if (!Cfg::DASH_STRIKE || targets.empty() || !me.can_cast()) return false;
    for (const auto& ab : me.abilities()) {
        if (!ab.is_dash() || !ab.is_ready() || !ab.info()) continue;
        const auto* d = std::get_if<bc::ability_dash>(&*ab.info());
        if (!d || (d->modifier <= 0.f && d->duration <= 0)) continue;
        const int radius = std::max(1, static_cast<int>(d->radius));
        const auto blocked = blocked_now();
        vec2 best = pos;
        int best_hits = min_hits - 1;
        for (auto t : (ab.valid_tiles() & ~blocked).positions()) {
            int hits = 0;
            for (auto e : targets) hits += cheb(e, t) <= radius;
            if (hits <= best_hits || burst_at(t) >= 0.6f * my_hp) continue;
            best_hits = hits, best = t;
        }
        if (best == pos) return false;
        try {
            if (ab.use(best)) {
                pos = best;
                return true;
            }
        } catch (...) {
        }
        return false;
    }
    return false;
}

bool Bot::fight_enemies(bool kills_only) {
    auto& me = bc::self();
    if (foes.empty()) return false;
    const float burst = my_burst();
    auto priority = [&](const Foe& f) {
        float s = 1.f - f.hp / f.max_hp + f.gems / 200.f;
        if (f.hp <= burst) s += 10.f;
        if (Cfg::BREAK_CHANNELS && f.channel == Channel::RECALL) s += Cfg::BREAK_RECALL;  // any hit cancels it
        if (f.channel == Channel::TRIBUTE) s += f.gems / 50.f;  // standing still with a bag
        if (Cfg::CI_FOCUS && (f.type == static_cast<int>(bc::champion_type::cassi) || f.type == static_cast<int>(bc::champion_type::issac))) {
            s += Cfg::CI_BONUS;
            for (const auto& o : foes)
                if (&o != &f && (o.type == static_cast<int>(bc::champion_type::cassi) || o.type == static_cast<int>(bc::champion_type::issac))
                    && o.hp > f.hp)
                    s += Cfg::CI_BONUS;  // the weaker half: its death takes the other one too
        }
        return s;
    };
    std::vector<const Foe*> order;
    for (const auto& f : foes)
        if ((!kills_only || f.hp <= burst) && !(Cfg::SPAWN_TARGET_SKIP && enemy_spawn.is_set(f.pos) && f.hp > burst)) order.push_back(&f);
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
        // A ranged poker (range 3) out-trades a melee farmer that ignores it: with allies
        // close and the fight in our favour, walk at it instead of eating free hits.
        if (Cfg::MELEE_CHASE_POKERS && !any && me.can_move()) {
            int near_allies = 0;
            for (const auto& m : mates) near_allies += cheb(m.pos, pos) <= Cfg::SKIRMISH_RANGE;
            const bool favoured = side_power(pos, true) < side_power(pos, false);
            if (near_allies > 0 && favoured)
                for (const auto* f : order) {
                    if (!f->ranged || cheb(f->pos, pos) > Cfg::POKER_RANGE) continue;
                    bitboard goal = square(f->pos, 1);
                    bool safe = false;
                    for (auto t : (square(pos, 1) & ~terrain).positions()) safe = safe || burst_at(t) < 0.5f * my_hp;
                    if (safe && move_to(goal, false)) break;
                }
        }
    }

    // Ranged with a ready reset: step into range of a target we can finish, then fire.
    if (Cfg::RANGED_CHASE && Cfg::RANGED_MOVE_RESET && ranged && !outmatched && me.can_move() && me.can_attack()
        && me.can_cast()) {
        bool reset_ready = false;
        for (const auto& ab : me.abilities()) reset_ready = reset_ready || (ab.is_attack_reset() && ab.is_ready());
        const auto reach = me.attack_tiles();
        bool any = false;
        for (const auto* f : order) any = any || reach.is_set(f->pos);
        if (reset_ready && !any)
            for (const auto* f : order) {
                if (f->hp > burst || cheb(f->pos, pos) != me.attack_range() + 1) continue;
                bitboard goal = square(f->pos, me.attack_range());
                bool safe = false;
                for (auto t : (goal & square(pos, 1)).positions()) safe = safe || burst_at(t) < 0.5f * my_hp;
                if (safe && move_to(goal, false)) break;
            }
    }

    // Open with a landing strike when the skirmish is ours.
    if (Cfg::DASH_STRIKE && !outmatched && !kills_only) {
        std::vector<vec2> at;
        for (const auto* f : order) at.push_back(f->pos);
        if (dash_strike(at, 1)) {
            std::erase_if(foes, [&](const Foe& f) {
                const auto& e = enemies[static_cast<std::size_t>(f.index)];
                return !e.is_visible() || !e.is_alive();
            });
            order.clear();
            for (const auto& f : foes)
                if (!(Cfg::SPAWN_TARGET_SKIP && enemy_spawn.is_set(f.pos) && f.hp > burst)) order.push_back(&f);
            std::sort(order.begin(), order.end(), [&](const Foe* a, const Foe* b) { return priority(*a) > priority(*b); });
        }
    }

    bool engaged = false;
    const bc::champion* hit = nullptr;
    if (!me.can_attack()) {
        const auto reach = me.attack_tiles();
        for (const auto* f : order)
            if (reach.is_set(f->pos)) {
                restore_attack();
                break;
            }
    }
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
    // Attack reset on the same target if it is still standing (FIX_SPELL_FIRST: unless a ready damage / stun spell
    // has a target and we have not moved, so the spell is castable).
    bool spell_first = false;
    if (Cfg::FIX_SPELL_FIRST && hit && me.can_cast() && me.can_move() && kind != bc::champion_type::marcella)
        for (const auto& ab : me.abilities()) {
            if (ab.is_attack_reset() || !ab.is_ready() || !(ab.is_damage() || ab.is_aoe_damage() || ab.is_cc())) continue;
            if (!ab.can_target_enemies() && !ab.can_target_ground()) continue;
            const auto tiles = ab.valid_tiles();
            for (const auto* f : order) spell_first = spell_first || tiles.is_set(f->pos);
        }
    if (hit && me.can_cast() && !spell_first)
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

// Slot holding this champion's stun, or -1. Explicit because the engine reports
// Ryth's area stun as plain area damage and Marcella's stun rides her reset.
int Bot::stun_slot() const {
    using T = bc::champion_type;
    switch (kind) {
        case T::cassi: case T::tavi: return 1;
        case T::prism: case T::ren: case T::ryth: case T::marcella: return 0;
        default: return -1;
    }
}

// Channels are fragile. Any damage cancels a recall (no heal, no escape); a stun
// cancels a tribute or a teleport crystal. Spend what it takes on the most
// valuable channel in reach this turn.
bool Bot::break_channels() {
    if (!Cfg::BREAK_CHANNELS) return false;
    auto& me = bc::self();
    std::vector<std::pair<float, const Foe*>> order;
    for (const auto& f : foes) {
        float v = 0.f;
        if (f.channel == Channel::RECALL) v = Cfg::BREAK_RECALL;
        else if (f.channel == Channel::TRIBUTE && f.gems >= 10) v = Cfg::BREAK_TRIBUTE;
        else if (f.channel == Channel::TELEPORT) v = Cfg::BREAK_TELEPORT;
        if (v > 0.f) order.emplace_back(v + f.gems / 50.f, &f);
    }
    if (order.empty()) return false;
    std::sort(order.begin(), order.end(), [](const auto& a, const auto& b) { return a.first > b.first; });

    const int stun = stun_slot();
    for (const auto& [value, f] : order) {
        const auto& e = enemies[static_cast<std::size_t>(f->index)];
        try {
            if (!e.is_alive() || !e.is_visible()) continue;
            if (f->channel == Channel::RECALL) {
                // Basic attack, a melee step-in, or any damaging spell.
                if (me.can_attack() && me.attack_tiles().is_set(f->pos)) {
                    me.attack(e);
                    acted_attack = true;
                    g_breaks++, g_break_kind = f->channel;
                    return true;
                }
                if (Cfg::BREAK_CHASE && !ranged && !outmatched && me.can_move() && me.can_attack() && cheb(f->pos, pos) == 2
                    && burst_at(pos) < 0.5f * my_hp && move_to(square(f->pos, 1), false)
                    && me.attack_tiles().is_set(f->pos)) {
                    me.attack(e);
                    acted_attack = true;
                    g_breaks++, g_break_kind = f->channel;
                    return true;
                }
                if (!Cfg::BREAK_RECALL_SPELLS || !me.can_cast()) continue;
                for (const auto& ab : me.abilities()) {
                    if (!ab.is_ready() || !(ab.is_damage() || ab.is_aoe_damage())) continue;
                    if (!ab.valid_tiles().is_set(f->pos)) continue;
                    if (ab.can_target_enemies() ? ab.use(e) : ab.use(f->pos)) {
                        g_breaks++, g_break_kind = f->channel;
                        return true;
                    }
                }
                continue;
            }
            // Tribute / teleport: only a stun will do.
            if (stun < 0 || !me.can_cast()) continue;
            const auto slots = me.abilities();  // returned by value: keep it alive
            const auto& ab = slots[static_cast<std::size_t>(stun)];
            if (!ab.is_ready()) continue;
            if (kind == bc::champion_type::marcella) {
                // Enhanced reset: the next basic attack stuns.
                if (me.attack_tiles().is_set(f->pos) && ab.use() && me.can_attack()) {
                    me.attack(e);
                    acted_attack = true;
                    g_breaks++, g_break_kind = f->channel;
                    return true;
                }
                continue;
            }
            if (!ab.valid_tiles().is_set(f->pos)) continue;
            if (ab.can_target_enemies() ? ab.use(e) : ab.use(f->pos)) {
                g_breaks++, g_break_kind = f->channel;
                return true;
            }
        } catch (...) {
        }
    }
    return false;
}

// Endgame denial. Every altar we stand near gets our lock (it only blocks the
// enemy), and a visible loaded enemy is chased down unless we are outmatched.
bool Bot::deny() {
    if (!denial) return false;
    auto& me = bc::self();
    g_stage = "deny";
    auto& lock = me.consumables()[bc::consumable_type::altar_lock];
    if (lock.count() > 0)
        for (auto a : altar_tiles) {
            if (cheb(a, pos) > 2 || bc::vision::has_altar_lock(a)) continue;
            if (Cfg::DENY_LOCK_BAG > 0) {  // keep the lock for an altar a loaded enemy is heading to
                bool carrier = false;
                for (const auto& f : foes) carrier = carrier || (f.gems >= Cfg::DENY_LOCK_BAG && cheb(f.pos, a) <= Cfg::DENY_LOCK_RANGE);
                for (const auto& g : ghosts) carrier = carrier || (g.gems >= Cfg::DENY_LOCK_BAG && cheb(g.pos, a) <= Cfg::DENY_LOCK_RANGE + g.slack);
                if (!carrier) continue;
            }
            try {
                if (lock.use(a)) break;
            } catch (...) {
            }
        }
    if (outmatched) return false;
    const Foe* prey = nullptr;
    for (const auto& f : foes)
        if (f.gems >= Cfg::DENY_HUNT_BAG && cheb(f.pos, pos) <= Cfg::DENY_CHASE_RANGE && (!prey || f.gems > prey->gems))
            prey = &f;
    if (!prey) return false;
    try {  // the prey can die or vanish mid-turn (error 5 / 97)
        if (!me.attack_tiles().is_set(prey->pos)) move_to(square(prey->pos, me.attack_range()));
        fight_enemies();
    } catch (...) {
    }
#ifdef KSK_TRACE
    std::cout << "DENY R" << round << " " << bc::to_string(kind) << " prey_gems=" << prey->gems << "\n";
#endif
    return true;
}

// Step so an approaching enemy, not us, is the nearest champion to the awake
// camps around us: the camp then fights for us.
bool Bot::hand_off_aggro() {
    if (!Cfg::AGGRO_HANDOFF || foes.empty() || !bc::self().can_move()) return false;
    std::vector<vec2> awake;
    for (const auto& c : camps)
        if (!c.is_dead() && c.is_awake() && cheb(c.position(), pos) <= 4) awake.push_back(c.position());
    if (awake.empty()) return false;
    // For each awake camp, how close is the nearest enemy (only those it can reach)?
    std::vector<int> enemy_d(awake.size(), 99);
    bool any = false;
    for (std::size_t i = 0; i < awake.size(); ++i)
        for (const auto& f : foes) {
            const int d = cheb(f.pos, awake[i]);
            if (d <= 3) enemy_d[i] = std::min(enemy_d[i], d), any = true;
        }
    if (!any) return false;
    auto handed = [&](vec2 t) {
        int n = 0;
        for (std::size_t i = 0; i < awake.size(); ++i)
            if (enemy_d[i] < 99 && cheb(t, awake[i]) > enemy_d[i]) ++n;
        return n;
    };
    const auto blocked = blocked_now();
    vec2 best = pos;
    int best_n = handed(pos);
    float best_b = burst_at(pos);
    for (auto t : blocked.reachable_tiles(pos, 1).positions()) {
        const int n = handed(t);
        const float b = burst_at(t);
        if (n > best_n || (n == best_n && n > 0 && b < best_b)) best = t, best_n = n, best_b = b;
    }
    if (best == pos || best_n == 0) return false;
    try {
        if (bc::self().move_absolute(best)) {
            pos = best;
            g_handoffs++;
            return true;
        }
    } catch (...) {
    }
    return false;
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
    // Camps can leave vision mid-turn; a stale read skips the cast, not the turn.
    try {
        cast_on_camps_unsafe(gid);
    } catch (...) {
    }
}

void Bot::cast_on_camps_unsafe(int gid) {
    auto& me = bc::self();
    if (!me.can_cast()) return;
    if (Cfg::DASH_STRIKE) {  // stun / hit awake fighting camps of this group with a landing strike
        std::vector<vec2> at;
        for (const auto& c : camps)
            if (!c.is_dead() && c.is_awake() && group_of(c.spawn_position()) == gid && spec_of(c).strength > 0.f)
                at.push_back(c.position());
        if (dash_strike(at, Cfg::DASH_STRIKE_CAMPS)) {
            camps = safe_camps();
            if (!me.can_cast()) return;
        }
    }
    auto relevant = [&](const bc::camp& c) {
        try {  // a camp can drop out of vision after we moved this turn
            if (!c.is_visible() || c.is_dead()) return false;
            const int g = group_of(c.spawn_position());
            return g == gid || c.is_awake();
        } catch (...) {
            return false;
        }
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

// A ranged champion that walked this turn has spent its attack; a ready reset
// buys it back so the step and the shot happen in the same turn.
bool Bot::restore_attack() {
    auto& me = bc::self();
    if (!Cfg::RANGED_MOVE_RESET || !ranged || acted_attack || me.can_attack() || !me.can_cast()) return false;
    for (const auto& ab : me.abilities()) {
        if (!ab.is_attack_reset() || !ab.is_ready()) continue;
        try {
            return ab.use() && me.can_attack();
        } catch (...) {
            return false;
        }
    }
    return false;
}

// Champion type that should capture this finished group. Every nearby ally runs
// the same rule on the same visible facts, so they agree without messages.
int Bot::capturer(const Group& g) const {
    auto near = [&](vec2 p) {
        for (auto t : g.tiles)
            if (cheb(p, t) <= Cfg::CAPTURE_RANGE) return true;
        return false;
    };
    auto score = [&](int type, int gems) {
        const bool vesper = type == static_cast<int>(bc::champion_type::vesper_vale);
        return (vesper && g.gold >= Cfg::CAPTURE_GOLD_MIN ? 100000 : 0) + gems * 16 + (15 - type);
    };
    int best = static_cast<int>(kind);
    int best_s = score(best, static_cast<int>(bc::self().gem_count()));
    for (const auto& m : mates) {
        if (!near(m.pos)) continue;
        const int s = score(m.type, m.gems);
        if (s > best_s) best_s = s, best = m.type;
    }
    if (!Cfg::CAPTURE_BY_BAG && best_s < 100000) return -1;  // no Vesper case: first come, first served
    return best;
}

// True once the designated capturer (someone else) stands on the group's region,
// so we can step off without resetting the capture timer.
bool Bot::hand_over(const Group& g) const {
    if (!Cfg::CAPTURE_ASSIGN) return false;
    const int who = capturer(g);
    if (who < 0 || who == static_cast<int>(kind)) return false;
    for (const auto& m : mates)
        if (m.type == who && g.spawn.is_set(m.pos)) return true;
    return false;
}

bool Bot::attack_camp(int gid) {
    auto& me = bc::self();
    const auto reach = me.attack_tiles();
    auto best_in_range = [&]() -> const bc::camp* {
        const bc::camp* pick = nullptr;
        for (const auto& c : camps) {
            try {  // a camp killed this turn can leave a handle that no longer reads
                if (c.is_dead() || !reach.is_set(c.position())) continue;
                if (group_of(c.spawn_position()) != gid && !c.is_awake()) continue;  // never wake a new group
                if (!pick || c.health() < pick->health()) pick = &c;
            } catch (...) {
            }
        }
        return pick;
    };
    const auto* pick = best_in_range();
    if (!pick) return false;
    restore_attack();
    if (me.can_attack()) {
        try {
            me.attack(*pick);  // an ally may have killed it earlier this round
        } catch (...) {
            camps = safe_camps();  // drop the stale entry before anyone reads it
            return false;
        }
        acted_attack = true;
        // Attack reset: refresh and swing again at whatever is still in range (FIX_SPELL_FIRST: unless a ready
        // damage / stun spell can hit this group and we have not moved; cast_on_camps below then uses the cast).
        bool spell_first = false;
        if (Cfg::FIX_SPELL_FIRST && me.can_cast() && me.can_move() && kind != bc::champion_type::marcella) {
            camps = safe_camps();
            for (const auto& ab : me.abilities()) {
                if (ab.is_attack_reset() || !ab.is_ready() || !(ab.is_damage() || ab.is_aoe_damage() || ab.is_cc())) continue;
                if (!ab.can_target_camps() && !ab.can_target_ground()) continue;
                const auto tiles = ab.valid_tiles();
                for (const auto& c : camps)
                    try {
                        if (!c.is_dead() && tiles.is_set(c.position()) && (group_of(c.spawn_position()) == gid || c.is_awake())
                            && (!ab.is_cc() || ab.is_damage() || spec_of(c).strength > 0.f))
                            spell_first = true;
                    } catch (...) {
                    }
            }
        }
        for (const auto& ab : me.abilities()) {
            if (spell_first) break;
            if (!ab.is_attack_reset() || !ab.is_ready() || !me.can_cast()) continue;
            camps = safe_camps();
            if (const auto* again = best_in_range()) {
                try {
                    if (ab.use() && me.can_attack()) me.attack(*again);
                } catch (...) {
                }
            }
            break;
        }
    }
    camps = safe_camps();
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
    bool calm = foes.empty() && capture_group < 0;
    for (const auto& c : camps)
        if (c.is_awake() && !c.is_dead() && cheb(c.position(), pos) <= 5) calm = false;
    if (Cfg::FIX_CAPTURE_CALM && calm)
        for (const auto& g : groups) {
            if (!g.reward) continue;
            for (auto t : g.tiles)
                if (cheb(t, pos) <= 5) { calm = false; break; }
            if (!calm) break;
        }
    const float base_floor = paired ? std::max(Cfg::RETREAT_HP, Cfg::PAIR_RETREAT_HP) : Cfg::RETREAT_HP;
    const float floor_hp = calm ? std::max(Cfg::CALM_HEAL_HP, base_floor) : base_floor;
    float frac = me.health() / std::max(me.max_health(), 1.f);
    // One death kills both halves: when the other half is low, both go home.
    if (paired && Cfg::PAIR_MIN_HP)
        for (const auto& m : mates)
            if (m.type == partner_type) frac = std::min(frac, m.hp / m.max_hp);
    // Retreat earlier when the damage aimed at us this turn would take us under:
    // a 6-elk herd hits ~360 a round, more than a 900-HP champion has left at 31%.
    bool burst_low = false;
    if (Cfg::BURST_RETREAT_MULT > 0.f) {
        float incoming = burst_here;
        for (const auto& c : camps)
            if (c.is_awake() && !c.is_dead() && cheb(c.position(), pos) <= 3) incoming += c.strength();
        burst_low = me.health() < Cfg::BURST_RETREAT_MULT * incoming;
    }
    bool doomed = false;
    if (Cfg::DOOMED_CAMP) {
        float incoming = 0.f, left = 0.f;
        bool alone = true;
        for (const auto& m : mates) alone = alone && cheb(m.pos, pos) > 2;
        for (const auto& c : camps)
            if (alone && c.is_awake() && !c.is_dead() && c.strength() > 0.f && cheb(c.position(), pos) <= spec_of(c).reach + 1
                && !(c.is_monolith() && target >= 0 && target == group_of(c.spawn_position()))  // a planned monolith fight
                && (group_of(c.spawn_position()) < 0 || claims_on(group_of(c.spawn_position())) == 0))  // no helper on the way
                incoming += c.strength(), left += c.health();
        if (incoming > 0.f) {
            const float taken = incoming * (has_jungle ? Cfg::JUNGLE_TAKEN : 1.f);
            doomed = me.health() < taken * (left / dps_single + Cfg::DC_ESCAPE);
            if (doomed)
                for (const auto& c : camps)
                    if (c.is_awake() && !c.is_dead() && cheb(c.position(), pos) <= spec_of(c).reach + 1) {
                        const int gid = group_of(c.spawn_position());
                        if (gid >= 0) groups[static_cast<std::size_t>(gid)].skip_until = round + Cfg::DC_SKIP;
                    }
        }
    }
    if (frac >= floor_hp && !burst_low && !doomed) return false;
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
    // Hit since last turn with nobody in sight (a bush ambusher, a ranged poke):
    // a recall would be broken by the next hit, so walk home instead.
    if (Cfg::SAFE_RECALL && me.health() < prev_hp && move_to(ally_spawn)) return true;
    me.recall();
    return true;
}

bool Bot::should_bank() const {
    auto& me = bc::self();
    const int bag = static_cast<int>(me.gem_count());
    if (bag == 0) return false;
    if (bc::global_submitted_gems(team::ally) + bag >= bc::constants::winning_gems) return true;  // the bag wins: always try
    if (Cfg::BLOCKED_ALTAR_FARM && round < bank_blocked_until) return false;  // no way to an altar: keep earning gold
    if (round + 40 >= static_cast<int>(bc::constants::max_rounds)) return true;
    if (Cfg::TEAM_CLOSEOUT) {
        int total = static_cast<int>(bc::global_submitted_gems(team::ally)) + bag;
        for (const auto& m : mates) total += m.gems;
        if (total >= static_cast<int>(bc::constants::winning_gems)) return true;
    }
    const bool carrier = Cfg::PRISM_CARRIER && kind == bc::champion_type::prism;
    const bool quiet = round - last_foe_round > Cfg::PRISM_SAFE_ROUNDS;
    int threshold = carrier && quiet ? Cfg::PRISM_BANK_BAG : Cfg::BANK_BAG;
    if (standing > 0 && round - last_foe_round <= Cfg::AHEAD_THREAT_ROUNDS)
        threshold = std::min(threshold, Cfg::AHEAD_BANK_BAG);
    if (standing < 0) threshold = std::max(threshold, Cfg::BEHIND_BANK_BAG);
    if (Cfg::PVP_BANKING && round - last_foe_round <= Cfg::PVP_RECENT_ROUNDS) threshold = std::min(threshold, Cfg::PVP_BANK_BAG);
    if (Cfg::CARRY_RISK && round - last_foe_round <= Cfg::CR_ROUNDS) threshold = std::min(threshold, Cfg::CR_BAG);
    if (bag >= threshold) return true;
    if (!(Cfg::DETOUR_BANKING && Cfg::DETOUR_REPLACES_NEAR) && altar_field.get(pos) <= Cfg::BANK_NEAR_DIST) return true;
    if (Cfg::DETOUR_BANKING && bag >= Cfg::DETOUR_MIN_BAG && round - detour_round <= Cfg::RETARGET_EVERY
        && detour <= Cfg::DETOUR_MAX)
        return true;
    // Enemies nearby: a bag is a bounty. Bank small bags when they are close
    // or stronger, bigger bags as soon as anyone is in sight range.
    if (bag >= Cfg::THREAT_BANK_BAG) {
        if (outmatched) return true;
        if (carrier) return false;  // even or winning: her bag is Focus for the fight
        const int range = bag >= Cfg::BANK_THREAT_BAG ? Cfg::THREAT_BANK_RANGE : 4;
        for (const auto& f : foes)
            if (cheb(f.pos, pos) <= range) return true;
        if (Cfg::GHOSTS && Cfg::GHOST_BANKING && bag >= Cfg::BANK_THREAT_BAG)
            for (const auto& g : ghosts)
                if (g.seen != round && cheb(g.pos, pos) <= range) return true;
    }
    return false;
}

bool Bot::bank() {
    if constexpr (Cfg::BANK_CACHE) return bank_cached();  // performance audit: cached altar geometry
    auto& me = bc::self();
    // Altars with enemies near them (seen now or remembered) are where carriers die.
    auto threatened = [&](vec2 a) {
        if (!Cfg::SAFE_ALTARS) return false;
        for (std::size_t i = 0; i < altar_tiles.size() && i < altar_hot.size(); ++i)
            if (altar_tiles[i] == a && round - altar_hot[i] <= Cfg::ALTAR_HOT_ROUNDS) return true;  // campers do not leave in 8 rounds
        for (const auto& f : foes)
            if (cheb(f.pos, a) <= Cfg::ALTAR_THREAT_RANGE) return true;
        for (const auto& g : ghosts)
            if (g.seen != round && cheb(g.pos, a) <= Cfg::ALTAR_THREAT_RANGE + g.slack) return true;
        return false;
    };
    // Only altars we can actually walk to count as a safe alternative.
    auto reachable = [&](vec2 a) {
        for (auto t : (square(a, bc::constants::submit_gems_range) & ~terrain).positions())
            if (spawn_field.get(t) < UNREACH) return true;
        return false;
    };
    bool any_safe = false;
    for (auto a : altar_tiles) any_safe = any_safe || (!threatened(a) && (!Cfg::REACHABLE_ANY_SAFE || reachable(a)));
    bitboard goals;
    for (auto a : altar_tiles) {
        if (bc::vision::has_altar_lock(a) && bc::vision::altar_lock_at(a).is_enemy()) {
            if (!Cfg::CLEAR_ENEMY_LOCKS) continue;
            // A lock never expires: three basic attacks are the only way to bank here again.
            const int reach = static_cast<int>(me.attack_range());
            if (cheb(a, pos) <= reach) {
                if (me.can_attack()) {
                    try {
                        me.attack(bc::vision::altar_lock_at(a));
                        acted_attack = true;
                    } catch (...) {
                    }
                }
                return true;
            }
            goals |= square(a, reach) & ~terrain;
            continue;
        }
        if (any_safe && threatened(a) && cheb(a, pos) > bc::constants::submit_gems_range) continue;
        if (cheb(a, pos) <= bc::constants::submit_gems_range) {
            // A tribute channel holds us still for ceil(bag/10) turns and damage does not stop
            // it, death does: do not start one we would not live through.
            if (Cfg::FIGHT_SIM_TRIBUTE && !foes.empty()) {
                const int turns = std::max(1, (static_cast<int>(me.gem_count()) + 9) / 10);
                if (simulate_fight(pos, turns, true).me_dies_at >= 0) {
                    if (escape() || step_away(enemy_pos)) return true;
                    continue;
                }
            }
            try {
                me.submit_gems(a);
                return true;
            } catch (...) {
            }
            continue;
        }
        goals |= square(a, bc::constants::submit_gems_range);
    }
    if (move_to(goals)) return true;
    // Every tribute tile walled off or occupied (boss_battle: the boss camp sits on
    // the only way in): banking is impossible for now, so farm instead.
    if (Cfg::BLOCKED_ALTAR_FARM && me.can_move()) {
        bank_blocked_until = round + Cfg::BLOCKED_ALTAR_ROUNDS;
        return false;
    }
    return true;
}

// Same decisions as bank(), with the static altar squares and reachability cached and
// altars looked up by index (PerformanceAudit.md 3.1): O(A) instead of O(A^2) per call.
bool Bot::bank_cached() {
    auto& me = bc::self();
    if (altar_sq.size() != altar_tiles.size()) {  // static per game: filled on first use, not in init
        altar_sq.clear(); altar_reach.clear();
    for (auto a : altar_tiles) {
        altar_sq.push_back(square(a, bc::constants::submit_gems_range));
        bool r = false;
        for (auto t : (square(a, bc::constants::submit_gems_range) & ~terrain).positions())
            if (spawn_field.get(t) < UNREACH) { r = true; break; }
        altar_reach.push_back(r ? 1 : 0);
    }
    }
    // Altars with enemies near them (seen now or remembered) are where carriers die.
    auto threatened = [&](std::size_t i) {
        if (!Cfg::SAFE_ALTARS) return false;
        const vec2 a = altar_tiles[i];
        if (i < altar_hot.size() && round - altar_hot[i] <= Cfg::ALTAR_HOT_ROUNDS) return true;  // campers do not leave in 8 rounds
        for (const auto& f : foes)
            if (cheb(f.pos, a) <= Cfg::ALTAR_THREAT_RANGE) return true;
        for (const auto& g : ghosts)
            if (g.seen != round && cheb(g.pos, a) <= Cfg::ALTAR_THREAT_RANGE + g.slack) return true;
        return false;
    };
    // Only altars we can actually walk to count as a safe alternative.
    bool any_safe = false;
    for (std::size_t i = 0; i < altar_tiles.size() && !any_safe; ++i) any_safe = !threatened(i) && (!Cfg::REACHABLE_ANY_SAFE || altar_reach[i]);
    bitboard goals;
    for (std::size_t ai = 0; ai < altar_tiles.size(); ++ai) {
        const vec2 a = altar_tiles[ai];
        if (bc::vision::has_altar_lock(a) && bc::vision::altar_lock_at(a).is_enemy()) {
            if (!Cfg::CLEAR_ENEMY_LOCKS) continue;
            // A lock never expires: three basic attacks are the only way to bank here again.
            const int reach = static_cast<int>(me.attack_range());
            if (cheb(a, pos) <= reach) {
                if (me.can_attack()) {
                    try {
                        me.attack(bc::vision::altar_lock_at(a));
                        acted_attack = true;
                    } catch (...) {
                    }
                }
                return true;
            }
            goals |= square(a, reach) & ~terrain;
            continue;
        }
        if (any_safe && threatened(ai) && cheb(a, pos) > bc::constants::submit_gems_range) continue;
        if (cheb(a, pos) <= bc::constants::submit_gems_range) {
            // A tribute channel holds us still for ceil(bag/10) turns and damage does not stop
            // it, death does: do not start one we would not live through.
            if (Cfg::FIGHT_SIM_TRIBUTE && !foes.empty()) {
                const int turns = std::max(1, (static_cast<int>(me.gem_count()) + 9) / 10);
                if (simulate_fight(pos, turns, true).me_dies_at >= 0) {
                    if (escape() || step_away(enemy_pos)) return true;
                    continue;
                }
            }
            try {
                me.submit_gems(a);
                return true;
            } catch (...) {
            }
            continue;
        }
        goals |= altar_sq[ai];
    }
    if (move_to(goals)) return true;
    // Every tribute tile walled off or occupied (boss_battle: the boss camp sits on
    // the only way in): banking is impossible for now, so farm instead.
    if (Cfg::BLOCKED_ALTAR_FARM && me.can_move()) {
        bank_blocked_until = round + Cfg::BLOCKED_ALTAR_ROUNDS;
        return false;
    }
    return true;
}

// ---------------------------------------------------------------- farm ----

bool Bot::farm() {
    auto& me = bc::self();
    int gid = -1;
    if (const int v = vulture_target(); v >= 0) {
        g_stage = "farm:vulture";
#ifdef KSK_TRACE
        std::cout << "VULTURE R" << round << " " << bc::to_string(kind) << " group=" << v << " live=" << live_hp[static_cast<std::size_t>(v)] << "\n";
#endif
        target = gid = v;
        need = 0;  // no waiting: the herd is already fighting someone else
        write_claim(v);
    } else {
        gid = choose_target();
    }
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
    if (gid != empty_group) empty_group = gid, empty_turns = 0;

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
            for (auto t : g.tiles) ring |= square(t, wait_ring(g)), inner |= square(t, wait_ring(g) - 2);
            ring &= ~inner;
            if (!ring.is_set(pos)) move_to(ring);
            return true;
        }
    }

    if (alive) {
        g_stage = "farm:fight";
        wait_turns = 0;
        g_stage = "farm:fight:first";
        if (attack_camp(gid) && (ranged || !me.can_move())) return true;
        if (Cfg::FIX_CAST_FIRST && ranged && me.can_cast() && me.can_move()) {
            cast_on_camps(gid);  // range-4 spells first: a step now would block them this turn
            if (!me.can_cast()) return true;
        }
        g_stage = "farm:fight:goals";
        bitboard goals;
        for (const auto& c : camps)
            if (!c.is_dead() && group_of(c.spawn_position()) == gid) goals |= square(c.position(), me.attack_range());
        g_stage = "farm:fight:move";
        if (!goals.is_set(pos)) move_to(goals);
        camps = safe_camps();
        g_stage = "farm:fight:second";
        attack_camp(gid);
        return true;
    }

    if (g.reward) {
        if (g.spawn.is_set(pos)) {
            capture_group = gid;  // stand still: the capture timer runs
            return true;
        }
        if (Cfg::CAPTURE_ASSIGN && capturer(g) >= 0) {
            const int who = capturer(g);
            // Ours: whoever holds the tile hands over on arrival. If every region
            // tile is taken (single-tile camps), fall through and leave it to them.
            if (who == static_cast<int>(kind) && move_to(g.spawn)) return true;
            for (const auto& m : mates)
                if (m.type == who && cheb(m.pos, g.tiles.front()) <= 3) {  // the capturer is right there
                    g.skip_until = round + 8;
                    target = -1;
                    return false;
                }
        }
        // Big rewards are shared: every ally on the region gets a cut, so the
        // bags (and their tribute channels) stay small.
        const bool share = Cfg::SPLIT_CAPTURES && g.gems >= Cfg::SPLIT_MIN_GEMS;
        if (!share)
            for (const auto& a : mates)
                if (g.spawn.is_set(a.pos)) {  // an ally is already capturing
                    g.skip_until = round + 8;
                    target = -1;
                    return false;
                }
        if (move_to(g.spawn) || !share) return true;
        g.skip_until = round + 8;  // no free tile to share
        target = -1;
        return false;
    }

    bitboard near;
    for (auto t : g.tiles) near |= square(t, 1);
    // Nothing visible to fight or capture although we are next to it: the camps
    // cannot respawn under an ally standing on the region (who may be boxed in
    // by us), so give up on it for a while instead of crowding it.
    if (Cfg::EMPTY_GROUP_SKIP && near.is_set(pos)) {
        if (++empty_turns > Cfg::EMPTY_GROUP_TURNS) {
            g.skip_until = round + Cfg::EMPTY_GROUP_SKIP_ROUNDS;
            target = -1;
            empty_turns = 0;
            return false;
        }
    }
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
        // Just died: the groups around where we fell are held by a stronger enemy;
        // farm elsewhere for a while instead of walking back into the same fight.
        if (Cfg::DEATH_AVOID && !dead_noted) {
            dead_noted = true;
            const int now = static_cast<int>(bc::round_number());
            for (auto& g : groups)
                if (cheb(g.tiles.front(), pos) <= Cfg::DEATH_AVOID_RANGE)
                    g.skip_until = std::max(g.skip_until, now + Cfg::DEATH_AVOID_ROUNDS);
        }
        g_stage = "dead";
        if (Cfg::DEAD_CLEARS_CLAIM) write_claim(-1);  // allies must not count a dead body in a squad
        shop();
        last_gems = 0;
        last_gold = me.gold_count();
        capture_group = -1;
        target = -1;
        return;
    }
    dead_noted = false;
    g_stage = "observe";
    observe();
    if ((Cfg::MAP_MODES || Cfg::RAID) && !owners_ready) set_owners();
    if (Cfg::RAID) {
        enemies_dead = 0;
        for (const auto& e : bc::champions(team::enemy))
            if (!e.is_alive()) ++enemies_dead;
    }
    struct HpMark { Bot* b; ~HpMark() { b->prev_hp = bc::self().health(); b->build_group_fields(); } } hp_mark_{this};
    if (Cfg::SCORE_POLICY) {
        const int gap = static_cast<int>(bc::global_submitted_gems(team::ally)) - static_cast<int>(bc::global_submitted_gems(team::enemy));
        standing = gap >= Cfg::LEAD_MARGIN && Cfg::SCORE_AHEAD ? 1 : gap <= -Cfg::LEAD_MARGIN && Cfg::SCORE_BEHIND ? -1 : 0;
    }
    {
        const int ours = static_cast<int>(bc::global_submitted_gems(team::ally));
        const int theirs = static_cast<int>(bc::global_submitted_gems(team::enemy));
        denial = Cfg::ENDGAME_DENIAL && theirs >= Cfg::DENY_ENEMY_GEMS && theirs > ours;
    }
    g_stage = "dps";
    estimate_dps();
    if constexpr (Cfg::LETHAL_FULL_HP || Cfg::RICH_SQUAD) apply_lethal_hp();
    g_stage = "memory";
    read_memory();
    g_stage = "capture";

    // A reward landing while we stand on a group's spawn means we captured it.
    // Gold-only camps pay no gems, so a jump in gold counts too (passive gold is
    // a trickle), and a group seen respawning is captured whoever got it.
    const unsigned gems = me.gem_count();
    const unsigned gold = me.gold_count();
    const bool paid = gems > last_gems || gold >= last_gold + 10;
    const bool gone = capture_group >= 0 && groups[static_cast<std::size_t>(capture_group)].respawn_at > round;
    if (paid || gone || (capture_group >= 0 && !groups[static_cast<std::size_t>(capture_group)].spawn.is_set(pos))) {
        const int g = group_of(pos);
        if (paid && g >= 0 && (!Cfg::CAPTURE_NEEDS_HOLD || g == capture_group)) {
            auto& grp = groups[static_cast<std::size_t>(g)];
            grp.respawn_at = round + grp.max_respawn;
            grp.reward = false;
            broadcast_capture(g);
            if (target == g) target = -1;
        }
        capture_group = -1;
    }
    last_gems = gems;
    last_gold = gold;

    g_stage = "shop";
    if (me.is_recalling() || me.is_submitting_gems() || me.is_teleporting()) return;
    if (!me.can_move() && !me.can_attack() && !me.can_cast()) return;  // stunned

    const bool on_spawn = ally_spawn.is_set(pos);
    if (on_spawn || kind == bc::champion_type::tavi) shop();
    if (on_spawn && me.health() < 0.9f * me.max_health() && enemies.empty()) return;  // heal up

    acted_attack = false;

    g_stage = "threat";
    assess_threat();
    note_invaders();
    call_help();
    g_stage = "retreat";
    if (retreat_if_hurt()) return;

    // Under a lethal burst, or losing a skirmish we are part of, disengage:
    // take a free kill first, then step out of reach.
    if (!foes.empty()) {
        int nearest = 99;
        for (const auto& f : foes) nearest = std::min(nearest, cheb(f.pos, pos));
        const bool lethal = burst_here * Cfg::LETHAL_MARGIN >= my_hp;
        bool bounty = false;  // far behind: a loaded enemy is worth a risky fight
        if (standing < 0)
            for (const auto& f : foes) bounty = bounty || f.gems >= Cfg::BEHIND_BOUNTY;
        const bool losing = outmatched && !bounty
            && (nearest <= Cfg::LOSING_RANGE || (nearest <= 6 && me.gem_count() >= static_cast<unsigned>(Cfg::THREAT_BANK_BAG)));
        if (lethal || losing) {
            g_stage = "escape";
            if (Cfg::ESCAPE_BANK_EMBARGO > 0 && me.gem_count() > 0)
                bank_blocked_until = std::max(bank_blocked_until, round + Cfg::ESCAPE_BANK_EMBARGO);
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
    if (Cfg::ISO_STEP && ranged && !foes.empty()) {
        bool alone = true, close = false, weak = true;
        for (const auto& m : mates) alone = alone && cheb(m.pos, pos) > Cfg::ISO_ALLY;
        for (const auto& f : foes)
            if (f.weight >= 1.f && cheb(f.pos, pos) <= Cfg::ISO_RANGE && !(Cfg::CONVERGE_FIX && enemy_spawn.is_set(f.pos))) {
                if (!f.ranged) close = true;
                weak = weak && f.hp <= Cfg::ISO_WEAK * my_hp;
            }
        if (alone && close && !weak) {
            g_stage = "iso";
            fight_enemies(true);  // a kill is still worth taking
            if (escape()) return;
        }
    }
    g_stage = "enemies:aggro";
    if (hand_off_aggro()) {
        camps = safe_camps();
        std::erase_if(foes, [&](const Foe& f) {
            const auto& e = enemies[static_cast<std::size_t>(f.index)];
            return !e.is_visible() || !e.is_alive();
        });
#ifdef KSK_TRACE
        std::cout << "HANDOFF R" << round << " " << bc::to_string(kind) << " total=" << g_handoffs << "\n";
#endif
    }
    g_stage = "enemies";
    try_lock_altar();
    g_stage = "enemies:channels";
    const vec2 before_break = pos;
    if (break_channels() || pos != before_break) {  // a step-in changes what we can see
#ifdef KSK_TRACE
        std::cout << "BREAK R" << round << " " << bc::to_string(kind) << " channel=" << g_break_kind << " total=" << g_breaks << "\n";
#endif
        std::erase_if(foes, [&](const Foe& f) {
            const auto& e = enemies[static_cast<std::size_t>(f.index)];
            return !e.is_visible() || !e.is_alive();
        });
        camps = safe_camps();
    }
    g_stage = "enemies:fight";
    const vec2 before_fight = pos;
    if (fight_enemies() || pos != before_fight) {  // kills leave vision; a chase step changes it
        // Anyone we just killed is gone from vision.
        std::erase_if(foes, [&](const Foe& f) {
            const auto& e = enemies[static_cast<std::size_t>(f.index)];
            return !e.is_visible() || !e.is_alive();
        });
        camps = safe_camps();
    }
    g_stage = "enemies:support";
    use_support_abilities();

    // Never walk off a capture or out of a fight we are winning.
    g_stage = "hold";
    if (capture_group >= 0 && groups[static_cast<std::size_t>(capture_group)].spawn.is_set(pos)) {
        auto& cg = groups[static_cast<std::size_t>(capture_group)];
        if (hand_over(cg)) {
#ifdef KSK_TRACE
            std::cout << "HANDOVER R" << round << " " << bc::to_string(kind) << " -> type " << capturer(cg) << " gold=" << cg.gold << "\n";
#endif
            cg.skip_until = round + 8;  // the designated capturer has it
            if (target == capture_group) target = -1;
            capture_group = -1;
        } else if (bc::global_submitted_gems(team::ally) + me.gem_count() < bc::constants::winning_gems) {
            attack_camp(capture_group);
            return;
        }
    }
    bool fighting = false;
    for (const auto& c : camps)
        if (!c.is_dead() && c.is_awake() && group_of(c.spawn_position()) == target && cheb(c.position(), pos) <= 3)
            fighting = true;

    g_stage = "bank";
    const bool wins_now = bc::global_submitted_gems(team::ally) + me.gem_count() >= bc::constants::winning_gems;
    if (should_bank() && (!fighting || me.gem_count() >= 100 || wins_now)) {  // a winning bag never waits on a camp
        if (bank() || !Cfg::BLOCKED_ALTAR_FARM) return;
    }
    // A bag that cannot be banked is no reason to skip shopping (spent gold still
    // counts in the gold tiebreak).
    const bool bag_stuck = Cfg::BLOCKED_ALTAR_FARM && round < bank_blocked_until;
    if (!fighting && (me.gem_count() == 0 || bag_stuck) && wants_shop()) {
        if (spawn_field.get(pos) <= 10) {
            if (move_to(ally_spawn)) return;
        } else if (me.gold_count() >= static_cast<unsigned>(Cfg::RECALL_SHOP_GOLD) && enemies.empty()) {
            me.recall();
            return;
        }
    }
    if constexpr (Cfg::CONVERGE)
        if (!fighting && capture_group < 0 && converge()) return;
    if (capture_group < 0 && deny()) return;
    if (!fighting && capture_group < 0 && answer_help()) return;
    if (Cfg::TP_SHORTCUT && tp_shortcut()) return;
    if (Cfg::WARD_SCOUT) ward_scout();
    g_stage = "farm";
    farm();
    g_stage = "turn:done";
#ifdef KSK_TRACE
    {
        static std::uint64_t low = ~0ull;
        const auto f = bc::fuel_remaining();
        if (round > 1 && f < low) low = f, std::cout << "FUEL R" << round << " " << bc::to_string(kind) << " left=" << f << "\n";
    }
    if (target >= 0 && groups[static_cast<std::size_t>(target)].monolith && round % 5 == 0)
        std::cout << "MONO R" << round << " " << bc::to_string(kind) << " tgt=" << target << " need=" << need
                  << " near=" << allies_near(groups[static_cast<std::size_t>(target)]) << " mhp=" << group_hp(target)
                  << " hp=" << my_hp << "/" << my_max << " gems=" << me.gem_count() << " dps=" << dps_single
                  << " d=" << cheb(pos, groups[static_cast<std::size_t>(target)].tiles.front()) << "\n";
    if (round % 100 == 0) std::cout << "GHOSTTURNS R" << round << " " << bc::to_string(kind) << " n=" << g_ghost_turns << " ghosts=" << ghosts.size() << "\n";
    if (round % 5 == 0 && round >= 80 && round <= 100) {
        std::cout << "R" << round << " " << bc::to_string(kind) << " body=" << body << " pos=" << pos.x << "," << pos.y
                  << " hp=" << me.health() << " gems=" << me.gem_count() << " gold=" << me.gold_count() << " tgt=" << target
                  << " need=" << need << " near=" << (target >= 0 ? allies_near(groups[static_cast<std::size_t>(target)]) : -1)
                  << " claims=";
        for (int b = 0; b < 6; ++b) std::cout << int(mem[b]) << ",";
        std::cout << " dps=" << dps_single << "/" << dps_multi;
        if (target >= 0) {
            const auto& tg = groups[static_cast<std::size_t>(target)];
            std::cout << " tgt_tile=" << tg.tiles.front().x << "," << tg.tiles.front().y << " here_d=" << here.get(tg.tiles.front())
                      << " gems=" << tg.gems << " gold=" << tg.gold << " camps=" << tg.camp_count << " resp_at=" << tg.respawn_at << " reward=" << tg.reward;
        }
        if (target >= 0) {
            const auto& tg = groups[static_cast<std::size_t>(target)];
            int vis = 0, bush = 0; for (auto t : tg.tiles) { vis += visible_now.is_set(t); bush += bc::map::bushes().is_set(t); }
            int living = 0; for (const auto& c : camps) if (!c.is_dead() && group_of(c.spawn_position()) == target) ++living;
            std::string st = "?";
            try { auto v = tg.handle.state(); st = std::holds_alternative<bc::map::camp_group_alive>(v) ? "alive" : std::holds_alternative<bc::map::camp_group_reward_available>(v) ? "reward" : "resp" + std::to_string(std::get<bc::map::camp_group_respawning>(v).timer); } catch (std::exception& e) { st = std::string("ERR:") + e.what(); }
            for (const auto& c : camps) if (!c.is_dead() && group_of(c.spawn_position()) == target) {
                const auto cp = c.position();
                std::cout << " hp=" << c.health() << " awake=" << c.is_awake() << " acted=" << acted_attack << " can_atk=" << bc::self().can_attack();
                std::cout << " camp@" << cp.x << "," << cp.y << " d=" << cheb(cp, pos) << " inreach=" << bc::self().attack_tiles().is_set(cp) << " around=";
                for (int dy = 1; dy >= -1; --dy) { for (int dx = -1; dx <= 1; ++dx) { vec2 q{cp.x + dx, cp.y + dy}; char ch = '.'; if (!bc::map::is_in_bounds(q)) ch = 'X'; else if (bc::map::walls().is_set(q)) ch = '#'; else if (bc::map::holes().is_set(q)) ch = 'o'; else if (bc::vision::has_champion(q)) ch = 'c'; else if (bc::vision::has_camp(q)) ch = '$'; std::cout << ch; } std::cout << "/"; }
            }
            std::cout << " tiles=" << tg.tiles.size() << " vis=" << vis << " bush=" << bush << " living=" << living << " camps_seen=" << camps.size() << " state=" << st;
        }
        std::cout << " stage=" << g_stage << "\n";
    }
#endif
}
