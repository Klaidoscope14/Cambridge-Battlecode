// nova farming, modelled on the top teams (Observations.md section 6): every champion farms cheap own-half camps from
// round ~19, never waits for help, commits to a target until it is captured, and holds the capture tiles.
// Path distances come from one cached distance field per camp group (as in v65), built when fuel allows.
#include <algorithm>
#include <cmath>
#include "bot.h"

void Bot::claim(int g) { write_byte(Mem::CLAIMS + body, static_cast<std::uint8_t>(g < 0 ? 0 : g + 1)); }

int Bot::path_to(int gi) {
    auto& f = gfield[static_cast<std::size_t>(gi)];
    if (!f) {
        if (fields_built_round == round || bc::fuel_remaining() < static_cast<std::uint64_t>(Nv::FIELD_FUEL)) {
            int d = UNREACH;  // no fuel for a field yet: straight-line estimate
            for (auto t : groups[static_cast<std::size_t>(gi)].tiles) d = std::min(d, cheb(t, pos));
            return d + 2;
        }
        fields_built_round = round;  // one ~11K field per turn at most
        f.emplace();
        bitboard visited;
        f->compute(terrain, groups[static_cast<std::size_t>(gi)].spawn, visited);
    }
    return static_cast<int>(f->get(pos));
}

const bc::distance_field* Bot::group_field(int gi) {
    path_to(gi);
    const auto& f = gfield[static_cast<std::size_t>(gi)];
    return f ? &*f : nullptr;
}

int Bot::helpers_at(int gi) const {
    int n = 0;
    const auto& g = groups[static_cast<std::size_t>(gi)];
    for (const auto& a : allies)
        for (auto t : g.tiles)
            if (cheb(a.pos, t) <= g.reach + 4) {  // on the wait ring or closer
                ++n;
                break;
            }
    return n;
}

int Bot::claimers(int gi) const {
    int n = 0;
    for (int b = 0; b < Mem::BODIES; ++b)
        if (b != body && mem[static_cast<std::size_t>(Mem::CLAIMS + b)] == gi + 1) ++n;
    return n;
}

// Claimers that count against me taking the group: on my own target only lower bodies (they keep it, higher ones yield).
int Bot::rivals(int gi) const {
    if (gi != target) return claimers(gi);
    int n = 0;
    for (int b = 0; b < body; ++b)
        if (mem[static_cast<std::size_t>(Mem::CLAIMS + b)] == gi + 1) ++n;
    return n;
}

// Helpers (besides me) a fighting group needs so each of us keeps SOLO_MARGIN of health:
// incoming per body falls as 1/(1+h) and the fight is (1+h) times shorter, so (1+h)^2 >= taken x hp / (dps x allowance).
int Bot::needed_helpers(int gi) const {
    const auto& g = groups[static_cast<std::size_t>(gi)];
    if (g.strength <= 0.f || g.reward) return 0;
    const float hp = g.live_hp >= 0.f ? g.live_hp : g.hp;
    const float taken = g.strength * (has_jungle ? Nv::JUNGLE_TAKEN : 1.f) * (g.camps > 1 ? 0.65f : 1.f);
    const float solo = taken * hp / camp_dps;                       // damage we would take clearing it alone
    const float allowance = my_hp - Nv::SOLO_MARGIN * my_max;
    int best = 99;
    if (allowance > 0.f) best = std::max(0, static_cast<int>(std::ceil(solo / allowance)) - 1);
    if (g.camps > 1) {  // pooled: (1+h)^2 >= solo / (POOL_SHARE x max health)
        const int h = std::max(1, static_cast<int>(std::ceil(std::sqrt(solo / (Nv::POOL_SHARE * my_max)))) - 1);
        best = std::min(best, h);
    }
    return best;
}

