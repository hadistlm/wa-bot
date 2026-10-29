from __future__ import annotations

import argparse
import logging
import time

from playwright.sync_api import Error as PlaywrightError

from wabot.bot import Bot
from wabot.config import Settings
from wabot.llm import FatalReplyError, GeminiReplyGenerator
from wabot.store import Store
from wabot.whatsapp.client import SessionExpiredError, WhatsAppClient

log = logging.getLogger("wabot")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="wabot", description="WhatsApp auto-reply bot")
    parser.add_argument("--login", action="store_true", help="scan the QR code, then exit")
    parser.add_argument("--dry-run", action="store_true", help="print replies, send nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = Settings()  # type: ignore[call-arg]
    headless = settings.headless and not args.login
    with WhatsAppClient(settings.profile_dir, settings.browser_channel, headless) as client:
        if args.login:
            log.info("Scan the QR code: WhatsApp > Settings > Linked Devices")
            client.login()
            log.info("Logged in. Session saved in %s", settings.profile_dir)
            return 0
        try:
            client.wait_logged_in()
        except SessionExpiredError as exc:
            log.error("%s", exc)
            return 1
        generator = GeminiReplyGenerator(
            settings.gemini_api_key.get_secret_value(),
            settings.gemini_model,
            settings.system_instruction(),
            settings.gemini_temperature,
            settings.gemini_max_output_tokens,
        )
        with Store(settings.db_path) as store:
            bot = Bot(
                client,
                generator,
                store,
                settings.allowlist,
                tags=settings.chat_tags,
                allow_groups=settings.allow_groups,
                threshold=settings.match_threshold,
                context_messages=settings.context_messages,
                dry_run=args.dry_run,
                skip_trivial=settings.skip_trivial,
                debounce=settings.debounce,
                max_replies_per_hour=settings.max_replies_per_hour,
                quiet=settings.quiet,
                afk_acknowledge=settings.afk_acknowledge,
                afk_ack_min_minutes=settings.afk_ack_min_minutes,
                skip_backlog=settings.skip_backlog,
                watch_mode=settings.watch_mode,
                open_delay=(settings.open_delay_min, settings.open_delay_max),
                reply_gap=(settings.reply_gap_min, settings.reply_gap_max),
                afk_chance=settings.afk_chance,
                afk_minutes=(settings.afk_min_minutes, settings.afk_max_minutes),
                char_delay_ms=settings.typing_char_delay_ms,
                max_typing_seconds=settings.max_typing_seconds,
                delay=(settings.reply_delay_min, settings.reply_delay_max),
            )
            log.info("running%s. Ctrl+C to stop", " (dry run)" if args.dry_run else "")
            try:
                while True:
                    try:
                        reply = bot.step()
                    except FatalReplyError as exc:
                        log.error("fatal: %s", exc)
                        return 1
                    except PlaywrightError as exc:
                        log.error("browser problem (was the window closed?): %s", exc)
                        return 1
                    if reply and args.dry_run:
                        print(f"[dry-run] {reply}")
                    time.sleep(settings.poll_interval)
            except KeyboardInterrupt:
                log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
