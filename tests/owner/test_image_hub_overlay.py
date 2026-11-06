# [owner] Image Hub migration: overlay, aliases, real dispatch, and local I/O.
from __future__ import annotations

import base64
import io
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from ruamel.yaml import YAML

from owner import image_hub
from owner.image_hub.schema import dispatch_model
import tools.image_generation_tool as image_tool


@pytest.fixture()
def overlay_home(tmp_path, monkeypatch):
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(home))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "unit-test-placeholder")
    from owner.patch_config import invalidate_owner_config_cache
    invalidate_owner_config_cache()
    yield home
    invalidate_owner_config_cache()


_YAML = YAML(typ="safe")


def _yaml_text(raw):
    buffer = io.StringIO()
    _YAML.dump(raw, buffer)
    return buffer.getvalue()


def write_overlay(home, raw):
    (home / "overlay.yaml").write_text(_yaml_text(raw), encoding="utf-8")
    from owner.patch_config import invalidate_owner_config_cache
    invalidate_owner_config_cache()


def test_overlay_ignores_legacy_file_and_all_five_preset_aliases(overlay_home, monkeypatch, capsys):
    source = YAML(typ="safe").load(Path("owner/config/overlay.yaml").read_text())["image_gen"]
    write_overlay(overlay_home, {"image_gen": source})
    (overlay_home / "patch.yaml").write_text("image_gen:\n  current: wrong\n")
    (overlay_home / "config.yaml").write_text("image_gen:\n  provider: image-hub\n")
    if image_hub._resolve_active_preset() is None:
        raise AssertionError("No overlay preset: " + repr(image_hub._read_overlay_image_gen()))
    assert image_hub._resolve_active_preset()["model"] == source["presets"][source["current"]]["model"]
    for name, preset in source["presets"].items():
        alias = preset["alias"][0]
        assert image_hub._match_preset_by_alias(alias)["model"] == preset["model"]
        assert image_hub._match_preset_by_alias(name)["model"] == preset["model"]
    assert "unit-test-placeholder" not in capsys.readouterr().err
    calls = {}
    with patch.object(image_hub.ImageHubProvider, "_generate_dashscope", side_effect=lambda **kw: calls.setdefault("call", kw)):
        image_hub.ImageHubProvider().generate("draw", model="qwen")
    assert calls["call"]["model_id"] == source["presets"]["dashscope-qwen"]["model"]


@pytest.mark.parametrize("raw", [None, "not-an-overlay: ["])
def test_missing_or_invalid_overlay_fails_open_without_legacy_fallback(overlay_home, raw):
    if raw is not None:
        (overlay_home / "overlay.yaml").write_text(raw)
    (overlay_home / "patch.yaml").write_text("image_gen:\n  current: legacy-secret-selection\n")
    assert image_hub._read_overlay_image_gen() == {}
    assert image_hub._resolve_active_preset() is None


def test_provider_declared_model_survives_dynamic_schema_and_dispatch(overlay_home):
    captured = {}
    provider = SimpleNamespace(
        name="image-hub", display_name="Image Hub",
        capabilities=lambda: {"modalities": ["text", "image"], "max_reference_images": 3},
        tool_parameter_overrides=image_hub.ImageHubProvider().tool_parameter_overrides,
        default_model=lambda: "configured-default",
        generate=lambda **kwargs: captured.update(kwargs) or {"success": True},
    )
    with patch.object(image_tool, "_read_configured_image_provider", return_value="image-hub"), \
         patch.object(image_tool, "_get_plugin_provider", return_value=provider), \
         patch.object(image_tool, "_read_configured_image_model", return_value="configured-model"):
        properties = image_tool._build_dynamic_image_schema()["parameters"]["properties"]
        assert properties["model"]["type"] == "string"
        image_tool._handle_image_generate({"prompt": "draw", "model": "qwen-pro"})
    assert captured["model"] == "qwen-pro"


def test_unrelated_text_provider_gets_no_model_surface(overlay_home):
    provider = SimpleNamespace(
        name="fal", display_name="FAL", capabilities=lambda: {"modalities": ["text"]},
        default_model=lambda: "fal-default",
    )
    with patch.object(image_tool, "_read_configured_image_provider", return_value="fal"), \
         patch.object(image_tool, "_get_plugin_provider", return_value=provider):
        assert "model" not in image_tool._build_dynamic_image_schema()["parameters"]["properties"]
    assert dispatch_model(provider, "should-not-reach", "configured") == "configured"


def test_i2i_local_image_safety_data_uri_and_dashscope_payload(overlay_home, tmp_path):
    source = YAML(typ="safe").load(Path("owner/config/overlay.yaml").read_text())["image_gen"]
    write_overlay(overlay_home, {"image_gen": source})
    overlay_home.joinpath("config.yaml").write_text("image_gen:\n  provider: image-hub\n")
    local = tmp_path / "source.png"
    local.write_bytes(b"mock-image")
    response = Mock()
    response.json.return_value = {"output": {"choices": [{"message": {"content": [{"image": "https://cdn.test/mock.png"}]}}]}}
    with patch.object(image_hub.requests, "post", return_value=response) as post, \
         patch.object(image_hub, "save_url_image", return_value=overlay_home / "generated.png"):
        result = image_hub.ImageHubProvider().generate(
            "make a poster", image_url=str(local), reference_image_urls=["b", "c", "d", "e"], model="image-edit")
    if not result.get("success"):
        raise AssertionError(result)
    payload = post.call_args.kwargs["json"]
    assert result["success"] and result["model"] == source["presets"]["dashscope-image-edit"]["model"]
    assert payload["model"] == result["model"]
    assert len(payload["input"]["messages"][0]["content"]) == 4
    assert payload["input"]["messages"][0]["content"][0]["image"] == "data:image/png;base64," + base64.b64encode(b"mock-image").decode()
    with patch("agent.file_safety.raise_if_read_blocked", side_effect=ValueError("blocked by policy")):
        with pytest.raises(ValueError, match="blocked by policy"):
            image_hub._maybe_local_to_data_uri(str(local))


