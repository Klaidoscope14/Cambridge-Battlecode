// Profiling build: per-turn fuel use and per-function fuel, printed every 500 rounds.
#include <cambc.h>
#include <iostream>
#include "bot.h"
#include "common.h"
#include "../../../tools/fuel_profile/prof.h"  // adjust the path when copying into a bot
#include "draft.h"

static void dump(unsigned round) {
    std::cout << "PROFTURN r=" << round << " kind=" << cambc::to_string(cambc::self().champion_name()) << " turns=" << Prof::turns
              << " avg=" << (Prof::turns ? Prof::turn_sum / Prof::turns : 0) << " max=" << Prof::turn_max << " over80k=" << Prof::turn_over80
              << " over95k=" << Prof::turn_over95 << " wrapped=" << Prof::turn_wrapped << " hist=";
    for (int i = 0; i < 11; ++i) std::cout << Prof::hist[i] << (i < 10 ? "," : "");
    std::cout << "\n";
    for (int i = 0; i < Prof::n; ++i)
        if (Prof::cnt[i]) std::cout << "PROFFN " << Prof::names[i] << " n=" << Prof::cnt[i] << " sum=" << Prof::sum[i] << " avg=" << Prof::sum[i] / Prof::cnt[i] << " max=" << Prof::mx[i] << " wrapped=" << Prof::wrapped[i] << "\n";
    std::cout << std::flush;
}

int main() {
    Bot bot;
    unsigned last_dump = 0;
    while (true) {
        const std::uint64_t t0 = cambc::fuel_remaining();
        bool draft = false;
        try {
            if (cambc::is_draft()) { draft = true; play_draft(); }
            else
                bot.play_turn();
        } catch (const std::exception& error) {
            std::cout << "bot error [" << g_stage << "]: " << error.what() << std::endl;
        } catch (...) {
            std::cout << "bot error [" << g_stage << "]: unknown exception" << std::endl;
        }
        if (!draft) {
            const std::uint64_t t1 = cambc::fuel_remaining();
            if (t1 > t0) ++Prof::turn_wrapped;
            else {
                const std::uint64_t used = t0 - t1;
                ++Prof::turns; Prof::turn_sum += used; if (used > Prof::turn_max) Prof::turn_max = used;
                if (used > 80000) ++Prof::turn_over80;
                if (used > 95000) ++Prof::turn_over95;
                ++Prof::hist[std::min<std::uint64_t>(used / 10000, 10)];
            }
            const unsigned r = static_cast<unsigned>(cambc::round_number());
            if (r >= last_dump + 500) { last_dump = r - r % 500; dump(r); }
        }
        cambc::end_turn();
    }
}
