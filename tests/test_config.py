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
