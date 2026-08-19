"""P2-9: provider-model cache busts on credential / model-config writes."""

from __future__ import annotations


def test_set_model_provider_clears_that_provider_cache(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  default: x\n  provider: openai\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("hermes_cli.config.is_managed", lambda: False)

    cleared = []
    monkeypatch.setattr(
        "hermes_cli.models.clear_provider_models_cache",
        lambda provider=None: cleared.append(provider),
    )
    from hermes_cli.config import set_config_value

    set_config_value("model.provider", "anthropic")
    assert "anthropic" in cleared


def test_set_unrelated_config_does_not_clear_model_cache(tmp_path, monkeypatch):
    home = tmp_path / ".hermes"
    home.mkdir()
    (home / "config.yaml").write_text("display:\n  skin: default\n")
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setattr("hermes_cli.config.is_managed", lambda: False)

    cleared = []
    monkeypatch.setattr(
        "hermes_cli.models.clear_provider_models_cache",
        lambda provider=None: cleared.append(provider),
    )
    from hermes_cli.config import set_config_value

    set_config_value("display.skin", "default")
    assert cleared == []
