import logging
import random

import pytest
from playwright._impl._errors import TargetClosedError
from playwright.sync_api import Error as PlaywrightError
from test_bot import FakeClient, FakeGen, inc, make

import wabot.__main__ as cli
from wabot.config import Settings
from wabot.lifecycle import (
    QuietShutdownNoise,
    browser_gone,
    format_duration,
    short_error,
    summary_line,
)
from wabot.models import Message
from wabot.whatsapp.client import WhatsAppClient

DRIVER_GONE = "Connection closed while reading from the driver"


# ---------------- telling a closed browser from a bug


@pytest.mark.parametrize(
    "exc",
    [
        TargetClosedError(),
        Exception(DRIVER_GONE),
        PlaywrightError("Target page, context or browser has been closed"),
        PlaywrightError("Page.goto: Target closed"),
        PlaywrightError("Browser closed unexpectedly"),
    ],
)
def test_closed_browser_is_recognised(exc):
    assert browser_gone(exc)


@pytest.mark.parametrize(
    "exc",
    [ValueError("boom"), KeyError("x"), PlaywrightError("Timeout 30000ms exceeded"), Exception()],
)
def test_real_bugs_are_not_mistaken_for_a_closed_browser(exc):
    assert not browser_gone(exc)


def test_short_error_is_one_readable_line():
    assert short_error(ValueError("boom\nsecond line")) == "ValueError: boom"
    assert short_error(KeyError()) == "KeyError"
    assert len(short_error(ValueError("x" * 500))) == 200


def test_durations_read_naturally():
    assert [format_duration(s) for s in (5, 59, 60, 125, 3600, 4320, 7200)] == [
        "5 s",
        "59 s",
        "1 min",
        "2 min",
        "1 h",
        "1 h 12 min",
        "2 h",
    ]


def test_summary_lines():
    assert (
        summary_line(3, 5, 4320)
        == "Session summary: replied to 3 chats (5 messages), ran 1 h 12 min."
    )
    assert summary_line(1, 1, 30) == "Session summary: replied to 1 chat (1 message), ran 30 s."
    assert summary_line(0, 0, 90) == "Session summary: no replies sent, ran 1 min."
    assert summary_line(2, 4, 90, dry_run=True) == (
        "Session summary: dry run, nothing was sent, ran 1 min."
    )


# ---------------- cleanup never raises


class Broken:
    def __init__(self, error):
        self.error = error

    def close(self):
        raise self.error

    stop = close


def test_exit_survives_a_dead_driver_and_hides_nothing_else():
    client = WhatsAppClient.__new__(WhatsAppClient)
    client._ctx = Broken(Exception(DRIVER_GONE))
    client._pw = Broken(Exception(DRIVER_GONE))
    assert client.__exit__(None, None, None) is None  # no traceback from cleanup


def test_exit_still_stops_the_driver_when_closing_the_browser_fails():
    stopped = []
    client = WhatsAppClient.__new__(WhatsAppClient)
    client._ctx = Broken(Exception(DRIVER_GONE))
    client._pw = type("P", (), {"stop": lambda self: stopped.append(True)})()
    client.__exit__(None, None, None)
    assert stopped == [True]


# ---------------- main(): friendly endings


class FakeBrowser:
    """Stands in for WhatsAppClient inside main()."""

    wait_error: BaseException | None = None
    login_error: BaseException | None = None

    def __init__(self, *a, **k):
        self.own_names = set()
        self.on_own_name = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return None

    def wait_logged_in(self):
        if self.wait_error:
            raise self.wait_error

    def login(self):
        if self.login_error:
            raise self.login_error


@pytest.fixture
def run(monkeypatch, tmp_path, caplog):
    """Run main() with a fake browser. Returns (exit code, log records)."""

    def go(argv, *, wait_error=None, login_error=None, bot_error=None):
        FakeBrowser.wait_error, FakeBrowser.login_error = wait_error, login_error
        monkeypatch.setattr(cli, "WhatsAppClient", FakeBrowser)
        monkeypatch.setattr(
            cli,
            "Settings",
            lambda: Settings(
                _env_file=None,
                gemini_api_key="k",
                profile_dir=tmp_path / "profile",
                db_path=tmp_path / "bot.db",
                persona_file=tmp_path / "p.md",
            ),
        )
        if bot_error:

            def boom(*a, **k):
                raise bot_error

            monkeypatch.setattr(cli, "_run_bot", boom)
        with caplog.at_level(logging.DEBUG):
            code = cli.main(argv)
        return code, caplog.records

    return go


def messages(records, level=None):
    return [r.getMessage() for r in records if level is None or r.levelno == level]


def test_ctrl_c_says_goodbye_without_a_traceback(run):
    code, records = run([], bot_error=KeyboardInterrupt())
    assert code == 0
    assert "Stopped. Bye." in messages(records)
    assert not any(r.exc_info for r in records)


