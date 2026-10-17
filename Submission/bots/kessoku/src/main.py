"""Entry point: run our own turn loop, dispatching draft vs gameplay.

The engine resumes us at cambc.end_turn(); state persists in the Bot object
across turns. A failed turn is logged and still yields so we never stall.
"""
import cambc

import draftbrain
from brain import Bot


def main():
    bot = Bot()
    while True:
        try:
            if cambc.is_draft():
                draftbrain.play()
            else:
                bot.play_turn()
        except Exception as error:
            print(f"bot error: {error}", flush=True)
        cambc.end_turn()


if __name__ == "__main__":
    main()
