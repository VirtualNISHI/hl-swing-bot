"""CLI helper to test the Discord webhook from .env."""
from __future__ import annotations

import argparse
import logging
import sys

from .config import load_settings
from .discord_client import DiscordClient


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a test message to Discord")
    parser.add_argument("message", nargs="?", default="hl-swing-bot: webhook OK ✅")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    for noisy in ("httpx", "httpcore", "httpcore.http11", "httpcore.connection"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    settings = load_settings()
    if not settings.discord_webhook_url:
        print("DISCORD_WEBHOOK_URL is empty. Set it in .env first.", file=sys.stderr)
        sys.exit(1)

    with DiscordClient(settings.discord_webhook_url) as d:
        d.send(content=args.message)
    print("sent.")


if __name__ == "__main__":
    main()
