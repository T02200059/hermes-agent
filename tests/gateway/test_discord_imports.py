"""Import-safety tests for the Discord gateway adapter."""

import builtins
import importlib
import sys


class TestDiscordImportSafety:
    def test_module_imports_even_when_discord_dependency_is_missing(self, monkeypatch):
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "discord" or name.startswith("discord."):
                raise ImportError("discord unavailable for test")
            return original_import(name, globals, locals, fromlist, level)

        # Purge the cached module so the import below actually re-runs the
        # module body with discord.py simulated-missing.
        monkeypatch.delitem(sys.modules, "plugins.platforms.discord.adapter", raising=False)
        monkeypatch.delitem(sys.modules, "plugins.platforms.discord", raising=False)
        monkeypatch.setattr(builtins, "__import__", fake_import)

        module = importlib.import_module("plugins.platforms.discord.adapter")

        assert module.DISCORD_AVAILABLE is False
        assert module.discord is None

    def test_module_state_restored_after_import_safety_run(self, monkeypatch):
        """[owner] A4-2 isolation guard: the import-safety test above re-imports the adapter
        with discord.py simulated-missing and leaves the module state reset (DISCORD_AVAILABLE
        False, fresh class object). Downstream tests in the same session monkeypatch the
        cached class — restore the real import state so the reset never leaks."""
        import builtins as _b
        import importlib as _il
        import sys as _s

        original_import = _b.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "discord" or name.startswith("discord."):
                raise ImportError("discord unavailable for test")
            return original_import(name, globals, locals, fromlist, level)

        _s.modules.pop("plugins.platforms.discord.adapter", None)
        _s.modules.pop("plugins.platforms.discord.adapter_media", None)
        _s.modules.pop("plugins.platforms.discord", None)
        _b.__import__ = fake_import
        try:
            _il.import_module("plugins.platforms.discord.adapter")
        finally:
            _b.__import__ = original_import
            # Real re-import with the genuine discord import path available again.
            _s.modules.pop("plugins.platforms.discord.adapter", None)
            _s.modules.pop("plugins.platforms.discord.adapter_media", None)
            _s.modules.pop("plugins.platforms.discord", None)
            _il.import_module("plugins.platforms.discord.adapter")
        module = _s.modules["plugins.platforms.discord.adapter"]
        assert module.DISCORD_AVAILABLE is True
