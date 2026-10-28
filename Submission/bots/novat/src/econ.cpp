// nova economy: small frequent tributes (median 21-26 gems), shopping and healing at spawn (~5% of the time),
// the top teams' item builds (Observations.md sections 7-9), wards near camps / altars, altar-lock denial.
#include <algorithm>
#include "bot.h"

namespace {
using I = bc::item_type;
struct Step { I shard, emblem; };
bool focus_type(bc::champion_type k) {
    return k == bc::champion_type::stellar || k == bc::champion_type::prism || k == bc::champion_type::cassi;
}
}  // namespace

bool Bot::altar_safe(vec2 a) const {
    if (vis.is_set(a)) try {  // lock queries throw out of sight (~2K fuel each)
        if (bc::vision::has_altar_lock(a) && bc::vision::altar_lock_at(a).is_enemy()) return false;
    } catch (...) {
    }
    for (const auto& e : enemies)
        if (cheb(e.pos, a) <= Nv::ALTAR_UNSAFE) return false;
    for (const auto& g : ghosts)
        if (g.seen != round && cheb(g.pos, a) <= Nv::ALTAR_UNSAFE) return false;
    return true;
}

bool Bot::should_bank() const {
    const int bag = static_cast<int>(bc::self().gem_count());
    if (bag == 0) return false;
    if (static_cast<int>(bc::global_submitted_gems(team::ally)) + bag >= static_cast<int>(bc::constants::winning_gems)) return true;
    if (round + 40 >= static_cast<int>(bc::constants::max_rounds)) return true;
    int full = kind == bc::champion_type::marcella ? Nv::BANK_BAG_MARCELLA : Nv::BANK_BAG;
    if (gem_gap >= Nv::BEHIND) full = std::min(full, Nv::AHEAD_BAG);
    const int d = static_cast<int>(altar_field.get(pos));
    if (bag >= full && d <= Nv::BANK_NEAR) return true;
    if (bag >= Nv::BANK_ANY) return true;
    if (bag >= Nv::DETOUR_BAG && d <= Nv::DETOUR) return true;
    if (bag >= Nv::THREAT_BAG && nearest_enemy <= Nv::THREAT_RANGE) return true;
    return false;
}

bool Bot::bank() {
    auto& me = bc::self();
    const int range = static_cast<int>(bc::constants::submit_gems_range);
    for (auto a : altar_tiles) {
        if (cheb(a, pos) > range || !vis.is_set(a) || !altar_safe(a)) continue;
        try {
            if (bc::vision::has_altar_lock(a)) continue;
            me.submit_gems(a);
            return true;
        } catch (...) {
        }
    }
    bitboard goals;
    for (auto a : altar_tiles)
        if (altar_safe(a)) goals |= square(a, range);
    goals &= ~terrain;
    if (goals.is_empty()) return false;
    return move_to(goals, nearest_enemy <= Nv::THREAT_RANGE, &altar_field);
}

