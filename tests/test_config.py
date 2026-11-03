from aggregator.config import Settings


def test_csv_lists_are_parsed(monkeypatch):
    monkeypatch.setenv("ALLOWED_USER_IDS", "1, 2,3")
    monkeypatch.setenv("TELEGRAM_GROUPS", "a, https://t.me/b")
    s = Settings(_env_file=None)
    assert s.allowed_user_ids == [1, 2, 3]
    assert s.telegram_groups == ["a", "https://t.me/b"]
    assert s.is_private_mode


def test_defaults_are_public_and_sane(monkeypatch):
    for var in ("ALLOWED_USER_IDS", "TELEGRAM_GROUPS", "ENABLED_SOURCES"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert not s.is_private_mode
    assert s.enabled_sources == ["bazaraki", "telegram"]
    assert s.best_deal_ratio == 0.75
    assert s.listing_max_age_days == 30
    assert s.anthropic_model  # configurable, never empty
