// Draft the top-10 core: Vesper, Heart of Ruin, Vendetta, Marcella, then Cassi & Issac (Observations.md section 3).
#include "draft.h"
#include <algorithm>
#include <vector>
#include "config.h"

using CD = bc::champion_draft;

void play_draft() {
    const auto ours = bc::draft::current_draft(team::ally);
    auto has = [&](CD p) { return std::find(ours.begin(), ours.end(), p) != ours.end(); };
    static const CD order[] = {CD::vesper_vale, CD::heart_of_ruin, CD::vendetta, CD::marcella, CD::cassi_and_issac,
                               CD::ryth, CD::tavi, CD::prism, CD::varg, CD::stellar, CD::willow, CD::ren};
    for (auto p : order) {
        if (has(p)) continue;
        try {
            bc::draft::pick(p);
            return;
        } catch (...) {  // unavailable: try the next one
        }
    }
}
