// Dispatch draft and gameplay; a failed turn is logged and still yields.
#include <cambc.h>
#include <iostream>
#include "bot.h"
#include "common.h"
#include "draft.h"

int main() {
    Bot bot;
    while (true) {
        try {
            if (cambc::is_draft())
                play_draft();
            else
                (void)bot;  // idle probe opponent: never acts
        } catch (const std::exception& error) {
            std::cout << "bot error [" << g_stage << "]: " << error.what() << std::endl;
        } catch (...) {
            std::cout << "bot error [" << g_stage << "]: unknown exception" << std::endl;
        }

        cambc::end_turn();
    }
}