float Bot::score(int gi, int dist, bool* needs_help, bool lead) const {
    const auto& g = groups[static_cast<std::size_t>(gi)];
    if (needs_help) *needs_help = false;
    if (g.monolith || round < g.skip_until || dist >= UNREACH) return -1.f;
    if (g.respawn_at > round + dist + 6) return -1.f;

    float value = static_cast<float>(g.gems) + Nv::GOLD_W * static_cast<float>(g.gold);
    if (kind == bc::champion_type::vesper_vale) value += Nv::GOLD_W * 0.2f * static_cast<float>(g.gold);
    if (kind == bc::champion_type::marcella) value += Nv::GOLD_W * 2.f * static_cast<float>(g.gems);
    float side = g.owner > 0 ? Nv::SIDE_OWN : g.owner < 0 ? Nv::SIDE_AWAY : Nv::SIDE_MID;
    if (Nv::MAP_MODES) side = g.owner > 0 ? (map_mode > 0 ? 1.3f : map_mode < 0 ? 1.f : 1.15f)
                            : g.owner < 0 ? (map_mode > 0 ? 0.6f : map_mode < 0 ? 1.f : 0.85f) : 1.f;
    if (g.owner < 0 && (enemies_dead >= Nv::RAID_DEAD || gem_gap <= -Nv::BEHIND)) side = Nv::SIDE_MID;

    // Assignment: a cluster belongs to whoever claimed it; a fighting group takes exactly the bodies it needs.
    const int others = claimers(gi), need = needed_helpers(gi);
    if (g.strength <= 0.f || g.reward) {
        if (rivals(gi) > 0) return -1.f;
    } else {
        if (rivals(gi) > need) return -1.f;             // full
        if (need > Nv::MAX_HELPERS || need >= bodies) return -1.f;
        if (need > others && !lead) return -1.f;  // busy champions never wait: join a squad only as its last member
        if (need > helpers_at(gi) && needs_help) *needs_help = true;  // the squad is on its way
        value /= static_cast<float>(1 + need);
        value *= 1.f + 0.5f * static_cast<float>(std::min(others, need));  // converge on a squad already forming
    }
    const float hp = g.reward ? 0.f : g.live_hp >= 0.f ? g.live_hp : g.hp;
    const float kill = hp / (camp_dps * static_cast<float>(1 + need));
    for (const auto& e : enemies)
        if (cheb(e.pos, g.center) <= 5) {
            value *= ratio >= Nv::ENGAGE ? 0.8f : 0.2f;
            break;
        }
    const float wait = static_cast<float>(std::max(0, g.respawn_at - round - dist));
    float time = static_cast<float>(dist) + kill + static_cast<float>(bc::constants::capture_time) + wait;
    if (Nv::SQUAD_WAIT && need > 0) time += Nv::SW_PENALTY * static_cast<float>(std::max(0, need - helpers_at(gi)));
    if (Nv::NEAR_SWEEP && dist <= Nv::NS_RANGE) value *= Nv::NS_MULT;
    return value * side / (time + 4.f);
}

void Bot::rescore() {
    int best = -1;
    float best_s = 0.f, cur_s = -1.f;
    int cur_d = UNREACH;
    for (std::size_t i = 0; i < groups.size(); ++i) {
        if (groups[i].monolith || round < groups[i].skip_until) continue;
        const int d = path_to(static_cast<int>(i));
        const float s = score(static_cast<int>(i), d, nullptr);
        if (static_cast<int>(i) == target) cur_s = std::max(s, score(target, d, nullptr, true)), cur_d = d;
        if (s > best_s) best_s = s, best = static_cast<int>(i);
    }
    if (best < 0) {  // nothing to take alone: help the nearest group an ally is short-handed on
        int best_d = UNREACH;
        for (std::size_t i = 0; i < groups.size(); ++i) {
            const int gi = static_cast<int>(i);
            if (groups[i].strength <= 0.f || claimers(gi) == 0 || claimers(gi) > needed_helpers(gi) || round < groups[i].skip_until) continue;
            bool lower = false;  // two idle leaders: the higher body joins the lower one (no swapping)
            for (int b = 0; b < body; ++b) lower = lower || mem[static_cast<std::size_t>(Mem::CLAIMS + b)] == gi + 1;
            if (target >= 0 && target != gi && !lower) continue;
            const int d = path_to(gi);
            if (d < best_d) best_d = d, best = gi, best_s = 0.01f;
        }
    }
    if (best < 0) {  // nobody to help either: idle champions lead a squad, the other idle ones assist it
        for (std::size_t i = 0; i < groups.size(); ++i) {
            if (groups[i].monolith || round < groups[i].skip_until) continue;
            const float s = score(static_cast<int>(i), path_to(static_cast<int>(i)), nullptr, true);
            if (s > best_s) best_s = s, best = static_cast<int>(i);
        }
        if (best >= 0) best_s = 0.01f;  // any solo target found later replaces it
    }
    last_score_round = round;
    // Commit: keep a live target unless the new one is far better and we have not arrived yet.
    if (target >= 0 && cur_s > 0.f && best != target && (cur_d <= 3 || best_s < Nv::SWITCH * cur_s)) return;
    if (best != target) target_since = round, wait_turns = 0;
    target = best;
    target_score = best_s;
    claim(target);
}

