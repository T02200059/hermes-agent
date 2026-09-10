"""Ownership assertion on GET /v1/media/{id}.

An entry records a digest of the session that registered it. A caller is
accepted when it presents that same session (or the LDAP identity it was routed
by). A caller that asserts nothing is let through — those are infrastructure
callers holding the API key, and entries written before the owner field existed
carry no owner at all.
"""
from __future__ import annotations

import pytest

pytest.importorskip("aiohttp")

from gateway.platforms.api_server import APIServerAdapter
from gateway.platforms.api_server_media import media_owner_token


class _Request:
    """Minimal stand-in: the check only reads ``request.headers.get``."""

    def __init__(self, **headers: str) -> None:
        self.headers = headers


def _matches(**headers: str) -> bool:
    owner = media_owner_token("sess-abc")
    return APIServerAdapter._media_owner_matches(_Request(**headers), owner)


class TestMediaOwnerMatches:
    def test_same_session_header_matches(self):
        assert _matches(**{"X-Hermes-Session-Id": "sess-abc"}) is True

    def test_different_session_header_does_not_match(self):
        assert _matches(**{"X-Hermes-Session-Id": "sess-other"}) is False

    def test_ldap_identity_header_matches_a_routed_caller(self):
        """A routed caller is registered under its session and carries both."""
        matching = media_owner_token("sess-abc")
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Identity": "sess-abc"}), matching
        ) is True

    def test_one_of_several_headers_is_enough(self):
        assert _matches(
            **{"X-Hermes-Session-Id": "sess-other", "X-Hermes-Identity": "sess-abc"}
        ) is True

    def test_unattributable_request_is_allowed(self):
        """No owner headers → infrastructure caller; never lock it out."""
        assert _matches() is True

    def test_blank_owner_headers_count_as_unasserted(self):
        assert _matches(**{"X-Hermes-Session-Id": "   "}) is True

    def test_unrelated_headers_are_ignored(self):
        assert _matches(**{"Authorization": "Bearer key"}) is True

    def test_empty_owner_never_matches_a_claim(self):
        """Legacy entries (no owner) are handled by the caller, not here."""
        assert APIServerAdapter._media_owner_matches(
            _Request(**{"X-Hermes-Session-Id": "sess-abc"}), ""
        ) is False


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
