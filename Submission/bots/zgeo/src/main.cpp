// Geometry probe: one champion prints camp groups, altars, spawns and terrain a few lines per turn.
#include <cambc.h>
#include <algorithm>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include "draft.h"
namespace bc = cambc;
static std::string tiles(const bc::bitboard& b) {
    std::ostringstream o;
    for (auto t : b.positions()) o << " " << t.x << "," << t.y;
    return o.str();
}
int main() {
    int stage = 0; bool me_prints = false; std::vector<std::string> lines; std::size_t next = 0;
    while (true) {
        try {
            if (bc::is_draft()) play_draft();
            else if (stage == 0) {
                stage = 1;
                int mine = static_cast<int>(bc::self().champion_name()), lo = 1 << 30;
                for (const auto& c : bc::champions(bc::team::ally)) lo = std::min(lo, static_cast<int>(c.champion_name()));
                me_prints = mine == lo;
            } else if (me_prints && stage == 1) {
                stage = 2;
                std::ostringstream o;
                o << "GEO W=" << bc::map::width() << " H=" << bc::map::height(); lines.push_back(o.str()); o.str("");
                o << "ALTARS";
                for (auto a : bc::map::altars().positions()) o << " " << a.x << "," << a.y << ":b0:w0";
                lines.push_back(o.str());
                for (const auto& h : bc::map::camp_groups()) {
                    float hp = 0, st = 0; int n = 0; std::string kinds;
                    for (const auto& c : h.camps()) {
                        ++n;
                        try { auto s = c.base_stats(); hp += s.base_health; st += s.base_strength; } catch (...) {}
                        kinds += c.is_monolith() ? " mono" : c.is_golem() ? " golem" : c.is_elk() ? " elk" : c.is_wolf() ? " wolf" : " cl";
                        kinds += "@" + std::to_string(c.spawn_position().x) + "," + std::to_string(c.spawn_position().y);
                    }
                    std::ostringstream g;
                    g << "GROUP gems=" << h.gem_value() << " gold=" << h.gold_value() << " n=" << n << " resp=" << h.max_respawn_timer()
                      << " hp=" << hp << " str=" << st << " tiles" << tiles(h.spawn_tiles()) << " kinds" << kinds;
                    lines.push_back(g.str());
                }
                lines.push_back("SPAWN_A" + tiles(bc::map::spawn_region(bc::team::ally)));
                lines.push_back("SPAWN_E" + tiles(bc::map::spawn_region(bc::team::enemy)));
                lines.push_back("WALLS" + tiles(bc::map::walls()));
                lines.push_back("HOLES" + tiles(bc::map::holes()));
                lines.push_back("BUSH" + tiles(bc::map::bushes()));
                lines.push_back("END");
            } else if (me_prints) {
                for (int k = 0; k < 4 && next < lines.size(); ++k) std::cout << lines[next++] << "\n";
                std::cout.flush();
            }
        } catch (const std::exception& e) { std::cout << "bot error: " << e.what() << std::endl; }
        bc::end_turn();
    }
}