bool Bot::attack_group_camp(int gi) {
    auto& me = bc::self();
    if (!me.can_attack()) return false;
    const auto reach = me.attack_tiles();
    auto choose = [&](int skip) {
        int pick = -1;
        for (std::size_t i = 0; i < cv.size(); ++i) {
            const auto& v = cv[i];
            if (static_cast<int>(i) == skip || !reach.is_set(v.pos) || (v.group != gi && !v.awake)) continue;  // never wake another group
            if (pick < 0 || v.hp < cv[static_cast<std::size_t>(pick)].hp) pick = static_cast<int>(i);
        }
        return pick;
    };
    const int pick = choose(-1);
    if (pick < 0) return false;
    try {
        const auto c = bc::vision::camp_at(cv[static_cast<std::size_t>(pick)].pos);
        me.attack(c);
        acted = true;
        for (const auto& ab : me.abilities()) {  // a ready attack reset swings again (Vendetta, Marcella)
            if (!ab.is_attack_reset() || !ab.is_ready() || !me.can_cast()) continue;
            try {
                if (!c.is_dead()) {
                    if (ab.use() && me.can_attack()) me.attack(c);
                } else if (Nv::MOVE_RESET) {  // the first swing killed it: spend the reset on the next camp in reach
                    const int next = choose(pick);
                    if (next >= 0 && ab.use() && me.can_attack()) me.attack(bc::vision::camp_at(cv[static_cast<std::size_t>(next)].pos));
                }
            } catch (...) {
            }
            break;
        }
    } catch (...) {
        return false;
    }
    return true;
}

void Bot::estimate_camp_dps() {
    auto& me = bc::self();
    const float str = me.strength();
    float d = str;
    for (const auto& ab : me.abilities()) {
        try {
            if (ab.is_attack_reset()) d += str / 8.f;
            else if (ab.is_damage() || ab.is_aoe_damage()) d += ab.damage_amount() / 8.f;
        } catch (...) {
        }
    }
    camp_dps = std::max(d, 10.f);
}

void Bot::cast_on_camps(int gi) {
    auto& me = bc::self();
    if (!me.can_cast()) return;
    for (const auto& ab : me.abilities()) {
        try {
            if (!ab.is_ready() || !(ab.can_target_camps() || ab.can_target_ground()) || !(ab.is_damage() || ab.is_aoe_damage())) continue;
            const auto tiles = ab.valid_tiles();
            int pick = -1, best = -1;
            for (std::size_t i = 0; i < cv.size(); ++i) {
                const auto& v = cv[i];
                if (v.dead || !tiles.is_set(v.pos) || (v.group != gi && !v.awake)) continue;
                int s = ab.is_aoe_damage() ? 0 : 100000 - static_cast<int>(v.hp);
                if (ab.is_aoe_damage())
                    for (const auto& o : cv) s += !o.dead && cheb(o.pos, v.pos) <= 1 ? 1 : 0;
                if (s > best) best = s, pick = static_cast<int>(i);
            }
            if (pick < 0) continue;
            const vec2 at = cv[static_cast<std::size_t>(pick)].pos;
            if (ab.can_target_camps() && !ab.is_aoe_damage() ? ab.use(bc::vision::camp_at(at)) : ab.use(at)) return;
        } catch (...) {
        }
    }
}

// Mid-fight with the target (one of its camps awake and us near it): finish it before re-scoring.
bool Bot::engaged() const {
    if (target < 0) return false;
    const auto& g = groups[static_cast<std::size_t>(target)];
    if (cheb(pos, g.center) > g.reach + 4) return false;
    for (const auto& v : cv)
        if (!v.dead && v.awake && v.group == target) return true;
    return false;
}

bool Bot::capturing() const {
    if (target < 0) return false;
    const auto& g = groups[static_cast<std::size_t>(target)];
    return g.reward && g.spawn.is_set(pos);
}

