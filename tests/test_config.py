from wabot.config import OUTPUT_RULES, Settings


def make(tmp_path, **kw):
    return Settings(_env_file=None, gemini_api_key="k", persona_file=tmp_path / "p.md", **kw)


def test_file_beats_env_and_name_replaced(tmp_path):
    (tmp_path / "p.md").write_text("# I am {name} {braces}")
    s = make(tmp_path, persona_name="Ann", persona_prompt="ignored")
    assert s.system_instruction().startswith("# I am Ann {braces}")
    assert s.system_instruction().endswith(OUTPUT_RULES.strip())


def test_env_prompt_fallback(tmp_path):
    assert (
        "Zed" in make(tmp_path, persona_name="Zed", persona_prompt="Be {name}").system_instruction()
    )


def test_allowlist_property(tmp_path):
    assert make(tmp_path, allowed_chats="a, b").allowlist == ("a", "b")


def test_quiet_hours_setting(tmp_path):
    assert make(tmp_path).quiet is None
    assert make(tmp_path, quiet_hours="23:00-07:00").quiet is not None


def test_afk_defaults(tmp_path):
    s = make(tmp_path)
    assert (s.afk_chance, s.afk_min_minutes, s.afk_max_minutes) == (0.1, 3.0, 20.0)


def test_afk_ack_and_backlog_defaults(tmp_path):
    s = make(tmp_path)
    assert (s.afk_acknowledge, s.afk_ack_min_minutes, s.skip_backlog) == (False, 5.0, True)


def test_list_mode_defaults(tmp_path):
    s = make(tmp_path)
    assert (s.watch_mode, s.headless, s.reply_gap_min, s.reply_gap_max) == (
        "list",
        False,
        15.0,
        45.0,
    )


def test_typing_defaults(tmp_path):
    s = make(tmp_path)
    assert (s.typing_char_delay_ms, s.typing_jitter, s.max_typing_seconds) == (200.0, 0.4, 30.0)
    assert (s.reply_delay_min, s.reply_delay_max) == (4.0, 12.0)
    assert (s.read_seconds_per_word, s.log_messages) == (0.25, True)
