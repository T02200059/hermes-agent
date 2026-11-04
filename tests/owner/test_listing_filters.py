"""C26: owner provider listing filters — alibaba dedupe + ambient anthropic gate."""

from __future__ import annotations


def _row(slug: str, **extra):
    base = {"slug": slug, "name": slug, "models": ["m"], "total_models": 1, "is_current": False}
    base.update(extra)
    return base


def test_filter_drops_coding_plan_and_keeps_one_paygo_cn():
    from owner.providers.listing_filters import filter_authenticated_provider_rows

    rows = [
        _row("alibaba"),
        _row("alibaba-cn"),
        _row("alibaba-coding-plan"),
        _row("deepseek"),
        _row("xai"),
    ]
    out = filter_authenticated_provider_rows(rows)
    slugs = [r["slug"] for r in out]
    assert slugs.count("alibaba-cn") == 1
    assert "alibaba" not in slugs
    assert "alibaba-coding-plan" not in slugs
    assert "deepseek" in slugs and "xai" in slugs


def test_filter_keeps_current_coding_plan_when_selected():
    from owner.providers.listing_filters import filter_authenticated_provider_rows

    rows = [
        _row("alibaba-coding-plan", is_current=True),
        _row("alibaba-cn"),
        _row("deepseek"),
    ]
    out = filter_authenticated_provider_rows(rows, current_provider="alibaba-coding-plan")
    slugs = [r["slug"] for r in out]
    assert "alibaba-coding-plan" in slugs
    assert "alibaba-cn" in slugs
    assert slugs.count("alibaba-cn") == 1


def test_filter_prefers_current_paygo_over_cn_preference():
    from owner.providers.listing_filters import filter_authenticated_provider_rows

    rows = [_row("alibaba", is_current=True), _row("alibaba-cn"), _row("moa")]
    out = filter_authenticated_provider_rows(rows, current_provider="alibaba")
    slugs = [r["slug"] for r in out]
    assert slugs == ["alibaba", "moa"]


def test_allow_ambient_anthropic_listing_default_false():
    from owner.providers.listing_filters import allow_ambient_anthropic_listing

    assert allow_ambient_anthropic_listing() is False


def test_has_valid_env_credential_coding_plan_requires_sk_sp():
    from owner.providers.credential_helpers import has_valid_env_credential

    env_paygo = {"DASHSCOPE_API_KEY": "sk-paygo-not-coding"}
    assert (
        has_valid_env_credential(
            ("DASHSCOPE_API_KEY",), "alibaba-coding-plan", read_env=env_paygo.get
        )
        is False
    )
    env_ok = {"DASHSCOPE_API_KEY": "sk-sp-coding-ok"}
    assert (
        has_valid_env_credential(
            ("DASHSCOPE_API_KEY",), "alibaba-coding-plan", read_env=env_ok.get
        )
        is True
    )


def test_has_valid_env_credential_rejects_ghp_accepts_gho_github_pat_ghu():
    from owner.providers.credential_helpers import has_valid_env_credential

    for bad in ("ghp_classic", "sk-something"):
        assert (
            has_valid_env_credential(("GH_TOKEN",), "copilot", read_env={"GH_TOKEN": bad}.get)
            is False
        )
    for good in ("gho_oauth", "github_pat_fine", "ghu_user"):
        assert (
            has_valid_env_credential(("GH_TOKEN",), "copilot", read_env={"GH_TOKEN": good}.get)
            is True
        )