bool Bot::farm() {
    if (target < 0 || (round - last_score_round >= Nv::RESCORE_EVERY && !engaged())) rescore();
    if (target < 0) {
        g_stage = "farm:none";
        return move_to(ally_spawn, false, &spawn_field);  // nothing we can take: shop / heal
    }
    auto& g = groups[static_cast<std::size_t>(target)];

    if (g.respawn_at > round + 2) {  // gone: pick another next turn
        g_stage = "farm:respawn";
        last_score_round = -100;
        return move_to(g.spawn, false, group_field(target));
    }
    // Capture: stand on the region until the reward lands, hitting anything in range meanwhile.
    if (g.reward) {
        if (g.spawn.is_set(pos)) {
            try {
                const auto cs = g.handle.capture_state();
                if (cs.state == bc::map::camp_group_capture_type::no_capture_available) {
                    g.reward = false;
                    last_score_round = -100;
                    return false;
                }
            } catch (...) {
            }
            g_stage = "farm:capture";
            attack_best();
            return true;
        }
        g_stage = "farm:to_capture";
        return move_to(g.spawn, false, group_field(target));
    }
    int near = UNREACH;
    for (auto t : g.tiles) near = std::min(near, cheb(t, pos));
    if (near <= 1 && g.alive_seen == 0) {  // nothing alive, nothing to capture: gone for now
        g.skip_until = round + Nv::SKIP_AFTER_FAIL;
        last_score_round = -100;
        return false;
    }
    // Squad target not started yet: hold just outside its reach until enough of us are here (v65), then go.
    bool needs_help = false;
    score(target, near, &needs_help, true);
    bool awake = false;
    for (const auto& v : cv) awake = awake || (!v.dead && v.awake && v.group == target);
    // Short-handed: hold outside the monsters' reach (an awake group resets after 2 rounds without damage).
    if (needs_help && Nv::SQUAD_WAIT && !awake && ++wait_turns > Nv::SW_REGROUP) {
        // Deadlock breaker (v65): join the squad most allies have committed to; after too long, give up.
        int join = -1, join_c = claimers(target);
        for (std::size_t i = 0; i < groups.size(); ++i) {
            const int gi = static_cast<int>(i);
            const int c = claimers(gi);
            if (gi == target || c <= join_c || groups[i].monolith || groups[i].strength <= 0.f || groups[i].respawn_at > round
                || round < groups[i].skip_until || path_to(gi) >= UNREACH)
                continue;
            join = gi, join_c = c;
        }
        if (join >= 0) {
            target = join, target_since = round, wait_turns = 0;
            claim(target);
            return move_to(groups[static_cast<std::size_t>(target)].spawn, false, group_field(target));
        }
        if (wait_turns > Nv::SW_GIVE_UP) {
            g.skip_until = round + Nv::SW_SKIP;
            wait_turns = 0;
            last_score_round = -100;
            return false;
        }
    }
    if (needs_help) {
        if (!Nv::SQUAD_WAIT && !awake && round - target_since > Nv::HELP_WAIT + near) {
            g.skip_until = round + Nv::SKIP_AFTER_FAIL;
            last_score_round = -100;
            return false;
        }
        g_stage = "farm:wait";
        bitboard ring, inner;
        for (auto t : g.tiles) ring |= square(t, g.reach + 3), inner |= square(t, g.reach + 1);
        for (const auto& v : cv)  // awake monsters chase: keep clear of where they stand now
            if (!v.dead && v.group == target) inner |= square(v.pos, g.reach + 1);
        ring &= ~inner & ~terrain;
        if (ring.is_set(pos)) return true;
        return move_to(ring, false, group_field(target));
    }
    g_stage = "farm:fight";
    cast_on_camps(target);
    if (attack_group_camp(target)) return true;
    bitboard goals;
    const int range = static_cast<int>(bc::self().attack_range());
    for (const auto& v : cv)
        if (!v.dead && v.group == target) goals |= square(v.pos, range);
    goals &= ~terrain;
    g_stage = "farm:approach";
    if (!goals.is_empty() && move_to(goals, false, group_field(target))) {
        if (Nv::MOVE_RESET) {  // in reach now: melee strikes on the same turn, ranged after an attack reset
            restore_attack();
            cast_on_camps(target);
            attack_group_camp(target);
        }
        return true;
    }
    g_stage = "farm:walk";
    return move_to(g.spawn, false, group_field(target));
}
