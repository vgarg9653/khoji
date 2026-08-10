#!/usr/bin/env python3
"""Local WhatsApp simulator — talk to the bot in your terminal.

No Twilio account, no Meta app, no webhook, no ngrok. This exercises exactly the
same engine the real webhook calls, so what you see here is what a student sees.

    python bot/simulate.py                 # interactive
    python bot/simulate.py --script demo   # scripted run, good for screenshots
"""

from __future__ import annotations

import argparse
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import load_env   # noqa: E402
load_env()

from engine import Bot                      # noqa: E402
from matching import Matcher                # noqa: E402

DEFAULT_DATA = HERE.parent / "deliverables" / "dataset" / "bot_matching.json"

# A realistic path through the flow: an ST student in Assam, class 10, low income.
DEMO_SCRIPT = ["hi", "Assam", "1", "10", "2", "1.5 lakh", "1"]

GREEN, DIM, BOLD, RESET = "\033[92m", "\033[2m", "\033[1m", "\033[0m"


def render(msg: str) -> str:
    """Approximate WhatsApp formatting in a terminal."""
    out = []
    for line in msg.split("\n"):
        out.append("   " + line)
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA),
                    help="path to bot_matching.json")
    ap.add_argument("--script", choices=["demo"], help="run a scripted conversation")
    ap.add_argument("--phone", default="+919999900000")
    args = ap.parse_args()

    path = pathlib.Path(args.data)
    if not path.exists():
        sys.exit(f"Dataset not found: {path}\n"
                 f"Run `python pipeline.py export && python src/make_deliverables.py` first.")

    matcher = Matcher.from_file(path)
    bot = Bot(matcher)

    st = matcher.stats()
    print(f"\n{BOLD}Khoji.AI — local simulator{RESET}")
    print(f"{DIM}{st['records']} scholarships | {st['verified']} verified | "
          f"{st['with_income_ceiling']} with income limits | "
          f"{st['with_deadline']} with deadlines{RESET}")
    print(f"{DIM}Type a message and press Enter. Ctrl-C or 'quit' to exit.{RESET}\n")

    if args.script:
        for msg in DEMO_SCRIPT:
            print(f"{GREEN}You ▸{RESET} {msg}")
            for reply in bot.handle(args.phone, msg):
                print(f"{BOLD}Bot ▾{RESET}\n{render(reply)}\n")
        return

    while True:
        try:
            msg = input(f"{GREEN}You ▸{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye 👋")
            return
        if msg.lower() in ("quit", "exit"):
            print("Bye 👋")
            return
        if not msg:
            continue
        for reply in bot.handle(args.phone, msg):
            print(f"{BOLD}Bot ▾{RESET}\n{render(reply)}\n")


if __name__ == "__main__":
    main()
