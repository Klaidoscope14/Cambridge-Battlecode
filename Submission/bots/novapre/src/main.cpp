// nova entry point: draft, then one gameplay turn per round; a failed turn is logged and still yields.
#include <cambc.h>
#include <iostream>
#include "bot.h"
#include "config.h"
#include "draft.h"

int main() {
    Bot bot;
    while (true) {
        try {
            if (cambc::is_draft())
                play_draft();
            else
                bot.play_turn();
        } catch (const std::exception& error) {
            std::cout << "nova error [" << g_stage << "]: " << error.what() << std::endl;
        } catch (...) {
            std::cout << "nova error [" << g_stage << "]: unknown exception" << std::endl;
        }
        cambc::end_turn();
    }
}
