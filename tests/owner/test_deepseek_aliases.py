"""Owner DeepSeek native alias: deepseek-v4-flash → deepseek-flash."""

from __future__ import annotations


def test_extra_alias_map_points_v4_flash_at_canonical_flash():
    from owner.providers.deepseek_aliases import EXTRA_DEEPSEEK_RETIRED_ALIASES

    assert EXTRA_DEEPSEEK_RETIRED_ALIASES["deepseek-v4-flash"] == "deepseek-flash"


def test_apply_merges_into_caller_map():
    from owner.providers.deepseek_aliases import apply_deepseek_retired_aliases

    m = {"deepseek-chat": "deepseek-flash"}
    apply_deepseek_retired_aliases(m)
    assert m["deepseek-chat"] == "deepseek-flash"
    assert m["deepseek-v4-flash"] == "deepseek-flash"


def test_normalize_deepseek_folds_v4_flash():
    # Importing model_normalize applies the owner glue.
    from hermes_cli.model_normalize import (
        _DEEPSEEK_RETIRED_ALIASES,
        normalize_model_for_provider,
    )

    assert _DEEPSEEK_RETIRED_ALIASES.get("deepseek-v4-flash") == "deepseek-flash"
    assert normalize_model_for_provider("deepseek-v4-flash", "deepseek") == "deepseek-flash"
    assert normalize_model_for_provider("deepseek-flash", "deepseek") == "deepseek-flash"
    assert normalize_model_for_provider("deepseek-v4-pro", "deepseek") == "deepseek-v4-pro"


def test_damodel_path_keeps_v4_flash():
    from hermes_cli.model_normalize import normalize_model_for_provider

    # Aggregator / proxy ids are not rewritten by the DeepSeek-native map.
    assert normalize_model_for_provider("deepseek-v4-flash", "damodel") == "deepseek-v4-flash"
