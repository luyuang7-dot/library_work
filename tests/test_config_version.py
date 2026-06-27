import config as app_config


def test_default_app_version_prefers_version_file(monkeypatch, tmp_path):
    (tmp_path / "VERSION").write_text("9.9.9\n", encoding="utf-8")
    monkeypatch.setattr(app_config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("APP_VERSION", "1.2.3")

    assert app_config._default_app_version() == "9.9.9"


def test_default_app_version_falls_back_to_env(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("APP_VERSION", "1.2.3")

    assert app_config._default_app_version() == "1.2.3"
