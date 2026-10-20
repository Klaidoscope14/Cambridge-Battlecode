// Adversary: park champions next to the nearest altar and hit anything in reach.
#include <cambc.h>
#include <algorithm>
#include <iostream>
namespace bc = cambc;
static bool ready = false;
static bc::distance_field field;
int main() {
    while (true) {
        try {
            if (bc::is_draft()) {
                const auto ours = bc::draft::current_draft(bc::team::ally);
                for (auto p : {bc::champion_draft::stellar, bc::champion_draft::ryth, bc::champion_draft::varg, bc::champion_draft::marcella, bc::champion_draft::vendetta, bc::champion_draft::ren})
                    if (std::find(ours.begin(), ours.end(), p) == ours.end()) { bc::draft::pick(p); break; }
            } else {
                auto& me = bc::self();
                if (!ready) {
                    ready = true;
                    auto terrain = bc::map::walls() | bc::map::holes() | bc::map::altars() | bc::map::spawn_region(bc::team::enemy);
                    bc::bitboard goals, visited;
                    for (auto a : bc::map::altars().positions()) { bc::bitboard b; b.draw_chebyshev(a, 2); goals |= b; }
                    goals &= ~terrain;
                    field.compute(terrain, goals, visited);
                }
                if (me.is_alive()) {
                    auto pos = me.position();
                    for (const auto& e : bc::vision::champions(bc::team::enemy)) {
                        if (!e.is_alive() || !e.is_visible()) continue;
                        if (me.can_attack() && me.attack_tiles().is_set(e.position())) { me.attack(e); break; }
                    }
                    if (field.get(pos) > 0 && me.can_move()) {
                        auto st = bc::map::walls() | bc::map::holes() | bc::map::altars() | bc::vision::champion_tiles() | bc::vision::camp_tiles();
                        st.set(pos, false);
                        auto steps = st.reachable_tiles(pos, 1).positions();
                        std::sort(steps.begin(), steps.end(), [&](bc::vec2 a, bc::vec2 b) { return field.get(a) < field.get(b); });
                        for (auto t : steps) { if (field.get(t) >= field.get(pos)) break; try { if (me.move_absolute(t)) break; } catch (...) {} }
                    }
                }
            }
        } catch (const std::exception& e) { std::cout << "err " << e.what() << std::endl; }
        bc::end_turn();
    }
}