def test_real_openai_b64_cache_and_registration_probe(overlay_home):
    source = YAML(typ="safe").load(Path("owner/config/overlay.yaml").read_text())["image_gen"]
    write_overlay(overlay_home, {"image_gen": source})
    response = Mock()
    response.json.return_value = {"data": [{"b64_json": base64.b64encode(b"mock-image").decode()}]}
    with patch.object(image_hub.requests, "post", return_value=response):
        result = image_hub.ImageHubProvider()._generate_openai(
            prompt="draw", model_id="unit-test/model", endpoint="https://example.test",
            api_key="unit-test-placeholder", size_raw="1024x1024", aspect="square")
    saved = Path(result["image"])
    assert saved.read_bytes() == b"mock-image"
    assert saved.is_relative_to(overlay_home / "cache" / "generated" / "images")

    context = SimpleNamespace(register_image_gen_provider=Mock())
    image_hub.register(context)
    context.register_image_gen_provider.assert_called_once()
    registered = context.register_image_gen_provider.call_args.args[0]
    assert isinstance(registered, image_hub.ImageHubProvider)
    assert registered.name == "image-hub"


def test_real_plugin_discovery_and_disable_gate(overlay_home):
    import agent.image_gen_registry as registry
    from hermes_cli.plugins import PluginManager
    from hermes_cli.plugins_discovery import scan_directory
    from hermes_cli.plugins_manifest import manifest_key

    source = YAML(typ="safe").load(Path("owner/config/overlay.yaml").read_text())["image_gen"]
    write_overlay(overlay_home, {"image_gen": source})
    manifests = scan_directory(Path("owner"), "user")
    provider_manifest = next(m for m in manifests if manifest_key(m) == "image-hub")
    manager = PluginManager(scope_key=overlay_home)
    manager._load_plugin(provider_manifest)
    registered = registry.get_provider("image-hub")
    assert registered is not None
    assert registered.display_name.endswith("(" + source["current"] + ")")
    assert {row["id"] for row in registered.list_models()} == {
        preset["model"] for preset in source["presets"].values()}

    with patch.object(image_tool, "_read_configured_image_provider", return_value="image-hub"), \
         patch.object(image_tool, "_get_plugin_provider", return_value=registered):
        schema = image_tool._build_dynamic_image_schema()
    assert "model" in schema["parameters"]["properties"]
    for preset in source["presets"].values():
        assert preset["alias"][0] in schema["parameters"]["properties"]["model"]["description"]

    # The real loader accepts the owner package linked as a user backend.
    plugins = overlay_home / "plugins"
    plugins.mkdir(parents=True, exist_ok=True)
    for name in ("fal", "openai"):
        (plugins / name).symlink_to((Path.cwd() / "plugins/image_gen" / name).resolve(), target_is_directory=True)
    (plugins / "image-hub").symlink_to((Path.cwd() / "owner/image_hub").resolve(), target_is_directory=True)
    (plugins / "owner-extensions").symlink_to((Path.cwd() / "owner/owner-extensions").resolve(), target_is_directory=True)
    manifests = scan_directory(plugins, "user")
    enabled = {manifest_key(manifest) for manifest in manifests}
    manager = PluginManager(scope_key=overlay_home)
    verdicts = {manifest_key(manifest): manager._gate_manifest(manifest, {"image-hub"}, enabled)
                for manifest in manifests}
    assert verdicts["image-hub"] is False
    assert manager._plugins["image-hub"].enabled is False
    assert registry.get_provider("image-hub") is registered


def test_full_plugin_discovery_registers_provider_without_unrelated_old_plugins(overlay_home):
    from hermes_cli import plugins as loader
    from agent import image_gen_registry as registry

    plugins = overlay_home / "plugins"
    plugins.mkdir()
    (plugins / "image-hub").symlink_to((Path.cwd() / "owner/image_hub").resolve(), target_is_directory=True)
    (plugins / "owner-extensions").symlink_to((Path.cwd() / "owner/owner-extensions").resolve(), target_is_directory=True)
    (overlay_home / "config.yaml").write_text(
        "image_gen:\n  provider: image-hub\nplugins:\n  enabled: [image-hub, owner-extensions]\n")
    manager = loader.PluginManager(scope_key=overlay_home)
    manager.discover_and_load()
    with patch.object(loader, "get_plugin_manager", return_value=manager):
        provider = image_tool._get_plugin_provider("image-hub")
    assert provider is not None
    assert provider.name == "image-hub"
    assert manager._plugins["image-hub"].enabled is True


def test_owner_extensions_import_succeeds_without_image_backend(overlay_home):
    import builtins
    import importlib.util
    import sys

    loader = Path("owner/owner-extensions/__init__.py")
    spec = importlib.util.spec_from_file_location("owner_only_hooks", loader)
    module = importlib.util.module_from_spec(spec)
    original_import = builtins.__import__
    def no_image_hub(name, *args, **kwargs):
        if name.startswith("owner.image_hub"):
            raise AssertionError("unrelated owner hooks must not import image_hub")
        return original_import(name, *args, **kwargs)
    with patch.dict(sys.modules, {"owner_only_hooks": module}), \
         patch("builtins.__import__", side_effect=no_image_hub):
        spec.loader.exec_module(module)
    assert hasattr(module, "register")
