// nova turn order: observe -> fight / disengage -> deny tributes -> bank -> shop / heal -> join -> farm -> ward.
#include <iostream>
#include "bot.h"

void Bot::play_turn() {
    if (!ready_) {
        g_stage = "init";
        init();
    }
    auto& me = bc::self();
    if (!me.is_alive()) {
        if (Nv::DEAD_SHOP) {
            g_stage = "dead";
            shop();
            target = -1;  // pick afresh after respawn (the claim byte stays until then, as in v65)
        }
        return;
    }
    g_stage = "observe";
    observe();
    struct Tr { const Bot* b; ~Tr() { b->trace(); } } tr_{this};
    acted = false;
    if (me.is_recalling() || me.is_submitting_gems() || me.is_teleporting()) return;
    if (!me.can_move() && !me.can_attack() && !me.can_cast()) return;  // stunned

    g_stage = "shop";
    if (on_spawn()) shop();
    g_stage = "assess";
    estimate_camp_dps();
    assess();

    g_stage = "fight";
    if (fight()) {
        place_ward();
        return;
    }
    g_stage = "deny";
    if (deny_tribute()) return;
    g_stage = "bank";
    if (should_bank() && bank()) return;
    g_stage = "home";
    if (go_home()) return;
    g_stage = "join";
    if (join()) return;
    g_stage = "farm";
    farm();
    place_ward();
}

void Bot::trace() const {
#ifdef NOVA_TRACE
    if (round % 25 == 0) {
        auto& me = bc::self();
        std::cout << "T r" << round << " " << bc::to_string(kind) << " pos " << pos.x << "," << pos.y << " hp " << static_cast<int>(my_hp)
                  << " gems " << me.gem_count() << " gold " << me.gold_count() << " stage " << g_stage << " tgt " << target;
        if (target >= 0) {
            const auto& g = groups[static_cast<std::size_t>(target)];
            std::cout << " tgtpos " << g.center.x << "," << g.center.y << " gems " << g.gems << " str " << g.strength << " live " << g.live_hp
                      << " alive " << g.alive_seen << " reward " << g.reward << " resp " << g.respawn_at;
        }
        std::cout << " ratio " << ratio << " ne " << nearest_enemy << "\n";
    }
#endif
}
