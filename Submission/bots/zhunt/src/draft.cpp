// Draft: score every champion for camp-farming throughput, tilted by map shape.
#include "draft.h"
#include <algorithm>
#include <array>
#include <cstring>
#include "common.h"

using CD = bc::champion_draft;

namespace {

struct MapShape {
    float cluster = 0.f;  // share of camp groups with 2+ monsters (splash / AoE value)
    float hostile = 0.f;  // share of groups that fight back (wolves, elk)
    float area = 0.f;
};

MapShape read_shape() {
    MapShape s;
    s.area = static_cast<float>(bc::map::width() * bc::map::height());
    const auto groups = bc::map::camp_groups();
    if (groups.empty()) return s;
    int clustered = 0, hostile = 0;
    for (const auto& g : groups) {
        const auto camps = g.camps();
        if (camps.size() >= 2) ++clustered;
        bool fights = false;
        for (const auto& c : camps)
            if (c.is_wolf() || c.is_elk()) fights = true;
        if (fights) ++hostile;
    }
    s.cluster = static_cast<float>(clustered) / groups.size();
    s.hostile = static_cast<float>(hostile) / groups.size();
    return s;
}

// Base value = sustained camp damage, durability and travel tools.
float score(CD pick, const MapShape& m) {
    float v = 0.f;
    switch (pick) {
        case CD::cassi_and_issac: v = Cfg::PAIR_DRAFT_SCORE; break;  // two farming bodies from one pick
        case CD::vendetta: v = 9.0f + (m.area >= 4000 ? 0.4f : 0.f); break;
        case CD::varg: v = 8.2f + 2.0f * m.cluster; break;
        case CD::stellar: v = 7.9f + 1.6f * m.cluster; break;
        case CD::ryth: v = 8.0f + 0.8f * m.hostile; break;
        case CD::marcella: v = 7.3f + 0.8f * m.hostile; break;
        case CD::tavi: v = 7.5f; break;
        case CD::vesper_vale: v = 7.1f + (m.area >= 4000 ? 0.4f : 0.f); break;
        case CD::ren: v = 6.6f + 0.4f * m.hostile; break;
        case CD::prism: v = 6.2f + 0.8f * m.cluster; break;
        case CD::willow: v = 5.0f; break;
        case CD::heart_of_ruin: v = Cfg::HOR_DRAFT_SCORE; break;  // patch 3.0: near 100% top-ladder pick rate
        default: v = 0.f;
    }
    return v;
}

}  // namespace

void play_draft() {
    static bool shape_ready = false;
    static MapShape shape;
    if (!shape_ready) {
        shape = read_shape();
        shape_ready = true;
    }

    const auto ours = bc::draft::current_draft(team::ally);
    if (Cfg::TEST_FORCE_PRISM && std::find(ours.begin(), ours.end(), CD::prism) == ours.end()) {
        bc::draft::pick(CD::prism);
        return;
    }
    if (Cfg::TEST_FORCE_RYTH && std::find(ours.begin(), ours.end(), CD::ryth) == ours.end()) {
        bc::draft::pick(CD::ryth);
        return;
    }
    if (Cfg::TEST_FORCE_VESPER && std::find(ours.begin(), ours.end(), CD::vesper_vale) == ours.end()) {
        bc::draft::pick(CD::vesper_vale);
        return;
    }
    // zhunt: the top-10 core, in their pick-rate order.
    for (auto p : {CD::vesper_vale, CD::marcella, CD::vendetta, CD::heart_of_ruin, CD::ryth, CD::tavi}) {
        if (std::find(ours.begin(), ours.end(), p) != ours.end()) continue;
        try {
            bc::draft::pick(p);
            return;
        } catch (...) {
        }
    }
    int opening = 3;  // DRAFT3: fewer forced openers on 3-champion maps
    if constexpr (Cfg::DRAFT3 < 3) {
        try {
            if (bc::draft::team_size() <= 3) opening = Cfg::DRAFT3;
        } catch (...) {
        }
    }
    if (Cfg::CI_DRAFT && std::find(ours.begin(), ours.end(), CD::cassi_and_issac) == ours.end()) {
        try {
            bc::draft::pick(CD::cassi_and_issac);  // throws if the enemy already has it
            return;
        } catch (...) {
        }
    }
    if (Cfg::TEST_FORCE_RANGED || Cfg::RANGED_META)  // patch 3.0 meta: open Vesper, Tavi, Willow
        for (auto p : {CD::vesper_vale, CD::tavi,
                       Cfg::MELEE_OPENER == 1 ? CD::vendetta : Cfg::MELEE_OPENER == 2 ? CD::marcella : CD::willow})
            if (opening-- > 0 && std::find(ours.begin(), ours.end(), p) == ours.end()) {
                bc::draft::pick(p);
                return;
            }
    auto has = [&](CD p) { return std::find(ours.begin(), ours.end(), p) != ours.end(); };
    std::vector<CD> theirs;
    try {
        theirs = bc::draft::current_draft(team::enemy);
    } catch (...) {
    }
    auto they = [&](CD p) { return std::find(theirs.begin(), theirs.end(), p) != theirs.end(); };
    const bool vs_linked = they(CD::cassi_and_issac);
    int fragile_ranged = 0;
    for (auto p : {CD::vesper_vale, CD::prism, CD::stellar, CD::willow, CD::tavi, CD::cassi_and_issac})
        fragile_ranged += they(p) ? 1 : 0;
    const bool frontliner = has(CD::marcella) || has(CD::varg) || has(CD::ryth);
    CD best = CD::vendetta;
    float best_score = -1.f;
    for (int i = 0; i <= static_cast<int>(CD::heart_of_ruin); ++i) {  // every draft choice, incl. ones added by patches
        const auto pick = static_cast<CD>(i);
        if (has(pick)) continue;
        float s = score(pick, shape);
        if (Cfg::COUNTER_DRAFT) {
            if (vs_linked && (pick == CD::stellar || pick == CD::prism || pick == CD::varg || pick == CD::ryth))
                s += Cfg::COUNTER_BONUS;
            if (fragile_ranged >= 2 && (pick == CD::varg || pick == CD::ren || pick == CD::vendetta))
                s += Cfg::COUNTER_BONUS;
        }
        if (Cfg::DRAFT_SYNERGY) {
            if (pick == CD::tavi && frontliner) s += Cfg::SYNERGY_BONUS;
            if ((pick == CD::marcella || pick == CD::varg || pick == CD::ryth) && has(CD::tavi)) s += 0.5f * Cfg::SYNERGY_BONUS;
        }
        if (s > best_score) best_score = s, best = pick;
    }

    // Opening plan for the champions: magic, version, our picks so far.
    std::array<std::byte, 8> plan{};
    plan[0] = std::byte{'K'};
    plan[1] = std::byte{1};
    for (std::size_t i = 0; i < ours.size() && i + 3 < plan.size(); ++i)
        plan[i + 2] = static_cast<std::byte>(static_cast<int>(ours[i]));
    plan[std::min<std::size_t>(ours.size(), 5) + 2] = static_cast<std::byte>(static_cast<int>(best));
    bc::draft_memory = std::span<const std::byte>{plan.data(), plan.size()};

    bc::draft::pick(best);
}
