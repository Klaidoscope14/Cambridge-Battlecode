// nova fights (Observations.md section 10): take contact when ahead, trade when even and already in range,
// step away early when behind or hurt, join an ally's winning fight, finish kills. Local power is Lanchester-style:
// total HP x total damage per round on each side within SKIRMISH tiles, remembered enemies at reduced weight.
#include <algorithm>
#include "bot.h"

namespace {
float my_damage(bc::champion_type kind, float hp, float max_hp) {
    float d = bc::self().strength();
    if (kind == bc::champion_type::heart_of_ruin) d *= 1.f + 0.5f * (1.f - hp / std::max(max_hp, 1.f));  // missing-health bonus
    return d;
}
}  // namespace

void Bot::assess() {
    nearest_enemy = 99;
    for (const auto& e : enemies) nearest_enemy = std::min(nearest_enemy, cheb(e.pos, pos));
    float our_hp = my_hp, our_dps = my_damage(kind, my_hp, my_max), their_hp = 0.f, their_dps = 0.f;
    for (const auto& a : allies)
        if (cheb(a.pos, pos) <= Nv::SKIRMISH) our_hp += a.hp, our_dps += a.dps + a.spell / 4.f;
    for (const auto& e : enemies)
        if (cheb(e.pos, pos) <= Nv::SKIRMISH) their_hp += e.hp, their_dps += e.dps + e.spell / 4.f;
    for (const auto& g : ghosts)
        if (g.seen != round && cheb(g.pos, pos) <= Nv::SKIRMISH + (round - g.seen))
            their_hp += g.weight * g.hp, their_dps += g.weight * (g.dps + g.spell / 4.f);
    ratio = their_hp <= 0.f ? 99.f : (our_hp * our_dps) / std::max(their_hp * their_dps, 1.f);
}

bool Bot::cast_spells() {
    auto& me = bc::self();
    if (!me.can_cast() || enemies.empty()) return false;
    bool cast = false;
    for (const auto& ab : me.abilities()) {
        if (!me.can_cast()) break;
        try {
            if (!ab.is_ready()) continue;
            const auto tiles = ab.valid_tiles();
            if (ab.is_shield()) {
                if (my_hp < 0.7f * my_max && nearest_enemy <= 4 && ab.use()) cast = true;
                continue;
            }
            if (ab.is_aoe_damage()) {
                // Land where the most enemies are caught (2+, or 1 we can finish).
                vec2 best{};
                int best_n = 0;
                for (const auto& e : enemies) {
                    if (!tiles.is_set(e.pos)) continue;
                    int n = 0;
                    for (const auto& o : enemies) n += cheb(o.pos, e.pos) <= 1 ? 1 : 0;
                    if (e.hp <= ab.damage_amount()) n += 1;
                    if (n > best_n) best_n = n, best = e.pos;
                }
                if (best_n >= 2 && ab.use(best)) cast = true;
                continue;
            }
            if (ab.is_damage() || ab.is_cc()) {
                const Unit* pick = nullptr;
                for (const auto& e : enemies) {
                    if (!tiles.is_set(e.pos)) continue;
                    if (ab.is_damage()) {
                        if (!pick || e.hp < pick->hp) pick = &e;  // finish the weakest
                    } else if (!pick || e.dps > pick->dps) {
                        pick = &e;  // stun the hardest hitter
                    }
                }
                if (!pick) continue;
                const auto& h = enemy_handles[static_cast<std::size_t>(pick->index)];
                if (ab.can_target_enemies() ? ab.use(h) : ab.use(pick->pos)) cast = true;
            }
        } catch (...) {
        }
    }
    return cast;
}