std::optional<bc::item_type> Bot::next_item() const {
    using C = bc::champion_type;
    const bool focus = focus_type(kind);
    std::vector<Step> plan;
    float hp_per_dmg = Nv::HEALTH_PER_DAMAGE;
    I stack_dmg = focus ? I::bruiser_shard_of_focus : I::bruiser_shard_of_strength;
    switch (kind) {
        case C::vesper_vale:
            plan = {{I::treasure_shard_of_strength, I::treasure_emblem_of_strength}, {I::jungle_shard_of_strength, I::jungle_emblem_of_strength},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
            break;
        case C::marcella:
            plan = {{I::treasure_shard_of_health, I::treasure_emblem_of_health}, {I::jungle_shard_of_strength, I::jungle_emblem_of_strength},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
            hp_per_dmg = 1.f;
            break;
        case C::vendetta:
            plan = {{I::treasure_shard_of_health, I::treasure_emblem_of_health}, {I::jungle_shard_of_strength, I::jungle_emblem_of_strength},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
            break;
        case C::heart_of_ruin:
            plan = {{I::treasure_shard_of_health, I::treasure_emblem_of_health}, {I::jungle_shard_of_focus, I::jungle_emblem_of_focus},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
            stack_dmg = I::bruiser_shard_of_focus;
            hp_per_dmg = 1.f;
            break;
        case C::cassi:
            plan = {{I::power_shard_of_focus, I::power_emblem_of_focus}, {I::durability_shard_of_focus, I::durability_emblem_of_focus},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
            break;
        case C::issac:
            plan = {{I::treasure_shard_of_strength, I::treasure_emblem_of_strength}, {I::power_shard_of_strength, I::power_emblem_of_strength},
                    {I::home_shard_of_health, I::home_emblem_of_health}};
            break;
        default:
            plan = {{focus ? I::treasure_shard_of_focus : I::treasure_shard_of_strength, focus ? I::treasure_emblem_of_focus : I::treasure_emblem_of_strength},
                    {focus ? I::jungle_shard_of_focus : I::jungle_shard_of_strength, focus ? I::jungle_emblem_of_focus : I::jungle_emblem_of_strength},
                    {I::bruiser_shard_of_health, I::bruiser_emblem_of_health}};
    }
    const auto owned = bc::self().item_count();
    for (const auto& s : plan)
        if (owned[s.emblem] == 0) return s.shard;
    // Stack Bruiser: damage stat, with Health shards at hp_per_dmg of them.
    const I dmg_emb = stack_dmg == I::bruiser_shard_of_focus ? I::bruiser_emblem_of_focus : I::bruiser_emblem_of_strength;
    const int dmg = static_cast<int>(owned[dmg_emb]) * 5 + static_cast<int>(owned[stack_dmg]);
    const int hp_emb = std::max(0, static_cast<int>(owned[I::bruiser_emblem_of_health]) - 1);  // the first one is the core build
    const int hp = hp_emb * 5 + static_cast<int>(owned[I::bruiser_shard_of_health]);
    if (static_cast<float>(hp) < hp_per_dmg * static_cast<float>(dmg)) return I::bruiser_shard_of_health;
    return stack_dmg;
}

void Bot::shop() {
    auto& me = bc::self();
    try {
        const auto lock = bc::consumable_type::altar_lock;
        const auto owned = me.item_count();
        const bool core_done = owned[I::bruiser_emblem_of_health] > 0 || owned[I::home_emblem_of_health] > 0;
        if (core_done && me.gold_count() >= static_cast<unsigned>(Nv::LOCK_GOLD) && me.consumables()[lock].count() == 0 && me.can_buy(lock))
            me.buy(lock);
    } catch (...) {
    }
    for (int i = 0; i < 16; ++i) {
        const auto item = next_item();
        try {
            if (!item || me.gold_count() < item->cost() || !me.can_buy(*item)) break;
            me.buy(*item);
        } catch (...) {
            break;
        }
    }
}

bool Bot::go_home() {
    auto& me = bc::self();
    const bool calm = nearest_enemy > Nv::SKIRMISH;
    if (on_spawn()) {
        if (calm && my_hp < Nv::HEALED_HP * my_max) return true;  // heal at turn end
        return false;
    }
    if (calm && my_hp < Nv::HEAL_HP * my_max) {
        if (static_cast<int>(spawn_field.get(pos)) > Nv::RECALL_RANGE && my_hp >= last_hp) {
            try {
                me.recall();
                return true;
            } catch (...) {
            }
        }
        return move_to(ally_spawn, false, &spawn_field);
    }
    if (calm && me.gem_count() == 0 && me.gold_count() >= static_cast<unsigned>(Nv::HOME_GOLD)
        && static_cast<int>(spawn_field.get(pos)) <= Nv::HOME_RANGE) {
        const auto item = next_item();
        if (item && me.gold_count() >= item->cost()) return move_to(ally_spawn, false, &spawn_field);
    }
    return false;
}

bool Bot::deny_tribute() {
    auto& me = bc::self();
    try {
        auto& lock = me.consumables()[bc::consumable_type::altar_lock];
        if (lock.count() == 0) return false;
        const int range = static_cast<int>(bc::constants::submit_gems_range);
        for (const auto& e : enemies) {
            if (!e.tributing || e.gems < 10) continue;
            for (auto a : altar_tiles) {
                if (cheb(a, e.pos) > range || cheb(a, pos) > 2 || !vis.is_set(a) || bc::vision::has_altar_lock(a)) continue;
                if (lock.use(a)) return true;
            }
        }
    } catch (...) {
    }
    return false;
}

void Bot::place_ward() {
    if (round - last_ward < Nv::WARD_EVERY) return;
    vec2 anchor = pos;
    if (target >= 0) anchor = groups[static_cast<std::size_t>(target)].center;
    else if (!altar_tiles.empty())
        anchor = *std::min_element(altar_tiles.begin(), altar_tiles.end(), [&](vec2 a, vec2 b) { return cheb(a, pos) < cheb(b, pos); });
    try {
        auto& me = bc::self();
        vec2 best = pos;
        int best_d = UNREACH;
        for (auto t : (me.ward_placement_tiles() & ~terrain).positions()) {
            if (cheb(t, anchor) > Nv::WARD_NEAR) continue;
            const int d = static_cast<int>(enemy_field.get(t));
            if (d < best_d) best_d = d, best = t;
        }
        if (best_d >= UNREACH) return;
        if (me.place_ward(best)) last_ward = round;
    } catch (...) {
        last_ward = round;
    }
}
