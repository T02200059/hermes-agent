"""Inbound-pipeline copy stays in ``locales`` (T2-20 A3 簇 5).

``gateway/run_inbound.py`` is one of upstream's split modules and the landing site
for the inbound-slash copy the owner tree had i18n-ised inside the monolith. Two
things must hold once ``GatewayRunner`` is bound to the module:

* every message the monolith had routed through ``t(...)`` renders **byte-identically
  in English** to the literal the split module used, so the cutover is copy-neutral;
* the two drain notices keep going through ``owner.gateway.lifecycle_copy`` so the
  ``{profile_tag}`` injection (改动清单 §7.14) survives, and no hard-coded English
  from the pre-i18n revision is left behind in the module.
"""
import pathlib
import re

import pytest

import gateway.run_inbound as inbound
from agent.i18n import t
from gateway.run_inbound import GatewayInboundMixin


def _src() -> str:
    return pathlib.Path(inbound.__file__).read_text(encoding="utf-8")


# The English the split module carried before the replay; each pair is
# (key, interpolation, expected render). KEEP IN SYNC with the host's literals.
VERBATIM: list[tuple[str, dict, str]] = [
    ("gateway.update_send_failed", {"error": "E"}, "✗ Failed to send response to update process: E"),
    ("gateway.update_sent", {"label": "L"}, "✓ Sent `L` to the update process."),
    ("gateway.force_stop_pending", {},
     "⚡ Force-stopped. The agent was still starting — session unlocked."),
    ("gateway.hook_blocked", {"command": "clear"}, "Command `/clear` was blocked by a hook."),
    ("gateway.learn_ack_described", {}, "Learning a skill from what you described…"),
    ("gateway.learn_ack_conversation", {}, "Learning a skill from this conversation…"),
    ("gateway.init_failed", {}, "Could not start /init — please try again."),
    ("gateway.init_ack_update", {}, "Updating AGENTS.md from a project scan…"),
    ("gateway.init_ack_generate", {}, "Generating AGENTS.md from a project scan…"),
    ("gateway.steer_usage_no_agent", {},
     "Usage: /steer <prompt>  (no agent is running; sending as a normal message)"),
    ("gateway.moa_prepare_failed", {}, "Failed to prepare MoA turn."),
    ("gateway.quick_command_no_output", {}, "Command returned no output."),
    ("gateway.quick_command_timeout", {}, "Quick command timed out (30s)."),
    ("gateway.quick_command_error", {"error": "E"}, "Quick command error: E"),
    ("gateway.quick_command_no_command", {"command": "q"},
     "Quick command '/q' has no command defined."),
    ("gateway.quick_command_unsupported_type", {"command": "q"},
     "Quick command '/q' has unsupported type (supported: 'exec', 'alias')."),
    ("gateway.quick_command_no_target", {"command": "q"},
     "Quick command '/q' has no target defined."),
    ("gateway.skill_disabled_for_platform", {"skill": "S", "platform": "P"},
     "The **S** skill is disabled for P.\nEnable it with: `hermes skills config`"),
    ("gateway.skills_disabled_stacked", {"skills": "A, B", "platform": "P"},
     "The **A, B** skill(s) in this stacked invocation are disabled for P.\n"
     "Enable them with: `hermes skills config`"),
    ("gateway.stacked_skills_load_failed", {"command": "c"},
     "Failed to load stacked skills for /c."),
    ("gateway.unknown_command", {"command": "c"},
     "Unknown command `/c`. Type /commands to see what's available, "
     "or resend without the leading slash to send as a regular message."),
    ("gateway.turn_lease.gateway_timeout", {},
     "⏳ Another turn is still running on this session. To protect the transcript, "
     "this message was not processed. Wait for the active turn to finish, then resend it."),
    ("gateway.busy_drain_no_work", {"profile_tag": "", "action": "restarting"},
     "⏳ Gateway is restarting and is not accepting new work right now."),
    ("gateway.busy_drain_maintenance", {"profile_tag": ""},
     "⏳ This agent is draining for a maintenance action and isn't accepting new turns right now. "
     "It'll be back in a moment — please resend shortly."),
]

# Hard-coded English the pre-i18n module carried; none may survive the replay.
RETIRED_LITERALS = [
    "Failed to send response to update process",
    "Force-stopped. The agent was still starting",
    "was blocked by a hook.",
    "Learning a skill from",
    "Could not start /init",
    "Updating AGENTS.md from a project scan",
    "Generating AGENTS.md from a project scan",
    "no agent is running; sending as a normal message",
    "Failed to prepare MoA turn.",
    "and is not accepting new work right now",
    "isn't accepting new turns right now",
    "Command returned no output.",
    "Quick command timed out (30s).",
    "Quick command error:",
    "has no command defined.",
    "has unsupported type",
    "has no target defined.",
    "Enable it with: `hermes skills config`",
    "Enable them with: `hermes skills config`",
    "Failed to load stacked skills for",
    "Unknown command `/{command}`.",
    "Another turn is still running on this session",
]


@pytest.mark.parametrize("key,kwargs,expected", VERBATIM, ids=[c[0] for c in VERBATIM])
def test_english_render_is_verbatim(key: str, kwargs: dict, expected: str) -> None:
    assert t(key, lang="en", **kwargs) == expected


@pytest.mark.parametrize("literal", RETIRED_LITERALS)
def test_no_hardcoded_english_left(literal: str) -> None:
    assert literal not in _src()


def test_module_imports_the_localizers() -> None:
    src = _src()
    assert "from agent.i18n import t" in src
    assert "from owner.gateway.lifecycle_copy import lifecycle_msg as _gateway_lifecycle_msg" in src


def test_drain_notices_use_owner_lifecycle_copy() -> None:
    src = _src()
    assert '_gateway_lifecycle_msg("gateway.busy_drain_maintenance")' in src
    assert '"gateway.busy_drain_no_work"' in src
    assert inbound._gateway_lifecycle_msg.__module__ == "owner.gateway.lifecycle_copy"


def test_skill_disabled_message_keeps_its_second_line() -> None:
    """A folded YAML scalar silently joined the two lines with a space once already."""
    got = t("gateway.skill_disabled_for_platform", lang="en", skill="S", platform="P")
    assert "\nEnable it with: `hermes skills config`" in got
    zh = t("gateway.skill_disabled_for_platform", lang="zh", skill="S", platform="P")
    assert "\n" in zh


def test_replay_did_not_strip_placeholder_slots() -> None:
    """Guards the tuple-return shape: the modules resolve at call time, not import time."""
    for key, kwargs, _ in VERBATIM:
        rendered = t(key, lang="en", **kwargs)
        assert not re.search(r"\{[a-z_]+\}", rendered), key