// Ranged champions cannot move and attack in one turn; a ready attack reset restores the attack (v65 RANGED_MOVE_RESET).
bool Bot::restore_attack() {
    auto& me = bc::self();
    if (!Nv::MOVE_RESET || !ranged || me.can_attack() || !me.can_cast()) return false;
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

bool Bot::attack_best() {
    auto& me = bc::self();
    if (!me.can_attack()) return false;
    const auto reach = me.attack_tiles();
    const float hit = my_damage(kind, my_hp, my_max);
    const Unit* pick = nullptr;
    auto key = [&](const Unit& e) { return (e.hp <= hit ? 1000.f : 0.f) + (e.tributing ? 10.f : 0.f) + 1.f - e.hp / e.max_hp; };
    for (const auto& e : enemies)
        if (reach.is_set(e.pos) && (!pick || key(e) > key(*pick))) pick = &e;
    if (!pick) return false;
    try {
        me.attack(enemy_handles[static_cast<std::size_t>(pick->index)]);
        acted = true;
    } catch (...) {
        return false;
    }
    for (const auto& ab : me.abilities()) {
        if (!ab.is_attack_reset() || !me.can_cast()) continue;
        try {
            const auto& h = enemy_handles[static_cast<std::size_t>(pick->index)];
            if (ab.is_ready() && h.is_alive()) {
                if (ab.use() && me.can_attack()) me.attack(h);
            } else if (Nv::MOVE_RESET && ab.is_ready()) {  // killed: the reset goes to the next enemy in reach
                const Unit* next = nullptr;
                for (const auto& e : enemies)
                    if (&e != pick && reach.is_set(e.pos) && (!next || key(e) > key(*next))) next = &e;
                if (next && ab.use() && me.can_attack()) me.attack(enemy_handles[static_cast<std::size_t>(next->index)]);
            }
        } catch (...) {
        }
        break;
    }
    return true;
}

bool Bot::engage() {
    auto& me = bc::self();
    cast_spells();
    if (attack_best()) return true;
    // Walk into range of the best target: killable first, then lowest health share.
    const float hit = my_damage(kind, my_hp, my_max);
    const Unit* pick = nullptr;
    auto key = [&](const Unit& e) { return (e.hp <= 2.f * hit ? 100.f : 0.f) + 1.f - e.hp / e.max_hp - 0.05f * static_cast<float>(cheb(e.pos, pos)); };
    for (const auto& e : enemies) {
        if (cheb(e.pos, pos) > Nv::SKIRMISH) continue;
        bool home = false;
        for (auto t : square(e.pos, Nv::SPAWN_GUARD).positions()) home = home || enemy_spawn.is_set(t);
        if (!home && (!pick || key(e) > key(*pick))) pick = &e;
    }
    if (!pick) return false;
    const bitboard goals = square(pick->pos, static_cast<int>(me.attack_range())) & ~terrain;
    const bool moved = move_to(goals);
    if (moved) {
        restore_attack();
        cast_spells();
        attack_best();
    }
    return moved || acted;
}

bool Bot::disengage() {
    auto& me = bc::self();
    // A bag next to an altar is banked even now (tribute is a channel, but the bag is safe once it lands).
    if (me.gem_count() > 0 && nearest_enemy > 2) {
        const int range = static_cast<int>(bc::constants::submit_gems_range);
        for (auto a : altar_tiles)
            if (cheb(a, pos) <= range && altar_safe(a)) {
                try {
                    if (!bc::vision::has_altar_lock(a)) {
                        me.submit_gems(a);
                        return true;
                    }
                } catch (...) {
                }
            }
    }
    // Step away toward healthy allies or home, preferring the least exposed tiles.
    bitboard goals = ally_spawn;
    for (const auto& a : allies)
        if (cheb(a.pos, pos) <= 10 && a.hp >= 0.5f * a.max_hp) goals |= square(a.pos, 1);
    goals &= ~terrain;
    if (move_to(goals, true)) {
        attack_best();  // ranged champions cannot also fire, melee can strike on the way out
        return true;
    }
    // Cornered: fight back.
    cast_spells();
    return attack_best();
}

bool Bot::join() {
    if (round < Nv::FIRST_ENGAGE || my_hp < Nv::JOIN_HP * my_max || bc::self().gem_count() >= 30 || ratio < 1.f) return false;
    // An ally within JOIN_RANGE with an enemy on it: walk in.
    const Unit* pick = nullptr;
    for (const auto& a : allies) {
        if (cheb(a.pos, pos) > Nv::JOIN_RANGE) continue;
        for (const auto& e : enemies)
            if (cheb(e.pos, a.pos) <= 4 && (!pick || e.hp < pick->hp)) pick = &e;
    }
    if (!pick) return false;
    const bitboard goals = square(pick->pos, static_cast<int>(bc::self().attack_range())) & ~terrain;
    if (move_to(goals)) {
        restore_attack();
        cast_spells();
        attack_best();
        return true;
    }
    return false;
}

bool Bot::capturing_soon() const {
    if (target < 0) return false;
    const auto& g = groups[static_cast<std::size_t>(target)];
    if (!g.reward) return false;
    for (auto t : g.tiles)
        if (cheb(t, pos) <= 3) return true;
    return false;
}

bool Bot::fight() {
    if (nearest_enemy > Nv::SKIRMISH) return false;
    float engage_at = Nv::ENGAGE;
    if (gem_gap <= -Nv::BEHIND) engage_at = Nv::ENGAGE_BEHIND;
    else if (gem_gap >= Nv::BEHIND) engage_at = Nv::ENGAGE_AHEAD;
    const bool heart = kind == bc::champion_type::heart_of_ruin;
    const float floor = heart && ratio >= 1.f ? Nv::HEART_HP : Nv::DISENGAGE_HP;
    if (my_hp < floor * my_max || (ratio < Nv::TRADE && nearest_enemy <= 5)) {
        g_stage = "disengage";
        return disengage();
    }
    if (ratio >= engage_at && nearest_enemy <= 5 && round >= Nv::FIRST_ENGAGE) {
        g_stage = "engage";
        return engage();
    }
    if (ratio >= Nv::TRADE && !capturing_soon()) {  // a capture is held by farm(), which hits from the tiles
        g_stage = "trade";
        cast_spells();
        return attack_best();
    }
    return false;
}
