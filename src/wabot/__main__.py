from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError

from wabot.bot import Bot
from wabot.config import Settings
from wabot.llm import FatalReplyError, GeminiReplyGenerator
from wabot.store import Store
from wabot.whatsapp.client import SessionExpiredError, WhatsAppClient
from wabot.whatsapp.dump import dump_dom
from wabot.whatsapp.selftest import (
    format_report,
    passed,
    resolve_chat,
    run_selftest,
    send_test,
)

log = logging.getLogger("wabot")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wabot", description="WhatsApp auto-reply bot")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--login", action="store_true", help="scan the QR code, then exit")
    mode.add_argument(
        "--selftest", action="store_true", help="check every selector on the live page, read-only"
    )
    mode.add_argument(
        "--list-chats", action="store_true", help="print the chats shown in the list, then exit"
    )
    mode.add_argument(
        "--dump-dom", action="store_true", help="save a redacted copy of the page structure"
    )
    mode.add_argument(
        "--send-test",
        metavar="TITLE",
        help="send ONE short test message to this chat, then check it appears",
    )
    parser.add_argument("--chat", metavar="TITLE", help="chat to open for --selftest/--dump-dom")
    parser.add_argument(
        "--chat-index",
        type=int,
        metavar="N",
        help="open the Nth chat in the list instead (1 = top)",
    )
    parser.add_argument("--out", default="data/dom", help="folder for dumps (default data/dom)")
    parser.add_argument("--dry-run", action="store_true", help="print replies, send nothing")
    return parser


def _diagnose(client: WhatsAppClient, args: argparse.Namespace) -> int:
    out = Path(args.out)
    if args.list_chats:
        for number, row in enumerate(client.chat_rows(), start=1):
            print(f"{number:>3}. {row.title}" + (f"  [unread {row.unread}]" if row.unread else ""))
        return 0
    if args.dump_dom:
        wanted = bool(args.chat or args.chat_index)
        title = resolve_chat(client, args.chat, args.chat_index) if wanted else None
        if wanted and (title is None or not client.open_chat(title)):
            log.error("could not open the chat: %s", client.open_error or "not in the list")
            return 1
        paths = dump_dom(client, out, with_chat=wanted)
        if wanted:
            client.close_chat()
        for path in paths:
            print(path)
        return 0 if paths else 1
    if args.send_test:
        log.warning("sending ONE test message to the chat you named")
        checks = send_test(client, args.send_test)
    else:
        name = args.chat
        if args.chat_index:
            name = resolve_chat(client, None, args.chat_index)
            if name is None:
                print("FAIL  --chat-index is outside the list")
                return 1
        checks = run_selftest(client, name, out)
    print(format_report(checks))
    return 0 if passed(checks) else 1


def _remember_own_names(client: WhatsAppClient, store: Store) -> None:
    """Keep the names WhatsApp shows on your own messages, so a restart still knows them."""
    client.own_names.update(json.loads(store.get_state("own_names") or "[]"))

    def save(_: str) -> None:
        store.set_state("own_names", json.dumps(sorted(client.own_names)))

    client.on_own_name = save


def _run_bot(client: WhatsAppClient, settings: Settings, args: argparse.Namespace) -> int:
    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        log.error("GEMINI_API_KEY is empty: set it in .env.local")
        return 1
    generator = GeminiReplyGenerator(
        api_key,
        settings.gemini_model,
        settings.system_instruction(),
        settings.gemini_temperature,
        settings.gemini_max_output_tokens,
    )
    with Store(settings.db_path) as store:
        _remember_own_names(client, store)
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
            delay=(settings.reply_delay_min, settings.reply_delay_max),
            char_delay_ms=settings.typing_char_delay_ms,
            max_typing_seconds=settings.max_typing_seconds,
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


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    settings = Settings()  # type: ignore[call-arg]
    diagnostic = args.selftest or args.dump_dom or args.list_chats or bool(args.send_test)
    headless = settings.headless and not (args.login or diagnostic)
    settings.profile_dir.mkdir(parents=True, exist_ok=True)
    own_names = [n.strip() for n in settings.own_names.split(",") if n.strip()]
    with WhatsAppClient(
        settings.profile_dir, settings.browser_channel, headless, own_names
    ) as client:
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
        try:
            if diagnostic:
                return _diagnose(client, args)
            return _run_bot(client, settings, args)
        except PlaywrightError as exc:
            log.error("browser problem: %s", exc)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