def test_closed_window_is_explained_and_is_not_an_error(run):
    code, records = run([], bot_error=Exception(DRIVER_GONE))
    assert code == 0
    assert any("browser window was closed" in m for m in messages(records, logging.WARNING))
    assert not any(r.exc_info for r in records)
    assert not any("Traceback" in m for m in messages(records))


def test_closed_window_during_login_asks_to_run_login_again(run):
    code, records = run(["--login"], login_error=TargetClosedError())
    assert code == 1
    assert "closed before login finished" in " ".join(messages(records, logging.ERROR))


def test_ctrl_c_during_login_is_friendly_too(run):
    code, records = run(["--login"], login_error=KeyboardInterrupt())
    assert code == 0 and "Stopped. Bye." in messages(records)


def test_closed_window_while_waiting_for_whatsapp(run):
    code, records = run(
        [], wait_error=PlaywrightError("Target page, context or browser has been closed")
    )
    assert code == 0
    assert any("browser window was closed" in m for m in messages(records))


def test_unexpected_error_is_one_line_and_points_to_verbose(run):
    code, records = run([], bot_error=ValueError("boom"))
    assert code == 1
    errors = messages(records, logging.ERROR)
    assert errors == [
        "Something went wrong: ValueError: boom. Run again with --verbose to see the details."
    ]
    assert not any(r.exc_info for r in records)


def test_verbose_adds_the_full_traceback(run):
    code, records = run(["--verbose"], bot_error=ValueError("boom"))
    assert code == 1
    assert any(r.exc_info and r.exc_info[0] is ValueError for r in records)


def test_expired_session_message_is_unchanged(run):
    from wabot.whatsapp.client import SessionExpiredError

    code, records = run([], wait_error=SessionExpiredError("session expired, run --login"))
    assert code == 1
    assert "session expired, run --login" in messages(records, logging.ERROR)


# ---------------- the bot's own goodbye


def test_bot_counts_what_it_sent():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    bot = make(c, g)
    bot.step()
    assert (bot.replied_chats, bot.messages_sent) == ({"Budi"}, 1)


def test_bot_counts_every_part_of_a_multi_message_reply():
    c, g = FakeClient(msgs=[inc(1)]), FakeGen()
    g.reply = "satu\n---\ndua\n---\ntiga"
    bot = make(c, g, tags={"Budi": "lover"}, rng=random.Random(2), sleep=lambda _: None)
    bot.step()
    assert (bot.replied_chats, bot.messages_sent) == ({"Budi"}, 3)


def test_dry_run_counts_nothing():
    c, g = FakeClient(msgs=[Message("id1", "Budi", "halo", "ts", False)]), FakeGen()
    bot = make(c, g, dry_run=True)
    bot.step()
    assert bot.messages_sent == 0 and not bot.replied_chats


def test_run_bot_prints_the_summary_when_stopped_with_ctrl_c(monkeypatch, tmp_path, caplog):
    class Quiet(FakeBrowser):
        def chat_rows(self):
            return []

    settings = Settings(
        _env_file=None,
        gemini_api_key="k",
        db_path=tmp_path / "bot.db",
        persona_file=tmp_path / "p.md",
        allowed_chats="Budi",
    )
    args = cli._parser().parse_args([])

    def stop(_seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.time, "sleep", stop)
    with caplog.at_level(logging.INFO), pytest.raises(KeyboardInterrupt):
        cli._run_bot(Quiet(), settings, args)
    assert "Session summary: no replies sent, ran 0 s." in messages(caplog.records)


# ---------------- asyncio noise after a dead browser pipe


def asyncio_record(error, message="Future exception was never retrieved"):
    return logging.LogRecord(
        "asyncio", logging.ERROR, __file__, 1, message, None, (type(error), error, None)
    )


@pytest.mark.parametrize(
    "error", [BrokenPipeError(32, "Broken pipe"), ConnectionResetError(), EOFError()]
)
def test_dead_pipe_noise_is_hidden(error):
    assert QuietShutdownNoise().filter(asyncio_record(error)) is False


def test_other_asyncio_errors_still_show():
    noise = QuietShutdownNoise()
    assert noise.filter(asyncio_record(ValueError("real problem"))) is True
    assert noise.filter(asyncio_record(BrokenPipeError(), message="Task was destroyed")) is True


def test_main_installs_the_filter_unless_verbose(run):
    asyncio_logger = logging.getLogger("asyncio")
    asyncio_logger.filters.clear()
    run([], bot_error=KeyboardInterrupt())
    assert any(isinstance(f, QuietShutdownNoise) for f in asyncio_logger.filters)
    asyncio_logger.filters.clear()
    run(["--verbose"], bot_error=KeyboardInterrupt())
    assert not any(isinstance(f, QuietShutdownNoise) for f in asyncio_logger.filters)
